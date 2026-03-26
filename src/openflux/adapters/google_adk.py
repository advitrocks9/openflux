"""Google ADK adapter - callback factory for Agent() constructor."""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from openflux._util import content_hash, generate_trace_id, utc_now
from openflux.schema import (
    ContextRecord,
    ContextType,
    SearchRecord,
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

try:
    _HAS_ADK = importlib.util.find_spec("google.adk") is not None
except (ModuleNotFoundError, ValueError):
    _HAS_ADK = False


_HANDOFF_TOOL = "transfer_to_agent"
_DEFAULT_SEARCH_TOOLS: set[str] = {"google_search", "web_search", "search", "retrieve"}
_DEFAULT_SOURCE_TOOLS: set[str] = {
    "read_file",
    "fetch_url",
    "load_document",
    "get_file",
    "read",
}
_DEFAULT_WRITE_TOOLS: set[str] = {
    "write_file",
    "save_file",
    "create_file",
    "edit_file",
    "write",
}
# Keys in tool args that hint at file/URL paths
_PATH_ARG_KEYS: frozenset[str] = frozenset(
    {
        "path",
        "file_path",
        "filename",
        "file",
        "url",
        "uri",
        "filepath",
    }
)


@dataclass(slots=True)
class _SessionAccumulator:
    session_id: str
    started_at: str = ""
    agent_name: str = ""
    model: str = ""
    task: str = ""
    decision: str = ""
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tools: list[ToolRecord] = field(default_factory=list)
    searches: list[SearchRecord] = field(default_factory=list)
    context: list[ContextRecord] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    has_error: bool = False
    llm_turn_count: int = 0
    # monotonic timestamps for sub-ms tool timing precision
    _tool_starts: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class ADKCallbacks:
    before_model: Any
    after_model: Any
    before_tool: Any
    after_tool: Any
    _adapter: GoogleADKAdapter


class GoogleADKAdapter:
    def __init__(
        self,
        agent: str = "google-adk",
        search_tools: set[str] | None = None,
        source_tools: set[str] | None = None,
        write_tools: set[str] | None = None,
        on_trace: Any | None = None,
    ) -> None:
        self._agent = agent
        self._search_tools = search_tools or _DEFAULT_SEARCH_TOOLS
        self._source_tools = source_tools or _DEFAULT_SOURCE_TOOLS
        self._write_tools = write_tools or _DEFAULT_WRITE_TOOLS
        self._on_trace = on_trace
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionAccumulator] = {}
        self._completed: list[Trace] = []

    def _get_or_create(self, session_id: str) -> _SessionAccumulator:
        if (acc := self._sessions.get(session_id)) is None:
            acc = _SessionAccumulator(session_id=session_id, started_at=utc_now())
            self._sessions[session_id] = acc
        return acc

    def _session_id_from_context(self, ctx: Any) -> str:
        session = getattr(ctx, "session", None)
        if session is not None:
            sid = getattr(session, "id", None)
            if sid:
                return str(sid)
        return getattr(ctx, "agent_name", "") or "unknown"

    def _before_model(self, callback_context: Any, llm_request: Any) -> None:
        sid = self._session_id_from_context(callback_context)
        with self._lock:
            acc = self._get_or_create(sid)

        # Each before_model call = one LLM inference turn
        acc.llm_turn_count += 1

        agent_name = getattr(callback_context, "agent_name", "")
        if agent_name:
            acc.agent_name = agent_name

        # Capture model from the request (e.g. "gemini-2.0-flash")
        model = getattr(llm_request, "model", None)
        if model:
            acc.model = str(model)

        # Extract task from the first user message in conversation contents
        if not acc.task:
            contents = getattr(llm_request, "contents", None)
            if contents:
                for msg in contents:
                    if getattr(msg, "role", "") == "user":
                        acc.task = _extract_text(msg)[:500]
                        break

        # ADK stores system instruction in llm_request.config.system_instruction
        config = getattr(llm_request, "config", None)
        instructions = getattr(config, "system_instruction", None) if config else None
        if instructions:
            text = _extract_text(instructions)
            if text:
                h = content_hash(text)
                # Deduplicate: only record if this exact prompt isn't already captured
                if not any(c.content_hash == h for c in acc.context):
                    acc.context.append(
                        ContextRecord(
                            type=ContextType.SYSTEM_PROMPT,
                            source=f"agent:{agent_name}",
                            content_hash=h,
                            content=text,
                            bytes=len(text.encode("utf-8")),
                            timestamp=utc_now(),
                        )
                    )

    def _after_model(self, callback_context: Any, llm_response: Any) -> None:
        sid = self._session_id_from_context(callback_context)
        with self._lock:
            acc = self._get_or_create(sid)

        # ADK LlmResponse uses model_version, not model
        model_version = getattr(llm_response, "model_version", "") or ""
        if model_version:
            acc.model = model_version

        usage = getattr(llm_response, "usage_metadata", None)
        if usage:
            acc.token_usage.input_tokens += getattr(usage, "prompt_token_count", 0) or 0
            acc.token_usage.output_tokens += (
                getattr(usage, "candidates_token_count", 0) or 0
            )
            # Gemini 2.5 models expose thinking tokens separately
            thoughts = getattr(usage, "thoughts_token_count", 0) or 0
            if thoughts:
                acc.metadata["thoughts_tokens"] = (
                    acc.metadata.get("thoughts_tokens", 0) + thoughts
                )
            # Map cached_content_token_count when the API exposes it
            cached = getattr(usage, "cached_content_token_count", 0) or 0
            acc.token_usage.cache_read_tokens += cached

        content = getattr(llm_response, "content", None)
        if content:
            # Capture last model text as the decision (overwrites each turn,
            # so final response becomes the decision)
            text = _extract_text(content)
            if text:
                acc.decision = text[:500]
            _detect_handoffs(content, acc)

    def _before_tool(self, tool: Any, args: dict[str, Any], tool_context: Any) -> None:
        sid = self._session_id_from_context(tool_context)
        with self._lock:
            acc = self._get_or_create(sid)

        call_id = getattr(tool_context, "function_call_id", "") or ""
        if call_id:
            acc._tool_starts[call_id] = time.monotonic()

    def _after_tool(
        self,
        tool: Any,
        args: dict[str, Any],
        tool_context: Any,
        tool_response: Any,
    ) -> None:
        sid = self._session_id_from_context(tool_context)
        with self._lock:
            acc = self._get_or_create(sid)

        tool_name = getattr(tool, "name", "") or str(tool)
        call_id = getattr(tool_context, "function_call_id", "") or ""
        now = utc_now()

        start_mono = acc._tool_starts.pop(call_id, None)
        end_mono = time.monotonic()
        duration_ms = (
            max(0, int((end_mono - start_mono) * 1000)) if start_mono is not None else 0
        )

        args_str = json.dumps(args, default=str)[:4096] if args else ""
        result_str = _serialize_tool_response(tool_response)

        if tool_name.lower() in self._search_tools:
            acc.searches.append(
                SearchRecord(query=args_str[:500], engine=tool_name, timestamp=now)
            )
        else:
            acc.tools.append(
                ToolRecord(
                    name=tool_name,
                    tool_input=args_str,
                    tool_output=result_str[:16384],
                    duration_ms=duration_ms,
                    error=False,
                    timestamp=now,
                )
            )

        # Heuristic: detect source reads from tool name or arg keys
        extracted_path = _extract_path_from_args(args)
        if tool_name.lower() in self._source_tools or (
            extracted_path and _looks_like_read(tool_name)
        ):
            source_type = (
                SourceType.URL
                if extracted_path.startswith(("http://", "https://"))
                else SourceType.FILE
            )
            acc.sources.append(
                SourceRecord(
                    type=source_type,
                    path=extracted_path,
                    content_hash=content_hash(result_str) if result_str else "",
                    tool=tool_name,
                    bytes_read=len(result_str.encode("utf-8")) if result_str else 0,
                    timestamp=now,
                )
            )

        # Heuristic: detect file writes from tool name
        if tool_name.lower() in self._write_tools and extracted_path:
            acc.files_modified.append(extracted_path)

    def flush(self) -> list[Trace]:
        with self._lock:
            pending = list(self._sessions.values())
            self._sessions.clear()

        traces: list[Trace] = []
        for acc in pending:
            trace = self._build_trace(acc)
            traces.append(trace)
            with self._lock:
                self._completed.append(trace)
            if self._on_trace:
                self._on_trace(trace)
            else:
                self._write_default_sink(trace)
        return traces

    def _build_trace(self, acc: _SessionAccumulator) -> Trace:
        now = utc_now()
        duration_ms = _compute_duration_ms(acc.started_at, now)
        tags = ["google-adk"]
        if acc.model:
            tags.append(acc.model)

        return Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or now,
            agent=self._agent,
            session_id=acc.session_id,
            model=acc.model,
            task=acc.task,
            decision=acc.decision,
            status=Status.ERROR if acc.has_error else Status.COMPLETED,
            scope=acc.agent_name or None,
            tags=tags,
            tools_used=acc.tools,
            searches=acc.searches,
            context=acc.context,
            sources_read=acc.sources,
            files_modified=acc.files_modified,
            token_usage=acc.token_usage,
            turn_count=acc.llm_turn_count,
            duration_ms=duration_ms,
            metadata=acc.metadata,
        )

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)

    def _write_default_sink(self, trace: Trace) -> None:
        import os

        try:
            from openflux.sinks.sqlite import SQLiteSink

            db_env = os.environ.get("OPENFLUX_DB_PATH", "")
            sink = SQLiteSink(db_env) if db_env else SQLiteSink()
            sink.write(trace)
            sink.close()
        except Exception:
            pass


