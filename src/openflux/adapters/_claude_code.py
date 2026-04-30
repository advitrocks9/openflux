"""Claude Code hooks adapter, invoked as a subprocess via shell hooks."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from openflux._util import (
    content_hash,
    generate_session_id,
    generate_trace_id,
    get_exclude_patterns,
    matches_exclude_pattern,
    truncate_content,
    utc_now,
)
from openflux.outcomes import capture_outcome, head_sha
from openflux.schema import (
    ContextRecord,
    ContextType,
    FidelityMode,
    SearchRecord,
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

logger = logging.getLogger(__name__)

CORRECTION_PATTERN = re.compile(
    r"(?i)\b(no[,.]?\s+(that'?s\s+)?(not|wrong)|"
    r"actually[,.]?\s+(do|use|change|try)|"
    r"instead[,.]?\s+(of|do|use)|"
    r"don'?t\s+(do|use|add|remove)|"
    r"stop\b|undo\b|revert\b|"
    r"I\s+(said|meant|want))",
)

# Claude Code wraps slash-command invocations and various system events in
# pseudo-XML tags inside the "user" message content. The first user message of
# a session is often pure tag noise (a /-command invocation, a session-resume
# system reminder, etc) with the real prompt only appearing on a later turn.
# Stripping is whitelisted to known wrapper tag names so legitimate prompts
# containing angle brackets (e.g. "Fix <select> handling") survive intact.
_KNOWN_WRAPPER_TAGS = (
    "local-command-caveat",
    "local-command-stdout",
    "local-command-stderr",
    "command-name",
    "command-message",
    "command-args",
    "system-reminder",
)
_KNOWN_TAG_RE = re.compile(
    r"<(?:" + "|".join(_KNOWN_WRAPPER_TAGS) + r")\b[^>]*>"
    r".*?"
    r"</(?:" + "|".join(_KNOWN_WRAPPER_TAGS) + r")>",
    re.DOTALL,
)
_COMMAND_NAME_RE = re.compile(r"<command-name>([^<]+)</command-name>")


def _clean_task_text(text: str) -> str:
    """Strip Claude Code system wrapper tags from a user-message body.

    Returns "" if nothing substantive remains after stripping (the caller
    should then try the next user message). Only known wrapper tag names
    are removed; unknown angle brackets pass through so prompts like
    `Fix <select> handling` aren't corrupted.
    """
    if not text:
        return ""
    cleaned = _KNOWN_TAG_RE.sub("", text).strip()
    return cleaned


def _slash_command_name(text: str) -> str:
    """Extract the slash-command name from a `<command-name>` tag if present.

    Used as a last-resort fallback when no later user message carries
    substantive prompt text. Returns "" if no command tag is found.
    """
    cmd = _COMMAND_NAME_RE.search(text or "")
    if not cmd:
        return ""
    return cmd.group(1).strip().lstrip("/")


def _extract_tool_result_text(block: dict[str, Any]) -> str:
    """Pull the text payload out of a tool_result content block.

    The Anthropic content-block schema lets `content` be either a string
    or a list of inner content blocks. Both forms appear in real Claude
    Code transcripts, so handle both.
    """
    inner: Any = block.get("content", "")
    if isinstance(inner, str):
        return inner
    if isinstance(inner, list):
        parts: list[str] = []
        for sub in inner:
            if isinstance(sub, dict) and sub.get("type") == "text":
                parts.append(str(sub.get("text", "")))
        return "\n".join(parts)
    return ""


def _register_tool_uses(
    msg: dict[str, Any],
    pending: dict[str, dict[str, Any]],
    timestamp: str,
) -> None:
    """Index every tool_use block in this assistant message by its id."""
    content: Any = msg.get("content", [])
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_id = str(block.get("id", ""))
        if not tool_id:
            continue
        tool_input = block.get("input", {})
        if not isinstance(tool_input, dict):
            tool_input = {}
        pending[tool_id] = {
            "name": str(block.get("name", "")),
            "input": tool_input,
            "ts": timestamp,
        }


def _harvest_tool_results(
    msg: dict[str, Any],
    pending: dict[str, dict[str, Any]],
    timestamp: str,
    fidelity: FidelityMode,
    exclude_patterns: list[str],
    data: TranscriptData,
) -> None:
    """Match tool_result blocks to pending tool_use ids and classify each.

    Reuses `_classify_tool` so backfilled traces carry the same shape of
    per-tool detail as live PostToolUse-hook traces.
    """
    content: Any = msg.get("content", [])
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool_use_id = str(block.get("tool_use_id", ""))
        invocation = pending.pop(tool_use_id, None)
        if invocation is None:
            continue
        tool_output = _extract_tool_result_text(block)
        error = bool(block.get("is_error"))
        classified = _classify_tool(
            tool_name=invocation["name"],
            tool_input=invocation["input"],
            tool_output=tool_output,
            error=error,
            timestamp=invocation["ts"] or timestamp,
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        for s in classified.get("searches", []):
            data.searches.append(SearchRecord(**s))
        for s in classified.get("sources", []):
            data.sources_read.append(SourceRecord(**s))
        for t in classified.get("tools", []):
            data.tools_used.append(ToolRecord(**t))
        for f in classified.get("files_modified", []):
            if f and f not in data.files_modified:
                data.files_modified.append(f)


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
    context: list[ContextRecord] = field(default_factory=lambda: list[ContextRecord]())
    # Reconstructed per-tool detail. Live `PostToolUse` hooks populate
    # these directly via `_classify_tool`. Backfill from a JSONL transcript
    # used to leave them empty (the fallback path lacked tool extraction),
    # which silently disabled the loop and error_storm anomaly classes.
    # Now populated by walking tool_use/tool_result content blocks.
    tools_used: list[ToolRecord] = field(default_factory=lambda: list[ToolRecord]())
    searches: list[SearchRecord] = field(default_factory=lambda: list[SearchRecord]())
    sources_read: list[SourceRecord] = field(
        default_factory=lambda: list[SourceRecord]()
    )
    files_modified: list[str] = field(default_factory=lambda: list[str]())
    # Map of Anthropic message_id → per-message billing record. Used to
    # populate `billable_messages` so the same API call across resumed/forked
    # session transcripts is billed exactly once (PK on message_id dedupes).
    messages: dict[str, dict[str, int | str]] = field(
        default_factory=lambda: dict[str, dict[str, int | str]]()
    )


@dataclass(slots=True)
class SessionMeta:
    session_id: str
    cwd: str = ""
    permission_mode: str = ""
    started_at: str = ""
    model: str = ""
    start_sha: str | None = None


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

    cwd = data.get("cwd", "")
    meta = SessionMeta(
        session_id=session_id,
        cwd=cwd,
        permission_mode=data.get("permission_mode", ""),
        started_at=utc_now(),
        model=data.get("model", ""),
        start_sha=head_sha(cwd) if cwd else None,
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
    if not isinstance(tool_output, str):
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
    if not isinstance(tool_output, str):
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
    _record_outcome_if_possible(meta)
    _cleanup(session_id)


def _record_outcome_if_possible(meta: SessionMeta) -> None:
    if not meta.cwd or not meta.start_sha:
        return
    test_cmd = os.environ.get("OPENFLUX_TEST_CMD") or None
    fields = capture_outcome(
        repo_dir=meta.cwd,
        start_sha=meta.start_sha,
        test_cmd=test_cmd,
    )
    try:
        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink()
        try:
            sink.record_outcome(
                session_id=meta.session_id,
                agent="claude-code",
                captured_at=utc_now(),
                start_sha=fields["start_sha"],
                end_sha=fields["end_sha"],
                lines_added=fields["lines_added"],
                lines_removed=fields["lines_removed"],
                files_changed=fields["files_changed"],
                tests_exit_code=fields["tests_exit_code"],
                tests_passed=fields["tests_passed"],
            )
        finally:
            sink.close()
    except Exception:
        logger.warning(
            "Failed to record outcome for session %s",
            meta.session_id,
            exc_info=True,
        )


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
        if event.get("tool_name"):
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

    if meta.started_at:
        from datetime import UTC, datetime

        try:
            start = datetime.fromisoformat(meta.started_at.replace("Z", "+00:00"))
            now = datetime.now(UTC)
            trace.duration_ms = int((now - start).total_seconds() * 1000)
        except ValueError:
            pass

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


_BILLABLE_MESSAGES_KEY = "_billable_messages"


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
    if td.context:
        trace.context.extend(td.context)
    # Per-tool detail reconstructed from tool_use/tool_result blocks. Only
    # extend with what the transcript provided so we don't double-count
    # records the live hook path may have already attached.
    if td.tools_used and not trace.tools_used:
        trace.tools_used.extend(td.tools_used)
    if td.searches and not trace.searches:
        trace.searches.extend(td.searches)
    if td.sources_read and not trace.sources_read:
        trace.sources_read.extend(td.sources_read)
    if td.files_modified and not trace.files_modified:
        for f in td.files_modified:
            if f not in trace.files_modified:
                trace.files_modified.append(f)
    # Prefer transcript turn_count (user entries), fall back to tool events
    trace.turn_count = td.turn_count if td.turn_count > 0 else tool_event_count
    if td.duration_ms > 0:
        trace.duration_ms = td.duration_ms
    if td.messages:
        # Stashed in metadata for _write_to_sinks to pick up; stripped
        # before persisting to traces table (it goes to billable_messages).
        trace.metadata[_BILLABLE_MESSAGES_KEY] = td.messages


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
            ms = int((now - start).total_seconds() * 1000)
            trace.duration_ms = max(ms, 1)  # a session with events took >0ms
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
    content: Any = message.get("content", "")
    if isinstance(content, str):
        return content
    # Content blocks array - concatenate text blocks
    blocks = cast(list[dict[str, Any]], content if isinstance(content, list) else [])
    parts: list[str] = []
    for block in blocks:
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _extract_assistant_text(message: dict[str, Any]) -> str:
    """Extract the last text block from an assistant message's content."""
    content: Any = message.get("content", [])
    if isinstance(content, str):
        return content
    # Walk content blocks in reverse to find last text
    blocks = cast(list[dict[str, Any]], content if isinstance(content, list) else [])
    for block in reversed(blocks):
        if block.get("type") == "text":
            return str(block.get("text", ""))
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

    first_timestamp: str = ""
    last_timestamp: str = ""
    last_correction_text: str = ""
    correction_count = 0
    git_branch: str = ""
    project_name: str = ""
    # Last-resort task fallback if every user message is pure tag noise.
    slash_fallback: str = ""
    # Multi-tool API responses get one transcript entry per tool_use
    # block; long responses also stream intermediate snapshots. All
    # copies share the message.id but `output_tokens` grows as the model
    # generates. We must keep the MAX usage per message.id (final state),
    # otherwise we either over-count (sum copies) or under-count (take
    # the first partial snapshot). input/cache fields are constant
    # across copies; max() is a no-op for them.
    usage_by_msg_id: dict[str, dict[str, int]] = {}
    # Track usage from messages without an id, accumulated as-is.
    anonymous_totals = TokenUsage()

    # Tool-use registry: id -> {name, input, ts}. Populated when an
    # assistant message contains a tool_use block; consumed when a
    # subsequent user message carries the matching tool_result block.
    # Without this, backfill never builds ToolRecord/SourceRecord/etc.
    # and the loop / error_storm anomaly classes can't fire.
    pending_tools: dict[str, dict[str, Any]] = {}
    fidelity = _get_fidelity()
    exclude_patterns = get_exclude_patterns()

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
                # Match any tool_result blocks against pending tool_use ids
                # and run them through the same classifier the live hook
                # path uses, so backfilled traces carry per-tool detail.
                _harvest_tool_results(
                    msg, pending_tools, ts, fidelity, exclude_patterns, data
                )
                text = _extract_user_text(msg)
                # First substantive user message → task. System tag soup
                # (slash-command boilerplate, session-resume reminders) is
                # stripped first; if nothing real is left, try the next turn.
                # Slash-command name is captured as a fallback in case no
                # turn ever has substantive text.
                if not data.task:
                    cleaned = _clean_task_text(text)
                    if cleaned:
                        data.task = truncate_content(cleaned, _TASK_MAX)
                    elif not slash_fallback:
                        slash_fallback = _slash_command_name(text)
                # Check for corrections in all user messages
                if text and CORRECTION_PATTERN.search(text):
                    correction_count += 1
                    last_correction_text = text

            elif entry_type == "assistant":
                model = msg.get("model", "")
                if not data.model and model and model != "<synthetic>":
                    data.model = model
                # "<synthetic>" entries are local injections (recovery,
                # restart prompts) that never hit the Anthropic API and
                # carry no real billable usage.
                usage = msg.get("usage")
                msg_id = msg.get("id", "")
                if usage and model != "<synthetic>":
                    if msg_id:
                        prior = usage_by_msg_id.get(msg_id)
                        if prior is None:
                            usage_by_msg_id[msg_id] = {
                                "input": usage.get("input_tokens", 0),
                                "output": usage.get("output_tokens", 0),
                                "cr": usage.get("cache_read_input_tokens", 0),
                                "cc": usage.get("cache_creation_input_tokens", 0),
                                "model": model,
                                "ts": ts,
                            }
                        else:
                            prior["input"] = max(
                                int(prior["input"]), usage.get("input_tokens", 0)
                            )
                            prior["output"] = max(
                                int(prior["output"]), usage.get("output_tokens", 0)
                            )
                            prior["cr"] = max(
                                int(prior["cr"]),
                                usage.get("cache_read_input_tokens", 0),
                            )
                            prior["cc"] = max(
                                int(prior["cc"]),
                                usage.get("cache_creation_input_tokens", 0),
                            )
                    else:
                        _accumulate_usage(usage, anonymous_totals)
                text = _extract_assistant_text(msg)
                if text:
                    # Keep updating - we want the last one
                    data.decision = truncate_content(text, _DECISION_MAX)
                # Register any tool_use blocks; the matching tool_result
                # comes in the next user message and is processed there.
                _register_tool_uses(msg, pending_tools, ts)

            # System messages carry context (system prompts, reminders)
            if entry_type == "system" or msg.get("role") == "system":
                text = _extract_user_text(msg) if msg else ""
                if text:
                    data.context.append(
                        ContextRecord(
                            type=ContextType.SYSTEM_PROMPT,
                            source="transcript",
                            content_hash=content_hash(text),
                            content=text[:4096],
                            bytes=len(text.encode("utf-8")),
                            timestamp=ts,
                        )
                    )

    # Duration from first→last transcript timestamp
    data.duration_ms = _timestamp_delta_ms(first_timestamp, last_timestamp)

    # Scope: project/branch
    if project_name or git_branch:
        data.scope = f"{project_name}/{git_branch}" if git_branch else project_name

    # Token usage (only set if we actually saw usage data)
    token_totals = TokenUsage(
        input_tokens=anonymous_totals.input_tokens
        + sum(int(u["input"]) for u in usage_by_msg_id.values()),
        output_tokens=anonymous_totals.output_tokens
        + sum(int(u["output"]) for u in usage_by_msg_id.values()),
        cache_read_tokens=anonymous_totals.cache_read_tokens
        + sum(int(u["cr"]) for u in usage_by_msg_id.values()),
        cache_creation_tokens=anonymous_totals.cache_creation_tokens
        + sum(int(u["cc"]) for u in usage_by_msg_id.values()),
    )
    if token_totals.input_tokens or token_totals.output_tokens:
        data.token_usage = token_totals

    # Per-message billing records. The sink dedupes on message_id PK so
    # the same Anthropic API call across resumed/forked sessions is
    # billed exactly once.
    for mid, vals in usage_by_msg_id.items():
        data.messages[mid] = {
            "model": vals["model"],
            "timestamp": vals["ts"],
            "input_tokens": int(vals["input"]),
            "output_tokens": int(vals["output"]),
            "cache_read_tokens": int(vals["cr"]),
            "cache_creation_tokens": int(vals["cc"]),
        }

    # Corrections
    if correction_count > 0:
        snippet = truncate_content(last_correction_text, _CORRECTION_TEXT_MAX)
        data.correction = f"Detected {correction_count} correction(s). Last: {snippet}"

    # Last-resort task fallback. If every user message in the session was
    # pure system-tag noise (slash command boilerplate, session-resume
    # reminders), fall back to the slash command name so the row still has
    # something more useful than an empty task.
    if not data.task and slash_fallback:
        data.task = slash_fallback

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


def _write_to_sinks(trace: Trace) -> None:
    try:
        from openflux.sinks.sqlite import SQLiteSink

        # Pull billable-messages payload off metadata before write; it
        # belongs in billable_messages, not in the traces.metadata column.
        messages = cast(
            dict[str, dict[str, int | str]],
            trace.metadata.pop(_BILLABLE_MESSAGES_KEY, {}),
        )
        sink = SQLiteSink()
        try:
            sink.write(trace)
            if messages:
                sink.record_messages(trace.agent, trace.session_id, messages)
        finally:
            sink.close()
    except Exception:
        logger.warning("Failed to write trace %s to SQLite", trace.id, exc_info=True)
        # Subprocess context: emit to stderr so data isn't lost
        sys.stderr.write(json.dumps(trace.to_dict(), default=str) + "\n")


class ClaudeCodeAdapter:
    @staticmethod
    def hook_config() -> dict[str, Any]:
        base = f"{sys.executable} -m openflux.adapters._claude_code"
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
