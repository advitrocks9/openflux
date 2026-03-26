"""Claude Code hooks adapter, invoked as a subprocess via shell hooks."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from openflux._util import (
    content_hash,
    generate_session_id,
    generate_trace_id,
    get_exclude_patterns,
    matches_exclude_pattern,
    truncate_content,
    utc_now,
)
from openflux.schema import (
    FidelityMode,
    SearchRecord,
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

CORRECTION_PATTERN = re.compile(
    r"(?i)\b(no[,.]?\s+(that'?s\s+)?(not|wrong)|"
    r"actually[,.]?\s+(do|use|change|try)|"
    r"instead[,.]?\s+(of|do|use)|"
    r"don'?t\s+(do|use|add|remove)|"
    r"stop\b|undo\b|revert\b|"
    r"I\s+(said|meant|want))",
)

_OPENFLUX_DIR = Path.home() / ".openflux"

_FILE_CONTENT_MAX = 4096
_URL_CONTENT_MAX = 16384
_TOOL_INPUT_MAX = 4096
_TOOL_OUTPUT_MAX = 16384
_TASK_MAX = 500
_DECISION_MAX = 300
_CORRECTION_TEXT_MAX = 300


@dataclass(slots=True)
class TranscriptData:
    """Extracted session-level data from Claude Code's JSONL transcript."""

    task: str = ""
    decision: str = ""
    model: str = ""
    token_usage: TokenUsage | None = None
    turn_count: int = 0
    duration_ms: int = 0
    scope: str | None = None
    correction: str | None = None


@dataclass(slots=True)
class SessionMeta:
    session_id: str
    cwd: str = ""
    permission_mode: str = ""
    started_at: str = ""
    model: str = ""


def _lock_file(f: Any) -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_EX)


def _unlock_file(f: Any) -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _buffer_path(session_id: str) -> Path:
    return _OPENFLUX_DIR / f".buffer_{session_id}.ndjson"


def _meta_path(session_id: str) -> Path:
    return _OPENFLUX_DIR / f".meta_{session_id}.json"


def _ensure_dir() -> None:
    _OPENFLUX_DIR.mkdir(parents=True, exist_ok=True)


def _append_event(session_id: str, event: dict[str, Any]) -> None:
    _ensure_dir()
    path = _buffer_path(session_id)
    with path.open("a", encoding="utf-8") as f:
        _lock_file(f)
        try:
            f.write(json.dumps(event, default=str) + "\n")
        finally:
            _unlock_file(f)


def _read_buffer(session_id: str) -> list[dict[str, Any]]:
    path = _buffer_path(session_id)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        _lock_file(f)
        try:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        finally:
            _unlock_file(f)
    return events


def _cleanup(session_id: str) -> None:
    for p in (_buffer_path(session_id), _meta_path(session_id)):
        p.unlink(missing_ok=True)


def _get_fidelity() -> FidelityMode:
    raw = os.environ.get("OPENFLUX_FIDELITY", "full")
    return FidelityMode(raw)


def _truncate_source(content: str, path: str, fidelity: FidelityMode) -> str:
    if not content:
        return ""
    if fidelity == FidelityMode.REDACTED:
        return ""
    limit = _URL_CONTENT_MAX if "://" in path else _FILE_CONTENT_MAX
    return truncate_content(content, limit)


def _truncate_tool_io(content: str, max_bytes: int, fidelity: FidelityMode) -> str:
    if not content:
        return ""
    if fidelity == FidelityMode.REDACTED:
        return truncate_content(content, 500)
    return truncate_content(content, max_bytes)


def _classify_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: str,
    error: bool,
    timestamp: str,
    fidelity: FidelityMode,
    exclude_patterns: list[str],
) -> dict[str, Any]:
    result: dict[str, list[Any]] = {
        "searches": [],
        "sources": [],
        "tools": [],
        "files_modified": [],
    }

    input_str = json.dumps(tool_input, default=str)

    match tool_name:
        case "Read":
            _classify_read(
                tool_input,
                tool_output,
                timestamp,
                fidelity,
                exclude_patterns,
                result,
            )
        case "WebSearch":
            _classify_web_search(
                tool_input,
                tool_output,
                timestamp,
                result,
            )
        case "WebFetch":
            _classify_web_fetch(
                tool_input,
                tool_output,
                timestamp,
                fidelity,
                exclude_patterns,
                result,
            )
        case "Bash":
            result["tools"].append(
                _make_tool_record(
                    "Bash", input_str, tool_output, error, timestamp, fidelity
                )
            )
        case "Grep" | "Glob":
            _classify_search_source(
                tool_name,
                tool_input,
                tool_output,
                timestamp,
                fidelity,
                exclude_patterns,
                result,
            )
        case "Edit" | "Write":
            _classify_write(
                tool_name,
                tool_input,
                tool_output,
                timestamp,
                fidelity,
                exclude_patterns,
                result,
            )
        case _:
            result["tools"].append(
                _make_tool_record(
                    tool_name,
                    input_str,
                    tool_output,
                    error,
                    timestamp,
                    fidelity,
                )
            )

    return result


