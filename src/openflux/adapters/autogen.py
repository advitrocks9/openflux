"""AutoGen v0.4 adapter - async stream consumer."""

from __future__ import annotations

import importlib.util
import json
import threading
from dataclasses import dataclass, field
from typing import Any

from openflux._util import generate_session_id, generate_trace_id, utc_now
from openflux.schema import (
    SearchRecord,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

_HAS_AUTOGEN = importlib.util.find_spec("autogen_agentchat") is not None


_DEFAULT_SEARCH_TOOLS: set[str] = {"web_search", "search", "retrieve"}


@dataclass(slots=True)
class _RunAccumulator:
    session_id: str
    started_at: str = ""
    model: str = ""
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tools: list[ToolRecord] = field(default_factory=list)
    searches: list[SearchRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    has_error: bool = False
    stop_reason: str = ""
    agents_seen: list[str] = field(default_factory=list)


class AutoGenStreamConsumer:
    """Consumes AutoGen v0.4 run_stream() messages into Traces."""

    def __init__(
        self,
        agent: str = "autogen",
        search_tools: set[str] | None = None,
        on_trace: Any | None = None,
    ) -> None:
        self._agent = agent
        self._search_tools = search_tools or _DEFAULT_SEARCH_TOOLS
        self._on_trace = on_trace
        self._lock = threading.Lock()
        self._acc: _RunAccumulator | None = None
        self._completed: list[Trace] = []

    def process(self, message: Any) -> None:
        with self._lock:
            if self._acc is None:
                self._acc = _RunAccumulator(
                    session_id=generate_session_id(),
                    started_at=utc_now(),
                )

        match type(message).__name__:
            case "TextMessage":
                self._handle_text_message(message)
            case "ToolCallRequestEvent":
                self._handle_tool_call_request(message)
            case "ToolCallExecutionEvent":
                self._handle_tool_call_execution(message)
            case "HandoffMessage":
                self._handle_handoff(message)
            case "StopMessage":
                self._handle_stop(message)
            case "ToolCallSummaryMessage":
                self._handle_tool_call_summary(message)
            case "TaskResult":
                self._handle_task_result(message)

    def flush(self) -> Trace | None:
        with self._lock:
            acc = self._acc
            self._acc = None
        if acc is None:
            return None
        return self._emit(acc)

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)

    def _handle_text_message(self, msg: Any) -> None:
        self._track_source(msg)
        self._extract_token_usage(msg)

    def _handle_tool_call_request(self, msg: Any) -> None:
        self._track_source(msg)
        content = getattr(msg, "content", [])
        if not isinstance(content, list):
            return

        with self._lock:
            acc = self._acc
        if acc is None:
            return

        for call in content:
            name = getattr(call, "name", "unknown")
            arguments = getattr(call, "arguments", "")
            call_id = getattr(call, "id", "")

            if isinstance(arguments, dict):
                arguments = json.dumps(arguments, default=str)

            if name.lower() in self._search_tools:
                acc.searches.append(
                    SearchRecord(
                        query=str(arguments)[:500],
                        engine=name,
                        timestamp=utc_now(),
                    )
                )
            else:
                acc.tools.append(
                    ToolRecord(
                        name=name,
                        tool_input=str(arguments)[:4096],
                        timestamp=utc_now(),
                    )
                )
                acc.metadata.setdefault("_pending_calls", {})[call_id] = (
                    len(acc.tools) - 1
                )

        self._extract_token_usage(msg)

    def _handle_tool_call_execution(self, msg: Any) -> None:
        self._track_source(msg)
        content = getattr(msg, "content", [])
        if not isinstance(content, list):
            return

        with self._lock:
            acc = self._acc
        if acc is None:
            return

        pending = acc.metadata.get("_pending_calls", {})
        is_error = False
        for result in content:
            call_id = getattr(result, "call_id", "")
            output = getattr(result, "content", "")
            is_error = getattr(result, "is_error", False)

            if isinstance(output, dict):
                output = json.dumps(output, default=str)

            if call_id in pending:
                idx = pending.pop(call_id)
                if idx < len(acc.tools):
                    acc.tools[idx].tool_output = str(output)[:16384]
                    acc.tools[idx].error = bool(is_error)
                    continue

            name = getattr(result, "name", "unknown")
            acc.tools.append(
                ToolRecord(
                    name=name,
                    tool_output=str(output)[:16384],
                    error=bool(is_error),
                    timestamp=utc_now(),
                )
            )

        if is_error:
            acc.has_error = True

    def _handle_handoff(self, msg: Any) -> None:
        self._track_source(msg)
        with self._lock:
            acc = self._acc
        if acc is None:
            return

        handoffs = acc.metadata.setdefault("handoffs", [])
        handoffs.append(
            {
                "from_agent": getattr(msg, "source", ""),
                "to_agent": getattr(msg, "target", ""),
            }
        )
        self._extract_token_usage(msg)

    def _handle_stop(self, msg: Any) -> None:
        self._track_source(msg)
        self._extract_token_usage(msg)
        with self._lock:
            acc = self._acc
        if acc is None:
            return
        acc.stop_reason = getattr(msg, "content", "stop")
        self.flush()

    def _handle_tool_call_summary(self, msg: Any) -> None:
        self._track_source(msg)
        self._extract_token_usage(msg)

    def _handle_task_result(self, msg: Any) -> None:
        with self._lock:
            acc = self._acc
        if acc is None:
            return
        acc.stop_reason = getattr(msg, "stop_reason", None) or ""
        self.flush()

    def _track_source(self, msg: Any) -> None:
        source = getattr(msg, "source", "")
        if not source:
            return
        with self._lock:
            acc = self._acc
        if acc is not None and source not in acc.agents_seen:
            acc.agents_seen.append(source)

    def _extract_token_usage(self, msg: Any) -> None:
        usage = getattr(msg, "models_usage", None)
        if usage is None:
            return
        with self._lock:
            acc = self._acc
        if acc is None:
            return
        acc.token_usage.input_tokens += getattr(usage, "prompt_tokens", 0)
        acc.token_usage.output_tokens += getattr(usage, "completion_tokens", 0)

    def _emit(self, acc: _RunAccumulator) -> Trace:
        acc.metadata.pop("_pending_calls", None)

        trace = Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or utc_now(),
            agent=self._agent,
            session_id=acc.session_id,
            model=acc.model,
            status=Status.ERROR if acc.has_error else Status.COMPLETED,
            tools_used=acc.tools,
            searches=acc.searches,
            token_usage=acc.token_usage,
            turn_count=len(acc.tools),
            metadata={
                **acc.metadata,
                **({"stop_reason": acc.stop_reason} if acc.stop_reason else {}),
                **({"agents_seen": acc.agents_seen} if acc.agents_seen else {}),
            },
        )

        with self._lock:
            self._completed.append(trace)

        if self._on_trace:
            self._on_trace(trace)
        else:
            self._write_default_sink(trace)

        return trace

    def _write_default_sink(self, trace: Trace) -> None:
        try:
            from openflux.sinks.sqlite import SQLiteSink

            sink = SQLiteSink()
            sink.write(trace)
            sink.close()
        except Exception:
            pass
