"""Simulated event tests for AutoGen v0.4 adapter.

Constructs mock message objects matching AutoGen's stream types and feeds
them through the AutoGenStreamConsumer, proving field extraction works
without making real API calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from openflux.adapters.autogen import AutoGenStreamConsumer
from openflux.schema import ContextRecord, ContextType, Trace

# The adapter dispatches via type(message).__name__, so we need classes
# whose names match exactly what AutoGen produces.


class TextMessage:
    def __init__(
        self,
        source: str = "assistant",
        content: str = "",
        models_usage: Any = None,
    ) -> None:
        self.source = source
        self.content = content
        self.models_usage = models_usage


class ToolCallRequestEvent:
    def __init__(
        self,
        source: str = "assistant",
        content: list[Any] | None = None,
        models_usage: Any = None,
        created_at: datetime | None = None,
    ) -> None:
        self.source = source
        self.content = content or []
        self.models_usage = models_usage
        self.created_at = created_at


class ToolCallExecutionEvent:
    def __init__(
        self,
        source: str = "assistant",
        content: list[Any] | None = None,
        models_usage: Any = None,
        created_at: datetime | None = None,
    ) -> None:
        self.source = source
        self.content = content or []
        self.models_usage = models_usage
        self.created_at = created_at


class StopMessage:
    def __init__(
        self,
        source: str = "assistant",
        content: str = "TERMINATE",
        models_usage: Any = None,
    ) -> None:
        self.source = source
        self.content = content
        self.models_usage = models_usage


class TaskResult:
    def __init__(self, stop_reason: str = "") -> None:
        self.stop_reason = stop_reason


class HandoffMessage:
    def __init__(
        self,
        source: str = "",
        target: str = "",
        models_usage: Any = None,
    ) -> None:
        self.source = source
        self.target = target
        self.models_usage = models_usage


class ToolCallSummaryMessage:
    def __init__(
        self,
        source: str = "assistant",
        models_usage: Any = None,
    ) -> None:
        self.source = source
        self.models_usage = models_usage


def _tool_call(
    name: str = "calculate",
    arguments: str = '{"x": 1}',
    call_id: str = "call-001",
) -> SimpleNamespace:
    return SimpleNamespace(name=name, arguments=arguments, id=call_id)


def _tool_result(
    call_id: str = "call-001",
    content: str = "42",
    is_error: bool = False,
    name: str = "calculate",
) -> SimpleNamespace:
    return SimpleNamespace(
        call_id=call_id, content=content, is_error=is_error, name=name
    )


def _usage(prompt_tokens: int = 0, completion_tokens: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )


class TestAutoGenFullWorkflow:
    """Complete message stream through the consumer, verifying all extracted fields."""

    def test_full_trace_fields(self) -> None:
        captured: list[Trace] = []
        context = [
            ContextRecord(
                type=ContextType.SYSTEM_PROMPT,
                source="config",
                content="You are a math assistant.",
                content_hash="abc",
                bytes=25,
            )
        ]
        consumer = AutoGenStreamConsumer(
            agent="test-autogen",
            model="gpt-4o-mini",
            scope="math-tasks",
            tags=["testing"],
            context=context,
            on_trace=captured.append,
        )

        # 1. User sends task
        consumer.process(
            TextMessage(
                source="user",
                content="Calculate 6 * 7 and search for prime numbers",
            )
        )

        # 2. Agent responds (turn 1)
        consumer.process(
            TextMessage(
                source="math_agent",
                content="I'll calculate that for you.",
                models_usage=_usage(prompt_tokens=200, completion_tokens=50),
            )
        )

        # 3. Tool call request: search tool + regular tool
        t0 = datetime.now(UTC)
        consumer.process(
            ToolCallRequestEvent(
                source="math_agent",
                content=[
                    _tool_call(name="search", arguments="prime numbers", call_id="c1"),
                    _tool_call(
                        name="calculate", arguments='{"expr": "6*7"}', call_id="c2"
                    ),
                ],
                models_usage=_usage(prompt_tokens=100, completion_tokens=30),
                created_at=t0,
            )
        )

        # 4. Tool execution results
        t1 = t0 + timedelta(milliseconds=500)
        consumer.process(
            ToolCallExecutionEvent(
                source="math_agent",
                content=[
                    _tool_result(call_id="c1", content="search results here"),
                    _tool_result(call_id="c2", content="42"),
                ],
                created_at=t1,
            )
        )

        # 5. Agent final response (turn 2)
        consumer.process(
            TextMessage(
                source="math_agent",
                content="The answer is 42. Here are some prime numbers.",
                models_usage=_usage(prompt_tokens=300, completion_tokens=80),
            )
        )

        # 6. Stop triggers trace emission
        consumer.process(StopMessage(source="math_agent", content="TERMINATE"))

        assert len(captured) == 1
        trace = captured[0]

        # Core identity
        assert trace.id.startswith("trc-")
        assert trace.timestamp != ""
        assert trace.agent == "test-autogen"
        assert trace.session_id.startswith("ses-")
        assert trace.schema_version == "0.2.0"

        # Model set from constructor
        assert trace.model == "gpt-4o-mini"
        assert trace.status == "completed"

        # Task from first user message
        assert "Calculate 6 * 7" in trace.task

        # Decision from last non-user TextMessage
        assert "The answer is 42" in trace.decision

        # Scope and tags from constructor
        assert trace.scope == "math-tasks"
        assert "testing" in trace.tags

        # Context passed through
        assert len(trace.context) == 1
        assert trace.context[0].content == "You are a math assistant."

        # Token usage accumulated across messages
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 600  # 200 + 100 + 300
        assert trace.token_usage.output_tokens == 160  # 50 + 30 + 80

        # Turn count: 2 TextMessages from agent + 1 ToolCallRequest
        assert trace.turn_count >= 3

        # Searches from "search" tool
        assert len(trace.searches) == 1
        assert trace.searches[0].engine == "search"

        # Tools: only "calculate" (search excluded from tools_used)
        assert len(trace.tools_used) >= 1
        calc_tools = [t for t in trace.tools_used if t.name == "calculate"]
        assert len(calc_tools) == 1
        assert calc_tools[0].tool_output == "42"

        # Duration calculated from tool timestamps
        assert calc_tools[0].duration_ms == 500

        # Metadata: stop_reason + agents_seen
        assert trace.metadata.get("stop_reason") == "TERMINATE"
        assert "math_agent" in trace.metadata.get("agents_seen", [])

    def test_error_propagation(self) -> None:
        """Tool execution error should set trace status to error."""
        captured: list[Trace] = []
        consumer = AutoGenStreamConsumer(agent="err-autogen", on_trace=captured.append)

        consumer.process(TextMessage(source="user", content="Do something"))
        consumer.process(
            ToolCallRequestEvent(
                source="agent",
                content=[_tool_call(name="broken", call_id="c-err")],
            )
        )
        consumer.process(
            ToolCallExecutionEvent(
                source="agent",
                content=[
                    _tool_result(
                        call_id="c-err",
                        content="Connection refused",
                        is_error=True,
                        name="broken",
                    ),
                ],
            )
        )

        trace = consumer.flush()
        assert trace is not None
        assert trace.status == "error"

    def test_handoff_tracked(self) -> None:
        """HandoffMessage should appear in metadata."""
        captured: list[Trace] = []
        consumer = AutoGenStreamConsumer(agent="handoff-test", on_trace=captured.append)

        consumer.process(TextMessage(source="user", content="Route this"))
        consumer.process(HandoffMessage(source="Triage", target="Expert"))

        trace = consumer.flush()
        assert trace is not None
        assert "handoffs" in trace.metadata
        assert trace.metadata["handoffs"][0]["from_agent"] == "Triage"
        assert trace.metadata["handoffs"][0]["to_agent"] == "Expert"

    def test_task_result_triggers_flush(self) -> None:
        """TaskResult message should auto-flush the accumulator."""
        captured: list[Trace] = []
        consumer = AutoGenStreamConsumer(
            agent="task-result-test", on_trace=captured.append
        )

        consumer.process(TextMessage(source="user", content="Run the job"))
        consumer.process(
            TextMessage(
                source="worker",
                content="Done",
                models_usage=_usage(prompt_tokens=50, completion_tokens=20),
            )
        )
        consumer.process(TaskResult(stop_reason="completed"))

        assert len(captured) == 1
        assert captured[0].metadata.get("stop_reason") == "completed"

    def test_source_tools_produce_source_records(self) -> None:
        """Tools in source_tools set should generate SourceRecords."""
        captured: list[Trace] = []
        consumer = AutoGenStreamConsumer(
            agent="source-test",
            source_tools={"read_file"},
            on_trace=captured.append,
        )

        consumer.process(TextMessage(source="user", content="Read config"))
        consumer.process(
            ToolCallRequestEvent(
                source="agent",
                content=[
                    _tool_call(
                        name="read_file", arguments="/etc/config", call_id="c-rf"
                    )
                ],
            )
        )
        consumer.process(
            ToolCallExecutionEvent(
                source="agent",
                content=[
                    _tool_result(
                        call_id="c-rf",
                        content="key=value",
                        name="read_file",
                    ),
                ],
            )
        )

        trace = consumer.flush()
        assert trace is not None
        assert len(trace.sources_read) == 1
        assert trace.sources_read[0].type == "tool_result"
        assert trace.sources_read[0].tool == "read_file"

    def test_flush_returns_cached_after_auto_flush(self) -> None:
        """Calling flush() after StopMessage auto-flushed should return cached trace."""
        captured: list[Trace] = []
        consumer = AutoGenStreamConsumer(agent="cache-test", on_trace=captured.append)

        consumer.process(TextMessage(source="user", content="hello"))
        consumer.process(StopMessage(source="agent"))

        # First flush already happened via StopMessage
        assert len(captured) == 1

        # Second explicit flush returns the cached trace
        cached = consumer.flush()
        assert cached is not None
        assert cached.id == captured[0].id

    def test_completed_traces_accumulate(self) -> None:
        """Multiple runs through the same consumer accumulate in completed_traces."""
        consumer = AutoGenStreamConsumer(agent="multi-run")

        for i in range(3):
            consumer.process(TextMessage(source="user", content=f"task {i}"))
            consumer.process(TextMessage(source="agent", content=f"done {i}"))
            consumer.flush()

        assert len(consumer.completed_traces) == 3
