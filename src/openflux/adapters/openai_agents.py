"""OpenAI Agents SDK adapter via TracingProcessor."""

import importlib.util
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

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

_HAS_AGENTS = importlib.util.find_spec("agents") is not None

if _HAS_AGENTS:
    from agents.tracing import TracingProcessor
else:
    TracingProcessor = object


_DEFAULT_SEARCH_TOOLS: set[str] = {
    "web_search",
    "search_web",
    "search",
    "retrieve",
    "bing_search",
    "google_search",
}

_DEFAULT_FILE_READ_TOOLS: set[str] = {
    "read_file",
    "file_reader",
    "load_file",
    "read_document",
    "file_search",
}

_DEFAULT_FILE_WRITE_TOOLS: set[str] = {
    "write_file",
    "file_writer",
    "save_file",
    "create_file",
    "edit_file",
    "append_file",
}


@dataclass(slots=True)
class _TraceAccumulator:
    trace_id: str
    started_at: str = ""
    first_span_at: str = ""
    last_span_at: str = ""
    agent_name: str = ""
    model: str = ""
    task: str = ""
    last_generation_output: str = ""
    generation_count: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tools: list[ToolRecord] = field(default_factory=lambda: list[ToolRecord]())
    searches: list[SearchRecord] = field(default_factory=lambda: list[SearchRecord]())
    sources: list[SourceRecord] = field(default_factory=lambda: list[SourceRecord]())
    context: list[ContextRecord] = field(default_factory=lambda: list[ContextRecord]())
    files_modified: list[str] = field(default_factory=lambda: list[str]())
    tags: list[str] = field(default_factory=lambda: list[str]())
    metadata: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())
    has_error: bool = False
    seen_context_hashes: set[str] = field(default_factory=lambda: set[str]())


def _estimate_results_count(raw_output: Any) -> int:
    """Best-effort count of search results from tool output."""
    if not raw_output:
        return 0
    output_str = str(raw_output)
    # Try JSON list first
    try:
        parsed = json.loads(output_str)
        if isinstance(parsed, list):
            return len(parsed)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    # Non-empty output means at least 1 result
    return 1 if output_str.strip() else 0


def _compute_duration_ms(started: str, ended: str) -> int:
    """Compute millisecond delta between two ISO timestamps."""
    if not started or not ended:
        return 0
    try:
        s = datetime.fromisoformat(started)
        e = datetime.fromisoformat(ended)
        return max(0, int((e - s).total_seconds() * 1000))
    except (ValueError, TypeError):
        return 0


