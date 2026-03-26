from __future__ import annotations

from typing import Any

import pytest

from openflux.schema import Status


class FakeTrace:
    def __init__(
        self,
        trace_id: str = "trace-001",
        workflow_name: str = "",
        name: str = "",
        group_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.workflow_name = workflow_name
        self.name = name
        self.group_id = group_id
        self.metadata = metadata


class FakeSpan:
    def __init__(
        self,
        trace_id: str = "trace-001",
        span_data: Any = None,
        error: Any = None,
        started_at: str = "",
        ended_at: str = "",
    ) -> None:
        self.trace_id = trace_id
        self.span_data = span_data
        self.error = error
        self.started_at = started_at
        self.ended_at = ended_at


class AgentSpanData:
    def __init__(self, name: str = "my-agent", output_type: str | None = None) -> None:
        self.name = name
        self.output_type = output_type


class GenerationSpanData:
    def __init__(
        self,
        model: str = "gpt-4o",
        usage: dict[str, int] | None = None,
        output: list[dict[str, Any]] | None = None,
    ) -> None:
        self.model = model
        self.usage = usage
        self.output = output


class FunctionSpanData:
    def __init__(
        self,
        name: str = "calculator",
        input: str | dict[str, Any] = "",
        output: str | dict[str, Any] = "",
    ) -> None:
        self.name = name
        self.input = input
        self.output = output


class HandoffSpanData:
    def __init__(self, from_agent: str = "agent-a", to_agent: str = "agent-b") -> None:
        self.from_agent = from_agent
        self.to_agent = to_agent


class GuardrailSpanData:
    def __init__(self, name: str = "content-filter", triggered: bool = False) -> None:
        self.name = name
        self.triggered = triggered


@pytest.fixture()
def processor() -> Any:
    from openflux.adapters.openai_agents import OpenFluxProcessor

    traces: list[Any] = []
    proc = OpenFluxProcessor(agent="test-agent", on_trace=traces.append)
    proc._test_traces = traces
    return proc


def _span(
    trace_id: str = "t1",
    span_data: Any = None,
    error: Any = None,
    started_at: str = "",
    ended_at: str = "",
) -> FakeSpan:
    return FakeSpan(
        trace_id=trace_id,
        span_data=span_data,
        error=error,
        started_at=started_at,
        ended_at=ended_at,
    )


class TestImportGuard:
    def test_loads_without_sdk(self) -> None:
        from openflux.adapters.openai_agents import _HAS_AGENTS

        assert isinstance(_HAS_AGENTS, bool)

    def test_instantiates_without_sdk(self) -> None:
        from openflux.adapters.openai_agents import OpenFluxProcessor

        proc = OpenFluxProcessor(agent="test")
        assert proc._agent == "test"


class TestTraceLifecycle:
    def test_simple_trace(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        traces = processor._test_traces
        assert len(traces) == 1
        assert traces[0].session_id == "t1"
        assert traces[0].agent == "test-agent"
        assert traces[0].status == Status.COMPLETED

    def test_end_without_start_noop(self, processor: Any) -> None:
        processor.on_trace_end(FakeTrace(trace_id="unknown"))
        assert len(processor._test_traces) == 0

    def test_completed_traces(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        assert len(processor.completed_traces) == 1


class TestSpanHandling:
    def test_agent_span(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=AgentSpanData(
                    name="research-agent", output_type="CalendarEvent"
                ),
            )
        )
        processor.on_trace_end(trace)
        result = processor._test_traces[0]
        assert result.metadata.get("output_type") == "CalendarEvent"

    def test_generation_span(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=GenerationSpanData(
                    model="gpt-4o", usage={"input_tokens": 100, "output_tokens": 50}
                ),
            )
        )
        processor.on_trace_end(trace)
        trace = processor._test_traces[0]
        assert trace.model == "gpt-4o"
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 100
        assert trace.token_usage.output_tokens == 50

    def test_function_span(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=FunctionSpanData(
                    name="calculator", input='{"expr": "2+2"}', output="4"
                ),
            )
        )
        processor.on_trace_end(trace)
        trace = processor._test_traces[0]
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "calculator"
        # turn_count tracks generation spans, not tool calls
        assert trace.turn_count == 0

    def test_function_span_dict_io(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=FunctionSpanData(
                    name="api_call",
                    input={"url": "https://api.example.com"},
                    output={"status": 200},
                ),
            )
        )
        processor.on_trace_end(trace)
        assert '"url"' in processor._test_traces[0].tools_used[0].tool_input

    def test_handoff_span(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=HandoffSpanData(from_agent="agent-a", to_agent="agent-b"),
            )
        )
        processor.on_trace_end(trace)
        trace = processor._test_traces[0]
        assert "handoffs" in trace.metadata
        assert trace.metadata["handoffs"][0]["to_agent"] == "agent-b"

    def test_guardrail_span(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=GuardrailSpanData(name="content-filter", triggered=True),
            )
        )
        processor.on_trace_end(trace)
        trace = processor._test_traces[0]
        assert "guardrails" in trace.metadata
        assert trace.metadata["guardrails"][0]["triggered"] is True

    def test_error_sets_status(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=FunctionSpanData(name="broken"),
                error="RuntimeError: boom",
            )
        )
        processor.on_trace_end(trace)
        assert processor._test_traces[0].status == Status.ERROR

    def test_no_span_data_skipped(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(_span(span_data=None))
        processor.on_trace_end(trace)
        assert len(processor._test_traces[0].tools_used) == 0


class TestSearchToolClassification:
    def test_default_search_tools(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=FunctionSpanData(name="web_search", input="query"),
            )
        )
        processor.on_trace_end(trace)
        trace = processor._test_traces[0]
        assert len(trace.searches) == 1
        assert trace.searches[0].engine == "web_search"
        assert len(trace.tools_used) == 0

    def test_custom_search_tools(self) -> None:
        from openflux.adapters.openai_agents import OpenFluxProcessor

        traces: list[Any] = []
        proc = OpenFluxProcessor(
            agent="test", search_tools={"my_search"}, on_trace=traces.append
        )
        trace = FakeTrace(trace_id="t1")
        proc.on_trace_start(trace)
        proc.on_span_end(_span(span_data=FunctionSpanData(name="my_search", input="q")))
        proc.on_trace_end(trace)
        assert len(traces[0].searches) == 1
        assert len(traces[0].tools_used) == 0

    def test_non_search_tool(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(_span(span_data=FunctionSpanData(name="calculator")))
        processor.on_trace_end(trace)
        trace = processor._test_traces[0]
        assert len(trace.searches) == 0
        assert len(trace.tools_used) == 1


class TestTokenAccumulation:
    def test_accumulates(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        for _ in range(3):
            processor.on_span_end(
                _span(
                    span_data=GenerationSpanData(
                        model="gpt-4o", usage={"input_tokens": 100, "output_tokens": 50}
                    ),
                )
            )
        processor.on_trace_end(trace)
        trace = processor._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 300
        assert trace.token_usage.output_tokens == 150


class TestFlushAndShutdown:
    def test_force_flush(self, processor: Any) -> None:
        processor.on_trace_start(FakeTrace(trace_id="t1"))
        processor.force_flush()
        assert len(processor._test_traces) == 1

    def test_shutdown(self, processor: Any) -> None:
        processor.on_trace_start(FakeTrace(trace_id="t1"))
        processor.shutdown()
        assert len(processor._test_traces) == 1


class TestFunctionSpanDuration:
    def test_calculated(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=FunctionSpanData(name="slow_tool"),
                started_at="2026-01-01T00:00:00",
                ended_at="2026-01-01T00:00:02",
            )
        )
        processor.on_trace_end(trace)
        assert processor._test_traces[0].tools_used[0].duration_ms == 2000


class TestTaskFromWorkflowName:
    def test_name_maps_to_task(self, processor: Any) -> None:
        """TraceImpl exposes workflow name as `name`, not `workflow_name`."""
        trace = FakeTrace(trace_id="t1", name="weather-workflow")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        assert processor._test_traces[0].task == "weather-workflow"

    def test_workflow_name_fallback(self, processor: Any) -> None:
        """Falls back to workflow_name when name is empty."""
        trace = FakeTrace(trace_id="t1", workflow_name="legacy-workflow")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        assert processor._test_traces[0].task == "legacy-workflow"

    def test_name_preferred_over_workflow_name(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1", name="primary", workflow_name="fallback")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        assert processor._test_traces[0].task == "primary"

    def test_empty_workflow_name(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        assert processor._test_traces[0].task == ""


class TestDecisionFromGeneration:
    def test_captures_last_assistant_output(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=GenerationSpanData(
                    model="gpt-4o",
                    output=[{"role": "assistant", "content": "First response"}],
                ),
            )
        )
        processor.on_span_end(
            _span(
                span_data=GenerationSpanData(
                    model="gpt-4o",
                    output=[{"role": "assistant", "content": "Final decision"}],
                ),
            )
        )
        processor.on_trace_end(trace)
        assert processor._test_traces[0].decision == "Final decision"

    def test_no_output_means_empty_decision(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(_span(span_data=GenerationSpanData(model="gpt-4o")))
        processor.on_trace_end(trace)
        assert processor._test_traces[0].decision == ""


class TestTraceDurationMs:
    def test_computed_from_span_timestamps(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=GenerationSpanData(model="gpt-4o"),
                started_at="2026-01-01T00:00:00",
                ended_at="2026-01-01T00:00:01",
            )
        )
        processor.on_span_end(
            _span(
                span_data=FunctionSpanData(name="tool"),
                started_at="2026-01-01T00:00:01",
                ended_at="2026-01-01T00:00:03",
            )
        )
        processor.on_trace_end(trace)
        # First span starts at :00, last span ends at :03 = 3000ms
        assert processor._test_traces[0].duration_ms == 3000

    def test_zero_when_no_timestamps(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(_span(span_data=GenerationSpanData(model="gpt-4o")))
        processor.on_trace_end(trace)
        assert processor._test_traces[0].duration_ms == 0


class TestTurnCount:
    def test_counts_generation_spans(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        for _ in range(3):
            processor.on_span_end(_span(span_data=GenerationSpanData(model="gpt-4o")))
        # Tool calls should not increment turn_count
        processor.on_span_end(_span(span_data=FunctionSpanData(name="calculator")))
        processor.on_trace_end(trace)
        assert processor._test_traces[0].turn_count == 3


class TestScope:
    def test_scope_from_agent_name(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1", name="my-workflow")
        processor.on_trace_start(trace)
        processor.on_span_end(_span(span_data=AgentSpanData(name="research-agent")))
        processor.on_trace_end(trace)
        # Agent name takes priority over task for scope
        assert processor._test_traces[0].scope == "research-agent"

    def test_scope_falls_back_to_task(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1", name="my-workflow")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        assert processor._test_traces[0].scope == "my-workflow"

    def test_scope_none_when_empty(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        assert processor._test_traces[0].scope is None


class TestTags:
    def test_group_id_tag(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1", group_id="session-123")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        assert "group:session-123" in processor._test_traces[0].tags

    def test_metadata_tags(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1", metadata={"tags": ["prod", "v2"]})
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        tags = processor._test_traces[0].tags
        assert "prod" in tags
        assert "v2" in tags

    def test_no_tags_when_absent(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_trace_end(trace)
        assert processor._test_traces[0].tags == []


class TestSearchResultsCount:
    def test_json_list_output(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=FunctionSpanData(
                    name="web_search",
                    input="python openai",
                    output='[{"title": "a"}, {"title": "b"}]',
                ),
            )
        )
        processor.on_trace_end(trace)
        assert processor._test_traces[0].searches[0].results_count == 2

    def test_nonempty_string_output(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=FunctionSpanData(
                    name="web_search", input="query", output="some result text"
                ),
            )
        )
        processor.on_trace_end(trace)
        assert processor._test_traces[0].searches[0].results_count == 1

    def test_empty_output(self, processor: Any) -> None:
        trace = FakeTrace(trace_id="t1")
        processor.on_trace_start(trace)
        processor.on_span_end(
            _span(
                span_data=FunctionSpanData(name="web_search", input="query", output=""),
            )
        )
        processor.on_trace_end(trace)
        assert processor._test_traces[0].searches[0].results_count == 0