def _classify_read(
    tool_input: dict[str, Any],
    tool_output: str,
    timestamp: str,
    fidelity: FidelityMode,
    exclude_patterns: list[str],
    result: dict[str, list[Any]],
) -> None:
    path = tool_input.get("file_path", "")
    excluded = matches_exclude_pattern(path, exclude_patterns)
    result["sources"].append(
        asdict(
            SourceRecord(
                type=SourceType.FILE,
                path=path,
                content_hash=content_hash(tool_output) if tool_output else "",
                content=""
                if excluded
                else _truncate_source(tool_output, path, fidelity),
                tool="Read",
                bytes_read=len(tool_output.encode("utf-8")) if tool_output else 0,
                timestamp=timestamp,
            )
        )
    )


def _classify_web_search(
    tool_input: dict[str, Any],
    tool_output: str,
    timestamp: str,
    result: dict[str, list[Any]],
) -> None:
    query = tool_input.get("query", tool_input.get("search_query", ""))
    lines = [ln for ln in tool_output.split("\n") if ln.strip()] if tool_output else []
    result["searches"].append(
        asdict(
            SearchRecord(
                query=query,
                engine="web_search",
                results_count=len(lines),
                timestamp=timestamp,
            )
        )
    )


def _classify_web_fetch(
    tool_input: dict[str, Any],
    tool_output: str,
    timestamp: str,
    fidelity: FidelityMode,
    exclude_patterns: list[str],
    result: dict[str, list[Any]],
) -> None:
    url = tool_input.get("url", "")
    excluded = matches_exclude_pattern(url, exclude_patterns)
    result["sources"].append(
        asdict(
            SourceRecord(
                type=SourceType.URL,
                path=url,
                content_hash=content_hash(tool_output) if tool_output else "",
                content=""
                if excluded
                else _truncate_source(tool_output, url, fidelity),
                tool="WebFetch",
                bytes_read=len(tool_output.encode("utf-8")) if tool_output else 0,
                timestamp=timestamp,
            )
        )
    )


def _classify_search_source(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: str,
    timestamp: str,
    fidelity: FidelityMode,
    exclude_patterns: list[str],
    result: dict[str, list[Any]],
) -> None:
    query = tool_input.get("pattern", tool_input.get("query", ""))
    lines = [ln for ln in tool_output.split("\n") if ln.strip()] if tool_output else []
    result["searches"].append(
        asdict(
            SearchRecord(
                query=query,
                engine=tool_name.lower(),
                results_count=len(lines),
                timestamp=timestamp,
            )
        )
    )
    for line in lines[:50]:
        path = line.split(":")[0].strip()
        if path and not matches_exclude_pattern(path, exclude_patterns):
            result["sources"].append(
                asdict(
                    SourceRecord(
                        type=SourceType.FILE,
                        path=path,
                        tool=tool_name,
                        timestamp=timestamp,
                    )
                )
            )


def _classify_write(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: str,
    timestamp: str,
    fidelity: FidelityMode,
    exclude_patterns: list[str],
    result: dict[str, list[Any]],
) -> None:
    path = tool_input.get("file_path", "")
    excluded = matches_exclude_pattern(path, exclude_patterns)
    content = tool_input.get("content", tool_input.get("new_string", ""))
    result["sources"].append(
        asdict(
            SourceRecord(
                type=SourceType.FILE,
                path=path,
                content_hash=content_hash(content) if content else "",
                content="" if excluded else _truncate_source(content, path, fidelity),
                tool=tool_name,
                bytes_read=len(content.encode("utf-8")) if content else 0,
                timestamp=timestamp,
            )
        )
    )
    if path:
        result["files_modified"].append(path)


