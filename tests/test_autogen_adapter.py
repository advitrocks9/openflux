from __future__ import annotations

from typing import Any

import pytest

from openflux.schema import Status


class FakeRequestUsage:
    def __init__(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class FakeFunctionCall:
    def __init__(self, id: str = "", name: str = "", arguments: str = "") -> None:
        self.id = id
        self.name = name
        self.arguments = arguments


class FakeFunctionExecutionResult:
    def __init__(
        self,
        call_id: str = "",
        name: str = "",
        content: str = "",
        is_error: bool = False,
    ) -> None:
        self.call_id = call_id
        self.name = name
        self.content = content
        self.is_error = is_error


class TextMessage:
    def __init__(
        self,
        source: str = "agent",
        content: str = "",
        models_usage: FakeRequestUsage | None = None,
    ) -> None:
        self.source = source
        self.content = content
        self.models_usage = models_usage


class ToolCallRequestEvent:
    def __init__(
        self,
        source: str = "agent",
        content: list[FakeFunctionCall] | None = None,
        models_usage: FakeRequestUsage | None = None,
    ) -> None:
        self.source = source
        self.content = content or []
        self.models_usage = models_usage


class ToolCallExecutionEvent:
    def __init__(
        self,
        source: str = "agent",
        content: list[FakeFunctionExecutionResult] | None = None,
    ) -> None:
        self.source = source
        self.content = content or []
        self.models_usage = None


class HandoffMessage:
    def __init__(
        self,
        source: str = "agent-a",
        target: str = "agent-b",
        content: str = "",
        models_usage: FakeRequestUsage | None = None,
    ) -> None:
        self.source = source
        self.target = target
        self.content = content
        self.models_usage = models_usage


class StopMessage:
    def __init__(
        self,
        source: str = "agent",
        content: str = "task complete",
        models_usage: FakeRequestUsage | None = None,
    ) -> None:
        self.source = source
        self.content = content
        self.models_usage = models_usage


class ToolCallSummaryMessage:
    def __init__(
        self,
        source: str = "agent",
        content: str = "",
        models_usage: FakeRequestUsage | None = None,
    ) -> None:
        self.source = source
        self.content = content
        self.models_usage = models_usage


class TaskResult:
    def __init__(
        self,
        messages: list[Any] | None = None,
        stop_reason: str | None = None,
    ) -> None:
        self.messages = messages or []
        self.stop_reason = stop_reason


@pytest.fixture()
def consumer() -> Any:
    from openflux.adapters.autogen import AutoGenStreamConsumer

    traces: list[Any] = []
    c = AutoGenStreamConsumer(agent="test-team", on_trace=traces.append)
    c._test_traces = traces
    return c


class TestImportGuard:
    def test_loads_without_sdk(self) -> None:
        from openflux.adapters.autogen import _HAS_AUTOGEN

        assert isinstance(_HAS_AUTOGEN, bool)

    def test_instantiates_without_sdk(self) -> None:
        from openflux.adapters.autogen import AutoGenStreamConsumer

        c = AutoGenStreamConsumer(agent="test")
        assert c._agent == "test"


class TestBasicLifecycle:
    def test_flush_on_stop_message(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="bot", content="hello"))
        consumer.process(StopMessage(source="bot"))
        assert len(consumer._test_traces) == 1
        assert consumer._test_traces[0].agent == "test-team"
        assert consumer._test_traces[0].status == Status.COMPLETED

    def test_flush_on_task_result(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="bot", content="done"))
        consumer.process(TaskResult(stop_reason="max turns reached"))
        assert len(consumer._test_traces) == 1
        assert (
            consumer._test_traces[0].metadata.get("stop_reason") == "max turns reached"
        )

    def test_manual_flush(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="bot"))
        trace = consumer.flush()
        assert trace is not None
        assert trace.agent == "test-team"

    def test_flush_empty_returns_none(self, consumer: Any) -> None:
        # Before any trace is emitted, flush returns None
        assert consumer.flush() is None

    def test_double_flush_returns_last_trace(self, consumer: Any) -> None:
        """After auto-flush (StopMessage), manual flush returns cached trace."""
        consumer.process(TextMessage(source="bot", content="hello"))
        consumer.process(StopMessage(source="bot"))
        # Auto-flush already happened; second flush returns the same trace
        trace = consumer.flush()
        assert trace is not None
        assert trace.agent == "test-team"

    def test_completed_traces_property(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="bot"))
        consumer.process(StopMessage())
        assert len(consumer.completed_traces) == 1


