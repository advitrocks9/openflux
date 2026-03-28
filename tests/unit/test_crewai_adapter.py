"""Simulated event tests for CrewAI adapter.

Uses a fake event bus that dispatches by class name, allowing us to emit
lightweight mock events that match the real crewai event names without
needing to construct complex crewai-internal objects.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from openflux.schema import Trace


def _has_crewai() -> bool:
    try:
        import crewai.events  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _has_crewai(), reason="crewai not installed")


class _FakeEventBus:
    """Dispatches by class identity. Handlers registered with real crewai
    event classes fire when we emit real instances of those classes."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[Any]] = {}

    def on(self, event_type: type) -> Any:
        def decorator(fn: Any) -> Any:
            self._handlers.setdefault(event_type, []).append(fn)
            return fn

        return decorator

    def emit(self, event: Any, source: Any = None) -> None:
        for handler in self._handlers.get(type(event), []):
            handler(source, event)


def _make_listener(
    agent: str = "test-crew",
    on_trace: Any = None,
) -> tuple[Any, _FakeEventBus]:
    """Construct an OpenFluxCrewListener wired to a fake event bus.

    Bypasses __init__ because the real BaseEventListener tries to register
    with the global crewai event bus, which we don't want in tests.
    """
    from openflux.adapters.crewai import OpenFluxCrewListener

    bus = _FakeEventBus()

    listener = object.__new__(OpenFluxCrewListener)
    listener._agent = agent
    listener._on_trace = on_trace
    listener._lock = threading.Lock()
    listener._session_id = "ses-test-session"
    listener._crew_name = ""
    listener._crew_started_at = ""
    listener._crew_trace_id = None
    listener._tasks = {}
    listener._agent_task = {}
    listener._completed = []
    listener._listeners_registered = False

    listener.setup_listeners(bus)
    return listener, bus


def _fake_task(
    task_id: str = "task-001", description: str = "Test task"
) -> SimpleNamespace:
    return SimpleNamespace(id=task_id, description=description)


def _fake_agent(role: str = "Researcher") -> SimpleNamespace:
    return SimpleNamespace(role=role)


def _crew_started(crew_name: str = "TestCrew") -> Any:
    """Build a real CrewKickoffStartedEvent with minimal required fields."""
    from crewai.events import CrewKickoffStartedEvent

    return CrewKickoffStartedEvent(crew_name=crew_name, inputs={})


def _crew_completed() -> Any:
    from crewai.events import CrewKickoffCompletedEvent

    evt = CrewKickoffCompletedEvent.__new__(CrewKickoffCompletedEvent)
    return evt


def _task_started(task: Any) -> Any:
    from crewai.events import TaskStartedEvent

    return TaskStartedEvent(context=None, task=task)


def _task_completed(task: Any, output: str = "") -> Any:
    from crewai.events import TaskCompletedEvent

    # Bypass pydantic validation — the adapter only reads via getattr
    evt = TaskCompletedEvent.__new__(TaskCompletedEvent)
    # Manually set the attributes the adapter reads
    object.__setattr__(evt, "output", output)
    object.__setattr__(evt, "task", task)
    return evt


def _agent_started(agent: Any, task: Any = None) -> Any:
    from crewai.events import AgentExecutionStartedEvent

    evt = AgentExecutionStartedEvent.__new__(AgentExecutionStartedEvent)
    object.__setattr__(evt, "agent", agent)
    object.__setattr__(evt, "task", task)
    object.__setattr__(evt, "tools", [])
    object.__setattr__(evt, "task_prompt", "")
    return evt


def _agent_completed(agent: Any, output: str = "") -> Any:
    from crewai.events import AgentExecutionCompletedEvent

    evt = AgentExecutionCompletedEvent.__new__(AgentExecutionCompletedEvent)
    object.__setattr__(evt, "agent", agent)
    object.__setattr__(evt, "output", output)
    object.__setattr__(evt, "task", None)
    return evt