def create_adk_callbacks(
    agent: str = "google-adk",
    search_tools: set[str] | None = None,
    source_tools: set[str] | None = None,
    write_tools: set[str] | None = None,
    on_trace: Any | None = None,
) -> ADKCallbacks:
    adapter = GoogleADKAdapter(
        agent=agent,
        search_tools=search_tools,
        source_tools=source_tools,
        write_tools=write_tools,
        on_trace=on_trace,
    )
    return ADKCallbacks(
        before_model=adapter._before_model,
        after_model=adapter._after_model,
        before_tool=adapter._before_tool,
        after_tool=adapter._after_tool,
        _adapter=adapter,
    )


def _extract_text(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    parts = getattr(obj, "parts", None)
    if parts:
        return "".join(getattr(p, "text", "") or "" for p in parts)
    text = getattr(obj, "text", None)
    return str(text) if text else str(obj)


def _detect_handoffs(content: Any, acc: _SessionAccumulator) -> None:
    parts = getattr(content, "parts", None)
    if not parts:
        return
    for part in parts:
        fc = getattr(part, "function_call", None)
        if fc is None:
            continue
        if getattr(fc, "name", "") == _HANDOFF_TOOL:
            args = getattr(fc, "args", {}) or {}
            target = args.get("agent_name", "") or args.get("agent", "")
            acc.metadata.setdefault("handoffs", []).append(
                {"from_agent": acc.agent_name, "to_agent": str(target)}
            )


def _compute_duration_ms(start: str, end: str) -> int:
    """Compute milliseconds between two ISO 8601 timestamps."""
    if not start or not end:
        return 0
    try:
        from datetime import datetime

        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return max(0, int((e - s).total_seconds() * 1000))
    except (ValueError, TypeError):
        return 0


def _extract_path_from_args(args: dict[str, Any]) -> str:
    """Pull a file path or URL from tool args using known key names."""
    if not args:
        return ""
    for key in _PATH_ARG_KEYS:
        val = args.get(key)
        if val and isinstance(val, str):
            return val
    return ""


def _looks_like_read(tool_name: str) -> bool:
    """Heuristic: does the tool name suggest a read operation?"""
    lower = tool_name.lower()
    return any(kw in lower for kw in ("read", "fetch", "load", "get", "download"))


def _serialize_tool_response(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    try:
        return json.dumps(response, default=str)
    except (TypeError, ValueError):
        return str(response)
