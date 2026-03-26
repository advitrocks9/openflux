from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from openflux.schema import ContextType, SourceType, Status


@pytest.fixture()
def handler() -> Any:
    from openflux.adapters.langchain import OpenFluxCallbackHandler

    traces: list[Any] = []
    h = OpenFluxCallbackHandler(agent="test-lc-agent", on_trace=traces.append)
    h._test_traces = traces
    return h


def _llm_result(
    token_usage: dict[str, int] | None = None,
    model_name: str = "",
) -> SimpleNamespace:
    llm_output: dict[str, Any] = {}
    if token_usage:
        llm_output["token_usage"] = token_usage
    if model_name:
        llm_output["model_name"] = model_name
    return SimpleNamespace(llm_output=llm_output)


def _document(
    page_content: str, metadata: dict[str, Any] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(page_content=page_content, metadata=metadata or {})


def _agent_finish(output: str) -> SimpleNamespace:
    return SimpleNamespace(return_values={"output": output})


def _agent_action(log: str) -> SimpleNamespace:
    return SimpleNamespace(log=log)


class TestImportGuard:
    def test_loads(self) -> None:
        from openflux.adapters.langchain import _HAS_LANGCHAIN

        assert isinstance(_HAS_LANGCHAIN, bool)

    def test_instantiates(self) -> None:
        from openflux.adapters.langchain import OpenFluxCallbackHandler

        h = OpenFluxCallbackHandler(agent="x")
        assert h._agent == "x"


class TestCallbackFlow:
    def test_model_captured(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start(
            {"kwargs": {"model_name": "gpt-4o"}},
            ["prompt"],
            run_id=run_id,
        )
        handler.on_agent_finish(_agent_finish("done"), run_id=run_id)
        assert handler._test_traces[0].model == "gpt-4o"

    def test_tool_record(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start({}, ["p"], run_id=run_id)
        tool_run = uuid4()
        handler._get_or_create_run(tool_run, run_id)
        handler.on_tool_start(
            {"name": "calculator"},
            "2+2",
            run_id=tool_run,
            parent_run_id=run_id,
        )
        handler.on_tool_end("4", run_id=tool_run, parent_run_id=run_id)
        handler.on_agent_finish(_agent_finish("4"), run_id=run_id)
        trace = handler._test_traces[0]
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "calculator"
        assert trace.tools_used[0].tool_output == "4"
        assert trace.turn_count == 1

    def test_tool_error(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start({}, ["p"], run_id=run_id)
        tool_run = uuid4()
        handler.on_tool_start(
            {"name": "broken"},
            "input",
            run_id=tool_run,
            parent_run_id=run_id,
        )
        handler.on_tool_error(
            RuntimeError("boom"),
            run_id=tool_run,
            parent_run_id=run_id,
        )
        handler.on_agent_finish(_agent_finish("failed"), run_id=run_id)
        trace = handler._test_traces[0]
        assert trace.status == Status.ERROR
        assert trace.tools_used[0].error is True
        assert "boom" in trace.tools_used[0].tool_output

    def test_decision_captured(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start({}, ["p"], run_id=run_id)
        handler.on_agent_finish(_agent_finish("The answer is 42"), run_id=run_id)
        assert handler._test_traces[0].decision == "The answer is 42"

    def test_completed_traces(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start({}, ["p"], run_id=run_id)
        handler.on_agent_finish(_agent_finish("ok"), run_id=run_id)
        assert len(handler.completed_traces) == 1


class TestRetrieverCallbacks:
    def test_search_record(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_chain_start({"name": "rag_chain"}, {"input": "query"}, run_id=run_id)
        ret_run = uuid4()
        handler._get_or_create_run(ret_run, run_id)
        handler.on_retriever_start(
            {"name": "vector_store"},
            "what is openflux?",
            run_id=ret_run,
            parent_run_id=run_id,
        )
        docs = [
            _document("OpenFlux is...", {"source": "docs/intro.md"}),
            _document("It normalizes...", {"source": "docs/arch.md"}),
        ]
        handler.on_retriever_end(docs, run_id=ret_run, parent_run_id=run_id)
        handler.on_chain_end({"output": "answer"}, run_id=run_id)
        trace = handler._test_traces[0]
        assert len(trace.searches) == 1
        assert trace.searches[0].query == "what is openflux?"
        assert trace.searches[0].engine == "vector_store"
        assert trace.searches[0].results_count == 2

    def test_source_and_context(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_chain_start({"name": "chain"}, {"input": "q"}, run_id=run_id)
        ret_run = uuid4()
        handler.on_retriever_start(
            {"name": "retriever"},
            "q",
            run_id=ret_run,
            parent_run_id=run_id,
        )
        handler.on_retriever_end(
            [_document("chunk content", {"source": "file.txt"})],
            run_id=ret_run,
            parent_run_id=run_id,
        )
        handler.on_chain_end({"output": "a"}, run_id=run_id)
        trace = handler._test_traces[0]
        assert len(trace.sources_read) == 1
        assert trace.sources_read[0].type == SourceType.DOCUMENT
        assert trace.sources_read[0].path == "file.txt"
        assert trace.sources_read[0].content == "chunk content"
        assert len(trace.context) == 1
        assert trace.context[0].type == ContextType.RAG_CHUNK
        assert trace.context[0].source == "file.txt"


class TestTokenUsage:
    def test_extracted(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start({}, ["p"], run_id=run_id)
        handler.on_llm_end(
            _llm_result(token_usage={"prompt_tokens": 200, "completion_tokens": 80}),
            run_id=run_id,
        )
        handler.on_agent_finish(_agent_finish("ok"), run_id=run_id)
        trace = handler._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 200
        assert trace.token_usage.output_tokens == 80

    def test_accumulates(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start({}, ["p"], run_id=run_id)
        for _ in range(3):
            llm_run = uuid4()
            handler.on_llm_start({}, ["p"], run_id=llm_run, parent_run_id=run_id)
            handler.on_llm_end(
                _llm_result(
                    token_usage={"prompt_tokens": 100, "completion_tokens": 50}
                ),
                run_id=llm_run,
                parent_run_id=run_id,
            )
        handler.on_agent_finish(_agent_finish("ok"), run_id=run_id)
        trace = handler._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 300
        assert trace.token_usage.output_tokens == 150


class TestModelName:
    def test_from_serialized(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start(
            {"kwargs": {"model_name": "claude-sonnet-4-20250514"}},
            ["p"],
            run_id=run_id,
        )
        handler.on_agent_finish(_agent_finish("ok"), run_id=run_id)
        assert handler._test_traces[0].model == "claude-sonnet-4-20250514"

    def test_from_llm_end(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start({}, ["p"], run_id=run_id)
        handler.on_llm_end(_llm_result(model_name="gpt-4o"), run_id=run_id)
        handler.on_agent_finish(_agent_finish("ok"), run_id=run_id)
        assert handler._test_traces[0].model == "gpt-4o"

    def test_from_chat_model_start(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_chat_model_start(
            {"kwargs": {"model_name": "claude-opus-4-20250514"}},
            [[]],
            run_id=run_id,
        )
        handler.on_agent_finish(_agent_finish("ok"), run_id=run_id)
        assert handler._test_traces[0].model == "claude-opus-4-20250514"


class TestLangGraphScope:
    def test_scope_from_chain(self, handler: Any) -> None:
        parent_id = uuid4()
        handler.on_chain_start(
            {"name": "rag_pipeline"},
            {"input": "question"},
            run_id=parent_id,
        )
        child_id = uuid4()
        handler.on_chain_start(
            {"name": "retrieve_node"},
            {},
            run_id=child_id,
            parent_run_id=parent_id,
        )
        handler.on_chain_end({"output": "answer"}, run_id=parent_id)
        # Top-level chain name takes priority for scope
        assert handler._test_traces[0].scope == "rag_pipeline"

    def test_task_from_input(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_chain_start(
            {"name": "chain"},
            {"input": "What is OpenFlux?"},
            run_id=run_id,
        )
        handler.on_chain_end({"output": "It's a telemetry standard"}, run_id=run_id)
        trace = handler._test_traces[0]
        assert trace.task == "What is OpenFlux?"
        assert trace.decision == "It's a telemetry standard"


class TestRunIdAccumulation:
    def test_child_events_roll_up(self, handler: Any) -> None:
        root = uuid4()
        handler.on_llm_start({}, ["p"], run_id=root)
        tool_run = uuid4()
        handler.on_tool_start(
            {"name": "search"},
            "query",
            run_id=tool_run,
            parent_run_id=root,
        )
        handler.on_tool_end("results", run_id=tool_run, parent_run_id=root)
        tool_run2 = uuid4()
        handler.on_tool_start(
            {"name": "calculator"},
            "1+1",
            run_id=tool_run2,
            parent_run_id=root,
        )
        handler.on_tool_end("2", run_id=tool_run2, parent_run_id=root)
        handler.on_agent_finish(_agent_finish("done"), run_id=root)
        assert len(handler._test_traces[0].tools_used) == 2

    def test_independent_runs_separate(self, handler: Any) -> None:
        r1, r2 = uuid4(), uuid4()
        handler.on_chain_start({"name": "c1"}, {"input": "q1"}, run_id=r1)
        handler.on_chain_start({"name": "c2"}, {"input": "q2"}, run_id=r2)
        handler.on_chain_end({"output": "a1"}, run_id=r1)
        handler.on_chain_end({"output": "a2"}, run_id=r2)
        assert len(handler._test_traces) == 2


class TestAgentAction:
    def test_reasoning_captured(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_llm_start({}, ["p"], run_id=run_id)
        handler.on_agent_action(
            _agent_action("I need to search for the answer"),
            run_id=run_id,
        )
        handler.on_agent_finish(_agent_finish("42"), run_id=run_id)
        trace = handler._test_traces[0]
        assert "reasoning" in trace.metadata
        assert "search for the answer" in trace.metadata["reasoning"][0]


class TestChainError:
    def test_marks_error(self, handler: Any) -> None:
        run_id = uuid4()
        handler.on_chain_start({"name": "c"}, {"input": "q"}, run_id=run_id)
        handler.on_chain_error(RuntimeError("chain failed"), run_id=run_id)
        handler.on_chain_end({"output": ""}, run_id=run_id)
        assert handler._test_traces[0].status == Status.ERROR
