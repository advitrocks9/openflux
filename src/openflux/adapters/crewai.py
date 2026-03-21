"""CrewAI adapter - BaseEventListener for the crewai_event_bus."""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any

from openflux._util import (
    content_hash,
    generate_session_id,
    generate_trace_id,
    utc_now,
)
from openflux.schema import (
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

_HAS_CREWAI = importlib.util.find_spec("crewai") is not None

if _HAS_CREWAI:
    from crewai.events import (
  # type: ignore[import-untyped]
        AgentExecutionCompletedEvent,
  AgentExecutionStartedEvent,
  BaseEventListener,
  CrewKickoffCompletedEvent,
  CrewKickoffStartedEvent,
  LLMCallCompletedEvent,
  LLMCallStartedEvent,
  TaskCompletedEvent,
  TaskStartedEvent,
  ToolUsageErrorEvent,
  ToolUsageFinishedEvent,
  ToolUsageStartedEvent,
)
else:
    BaseEventListener = object  # type: ignore[assignment,misc]


@dataclass(slots=True)
class _TaskAccumulator:
    task_id: str
    started_at: str = ""
    task_description: str = ""
    agent_role: str = ""
    model: str = ""
    decision: str = ""
    has_error: bool = False
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tools: list[ToolRecord] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    llm_call_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    _pending_tool_name: str = ""
    _pending_tool_input: str = ""
    _pending_tool_timestamp: str = ""
    _pending_tool_start_ns: int = 0


class OpenFluxCrewListener(BaseEventListener):  # type: ignore[misc]
    """One Trace per task. Parallel tasks get independent accumulators."""

    def __init__(
        self,
        agent: str = "crewai-crew",
        on_trace: Any | None = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._on_trace = on_trace
        self._lock = threading.Lock()
        self._session_id = generate_session_id()
        self._crew_name = ""
        self._crew_started_at = ""
        self._tasks: dict[str, _TaskAccumulator] = {}
        self._agent_task: dict[str, str] = {}
        self._completed: list[Trace] = []

    def setup_listeners(self, crewai_event_bus: Any) -> None:  # type: ignore[override]
        @crewai_event_bus.on(CrewKickoffStartedEvent)
        def _on_crew_started(source: Any, event: Any) -> None:
            self._crew_name = getattr(event, "crew_name", "")
            self._crew_started_at = utc_now()
            self._session_id = generate_session_id()

        @crewai_event_bus.on(CrewKickoffCompletedEvent)
        def _on_crew_completed(source: Any, event: Any) -> None:
            self._flush_remaining()

        @crewai_event_bus.on(AgentExecutionStartedEvent)
        def _on_agent_started(source: Any, event: Any) -> None:
            agent_obj = getattr(event, "agent", None)
            role = getattr(agent_obj, "role", "") if agent_obj else ""
            task_key = self._current_task_key()
            if task_key and role:
                with self._lock:
                    self._agent_task[role] = task_key
                    acc = self._tasks.get(task_key)
                    if acc and not acc.agent_role:
                        acc.agent_role = role

        @crewai_event_bus.on(AgentExecutionCompletedEvent)
        def _on_agent_completed(source: Any, event: Any) -> None:
            agent_obj = getattr(event, "agent", None)
            role = getattr(agent_obj, "role", "") if agent_obj else ""
            output = str(getattr(event, "output", ""))[:4096]
            acc = self._find_acc_for_agent(role)
            if acc and output and not acc.decision:
                acc.decision = output

        @crewai_event_bus.on(TaskStartedEvent)
        def _on_task_started(source: Any, event: Any) -> None:
            task_obj = getattr(event, "task", None)
            task_key = self._task_key(task_obj)
            description = (
                getattr(task_obj, "description", "")[:2000] if task_obj else ""
            )
            with self._lock:
                if task_key not in self._tasks:
                    self._tasks[task_key] = _TaskAccumulator(
                        task_id=task_key,
                        started_at=utc_now(),
                        task_description=description,
                    )

        @crewai_event_bus.on(TaskCompletedEvent)
        def _on_task_completed(source: Any, event: Any) -> None:
            task_obj = getattr(event, "task", None)
            task_key = self._task_key(task_obj)
            output = str(getattr(event, "output", ""))[:4096]
            with self._lock:
                acc = self._tasks.get(task_key)
            if acc is not None:
                if output and not acc.decision:
                    acc.decision = output
                self._flush_task(acc)

        @crewai_event_bus.on(LLMCallStartedEvent)
        def _on_llm_started(source: Any, event: Any) -> None:
            acc = self._current_acc()
            if acc is not None:
                acc.llm_call_count += 1

        @crewai_event_bus.on(LLMCallCompletedEvent)
        def _on_llm_completed(source: Any, event: Any) -> None:
            acc = self._current_acc()
            if acc is None:
                return
            usage = getattr(event, "usage", None) or getattr(event, "token_usage", None)
            if usage:
                if isinstance(usage, dict):
                    acc.token_usage.input_tokens += usage.get(
                        "prompt_tokens", 0
                    ) or usage.get("input_tokens", 0)
                    acc.token_usage.output_tokens += usage.get(
                        "completion_tokens", 0
                    ) or usage.get("output_tokens", 0)
                else:
                    acc.token_usage.input_tokens += getattr(
                        usage, "prompt_tokens", 0
                    ) or getattr(usage, "input_tokens", 0)
                    acc.token_usage.output_tokens += getattr(
                        usage, "completion_tokens", 0
                    ) or getattr(usage, "output_tokens", 0)

            model = getattr(event, "model", "") or getattr(event, "model_name", "")
            if model:
                acc.model = str(model)

            response = getattr(event, "response", None)
            if response:
                text = str(response)[:4096]
                acc.sources.append(
                    SourceRecord(
                        type=SourceType.API,
                        path=f"llm/{acc.model or 'unknown'}",
                        content_hash=content_hash(text),
                        content=text,
                        tool="llm",
                        bytes_read=len(text.encode("utf-8")),
                        timestamp=utc_now(),
                    )
                )

        @crewai_event_bus.on(ToolUsageStartedEvent)
        def _on_tool_started(source: Any, event: Any) -> None:
            acc = self._current_acc()
            if acc is None:
                return
            tool_name = getattr(event, "tool_name", "") or getattr(event, "name", "")
            tool_args = getattr(event, "tool_args", "") or getattr(
                event, "arguments", ""
            )
            if isinstance(tool_args, dict):
                tool_args = json.dumps(tool_args, default=str)
            acc._pending_tool_name = str(tool_name)
            acc._pending_tool_input = str(tool_args)[:4096]
            acc._pending_tool_timestamp = utc_now()
            acc._pending_tool_start_ns = time.monotonic_ns()

        @crewai_event_bus.on(ToolUsageFinishedEvent)
        def _on_tool_finished(source: Any, event: Any) -> None:
            acc = self._current_acc()
            if acc is None:
                return
            result = str(getattr(event, "result", ""))[:16384]
            duration_ms = 0
            if acc._pending_tool_start_ns:
                duration_ms = (
                    time.monotonic_ns() - acc._pending_tool_start_ns
                ) // 1_000_000
            acc.tools.append(
                ToolRecord(
                    name=acc._pending_tool_name,
                    tool_input=acc._pending_tool_input,
                    tool_output=result,
                    duration_ms=duration_ms,
                    timestamp=acc._pending_tool_timestamp,
                )
            )
            acc._pending_tool_name = ""
            acc._pending_tool_input = ""
            acc._pending_tool_timestamp = ""
            acc._pending_tool_start_ns = 0

        @crewai_event_bus.on(ToolUsageErrorEvent)
        def _on_tool_error(source: Any, event: Any) -> None:
            acc = self._current_acc()
            if acc is None:
                return
            error_msg = str(getattr(event, "error", ""))[:16384]
            duration_ms = 0
            if acc._pending_tool_start_ns:
                duration_ms = (
                    time.monotonic_ns() - acc._pending_tool_start_ns
                ) // 1_000_000
            acc.tools.append(
                ToolRecord(
                    name=acc._pending_tool_name,
                    tool_input=acc._pending_tool_input,
                    tool_output=error_msg,
                    duration_ms=duration_ms,
                    error=True,
                    timestamp=acc._pending_tool_timestamp,
                )
            )
            acc._pending_tool_name = ""
            acc._pending_tool_input = ""
            acc._pending_tool_timestamp = ""
            acc._pending_tool_start_ns = 0
            acc.has_error = True

    def _task_key(self, task_obj: Any) -> str:
        task_id = getattr(task_obj, "id", None)
        if task_id:
            return str(task_id)
        return str(id(task_obj)) if task_obj else "unknown"

    def _current_task_key(self) -> str | None:
        with self._lock:
            if not self._tasks:
                return None
            return next(reversed(self._tasks))

    def _current_acc(self) -> _TaskAccumulator | None:
        key = self._current_task_key()
        if key is None:
            return None
        with self._lock:
            return self._tasks.get(key)

    def _find_acc_for_agent(self, role: str) -> _TaskAccumulator | None:
        with self._lock:
            task_key = self._agent_task.get(role)
            if task_key:
                return self._tasks.get(task_key)
        return self._current_acc()

    def _flush_task(self, acc: _TaskAccumulator) -> None:
        trace = self._build_trace(acc)
        with self._lock:
            self._completed.append(trace)
            self._tasks.pop(acc.task_id, None)
            self._agent_task = {
                k: v for k, v in self._agent_task.items() if v != acc.task_id
            }
        if self._on_trace:
            self._on_trace(trace)
        else:
            self._write_default_sink(trace)

    def _flush_remaining(self) -> None:
        with self._lock:
            remaining = list(self._tasks.values())
        for acc in remaining:
            self._flush_task(acc)

    def _build_trace(self, acc: _TaskAccumulator) -> Trace:
        now = utc_now()
        duration_ms = 0
        if acc.started_at:
            from datetime import datetime

            try:
                start = datetime.fromisoformat(acc.started_at.replace("Z", "+00:00"))
                end = datetime.now(UTC)
                duration_ms = int((end - start).total_seconds() * 1000)
            except (ValueError, TypeError):
                pass

        metadata: dict[str, Any] = {**acc.metadata}
        if self._crew_name:
            metadata["crew_name"] = self._crew_name

        return Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or now,
            agent=self._agent,
            session_id=self._session_id,
            model=acc.model,
            task=acc.task_description,
            decision=acc.decision,
            status=Status.ERROR if acc.has_error else Status.COMPLETED,
            scope=acc.agent_role or None,
            tools_used=acc.tools,
            sources_read=acc.sources,
            turn_count=acc.llm_call_count,
            token_usage=acc.token_usage,
            duration_ms=duration_ms,
            metadata=metadata,
        )

    def _write_default_sink(self, trace: Trace) -> None:
        try:
            from openflux.sinks.sqlite import SQLiteSink

            sink = SQLiteSink()
            sink.write(trace)
            sink.close()
        except Exception:
            pass

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)