class OpenFluxProcessor(TracingProcessor):
    """TracingProcessor that accumulates spans into Traces."""

    def __init__(
        self,
        agent: str = "openai-agent",
        search_tools: set[str] | None = None,
        file_read_tools: set[str] | None = None,
        file_write_tools: set[str] | None = None,
        on_trace: Any | None = None,
        parent_id: str | None = None,
    ) -> None:
        self._agent = agent
        self._search_tools = search_tools or _DEFAULT_SEARCH_TOOLS
        self._file_read_tools = file_read_tools or _DEFAULT_FILE_READ_TOOLS
        self._file_write_tools = file_write_tools or _DEFAULT_FILE_WRITE_TOOLS
        self._on_trace = on_trace
        self._parent_id = parent_id
        self._lock = threading.Lock()
        self._traces: dict[str, _TraceAccumulator] = {}
        self._completed: list[Trace] = []

    def on_trace_start(self, trace: Any) -> None:
        trace_id: str = str(getattr(trace, "trace_id", str(trace)))
        # TraceImpl exposes workflow name as `name`, not `workflow_name`
        task: str = str(
            getattr(trace, "name", "") or getattr(trace, "workflow_name", "") or ""
        )

        # Extract tags from group_id and metadata if available
        tags: list[str] = []
        group_id: str = str(getattr(trace, "group_id", "") or "")
        if group_id:
            tags.append(f"group:{group_id}")
        trace_meta = getattr(trace, "metadata", None)
        if isinstance(trace_meta, dict):
            meta_tags = trace_meta.get("tags")
            if isinstance(meta_tags, list):
                tags.extend(str(t) for t in meta_tags)

        with self._lock:
            self._traces[trace_id] = _TraceAccumulator(
                trace_id=trace_id,
                started_at=utc_now(),
                task=task,
                tags=tags,
            )

    def on_trace_end(self, trace: Any) -> None:
        trace_id: str = str(getattr(trace, "trace_id", str(trace)))
        with self._lock:
            acc = self._traces.pop(trace_id, None)
        if acc is None:
            return

        trace = self._build_trace(acc)
        with self._lock:
            self._completed.append(trace)

        if self._on_trace:
            self._on_trace(trace)
        else:
            self._write_default_sink(trace)

    def on_span_start(self, span: Any) -> None:
        pass

    def on_span_end(self, span: Any) -> None:
        trace_id: str = str(getattr(span, "trace_id", ""))
        with self._lock:
            acc = self._traces.get(trace_id)
        if acc is None:
            return

        span_data = getattr(span, "span_data", None)
        if span_data is None:
            return

        if getattr(span, "error", None):
            acc.has_error = True

        # Track span timestamps for trace-level duration_ms
        self._update_span_timestamps(span, acc)

        class_name = type(span_data).__name__
        match class_name:
            case "AgentSpanData":
                self._handle_agent_span(span_data, acc)
            case "GenerationSpanData":
                self._handle_generation_span(span_data, acc)
            case "FunctionSpanData":
                self._handle_function_span(span, span_data, acc)
            case "HandoffSpanData":
                self._handle_handoff_span(span_data, acc)
            case "GuardrailSpanData":
                self._handle_guardrail_span(span_data, acc)
            case _:
                pass

    def shutdown(self) -> None:
        self.force_flush()

    def force_flush(self) -> None:
        with self._lock:
            pending = list(self._traces.values())
            self._traces.clear()

        for acc in pending:
            trace = self._build_trace(acc)
            if self._on_trace:
                self._on_trace(trace)

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)

    def _update_span_timestamps(self, span: Any, acc: _TraceAccumulator) -> None:
        """Track earliest start and latest end across all spans."""
        started = str(getattr(span, "started_at", "") or "")
        ended = str(getattr(span, "ended_at", "") or "")
        if started and (not acc.first_span_at or started < acc.first_span_at):
            acc.first_span_at = started
        if ended and (not acc.last_span_at or ended > acc.last_span_at):
            acc.last_span_at = ended

    def _handle_agent_span(self, span_data: Any, acc: _TraceAccumulator) -> None:
        name: str = str(getattr(span_data, "name", ""))
        if name:
            acc.agent_name = name
        # AgentSpanData has no instructions field — system prompts can't be captured
        output_type: str | None = getattr(span_data, "output_type", None)
        if output_type:
            acc.metadata["output_type"] = str(output_type)

    def _handle_generation_span(self, span_data: Any, acc: _TraceAccumulator) -> None:
        acc.generation_count += 1
        model: str = str(getattr(span_data, "model", ""))
        if model:
            acc.model = model
        self._accumulate_usage(span_data, acc)
        self._capture_decision(span_data, acc)
        self._capture_context_from_generation(span_data, acc)

    def _accumulate_usage(self, span_data: Any, acc: _TraceAccumulator) -> None:
        raw_usage = getattr(span_data, "usage", None)
        if raw_usage and isinstance(raw_usage, dict):
            usage = cast(dict[str, Any], raw_usage)
            acc.token_usage.input_tokens += int(
                usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
            )
            acc.token_usage.output_tokens += int(
                usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
            )

    def _capture_decision(self, span_data: Any, acc: _TraceAccumulator) -> None:
        """Extract last assistant message content as the trace decision."""
        output = getattr(span_data, "output", None)
        if not output or not isinstance(output, (list, tuple)):
            return
        # Walk output messages in reverse to find last assistant content
        for msg in reversed(output):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if content:
                    acc.last_generation_output = str(content)[:2048]
                    return

    def _capture_context_from_generation(
        self, span_data: Any, acc: _TraceAccumulator
    ) -> None:
        """Extract system prompts from generation input as context records."""
        raw_input = getattr(span_data, "input", None)
        if not raw_input or not isinstance(raw_input, (list, tuple)):
            return
        for msg in raw_input:
            if not isinstance(msg, dict):
                continue
            if msg.get("role") == "system":
                text = str(msg.get("content", ""))
                if text:
                    h = content_hash(text)
                    if h in acc.seen_context_hashes:
                        continue
                    acc.seen_context_hashes.add(h)
                    acc.context.append(
                        ContextRecord(
                            type=ContextType.SYSTEM_PROMPT,
                            source="generation",
                            content_hash=h,
                            content=text[:4096],
                            bytes=len(text.encode("utf-8")),
                            timestamp=utc_now(),
                        )
                    )

    def _handle_function_span(
        self, span: Any, span_data: Any, acc: _TraceAccumulator
    ) -> None:
        name: str = str(getattr(span_data, "name", ""))
        raw_input: Any = getattr(span_data, "input", "")
        raw_output: Any = getattr(span_data, "output", "")

        if isinstance(raw_input, dict):
            raw_input = json.dumps(raw_input, default=str)
        if isinstance(raw_output, dict):
            raw_output = json.dumps(raw_output, default=str)

        name_lower = name.lower()

        if name_lower in self._search_tools:
            acc.searches.append(
                SearchRecord(
                    query=str(raw_input)[:500] if raw_input else "",
                    engine=name,
                    results_count=_estimate_results_count(raw_output),
                    timestamp=utc_now(),
                )
            )
        else:
            error = bool(getattr(span, "error", None))
            started = getattr(span, "started_at", "")
            ended = getattr(span, "ended_at", "")
            duration_ms = _compute_duration_ms(str(started), str(ended))

            acc.tools.append(
                ToolRecord(
                    name=name,
                    tool_input=str(raw_input)[:4096],
                    tool_output=str(raw_output)[:16384],
                    duration_ms=duration_ms,
                    error=error,
                    timestamp=utc_now(),
                )
            )

        # Classify file reads as sources
        if name_lower in self._file_read_tools:
            path = self._extract_path_from_input(str(raw_input))
            output_str = str(raw_output) if raw_output else ""
            acc.sources.append(
                SourceRecord(
                    type=SourceType.FILE,
                    path=path,
                    content_hash=content_hash(output_str) if output_str else "",
                    content=output_str[:4096],
                    tool=name,
                    bytes_read=len(output_str.encode("utf-8")) if output_str else 0,
                    timestamp=utc_now(),
                )
            )

        # Classify file writes as files_modified
        if name_lower in self._file_write_tools:
            path = self._extract_path_from_input(str(raw_input))
            if path and path not in acc.files_modified:
                acc.files_modified.append(path)

    @staticmethod
    def _extract_path_from_input(tool_input: str) -> str:
        """Best-effort extraction of a file path from tool input."""
        try:
            data = json.loads(tool_input)
            if isinstance(data, dict):
                for key in ("file_path", "path", "filename", "file", "name"):
                    val = data.get(key)
                    if val and isinstance(val, str):
                        return val
        except (json.JSONDecodeError, TypeError):
            pass
        stripped = tool_input.strip()
        if "/" in stripped or stripped.startswith("."):
            return stripped[:500]
        return ""

    def _handle_handoff_span(self, span_data: Any, acc: _TraceAccumulator) -> None:
        handoffs: list[dict[str, str]] = acc.metadata.setdefault("handoffs", [])
        handoffs.append(
            {
                "from_agent": str(getattr(span_data, "from_agent", "")),
                "to_agent": str(getattr(span_data, "to_agent", "")),
            }
        )

    def _handle_guardrail_span(self, span_data: Any, acc: _TraceAccumulator) -> None:
        guardrails: list[dict[str, Any]] = acc.metadata.setdefault("guardrails", [])
        guardrails.append(
            {
                "name": str(getattr(span_data, "name", "")),
                "triggered": bool(getattr(span_data, "triggered", False)),
            }
        )

    def _build_trace(self, acc: _TraceAccumulator) -> Trace:
        duration_ms = _compute_duration_ms(acc.first_span_at, acc.last_span_at)
        # scope defaults to agent name, falling back to task/workflow name
        scope = acc.agent_name or acc.task or None
        return Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or utc_now(),
            agent=self._agent,
            session_id=acc.trace_id,
            parent_id=self._parent_id,
            model=acc.model,
            task=acc.task,
            decision=acc.last_generation_output,
            status=Status.ERROR if acc.has_error else Status.COMPLETED,
            scope=scope,
            tags=acc.tags,
            context=acc.context,
            tools_used=acc.tools,
            searches=acc.searches,
            sources_read=acc.sources,
            files_modified=acc.files_modified,
            token_usage=acc.token_usage,
            turn_count=acc.generation_count,
            duration_ms=duration_ms,
            metadata=acc.metadata,
        )

    def _write_default_sink(self, trace: Trace) -> None:
        try:
            import os
            from pathlib import Path

            from openflux.sinks.sqlite import SQLiteSink

            db_env = os.environ.get("OPENFLUX_DB_PATH", "")
            sink = SQLiteSink(path=Path(db_env)) if db_env else SQLiteSink()
            sink.write(trace)
            sink.close()
        except Exception:
            pass