class TestTokenUsage:
    def test_extracts_from_text_message(self, consumer: Any) -> None:
        consumer.process(
            TextMessage(
                source="bot",
                models_usage=FakeRequestUsage(prompt_tokens=100, completion_tokens=50),
            )
        )
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 100
        assert trace.token_usage.output_tokens == 50

    def test_accumulates_across_messages(self, consumer: Any) -> None:
        for _ in range(3):
            consumer.process(
                TextMessage(
                    source="bot",
                    models_usage=FakeRequestUsage(
                        prompt_tokens=50, completion_tokens=20
                    ),
                )
            )
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 150
        assert trace.token_usage.output_tokens == 60

    def test_none_usage_ignored(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="bot", models_usage=None))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 0


class TestToolCalls:
    def test_request_and_execution_paired(self, consumer: Any) -> None:
        consumer.process(
            ToolCallRequestEvent(
                source="bot",
                content=[
                    FakeFunctionCall(
                        id="call-1", name="calculator", arguments='{"x": 2}'
                    )
                ],
            )
        )
        consumer.process(
            ToolCallExecutionEvent(
                source="bot",
                content=[FakeFunctionExecutionResult(call_id="call-1", content="4")],
            )
        )
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "calculator"
        assert trace.tools_used[0].tool_input == '{"x": 2}'
        assert trace.tools_used[0].tool_output == "4"
        # ToolCallRequestEvent counts as a turn (agent action)
        assert trace.turn_count == 1

    def test_execution_error_sets_status(self, consumer: Any) -> None:
        consumer.process(
            ToolCallRequestEvent(
                source="bot",
                content=[FakeFunctionCall(id="c1", name="risky_tool", arguments="")],
            )
        )
        consumer.process(
            ToolCallExecutionEvent(
                source="bot",
                content=[
                    FakeFunctionExecutionResult(
                        call_id="c1",
                        content="boom",
                        is_error=True,
                    )
                ],
            )
        )
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.status == Status.ERROR
        assert trace.tools_used[0].error is True

    def test_unmatched_execution_creates_standalone(self, consumer: Any) -> None:
        consumer.process(
            ToolCallExecutionEvent(
                source="bot",
                content=[
                    FakeFunctionExecutionResult(
                        call_id="orphan",
                        name="mystery",
                        content="result",
                    )
                ],
            )
        )
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "mystery"

    def test_multiple_parallel_tool_calls(self, consumer: Any) -> None:
        consumer.process(
            ToolCallRequestEvent(
                source="bot",
                content=[
                    FakeFunctionCall(id="c1", name="tool_a", arguments="a"),
                    FakeFunctionCall(id="c2", name="tool_b", arguments="b"),
                ],
            )
        )
        consumer.process(
            ToolCallExecutionEvent(
                source="bot",
                content=[
                    FakeFunctionExecutionResult(call_id="c1", content="ra"),
                    FakeFunctionExecutionResult(call_id="c2", content="rb"),
                ],
            )
        )
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert len(trace.tools_used) == 2
        assert trace.tools_used[0].tool_output == "ra"
        assert trace.tools_used[1].tool_output == "rb"


class TestSearchClassification:
    def test_search_tool_classified(self, consumer: Any) -> None:
        consumer.process(
            ToolCallRequestEvent(
                source="bot",
                content=[
                    FakeFunctionCall(
                        id="s1", name="web_search", arguments="python docs"
                    )
                ],
            )
        )
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert len(trace.searches) == 1
        assert trace.searches[0].engine == "web_search"
        assert trace.searches[0].query == "python docs"
        assert len(trace.tools_used) == 0

    def test_custom_search_tools(self) -> None:
        from openflux.adapters.autogen import AutoGenStreamConsumer

        traces: list[Any] = []
        c = AutoGenStreamConsumer(
            agent="test",
            search_tools={"my_search"},
            on_trace=traces.append,
        )
        c.process(
            ToolCallRequestEvent(
                source="bot",
                content=[FakeFunctionCall(id="s1", name="my_search", arguments="q")],
            )
        )
        c.process(StopMessage())
        assert len(traces[0].searches) == 1


