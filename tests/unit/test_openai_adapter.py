"""Simulated event tests for OpenAI Agents SDK adapter.

Constructs mock span objects and feeds them through the TracingProcessor,
proving field extraction works without making real API calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from openflux.adapters.openai_agents import OpenFluxProcessor
from openflux.schema import Trace

# The adapter dispatches via type(span_data).__name__, so we need real
# classes with the right names rather than SimpleNamespace with __class__ hacks.


class AgentSpanData:
    def __init__(self, name: str = "", output_type: str = "text") -> None:
        self.name = name
        self.output_type = output_type


class GenerationSpanData:
    def __init__(
        self,
        model: str = "gpt-4o-mini",
        usage: dict[str, int] | None = None,
        input: list[dict[str, str]] | None = None,
        output: list[dict[str, str]] | None = None,
    ) -> None:
        self.model = model
        self.usage = usage or {}
        self.input = input or []
        self.output = output or []


class FunctionSpanData:
    def __init__(self, name: str = "", input: Any = "", output: Any = "") -> None:
        self.name = name
        self.input = input
        self.output = output


class HandoffSpanData:
    def __init__(self, from_agent: str = "", to_agent: str = "") -> None:
        self.from_agent = from_agent
        self.to_agent = to_agent


class GuardrailSpanData:
    def __init__(self, name: str = "", triggered: bool = False) -> None:
        self.name = name
        self.triggered = triggered


def _mock_trace(trace_id: str = "trace-abc123") -> SimpleNamespace:
    return SimpleNamespace(trace_id=trace_id, name="agent-run")


def _mock_span(
    trace_id: str,
    span_data: Any,
    *,
    started_at: str = "2025-01-15T10:00:00Z",
    ended_at: str = "2025-01-15T10:00:05Z",
    error: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=trace_id,
        span_data=span_data,
        started_at=started_at,
        ended_at=ended_at,
        error=error,
    )


def _generation(
    model: str = "gpt-4o-mini",
    input_tokens: int = 500,
    output_tokens: int = 150,
    system_prompt: str = "You are a helpful research assistant.",
    assistant_response: str = "Based on my analysis, the answer is 42.",
) -> GenerationSpanData:
    return GenerationSpanData(
        model=model,
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "What is the answer?"},
        ],
        output=[
            {"role": "assistant", "content": assistant_response},
        ],
    )


class TestOpenAIFullWorkflow:
    """Feed a complete span sequence through the processor and verify the trace."""

    def test_full_trace_fields(self) -> None:
        captured: list[Trace] = []
        processor = OpenFluxProcessor(
            agent="test-openai-agent",
            on_trace=captured.append,
            parent_id="trc-parent000001",
        )

        tid = "trace-full-001"
        mock_trace = _mock_trace(tid)
        processor.on_trace_start(mock_trace)

        # Agent span
        processor.on_span_end(_mock_span(tid, AgentSpanData(name="ResearchAgent")))

        # Generation span with system prompt, usage, and assistant output
        processor.on_span_end(_mock_span(tid, _generation()))

        # Search tool
        processor.on_span_end(
            _mock_span(
                tid,
                FunctionSpanData(
                    name="web_search",
                    input="latest AI research papers",
                    output='[{"title": "Paper A"}, {"title": "Paper B"}]',
                ),
            )
        )

        # Regular tool
        processor.on_span_end(
            _mock_span(
                tid,
                FunctionSpanData(
                    name="calculate",
                    input='{"x": 1, "y": 2}',
                    output="3",
                ),
            )
        )

        # File read tool (produces source record + tool record)
        processor.on_span_end(
            _mock_span(
                tid,
                FunctionSpanData(
                    name="read_file",
                    input='{"file_path": "/src/main.py"}',
                    output="def main(): pass",
                ),
            )
        )

        # File write tool (produces tool record + files_modified)
        processor.on_span_end(
            _mock_span(
                tid,
                FunctionSpanData(
                    name="write_file",
                    input='{"file_path": "/src/output.py"}',
                    output="ok",
                ),
            )
        )

        # Handoff span
        processor.on_span_end(
            _mock_span(
                tid, HandoffSpanData(from_agent="Triage", to_agent="ResearchAgent")
            )
        )

        # Guardrail span
        processor.on_span_end(
            _mock_span(tid, GuardrailSpanData(name="content-filter", triggered=False))
        )

        processor.on_trace_end(mock_trace)

        assert len(captured) == 1
        trace = captured[0]

        # Core identity
        assert trace.id.startswith("trc-")
        assert trace.timestamp != ""
        assert trace.agent == "test-openai-agent"
        assert trace.session_id == tid
        assert trace.parent_id == "trc-parent000001"
        assert trace.schema_version == "0.2.0"

        # Model + status
        assert trace.model == "gpt-4o-mini"
        assert trace.status == "completed"

        # Decision from last assistant message
        assert trace.decision == "Based on my analysis, the answer is 42."

        # Scope defaults to agent name
        assert trace.scope == "ResearchAgent"

        # Token usage accumulated from generation span
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 500
        assert trace.token_usage.output_tokens == 150

        # Turn count = generation_count
        assert trace.turn_count == 1

        # Duration derived from span timestamps
        assert trace.duration_ms >= 0

        # Context from system prompt
        assert len(trace.context) == 1
        assert trace.context[0].type == "system_prompt"
        assert "helpful research assistant" in trace.context[0].content

        # Searches from web_search tool
        assert len(trace.searches) == 1
        assert trace.searches[0].engine == "web_search"
        assert trace.searches[0].results_count == 2

        # Tools: calculate + read_file + write_file (search tools excluded)
        assert len(trace.tools_used) == 3
        tool_names = {t.name for t in trace.tools_used}
        assert tool_names == {"calculate", "read_file", "write_file"}

        # Source from read_file
        assert len(trace.sources_read) == 1
        assert trace.sources_read[0].type == "file"
        assert trace.sources_read[0].path == "/src/main.py"

        # files_modified from write_file
        assert trace.files_modified == ["/src/output.py"]

        # Metadata from handoff + guardrail spans
        assert "handoffs" in trace.metadata
        assert len(trace.metadata["handoffs"]) == 1
        assert trace.metadata["handoffs"][0]["to_agent"] == "ResearchAgent"
        assert "guardrails" in trace.metadata
        assert len(trace.metadata["guardrails"]) == 1
        assert trace.metadata["guardrails"][0]["name"] == "content-filter"

    def test_error_status_propagation(self) -> None:
        """Span with error attribute sets trace status to error."""
        captured: list[Trace] = []
        processor = OpenFluxProcessor(agent="err-agent", on_trace=captured.append)

        tid = "trace-err-001"
        processor.on_trace_start(_mock_trace(tid))

        error_span = _mock_span(
            tid,
            _generation(),
            error={"message": "Rate limit exceeded"},
        )
        processor.on_span_end(error_span)

        processor.on_trace_end(_mock_trace(tid))

        assert len(captured) == 1
        assert captured[0].status == "error"

    def test_multiple_generations_accumulate_tokens(self) -> None:
        """Multiple generation spans should sum token usage and track turn count."""
        captured: list[Trace] = []
        processor = OpenFluxProcessor(agent="multi-gen", on_trace=captured.append)

        tid = "trace-multi-001"
        processor.on_trace_start(_mock_trace(tid))

        processor.on_span_end(
            _mock_span(tid, _generation(input_tokens=100, output_tokens=50))
        )
        processor.on_span_end(
            _mock_span(tid, _generation(input_tokens=200, output_tokens=75))
        )
        processor.on_span_end(
            _mock_span(tid, _generation(input_tokens=300, output_tokens=100))
        )

        processor.on_trace_end(_mock_trace(tid))

        trace = captured[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 600
        assert trace.token_usage.output_tokens == 225
        assert trace.turn_count == 3

    def test_deduplicates_system_prompts(self) -> None:
        """Identical system prompts across generations should appear only once."""
        captured: list[Trace] = []
        processor = OpenFluxProcessor(agent="dedup-agent", on_trace=captured.append)

        tid = "trace-dedup-001"
        processor.on_trace_start(_mock_trace(tid))

        same_prompt = "You are a helpful assistant."
        processor.on_span_end(_mock_span(tid, _generation(system_prompt=same_prompt)))
        processor.on_span_end(_mock_span(tid, _generation(system_prompt=same_prompt)))

        processor.on_trace_end(_mock_trace(tid))

        trace = captured[0]
        assert len(trace.context) == 1

    def test_custom_search_tools(self) -> None:
        """User-provided search_tools set should classify tools as searches."""
        captured: list[Trace] = []
        processor = OpenFluxProcessor(
            agent="custom-search",
            search_tools={"my_custom_search"},
            on_trace=captured.append,
        )

        tid = "trace-custom-001"
        processor.on_trace_start(_mock_trace(tid))

        processor.on_span_end(
            _mock_span(
                tid,
                FunctionSpanData(name="my_custom_search", input="query"),
            )
        )

        processor.on_trace_end(_mock_trace(tid))

        trace = captured[0]
        assert len(trace.searches) == 1
        assert trace.searches[0].engine == "my_custom_search"
        assert len(trace.tools_used) == 0

    def test_prompt_tokens_key_alias(self) -> None:
        """Usage dict with prompt_tokens/completion_tokens keys (OpenAI style)."""
        captured: list[Trace] = []
        processor = OpenFluxProcessor(agent="alias-agent", on_trace=captured.append)

        tid = "trace-alias-001"
        processor.on_trace_start(_mock_trace(tid))

        gen = _generation()
        gen.usage = {"prompt_tokens": 400, "completion_tokens": 120}
        processor.on_span_end(_mock_span(tid, gen))

        processor.on_trace_end(_mock_trace(tid))

        trace = captured[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 400
        assert trace.token_usage.output_tokens == 120

    def test_completed_traces_property(self) -> None:
        """completed_traces should accumulate across multiple trace lifecycles."""
        processor = OpenFluxProcessor(agent="prop-agent")

        for i in range(3):
            tid = f"trace-prop-{i}"
            processor.on_trace_start(_mock_trace(tid))
            processor.on_span_end(_mock_span(tid, AgentSpanData(name=f"Agent{i}")))
            processor.on_trace_end(_mock_trace(tid))

        assert len(processor.completed_traces) == 3

    def test_force_flush_emits_pending(self) -> None:
        """force_flush should emit traces that never got on_trace_end."""
        captured: list[Trace] = []
        processor = OpenFluxProcessor(agent="flush-agent", on_trace=captured.append)

        tid = "trace-orphan-001"
        processor.on_trace_start(_mock_trace(tid))
        processor.on_span_end(_mock_span(tid, AgentSpanData(name="OrphanAgent")))

        processor.force_flush()
        assert len(captured) == 1
        assert captured[0].agent == "flush-agent"