def _make_tool_record(
    name: str,
    input_str: str,
    output: str,
    error: bool,
    timestamp: str,
    fidelity: FidelityMode,
) -> dict[str, Any]:
    return asdict(
        ToolRecord(
            name=name,
            tool_input=_truncate_tool_io(input_str, _TOOL_INPUT_MAX, fidelity),
            tool_output=_truncate_tool_io(output, _TOOL_OUTPUT_MAX, fidelity),
            error=error,
            timestamp=timestamp,
        )
    )


def _read_stdin() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    return json.loads(raw)


def handle_session_start(data: dict[str, Any]) -> None:
    session_id = data.get("session_id", generate_session_id())
    _ensure_dir()

    meta = SessionMeta(
        session_id=session_id,
        cwd=data.get("cwd", ""),
        permission_mode=data.get("permission_mode", ""),
        started_at=utc_now(),
        model=data.get("model", ""),
    )

    meta_path = _meta_path(session_id)
    meta_path.write_text(json.dumps(asdict(meta), default=str), encoding="utf-8")

    _buffer_path(session_id).touch()


def handle_post_tool_use(data: dict[str, Any]) -> None:
    session_id = data.get("session_id", "")
    if not session_id:
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_output = data.get("tool_response", "")
    if isinstance(tool_output, dict):
        tool_output = json.dumps(tool_output, default=str)

    timestamp = utc_now()
    fidelity = _get_fidelity()
    exclude_patterns = get_exclude_patterns()

    classified = _classify_tool(
        tool_name,
        tool_input,
        tool_output,
        error=False,
        timestamp=timestamp,
        fidelity=fidelity,
        exclude_patterns=exclude_patterns,
    )

    event: dict[str, Any] = {
        "tool_name": tool_name,
        "timestamp": timestamp,
        "classified": classified,
    }
    _append_event(session_id, event)


def handle_post_tool_use_failure(data: dict[str, Any]) -> None:
    session_id = data.get("session_id", "")
    if not session_id:
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    tool_output = data.get("tool_response", data.get("error", ""))
    if isinstance(tool_output, dict):
        tool_output = json.dumps(tool_output, default=str)

    timestamp = utc_now()
    fidelity = _get_fidelity()
    exclude_patterns = get_exclude_patterns()

    classified = _classify_tool(
        tool_name,
        tool_input,
        tool_output,
        error=True,
        timestamp=timestamp,
        fidelity=fidelity,
        exclude_patterns=exclude_patterns,
    )

    event: dict[str, Any] = {
        "tool_name": tool_name,
        "timestamp": timestamp,
        "error": True,
        "classified": classified,
    }
    _append_event(session_id, event)


def handle_subagent_start(data: dict[str, Any]) -> None:
    session_id = data.get("session_id", "")
    if not session_id:
        return

    event: dict[str, Any] = {
        "type": "subagent_start",
        "timestamp": utc_now(),
        "agent_id": data.get("agent_id", ""),
        "agent_type": data.get("agent_type", ""),
        "parent_session_id": session_id,
    }
    _append_event(session_id, event)


def handle_session_end(data: dict[str, Any]) -> None:
    session_id = data.get("session_id", "")
    if not session_id:
        return

    events = _read_buffer(session_id)
    if not events:
        _cleanup(session_id)
        return

    meta_file = _meta_path(session_id)
    meta = SessionMeta(session_id=session_id)
    if meta_file.exists():
        raw_meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta = SessionMeta(**raw_meta)

    trace = _build_trace(events, meta, data)
    _write_to_sinks(trace)
    _cleanup(session_id)


_TAG_RULES: dict[str, frozenset[str]] = {
    "code-edit": frozenset({"Edit", "Write"}),
    "web-research": frozenset({"WebSearch", "WebFetch"}),
    "shell": frozenset({"Bash"}),
    "file-search": frozenset({"Grep", "Glob"}),
    "file-read": frozenset({"Read"}),
}


def _derive_tags(events: list[dict[str, Any]], has_error: bool) -> list[str]:
    """Auto-generate tags from observed tool usage patterns."""
    seen_tools: set[str] = set()
    for event in events:
        tool_name = event.get("tool_name", "")
        if tool_name:
            seen_tools.add(tool_name)

    tags: list[str] = []
    for tag, tool_set in _TAG_RULES.items():
        if seen_tools & tool_set:
            tags.append(tag)
    if has_error:
        tags.append("has-errors")
    return tags


