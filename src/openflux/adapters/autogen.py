"""AutoGen v0.4 adapter - async stream consumer."""

from __future__ import annotations

import importlib.util
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from openflux._util import (
    generate_session_id,
    generate_trace_id,
    utc_now,
    write_trace_to_default_sink,
)
from openflux.schema import (
    ContextRecord,
    SearchRecord,
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

logger = logging.getLogger("openflux")

_HAS_AUTOGEN = importlib.util.find_spec("autogen_agentchat") is not None


_DEFAULT_SEARCH_TOOLS: set[str] = {"web_search", "search", "retrieve"}
_DEFAULT_SOURCE_TOOLS: set[str] = {"read_file", "fetch_url"}


@dataclass(slots=True)
class _RunAccumulator:
    session_id: str
    started_at: str = ""
    model: str = ""
    task: str = ""
    decision: str = ""
    turn_count: int = 0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tools: list[ToolRecord] = field(default_factory=list)
    searches: list[SearchRecord] = field(default_factory=list)
    sources_read: list[SourceRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    has_error: bool = False
    stop_reason: str = ""
    agents_seen: list[str] = field(default_factory=list)
    _start_mono: float = 0.0


class AutoGenStreamConsumer:
    """Consumes AutoGen v0.4 run_stream() messages into Traces."""

    def __init__(
        self,
        agent: str = "autogen",
        model: str = "",
        search_tools: set[str] | None = None,
        source_tools: set[str] | None = None,
        scope: str | None = None,
        tags: list[str] | None = None,
        context: list[ContextRecord] | None = None,
        on_trace: Callable[[Trace], None] | None = None,
    ) -> None:
        self._agent = agent
        self._model = model
        self._search_tools = search_tools or _DEFAULT_SEARCH_TOOLS
        self._source_tools = source_tools or _DEFAULT_SOURCE_TOOLS
        self._scope = scope
        self._tags = tags or []
        self._context = context or []
        self._on_trace = on_trace
        self._lock = threading.Lock()
        self._acc: _RunAccumulator | None = None
        self._completed: list[Trace] = []
        self._last_trace: Trace | None = None

    def process(self, message: Any) -> None:
        try:
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
        except Exception:
            logger.warning("OpenFlux: error in process callback", exc_info=True)

    def flush(self) -> Trace | None:
        with self._lock:
            acc = self._acc
            self._acc = None
        if acc is None:
            # Return cached trace so callers after auto-flush aren't surprised
            return self._last_trace
        return self._emit(acc)

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)

    def _handle_text_message(self, msg: Any) -> None:
        self._track_source(msg)
        source = getattr(msg, "source", "")
        content = getattr(msg, "content", "")

        with self._lock:
            acc = self._acc
        if acc is not None:
            # Extract task from first user message
            if source == "user" and not acc.task and content:
                acc.task = str(content)[:500]
            # Count non-user TextMessages as conversation turns
            if source and source != "user":
                acc.turn_count += 1
                # Track last agent response as decision
                if content:
                    acc.decision = str(content)[:500]

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

        # Each tool call request is an agent action, counts as a turn
        acc.turn_count += 1

        for call in content:
            name = getattr(call, "name", "unknown")
            arguments = getattr(call, "arguments", "")
            call_id = getattr(call, "id", "")
            # Store request timestamp for duration_ms calculation
            request_ts = getattr(call, "created_at", None)

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
                # Track search call_ids so execution results are skipped
                if call_id:
                    acc.metadata.setdefault("_search_calls", set()).add(call_id)
            else:
                acc.tools.append(
                    ToolRecord(
                        name=name,
                        tool_input=str(arguments)[:4096],
                        timestamp=utc_now(),
                    )
                )
                # Store (index, created_at) for duration calculation
                msg_created = getattr(msg, "created_at", None) or request_ts
                acc.metadata.setdefault("_pending_calls", {})[call_id] = (
                    len(acc.tools) - 1,
                    msg_created,
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
        search_calls = acc.metadata.get("_search_calls", set())
        exec_created = getattr(msg, "created_at", None)
        is_error = False
        for result in content:
            call_id = getattr(result, "call_id", "")
            # Skip execution results for search tools
            if call_id in search_calls:
                continue
            output = getattr(result, "content", "")
            is_error = getattr(result, "is_error", False)
            name = getattr(result, "name", "unknown")

            if isinstance(output, dict):
                output = json.dumps(output, default=str)

            output_str = str(output)[:16384]

            if call_id in pending:
                idx, req_created = pending.pop(call_id)
                if idx < len(acc.tools):
                    acc.tools[idx].tool_output = output_str
                    acc.tools[idx].error = bool(is_error)
                    # Compute duration from request/execution created_at
                    if req_created and exec_created:
                        delta = (exec_created - req_created).total_seconds()
                        acc.tools[idx].duration_ms = max(0, int(delta * 1000))
                    name = acc.tools[idx].name
                    self._maybe_record_source(acc, name, output_str)
                    continue

            acc.tools.append(
                ToolRecord(
                    name=name,
                    tool_output=output_str,
                    error=bool(is_error),
                    timestamp=utc_now(),
                )
            )
            self._maybe_record_source(acc, name, output_str)

        if is_error:
            acc.has_error = True

    def _handle_handoff(self, msg: Any) -> None:
        self._track_source(msg)
        with self._lock:
            acc = self._acc
        if acc is None:
            return

        # Handoff is an agent action, counts as a turn
        acc.turn_count += 1
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

    def _maybe_record_source(
        self, acc: _RunAccumulator, tool_name: str, output: str
    ) -> None:
        """Heuristic: tools matching source_tools produce SourceRecords."""
        if tool_name.lower() not in self._source_tools:
            return
        acc.sources_read.append(
            SourceRecord(
                type=SourceType.TOOL_RESULT,
                tool=tool_name,
                content=output[:4096],
                timestamp=utc_now(),
            )
        )

    def _emit(self, acc: _RunAccumulator) -> Trace:
        acc.metadata.pop("_pending_calls", None)
        acc.metadata.pop("_search_calls", None)

        duration_ms = 0
        if acc._start_mono > 0:
            duration_ms = int((time.monotonic() - acc._start_mono) * 1000)

        # Auto-generate agent tags from agents_seen
        auto_tags = [f"agent:{a}" for a in acc.agents_seen]
        merged_tags = list(self._tags) + auto_tags

        trace = Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or utc_now(),
            agent=self._agent,
            session_id=acc.session_id,
            model=acc.model or self._model,
            task=acc.task,
            decision=acc.decision,
            status=Status.ERROR if acc.has_error else Status.COMPLETED,
            scope=self._scope,
            tags=merged_tags,
            context=list(self._context),
            sources_read=acc.sources_read,
            tools_used=acc.tools,
            searches=acc.searches,
            token_usage=acc.token_usage,
            turn_count=acc.turn_count,
            duration_ms=duration_ms,
            metadata={
                **acc.metadata,
                **({"stop_reason": acc.stop_reason} if acc.stop_reason else {}),
                **({"agents_seen": acc.agents_seen} if acc.agents_seen else {}),
            },
        )

        with self._lock:
            self._completed.append(trace)
        self._last_trace = trace

        if self._on_trace:
            self._on_trace(trace)
        else:
            self._write_default_sink(trace)

        return trace

    def _write_default_sink(self, trace: Trace) -> None:
        write_trace_to_default_sink(trace)
