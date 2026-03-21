"""OpenAI Agents SDK adapter via TracingProcessor."""

import importlib.util
import json
import threading
from dataclasses import dataclass, field
from typing import Any, cast

from openflux._util import content_hash, generate_trace_id, utc_now
from openflux.schema import (
    ContextRecord,
    ContextType,
    SearchRecord,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

_HAS_AGENTS = importlib.util.find_spec("agents") is not None

if _HAS_AGENTS:
    from agents.tracing import TracingProcessor  # type: ignore[import-untyped]
else:
    TracingProcessor = object  # type: ignore[assignment,misc]


_DEFAULT_SEARCH_TOOLS: set[str] = {"web_search", "search", "retrieve"}


@dataclass(slots=True)
class _TraceAccumulator:
    trace_id: str
    started_at: str = ""
    agent_name: str = ""
    model: str = ""
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tools: list[ToolRecord] = field(default_factory=lambda: list[ToolRecord]())
    searches: list[SearchRecord] = field(default_factory=lambda: list[SearchRecord]())
    context: list[ContextRecord] = field(default_factory=lambda: list[ContextRecord]())
    metadata: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())
    has_error: bool = False


class OpenFluxProcessor(TracingProcessor):  # type: ignore[misc]
    """TracingProcessor that accumulates spans into Traces."""

    def __init__(
        self,
        agent: str = "openai-agent",
        search_tools: set[str] | None = None,
        on_trace: Any | None = None,
    ) -> None:
        self._agent = agent
        self._search_tools = search_tools or _DEFAULT_SEARCH_TOOLS
        self._on_trace = on_trace
        self._lock = threading.Lock()
        self._traces: dict[str, _TraceAccumulator] = {}
        self._completed: list[Trace] = []

    def on_trace_start(self, trace: Any) -> None:
        trace_id: str = str(getattr(trace, "trace_id", str(trace)))
        with self._lock:
            self._traces[trace_id] = _TraceAccumulator(
                trace_id=trace_id,
                started_at=utc_now(),
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

    def _handle_agent_span(self, span_data: Any, acc: _TraceAccumulator) -> None:
        name: str = str(getattr(span_data, "name", ""))
        if name:
            acc.agent_name = name
        instructions: str | None = getattr(span_data, "instructions", None)
        if instructions:
            acc.context.append(
                ContextRecord(
                    type=ContextType.SYSTEM_PROMPT,
                    source=f"agent:{name}",
                    content_hash=content_hash(instructions),
                    content=instructions,
                    bytes=len(instructions.encode("utf-8")),
                    timestamp=utc_now(),
                )
            )

    def _handle_generation_span(self, span_data: Any, acc: _TraceAccumulator) -> None:
        model: str = str(getattr(span_data, "model", ""))
        if model:
            acc.model = model
        raw_usage = getattr(span_data, "usage", None)
        if raw_usage and isinstance(raw_usage, dict):
            usage = cast(dict[str, Any], raw_usage)
            acc.token_usage.input_tokens += int(usage.get("input_tokens", 0))
            acc.token_usage.output_tokens += int(usage.get("output_tokens", 0))

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

        if name.lower() in self._search_tools:
            acc.searches.append(
                SearchRecord(
                    query=str(raw_input)[:500] if raw_input else "",
                    engine=name,
                    timestamp=utc_now(),
                )
            )
        else:
            error = bool(getattr(span, "error", None))
            started = getattr(span, "started_at", "")
            ended = getattr(span, "ended_at", "")
            duration_ms = 0
            if started and ended:
                try:
                    from datetime import datetime

                    s = datetime.fromisoformat(str(started))
                    e = datetime.fromisoformat(str(ended))
                    duration_ms = int((e - s).total_seconds() * 1000)
                except (ValueError, TypeError):
                    pass

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
        return Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or utc_now(),
            agent=self._agent,
            session_id=acc.trace_id,
            model=acc.model,
            status=Status.ERROR if acc.has_error else Status.COMPLETED,
            tools_used=acc.tools,
            searches=acc.searches,
            context=acc.context,
            token_usage=acc.token_usage,
            turn_count=len(acc.tools),
            metadata=acc.metadata,
        )

    def _write_default_sink(self, trace: Trace) -> None:
        try:
            from openflux.sinks.sqlite import SQLiteSink

            sink = SQLiteSink()
            sink.write(trace)
            sink.close()
        except Exception:
            pass