def _build_trace(
    events: list[dict[str, Any]],
    meta: SessionMeta,
    end_data: dict[str, Any],
) -> Trace:
    trace = Trace(
        id=generate_trace_id(),
        timestamp=meta.started_at or utc_now(),
        agent="claude-code",
        session_id=meta.session_id,
        model=meta.model,
        status=Status.COMPLETED,
    )

    all_files_modified: list[str] = []
    has_error = False
    tool_event_count = 0

    for event in events:
        classified = event.get("classified", {})
        if event.get("error"):
            has_error = True
        # Count all tool events, not just those classified as tools_used
        tool_event_count += 1

        for search_dict in classified.get("searches", []):
            trace.searches.append(SearchRecord(**search_dict))
        for source_dict in classified.get("sources", []):
            trace.sources_read.append(SourceRecord(**source_dict))
        for tool_dict in classified.get("tools", []):
            trace.tools_used.append(ToolRecord(**tool_dict))
        all_files_modified.extend(classified.get("files_modified", []))

    seen: set[str] = set()
    for f in all_files_modified:
        if f not in seen:
            seen.add(f)
            trace.files_modified.append(f)

    if has_error:
        trace.status = Status.ERROR

    trace.metadata["environment"] = {
        "cwd": meta.cwd,
        "permission_mode": meta.permission_mode,
    }

    # Try transcript parsing first (richest data source), fall back to hook data
    transcript = _try_parse_transcript(meta, end_data)
    if transcript:
        _apply_transcript_data(trace, transcript, tool_event_count)
    else:
        _apply_fallback_data(trace, meta, tool_event_count)

    trace.tags = _derive_tags(events, has_error)
    return trace


def _try_parse_transcript(
    meta: SessionMeta, end_data: dict[str, Any]
) -> TranscriptData | None:
    """Attempt to find and parse the Claude Code JSONL transcript."""
    # Check if hook provided transcript_path directly
    transcript_path = end_data.get("transcript_path", "")
    if transcript_path:
        path = Path(transcript_path)
        if path.exists():
            return _parse_transcript(path)

    # Discover transcript from session_id + cwd
    path = _find_transcript(meta.session_id, meta.cwd)
    if path:
        return _parse_transcript(path)

    return None


def _apply_transcript_data(
    trace: Trace, td: TranscriptData, tool_event_count: int
) -> None:
    """Populate trace fields from parsed transcript data."""
    if td.task:
        trace.task = td.task
    if td.decision:
        trace.decision = td.decision
    if td.model:
        trace.model = td.model
    if td.token_usage:
        trace.token_usage = td.token_usage
    if td.correction:
        trace.correction = td.correction
    if td.scope:
        trace.scope = td.scope
    # Prefer transcript turn_count (user entries), fall back to tool events
    trace.turn_count = td.turn_count if td.turn_count > 0 else tool_event_count
    # Prefer transcript duration (first→last timestamp), more accurate
    trace.duration_ms = td.duration_ms


def _apply_fallback_data(
    trace: Trace, meta: SessionMeta, tool_event_count: int
) -> None:
    """Populate trace fields when transcript is unavailable."""
    trace.turn_count = tool_event_count
    # Derive scope from cwd when transcript is unavailable
    if meta.cwd:
        trace.scope = Path(meta.cwd).name
    # Duration from session_start → now
    if meta.started_at:
        from datetime import UTC, datetime

        try:
            start = datetime.fromisoformat(meta.started_at.replace("Z", "+00:00"))
            now = datetime.now(UTC)
            trace.duration_ms = int((now - start).total_seconds() * 1000)
        except ValueError:
            pass


def _find_transcript(session_id: str, cwd: str) -> Path | None:
    """Locate the Claude Code JSONL transcript for this session."""
    if not cwd:
        return None
    # Claude Code normalizes cwd: /Users/foo/bar → -Users-foo-bar
    normalized = cwd.replace("/", "-").replace("\\", "-")
    path = Path.home() / ".claude" / "projects" / normalized / f"{session_id}.jsonl"
    return path if path.exists() else None


def _extract_user_text(message: dict[str, Any]) -> str:
    """Extract text from a user message's content (string or content blocks)."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    # Content blocks array — concatenate text blocks
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _extract_assistant_text(message: dict[str, Any]) -> str:
    """Extract the last text block from an assistant message's content."""
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    # Walk content blocks in reverse to find last text
    for block in reversed(content):
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return ""


def _accumulate_usage(usage: dict[str, Any], totals: TokenUsage) -> None:
    """Add a single message's usage to running totals."""
    totals.input_tokens += usage.get("input_tokens", 0)
    totals.output_tokens += usage.get("output_tokens", 0)
    totals.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
    totals.cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)


