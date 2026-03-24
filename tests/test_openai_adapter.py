from __future__ import annotations

from typing import Any

import pytest

from openflux.schema import ContextType, Status


class FakeTrace:
    def __init__(self, trace_id: str = "trace-001") -> None:
        self.trace_id = trace_id


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
    def __init__(self, name: str = "my-agent", instructions: str | None = None) -> None:
        self.name = name
        self.instructions = instructions


class GenerationSpanData:
    def __init__(
        self, model: str = "gpt-4o", usage: dict[str, int] | None = None
    ) -> None:
        self.model = model
        self.usage = usage


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
                    name="research-agent", instructions="You are a helpful assistant."
                ),
            )
        )
        processor.on_trace_end(trace)
        trace = processor._test_traces[0]
        assert len(trace.context) == 1
        assert trace.context[0].type == ContextType.SYSTEM_PROMPT
        assert "research-agent" in trace.context[0].source

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
        assert trace.turn_count == 1

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