def _llm_started() -> Any:
    from crewai.events import LLMCallStartedEvent

    evt = LLMCallStartedEvent.__new__(LLMCallStartedEvent)
    return evt


def _llm_completed(
    usage: dict[str, int] | None = None,
    model: str = "",
    response: str = "",
) -> Any:
    from crewai.events import LLMCallCompletedEvent

    evt = LLMCallCompletedEvent.__new__(LLMCallCompletedEvent)
    object.__setattr__(evt, "usage", usage)
    object.__setattr__(evt, "token_usage", None)
    object.__setattr__(evt, "model", model)
    object.__setattr__(evt, "model_name", "")
    object.__setattr__(evt, "response", response)
    return evt


def _tool_started(tool_name: str = "", tool_args: str = "") -> Any:
    from crewai.events import ToolUsageStartedEvent

    evt = ToolUsageStartedEvent.__new__(ToolUsageStartedEvent)
    object.__setattr__(evt, "tool_name", tool_name)
    object.__setattr__(evt, "name", "")
    object.__setattr__(evt, "tool_args", tool_args)
    object.__setattr__(evt, "arguments", "")
    return evt


def _tool_finished(result: str = "") -> Any:
    from crewai.events import ToolUsageFinishedEvent

    evt = ToolUsageFinishedEvent.__new__(ToolUsageFinishedEvent)
    object.__setattr__(evt, "result", result)
    return evt


def _tool_error(error: str = "") -> Any:
    from crewai.events import ToolUsageErrorEvent

    evt = ToolUsageErrorEvent.__new__(ToolUsageErrorEvent)
    object.__setattr__(evt, "error", error)
    return evt