def _parse_transcript(path: Path) -> TranscriptData:
    """Parse Claude Code's JSONL transcript for session-level fields."""
    data = TranscriptData()
    token_totals = TokenUsage()

    first_timestamp: str = ""
    last_timestamp: str = ""
    last_correction_text: str = ""
    correction_count = 0
    git_branch: str = ""
    project_name: str = ""

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = entry.get("timestamp", "")
            if ts:
                if not first_timestamp:
                    first_timestamp = ts
                last_timestamp = ts

            if not git_branch:
                git_branch = entry.get("gitBranch", "")
            if not project_name:
                cwd = entry.get("cwd", "")
                if cwd:
                    project_name = Path(cwd).name

            msg = entry.get("message", {})
            entry_type = entry.get("type", "")

            if entry_type == "user":
                data.turn_count += 1
                text = _extract_user_text(msg)
                # First user message → task
                if not data.task and text:
                    data.task = truncate_content(text, _TASK_MAX)
                # Check for corrections in all user messages
                if text and CORRECTION_PATTERN.search(text):
                    correction_count += 1
                    last_correction_text = text

            elif entry_type == "assistant":
                if not data.model:
                    data.model = msg.get("model", "")
                usage = msg.get("usage")
                if usage:
                    _accumulate_usage(usage, token_totals)
                text = _extract_assistant_text(msg)
                if text:
                    # Keep updating — we want the last one
                    data.decision = truncate_content(text, _DECISION_MAX)

    # Duration from first→last transcript timestamp
    data.duration_ms = _timestamp_delta_ms(first_timestamp, last_timestamp)

    # Scope: project/branch
    if project_name or git_branch:
        data.scope = f"{project_name}/{git_branch}" if git_branch else project_name

    # Token usage (only set if we actually saw usage data)
    if token_totals.input_tokens or token_totals.output_tokens:
        data.token_usage = token_totals

    # Corrections
    if correction_count > 0:
        snippet = truncate_content(last_correction_text, _CORRECTION_TEXT_MAX)
        data.correction = f"Detected {correction_count} correction(s). Last: {snippet}"

    return data


def _timestamp_delta_ms(first: str, last: str) -> int:
    """Compute millisecond delta between two ISO 8601 timestamps."""
    if not first or not last:
        return 0
    from datetime import datetime

    try:
        t0 = datetime.fromisoformat(first.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(last.replace("Z", "+00:00"))
        return max(0, int((t1 - t0).total_seconds() * 1000))
    except ValueError:
        return 0


def _detect_corrections(transcript_path: str, trace: Trace) -> None:
    path = Path(transcript_path)
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        matches = CORRECTION_PATTERN.findall(text)
        if matches:
            trace.correction = f"Detected {len(matches)} potential correction(s)"
    except OSError:
        pass


def _write_to_sinks(trace: Trace) -> None:
    db_path = os.environ.get("OPENFLUX_DB_PATH", "")
    try:
        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path or None)
        sink.write(trace)
        sink.close()
    except Exception:
        # Fallback to stderr so data isn't lost
        sys.stderr.write(json.dumps(trace.to_dict(), default=str) + "\n")


class ClaudeCodeAdapter:
    @staticmethod
    def hook_config() -> dict[str, Any]:
        base = "python3 -m openflux.adapters._claude_code"
        return {
            "hooks": {
                "SessionStart": [
                    {"type": "command", "command": f"{base} session_start"}
                ],
                "PostToolUse": [
                    {"type": "command", "command": f"{base} post_tool_use"}
                ],
                "PostToolUseFailure": [
                    {"type": "command", "command": f"{base} post_tool_use_failure"}
                ],
                "SubagentStart": [
                    {"type": "command", "command": f"{base} subagent_start"}
                ],
                "Stop": [{"type": "command", "command": f"{base} session_end"}],
                "SessionEnd": [{"type": "command", "command": f"{base} session_end"}],
            }
        }


_SUBCOMMANDS = {
    "session_start": handle_session_start,
    "post_tool_use": handle_post_tool_use,
    "post_tool_use_failure": handle_post_tool_use_failure,
    "subagent_start": handle_subagent_start,
    "session_end": handle_session_end,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _SUBCOMMANDS:
        valid = ", ".join(_SUBCOMMANDS)
        print(
            f"Usage: python3 -m openflux.adapters._claude_code <{valid}>",
            file=sys.stderr,
        )
        sys.exit(1)

    subcommand = sys.argv[1]
    data = _read_stdin()
    _SUBCOMMANDS[subcommand](data)


if __name__ == "__main__":
    main()