class TestHandoff:
    def test_records_handoff(self, consumer: Any) -> None:
        consumer.process(HandoffMessage(source="planner", target="coder"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert "handoffs" in trace.metadata
        assert trace.metadata["handoffs"][0] == {
            "from_agent": "planner",
            "to_agent": "coder",
        }


class TestAgentTracking:
    def test_tracks_multiple_agents(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="planner"))
        consumer.process(TextMessage(source="coder"))
        consumer.process(TextMessage(source="planner"))  # deduplicated
        consumer.process(StopMessage(source="coder"))
        trace = consumer._test_traces[0]
        assert trace.metadata.get("agents_seen") == ["planner", "coder"]


class TestTaskExtraction:
    def test_extracts_task_from_first_user_message(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="user", content="Count from 1 to 3."))
        consumer.process(TextMessage(source="planner", content="I'll count now."))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.task == "Count from 1 to 3."

    def test_ignores_subsequent_user_messages(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="user", content="First task"))
        consumer.process(TextMessage(source="user", content="Second message"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.task == "First task"

    def test_ignores_non_user_for_task(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="planner", content="I'm thinking"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.task == ""


class TestTurnCount:
    def test_counts_non_user_text_messages(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="user", content="do something"))
        consumer.process(TextMessage(source="planner", content="planning"))
        consumer.process(TextMessage(source="executor", content="executing"))
        consumer.process(TextMessage(source="planner", content="reviewing"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.turn_count == 3

    def test_user_messages_not_counted(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="user", content="task"))
        consumer.process(TextMessage(source="user", content="follow up"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.turn_count == 0


class TestDecision:
    def test_captures_last_agent_message(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="planner", content="step 1"))
        consumer.process(TextMessage(source="executor", content="final answer"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.decision == "final answer"

    def test_ignores_user_messages(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="user", content="user says"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.decision == ""


class TestModel:
    def test_model_from_constructor(self) -> None:
        from openflux.adapters.autogen import AutoGenStreamConsumer

        traces: list[Any] = []
        c = AutoGenStreamConsumer(
            agent="test", model="gpt-4o-mini", on_trace=traces.append
        )
        c.process(TextMessage(source="bot", content="hi"))
        c.process(StopMessage())
        assert traces[0].model == "gpt-4o-mini"

    def test_model_default_empty(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="bot"))
        consumer.process(StopMessage())
        assert consumer._test_traces[0].model == ""


class TestDuration:
    def test_duration_ms_positive(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="bot", content="working"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.duration_ms >= 0


class TestMultipleRuns:
    def test_second_run_starts_fresh(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="bot"))
        consumer.process(StopMessage())
        consumer.process(TextMessage(source="bot2"))
        consumer.process(StopMessage())
        assert len(consumer._test_traces) == 2
        assert (
            consumer._test_traces[0].session_id != consumer._test_traces[1].session_id
        )


class TestTurnCountExpanded:
    """Issue 2: ToolCallRequestEvent and HandoffMessage count as turns."""

    def test_tool_request_counts_as_turn(self, consumer: Any) -> None:
        consumer.process(
            ToolCallRequestEvent(
                source="bot",
                content=[FakeFunctionCall(id="c1", name="calc", arguments="1+1")],
            )
        )
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.turn_count == 1

    def test_handoff_counts_as_turn(self, consumer: Any) -> None:
        consumer.process(HandoffMessage(source="planner", target="coder"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert trace.turn_count == 1

    def test_mixed_turns(self, consumer: Any) -> None:
        """TextMessage + ToolCallRequest + Handoff all counted."""
        consumer.process(TextMessage(source="planner", content="thinking"))
        consumer.process(
            ToolCallRequestEvent(
                source="planner",
                content=[FakeFunctionCall(id="c1", name="t", arguments="")],
            )
        )
        consumer.process(HandoffMessage(source="planner", target="coder"))
        consumer.process(TextMessage(source="coder", content="done"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        # 1 text (planner) + 1 tool request + 1 handoff + 1 text (coder)
        assert trace.turn_count == 4


class TestToolDuration:
    """Issue 3: ToolRecord.duration_ms from created_at timestamps."""

    def test_duration_computed_from_created_at(self) -> None:
        from datetime import UTC, datetime, timedelta

        from openflux.adapters.autogen import AutoGenStreamConsumer

        traces: list[Any] = []
        c = AutoGenStreamConsumer(agent="test", on_trace=traces.append)

        t0 = datetime(2026, 1, 1, tzinfo=UTC)
        t1 = t0 + timedelta(milliseconds=250)

        req = ToolCallRequestEvent(
            source="bot",
            content=[FakeFunctionCall(id="c1", name="slow_tool", arguments="x")],
        )
        req.created_at = t0  # type: ignore[attr-defined]

        exe = ToolCallExecutionEvent(
            source="bot",
            content=[FakeFunctionExecutionResult(call_id="c1", content="done")],
        )
        exe.created_at = t1  # type: ignore[attr-defined]

        c.process(req)
        c.process(exe)
        c.process(StopMessage())
        assert traces[0].tools_used[0].duration_ms == 250


class TestScope:
    """Issue 4: scope passed via constructor."""

    def test_scope_set(self) -> None:
        from openflux.adapters.autogen import AutoGenStreamConsumer

        traces: list[Any] = []
        c = AutoGenStreamConsumer(
            agent="test", scope="round_robin", on_trace=traces.append
        )
        c.process(TextMessage(source="bot"))
        c.process(StopMessage())
        assert traces[0].scope == "round_robin"

    def test_scope_default_none(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="bot"))
        consumer.process(StopMessage())
        assert consumer._test_traces[0].scope is None


class TestTags:
    """Issue 5: tags from constructor + auto-generated agent tags."""

    def test_user_tags_passed(self) -> None:
        from openflux.adapters.autogen import AutoGenStreamConsumer

        traces: list[Any] = []
        c = AutoGenStreamConsumer(
            agent="test", tags=["env:prod"], on_trace=traces.append
        )
        c.process(TextMessage(source="bot"))
        c.process(StopMessage())
        assert "env:prod" in traces[0].tags

    def test_auto_agent_tags(self, consumer: Any) -> None:
        consumer.process(TextMessage(source="planner", content="hi"))
        consumer.process(TextMessage(source="coder", content="done"))
        consumer.process(StopMessage())
        trace = consumer._test_traces[0]
        assert "agent:planner" in trace.tags
        assert "agent:coder" in trace.tags


class TestContext:
    """Issue 6: context injected via constructor."""

    def test_context_injected(self) -> None:
        from openflux.adapters.autogen import AutoGenStreamConsumer
        from openflux.schema import ContextRecord, ContextType

        ctx = ContextRecord(
            type=ContextType.SYSTEM_PROMPT,
            source="user",
            content="You are a helpful assistant.",
        )
        traces: list[Any] = []
        c = AutoGenStreamConsumer(agent="test", context=[ctx], on_trace=traces.append)
        c.process(TextMessage(source="bot"))
        c.process(StopMessage())
        assert len(traces[0].context) == 1
        assert traces[0].context[0].content == "You are a helpful assistant."


class TestSourceTools:
    """Issue 7: source_tools heuristic creates SourceRecords."""

    def test_source_tool_creates_record(self) -> None:
        from openflux.adapters.autogen import AutoGenStreamConsumer

        traces: list[Any] = []
        c = AutoGenStreamConsumer(agent="test", on_trace=traces.append)
        c.process(
            ToolCallRequestEvent(
                source="bot",
                content=[
                    FakeFunctionCall(id="c1", name="read_file", arguments="f.txt")
                ],
            )
        )
        c.process(
            ToolCallExecutionEvent(
                source="bot",
                content=[
                    FakeFunctionExecutionResult(
                        call_id="c1", name="read_file", content="file contents here"
                    )
                ],
            )
        )
        c.process(StopMessage())
        trace = traces[0]
        assert len(trace.sources_read) == 1
        assert trace.sources_read[0].tool == "read_file"
        assert trace.sources_read[0].content == "file contents here"

    def test_custom_source_tools(self) -> None:
        from openflux.adapters.autogen import AutoGenStreamConsumer

        traces: list[Any] = []
        c = AutoGenStreamConsumer(
            agent="test",
            source_tools={"my_reader"},
            on_trace=traces.append,
        )
        c.process(
            ToolCallRequestEvent(
                source="bot",
                content=[
                    FakeFunctionCall(id="c1", name="my_reader", arguments="doc.pdf")
                ],
            )
        )
        c.process(
            ToolCallExecutionEvent(
                source="bot",
                content=[
                    FakeFunctionExecutionResult(
                        call_id="c1", name="my_reader", content="pdf text"
                    )
                ],
            )
        )
        c.process(StopMessage())
        assert len(traces[0].sources_read) == 1

    def test_non_source_tool_no_record(self, consumer: Any) -> None:
        consumer.process(
            ToolCallRequestEvent(
                source="bot",
                content=[FakeFunctionCall(id="c1", name="calculator", arguments="2+2")],
            )
        )
        consumer.process(
            ToolCallExecutionEvent(
                source="bot",
                content=[
                    FakeFunctionExecutionResult(
                        call_id="c1", name="calculator", content="4"
                    )
                ],
            )
        )
        consumer.process(StopMessage())
        assert len(consumer._test_traces[0].sources_read) == 0