class TestCrewAIFullWorkflow:
    """Fire a complete event sequence through the listener and verify the trace."""

    def test_full_trace_fields(self) -> None:
        captured: list[Trace] = []
        listener, bus = _make_listener(agent="test-crew", on_trace=captured.append)

        task = _fake_task(task_id="t1", description="Research AI safety trends")
        agent = _fake_agent(role="Researcher")

        bus.emit(_crew_started(crew_name="SafetyCrew"))
        bus.emit(_task_started(task=task))
        bus.emit(_agent_started(agent=agent, task=task))

        # LLM call 1
        bus.emit(_llm_started())
        bus.emit(
            _llm_completed(
                usage={"prompt_tokens": 500, "completion_tokens": 150},
                model="gpt-4o-mini",
                response="I need to search for recent AI safety papers.",
            )
        )

        # Tool usage
        bus.emit(_tool_started(tool_name="web_search", tool_args="AI safety 2025"))
        bus.emit(_tool_finished(result="Found 3 relevant papers"))

        # LLM call 2
        bus.emit(_llm_started())
        bus.emit(
            _llm_completed(
                usage={"prompt_tokens": 800, "completion_tokens": 200},
                model="gpt-4o-mini",
                response="Based on the search results, here are the key trends.",
            )
        )

        # Agent completes
        bus.emit(
            _agent_completed(
                agent=agent,
                output="AI safety trends: alignment, interpretability, governance.",
            )
        )

        # Task completes (triggers trace emission)
        bus.emit(_task_completed(task=task, output="Final report on AI safety"))

        assert len(captured) == 1
        trace = captured[0]

        # Core identity
        assert trace.id.startswith("trc-")
        assert trace.timestamp != ""
        assert trace.agent == "test-crew"
        assert trace.session_id.startswith("ses-")
        assert trace.schema_version == "0.2.0"

        # Model
        assert trace.model == "gpt-4o-mini"
        assert trace.status == "completed"

        # Task from TaskStartedEvent description
        assert trace.task == "Research AI safety trends"

        # Decision from AgentExecutionCompletedEvent output
        assert "AI safety trends" in trace.decision

        # Scope = agent role
        assert trace.scope == "Researcher"

        # Tags include crew name and agent role
        assert "SafetyCrew" in trace.tags
        assert "Researcher" in trace.tags

        # Token usage accumulated across LLM calls
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 1300
        assert trace.token_usage.output_tokens == 350

        # Turn count = LLM call count
        assert trace.turn_count == 2

        # Tools
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "web_search"
        assert trace.tools_used[0].tool_input == "AI safety 2025"
        assert trace.tools_used[0].tool_output == "Found 3 relevant papers"

        # Sources from LLM responses
        assert len(trace.sources_read) >= 1

        # Duration should be non-negative
        assert trace.duration_ms >= 0

        # Metadata includes crew_name
        assert trace.metadata.get("crew_name") == "SafetyCrew"

    def test_tool_error_sets_error_status(self) -> None:
        """ToolUsageErrorEvent should mark the trace as errored."""
        captured: list[Trace] = []
        listener, bus = _make_listener(agent="err-crew", on_trace=captured.append)

        task = _fake_task(task_id="t-err", description="Failing task")
        bus.emit(_task_started(task=task))

        bus.emit(_llm_started())
        bus.emit(
            _llm_completed(
                usage={"prompt_tokens": 100, "completion_tokens": 30},
                model="gpt-4o-mini",
            )
        )

        bus.emit(_tool_started(tool_name="broken_api", tool_args="params"))
        bus.emit(_tool_error(error="ConnectionError: timed out"))

        bus.emit(_task_completed(task=task))

        assert len(captured) == 1
        trace = captured[0]
        assert trace.status == "error"
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].error is True
        assert "timed out" in trace.tools_used[0].tool_output

    def test_multiple_tasks_produce_separate_traces(self) -> None:
        """Each task completion should emit an independent trace."""
        captured: list[Trace] = []
        listener, bus = _make_listener(agent="multi-crew", on_trace=captured.append)

        bus.emit(_crew_started(crew_name="MultiCrew"))

        for i in range(3):
            task = _fake_task(task_id=f"t-{i}", description=f"Task number {i}")
            bus.emit(_task_started(task=task))
            bus.emit(_llm_started())
            bus.emit(
                _llm_completed(
                    usage={"prompt_tokens": 100, "completion_tokens": 50},
                    model="gpt-4o-mini",
                )
            )
            bus.emit(_task_completed(task=task, output=f"Result {i}"))

        assert len(captured) == 3
        for i, trace in enumerate(captured):
            assert trace.task == f"Task number {i}"

    def test_crew_completed_flushes_remaining(self) -> None:
        """CrewKickoffCompletedEvent should flush any tasks not yet completed."""
        captured: list[Trace] = []
        listener, bus = _make_listener(agent="flush-crew", on_trace=captured.append)

        task = _fake_task(task_id="t-orphan", description="Orphan task")
        bus.emit(_task_started(task=task))
        bus.emit(_llm_started())
        bus.emit(
            _llm_completed(
                usage={"prompt_tokens": 200, "completion_tokens": 60},
                model="gpt-4o-mini",
            )
        )

        bus.emit(_crew_completed())

        assert len(captured) == 1
        assert captured[0].task == "Orphan task"

    def test_completed_traces_property(self) -> None:
        """completed_traces should accumulate across task completions."""
        listener, bus = _make_listener(agent="prop-crew")

        for i in range(2):
            task = _fake_task(task_id=f"prop-{i}", description=f"Prop task {i}")
            bus.emit(_task_started(task=task))
            bus.emit(_task_completed(task=task, output=f"Done {i}"))

        assert len(listener.completed_traces) == 2

    def test_tool_duration_measured(self) -> None:
        """Tool duration should be computed from start to finish."""
        captured: list[Trace] = []
        listener, bus = _make_listener(agent="dur-crew", on_trace=captured.append)

        task = _fake_task(task_id="t-dur", description="Duration test")
        bus.emit(_task_started(task=task))

        bus.emit(_tool_started(tool_name="slow_tool", tool_args="input"))
        time.sleep(0.01)
        bus.emit(_tool_finished(result="done"))

        bus.emit(_task_completed(task=task))

        trace = captured[0]
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].duration_ms >= 5
