from __future__ import annotations

from typing import Any

import pytest

from openflux.adapters.google_adk import (
    GoogleADKAdapter,
    _detect_handoffs,
    _extract_text,
    _SessionAccumulator,
    create_adk_callbacks,
)
from openflux.schema import ContextType, Status


class FakeSession:
    def __init__(self, session_id: str = "ses-abc123") -> None:
        self.id = session_id


class FakeCallbackContext:
    def __init__(
        self,
        agent_name: str = "test-agent",
        session: FakeSession | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.session = session or FakeSession()


class FakeToolContext(FakeCallbackContext):
    def __init__(
        self,
        function_call_id: str = "fc-001",
        agent_name: str = "test-agent",
        session: FakeSession | None = None,
    ) -> None:
        super().__init__(agent_name=agent_name, session=session)
        self.function_call_id = function_call_id


class FakePart:
    def __init__(self, text: str = "", function_call: Any = None) -> None:
        self.text = text
        self.function_call = function_call


class FakeContent:
    def __init__(self, parts: list[FakePart] | None = None) -> None:
        self.parts = parts or []


class FakeUsageMetadata:
    def __init__(
        self,
        prompt_token_count: int = 0,
        candidates_token_count: int = 0,
    ) -> None:
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class FakeLlmRequest:
    def __init__(self, system_instruction: Any = None) -> None:
        self.system_instruction = system_instruction


class FakeLlmResponse:
    def __init__(
        self,
        model: str = "",
        usage_metadata: FakeUsageMetadata | None = None,
        content: FakeContent | None = None,
    ) -> None:
        self.model = model
        self.usage_metadata = usage_metadata
        self.content = content


class FakeTool:
    def __init__(self, name: str = "calculator") -> None:
        self.name = name


class FakeFunctionCall:
    def __init__(self, name: str = "", args: dict[str, Any] | None = None) -> None:
        self.name = name
        self.args = args or {}


@pytest.fixture()
def adapter() -> GoogleADKAdapter:
    collected: list[Any] = []
    return GoogleADKAdapter(agent="test-adk", on_trace=collected.append)


@pytest.fixture()
def ctx() -> FakeCallbackContext:
    return FakeCallbackContext()


@pytest.fixture()
def tool_ctx() -> FakeToolContext:
    return FakeToolContext()


class TestCreateCallbacks:
    def test_returns_four_callbacks(self) -> None:
        cb = create_adk_callbacks(agent="my-agent")
        assert callable(cb.before_model)
        assert callable(cb.after_model)
        assert callable(cb.before_tool)
        assert callable(cb.after_tool)
        assert cb._adapter is not None

    def test_custom_agent_name(self) -> None:
        cb = create_adk_callbacks(agent="custom")
        assert cb._adapter._agent == "custom"


class TestBeforeModel:
    def test_captures_system_instruction(
        self, adapter: GoogleADKAdapter, ctx: FakeCallbackContext
    ) -> None:
        request = FakeLlmRequest(system_instruction="You are a helpful bot.")
        result = adapter._before_model(ctx, request)
        assert result is None  # should not override

        acc = adapter._sessions[ctx.session.id]
        assert len(acc.context) == 1
        assert acc.context[0].type == ContextType.SYSTEM_PROMPT
        assert acc.context[0].content == "You are a helpful bot."
        assert acc.context[0].bytes == len(b"You are a helpful bot.")

    def test_captures_content_object_instruction(
        self, adapter: GoogleADKAdapter, ctx: FakeCallbackContext
    ) -> None:
        instruction = FakeContent(parts=[FakePart(text="Be concise.")])
        request = FakeLlmRequest(system_instruction=instruction)
        adapter._before_model(ctx, request)

        acc = adapter._sessions[ctx.session.id]
        assert acc.context[0].content == "Be concise."

    def test_sets_agent_name(
        self, adapter: GoogleADKAdapter, ctx: FakeCallbackContext
    ) -> None:
        request = FakeLlmRequest()
        adapter._before_model(ctx, request)
        acc = adapter._sessions[ctx.session.id]
        assert acc.agent_name == "test-agent"

    def test_no_instruction_no_context(
        self, adapter: GoogleADKAdapter, ctx: FakeCallbackContext
    ) -> None:
        request = FakeLlmRequest(system_instruction=None)
        adapter._before_model(ctx, request)
        acc = adapter._sessions[ctx.session.id]
        assert len(acc.context) == 0


class TestAfterModel:
    def test_extracts_token_usage(
        self, adapter: GoogleADKAdapter, ctx: FakeCallbackContext
    ) -> None:
        usage = FakeUsageMetadata(prompt_token_count=100, candidates_token_count=50)
        response = FakeLlmResponse(model="gemini-2.0-flash", usage_metadata=usage)
        result = adapter._after_model(ctx, response)
        assert result is None

        acc = adapter._sessions[ctx.session.id]
        assert acc.token_usage.input_tokens == 100
        assert acc.token_usage.output_tokens == 50
        assert acc.model == "gemini-2.0-flash"

    def test_accumulates_tokens_across_calls(
        self, adapter: GoogleADKAdapter, ctx: FakeCallbackContext
    ) -> None:
        usage1 = FakeUsageMetadata(prompt_token_count=50, candidates_token_count=20)
        usage2 = FakeUsageMetadata(prompt_token_count=30, candidates_token_count=10)
        adapter._after_model(ctx, FakeLlmResponse(usage_metadata=usage1))
        adapter._after_model(ctx, FakeLlmResponse(usage_metadata=usage2))

        acc = adapter._sessions[ctx.session.id]
        assert acc.token_usage.input_tokens == 80
        assert acc.token_usage.output_tokens == 30

    def test_detects_handoff(
        self, adapter: GoogleADKAdapter, ctx: FakeCallbackContext
    ) -> None:
        fc = FakeFunctionCall(
            name="transfer_to_agent", args={"agent_name": "specialist"}
        )
        content = FakeContent(parts=[FakePart(function_call=fc)])
        response = FakeLlmResponse(content=content)

        # seed agent name first
        adapter._before_model(ctx, FakeLlmRequest())
        adapter._after_model(ctx, response)

        acc = adapter._sessions[ctx.session.id]
        assert "handoffs" in acc.metadata
        assert acc.metadata["handoffs"][0]["to_agent"] == "specialist"
        assert acc.metadata["handoffs"][0]["from_agent"] == "test-agent"

    def test_no_usage_metadata(
        self, adapter: GoogleADKAdapter, ctx: FakeCallbackContext
    ) -> None:
        response = FakeLlmResponse(model="gemini-pro")
        adapter._after_model(ctx, response)
        acc = adapter._sessions[ctx.session.id]
        assert acc.token_usage.input_tokens == 0
        assert acc.model == "gemini-pro"


class TestToolCallbacks:
    def test_records_tool_call(
        self, adapter: GoogleADKAdapter, tool_ctx: FakeToolContext
    ) -> None:
        tool = FakeTool(name="calculator")
        args = {"expression": "2+2"}

        adapter._before_tool(tool, args, tool_ctx)
        adapter._after_tool(tool, args, tool_ctx, {"result": 4})

        acc = adapter._sessions[tool_ctx.session.id]
        assert len(acc.tools) == 1
        assert acc.tools[0].name == "calculator"
        assert '"expression"' in acc.tools[0].tool_input
        assert '"result"' in acc.tools[0].tool_output

    def test_classifies_search_tool(
        self, adapter: GoogleADKAdapter, tool_ctx: FakeToolContext
    ) -> None:
        tool = FakeTool(name="google_search")
        args = {"query": "weather today"}

        adapter._before_tool(tool, args, tool_ctx)
        adapter._after_tool(tool, args, tool_ctx, {"results": []})

        acc = adapter._sessions[tool_ctx.session.id]
        assert len(acc.searches) == 1
        assert acc.searches[0].engine == "google_search"
        assert len(acc.tools) == 0  # not classified as regular tool

    def test_custom_search_tools(self, tool_ctx: FakeToolContext) -> None:
        adapter = GoogleADKAdapter(
            agent="test", search_tools={"my_search"}, on_trace=lambda r: None
        )
        tool = FakeTool(name="my_search")
        adapter._before_tool(tool, {"q": "test"}, tool_ctx)
        adapter._after_tool(tool, {"q": "test"}, tool_ctx, {})

        acc = adapter._sessions[tool_ctx.session.id]
        assert len(acc.searches) == 1

    def test_duration_ms_computed(
        self, adapter: GoogleADKAdapter, tool_ctx: FakeToolContext
    ) -> None:
        tool = FakeTool(name="slow_tool")
        adapter._before_tool(tool, {}, tool_ctx)

        adapter._after_tool(tool, {}, tool_ctx, {"ok": True})

        acc = adapter._sessions[tool_ctx.session.id]
        assert acc.tools[0].duration_ms >= 0

    def test_none_tool_response(
        self, adapter: GoogleADKAdapter, tool_ctx: FakeToolContext
    ) -> None:
        tool = FakeTool(name="void_tool")
        adapter._before_tool(tool, {}, tool_ctx)
        adapter._after_tool(tool, {}, tool_ctx, None)

        acc = adapter._sessions[tool_ctx.session.id]
        assert acc.tools[0].tool_output == ""


class TestFlush:
    def test_flush_builds_trace(self, ctx: FakeCallbackContext) -> None:
        collected: list[Any] = []
        adapter = GoogleADKAdapter(agent="flush-test", on_trace=collected.append)

        usage = FakeUsageMetadata(prompt_token_count=200, candidates_token_count=100)
        adapter._before_model(ctx, FakeLlmRequest())
        resp = FakeLlmResponse(model="gemini-2.0", usage_metadata=usage)
        adapter._after_model(ctx, resp)

        traces = adapter.flush()
        assert len(traces) == 1
        assert len(collected) == 1

        trace = traces[0]
        assert trace.id.startswith("trc-")
        assert trace.agent == "flush-test"
        assert trace.session_id == ctx.session.id
        assert trace.model == "gemini-2.0"
        assert trace.status == Status.COMPLETED
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 200
        assert trace.token_usage.output_tokens == 100

    def test_flush_clears_sessions(
        self, adapter: GoogleADKAdapter, ctx: FakeCallbackContext
    ) -> None:
        adapter._before_model(ctx, FakeLlmRequest())
        adapter.flush()
        assert len(adapter._sessions) == 0

    def test_flush_empty(self, adapter: GoogleADKAdapter) -> None:
        traces = adapter.flush()
        assert traces == []

    def test_completed_traces_property(self, ctx: FakeCallbackContext) -> None:
        adapter = GoogleADKAdapter(agent="prop-test", on_trace=lambda r: None)
        adapter._before_model(ctx, FakeLlmRequest())
        adapter.flush()
        assert len(adapter.completed_traces) == 1


class TestMultipleSessions:
    def test_separate_sessions(self) -> None:
        adapter = GoogleADKAdapter(agent="multi", on_trace=lambda r: None)
        ctx1 = FakeCallbackContext(session=FakeSession("ses-1"))
        ctx2 = FakeCallbackContext(session=FakeSession("ses-2"))

        adapter._before_model(ctx1, FakeLlmRequest())
        adapter._before_model(ctx2, FakeLlmRequest())

        adapter._after_model(
            ctx1,
            FakeLlmResponse(
                model="gemini-flash",
                usage_metadata=FakeUsageMetadata(prompt_token_count=10),
            ),
        )
        adapter._after_model(
            ctx2,
            FakeLlmResponse(
                model="gemini-pro",
                usage_metadata=FakeUsageMetadata(prompt_token_count=20),
            ),
        )

        traces = adapter.flush()
        assert len(traces) == 2
        models = {r.model for r in traces}
        assert models == {"gemini-flash", "gemini-pro"}


class TestHelpers:
    def test_extract_text_string(self) -> None:
        assert _extract_text("hello") == "hello"

    def test_extract_text_content_parts(self) -> None:
        content = FakeContent(parts=[FakePart(text="a"), FakePart(text="b")])
        assert _extract_text(content) == "ab"

    def test_extract_text_single_text_attr(self) -> None:
        class Obj:
            text = "simple"

        assert _extract_text(Obj()) == "simple"

    def test_detect_handoffs_no_parts(self) -> None:
        acc = _SessionAccumulator(session_id="test", agent_name="origin")
        _detect_handoffs(object(), acc)
        assert "handoffs" not in acc.metadata

    def test_detect_handoffs_non_transfer(self) -> None:
        acc = _SessionAccumulator(session_id="test", agent_name="origin")
        fc = FakeFunctionCall(name="regular_tool", args={})
        content = FakeContent(parts=[FakePart(function_call=fc)])
        _detect_handoffs(content, acc)
        assert "handoffs" not in acc.metadata
