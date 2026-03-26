from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from openflux.schema import ContextType, Status


def _mock_task(task_id: str = "task-1", description: str = "Analyze data") -> Any:
    return SimpleNamespace(id=task_id, description=description)


def _mock_agent(
    role: str = "Researcher",
    backstory: str = "",
    goal: str = "",
) -> Any:
    return SimpleNamespace(role=role, backstory=backstory, goal=goal)


@pytest.fixture()
def listener() -> Any:
    from openflux.adapters.crewai import OpenFluxCrewListener

    traces: list[Any] = []
    lis = OpenFluxCrewListener(agent="test-crew", on_trace=traces.append)
    lis._test_traces = traces
    return lis


@pytest.fixture()
def bus() -> Any:
    handlers: dict[type, list[Any]] = {}

    class MockBus:
        def on(self, event_type: type) -> Any:
            def decorator(fn: Any) -> Any:
                handlers.setdefault(event_type, []).append(fn)
                return fn

            return decorator

        def emit(self, source: Any, event: Any) -> None:
            for handler in handlers.get(type(event), []):
                handler(source, event)

    bus = MockBus()
    bus._handlers = handlers
    return bus


@pytest.fixture()
def wired(listener: Any, bus: Any) -> tuple[Any, Any]:
    listener.setup_listeners(bus)
    return listener, bus


class CrewKickoffStartedEvent:
    def __init__(self, crew_name: str = "test-crew") -> None:
        self.crew_name = crew_name


class CrewKickoffCompletedEvent:
    def __init__(self, output: str = "") -> None:
        self.output = output


class AgentExecutionStartedEvent:
    def __init__(self, agent: Any = None) -> None:
        self.agent = agent


class AgentExecutionCompletedEvent:
    def __init__(self, agent: Any = None, output: str = "") -> None:
        self.agent = agent
        self.output = output


class TaskStartedEvent:
    def __init__(self, task: Any = None) -> None:
        self.task = task


class TaskCompletedEvent:
    def __init__(self, task: Any = None, output: str = "") -> None:
        self.task = task
        self.output = output


class LLMCallStartedEvent:
    pass


class LLMCallCompletedEvent:
    def __init__(
        self,
        usage: dict[str, int] | None = None,
        model: str = "",
        response: Any = "",
    ) -> None:
        self.usage = usage
        self.model = model
        self.response = response


class ToolUsageStartedEvent:
    def __init__(self, tool_name: str = "", tool_args: str = "") -> None:
        self.tool_name = tool_name
        self.tool_args = tool_args


class ToolUsageFinishedEvent:
    def __init__(self, result: str = "") -> None:
        self.result = result


class ToolUsageErrorEvent:
    def __init__(self, error: str = "") -> None:
        self.error = error


class KnowledgeRetrievalCompletedEvent:
    def __init__(self, query: str = "", retrieved_knowledge: str = "") -> None:
        self.query = query
        self.retrieved_knowledge = retrieved_knowledge


class MemoryRetrievalCompletedEvent:
    def __init__(self, memory_content: str = "") -> None:
        self.memory_content = memory_content


@pytest.fixture()
def setup(listener: Any, bus: Any) -> tuple[Any, Any]:
    import openflux.adapters.crewai as mod

    originals = {}
    mock_types = {
        "CrewKickoffStartedEvent": CrewKickoffStartedEvent,
        "CrewKickoffCompletedEvent": CrewKickoffCompletedEvent,
        "AgentExecutionStartedEvent": AgentExecutionStartedEvent,
        "AgentExecutionCompletedEvent": AgentExecutionCompletedEvent,
        "TaskStartedEvent": TaskStartedEvent,
        "TaskCompletedEvent": TaskCompletedEvent,
        "LLMCallStartedEvent": LLMCallStartedEvent,
        "LLMCallCompletedEvent": LLMCallCompletedEvent,
        "ToolUsageStartedEvent": ToolUsageStartedEvent,
        "ToolUsageFinishedEvent": ToolUsageFinishedEvent,
        "ToolUsageErrorEvent": ToolUsageErrorEvent,
        "KnowledgeRetrievalCompletedEvent": KnowledgeRetrievalCompletedEvent,
        "MemoryRetrievalCompletedEvent": MemoryRetrievalCompletedEvent,
    }
    for name, cls in mock_types.items():
        originals[name] = getattr(mod, name, None)
        setattr(mod, name, cls)

    listener.setup_listeners(bus)

    yield listener, bus

    for name, orig in originals.items():
        if orig is not None:
            setattr(mod, name, orig)
        elif hasattr(mod, name):
            delattr(mod, name)


class TestImportGuard:
    def test_loads(self) -> None:
        from openflux.adapters.crewai import _HAS_CREWAI

        assert isinstance(_HAS_CREWAI, bool)

    def test_instantiates(self) -> None:
        from openflux.adapters.crewai import OpenFluxCrewListener

        lis = OpenFluxCrewListener(agent="x")
        assert lis._agent == "x"


class TestCrewLifecycle:
    def test_crew_started_sets_name(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        bus.emit(None, CrewKickoffStartedEvent(crew_name="my-crew"))
        assert listener._crew_name == "my-crew"

    def test_crew_completed_flushes(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, CrewKickoffCompletedEvent(output="done"))
        assert len(listener._test_traces) == 1


class TestTaskLifecycle:
    def test_task_produces_trace(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task(description="Summarize report")
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, TaskCompletedEvent(task=task, output="Summary here"))
        trace = listener._test_traces[0]
        assert trace.task == "Summarize report"
        assert trace.decision == "Summary here"
        assert trace.agent == "test-crew"

    def test_parallel_tasks_separate_traces(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        t1 = _mock_task("t1", "Task one")
        t2 = _mock_task("t2", "Task two")
        bus.emit(None, TaskStartedEvent(task=t1))
        bus.emit(None, TaskStartedEvent(task=t2))
        bus.emit(None, TaskCompletedEvent(task=t1, output="out1"))
        bus.emit(None, TaskCompletedEvent(task=t2, output="out2"))
        assert len(listener._test_traces) == 2
        tasks = {r.task for r in listener._test_traces}
        assert tasks == {"Task one", "Task two"}

    def test_status_default_completed(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, TaskCompletedEvent(task=task, output="ok"))
        assert listener._test_traces[0].status == Status.COMPLETED


class TestAgentEvents:
    def test_agent_role_as_scope(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        agent = _mock_agent("Data Analyst")
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, AgentExecutionStartedEvent(agent=agent))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        assert listener._test_traces[0].scope == "Data Analyst"

    def test_agent_output_as_decision(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        agent = _mock_agent("Writer")
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, AgentExecutionStartedEvent(agent=agent))
        bus.emit(None, AgentExecutionCompletedEvent(agent=agent, output="The report"))
        bus.emit(None, TaskCompletedEvent(task=task, output=""))
        assert listener._test_traces[0].decision == "The report"

    def test_backstory_captured_as_context(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        agent = _mock_agent(
            "Analyst", backstory="You are a senior data analyst.", goal="Analyze data"
        )
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, AgentExecutionStartedEvent(agent=agent))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        trace = listener._test_traces[0]
        assert len(trace.context) == 1
        ctx = trace.context[0]
        assert ctx.type == ContextType.SYSTEM_PROMPT
        assert ctx.source == "agent:Analyst"
        assert "senior data analyst" in ctx.content

    def test_goal_captured_in_metadata(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        agent = _mock_agent("Analyst", goal="Find patterns in sales data")
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, AgentExecutionStartedEvent(agent=agent))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        trace = listener._test_traces[0]
        assert trace.metadata["agent_goal"] == "Find patterns in sales data"


class TestToolEvents:
    def test_tool_record_created(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(
            None, ToolUsageStartedEvent(tool_name="web_search", tool_args="AI news")
        )
        bus.emit(None, ToolUsageFinishedEvent(result="Found 10 articles"))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        trace = listener._test_traces[0]
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "web_search"
        assert trace.tools_used[0].tool_input == "AI news"
        assert trace.tools_used[0].tool_output == "Found 10 articles"
        assert trace.tools_used[0].error is False

    def test_tool_error(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, ToolUsageStartedEvent(tool_name="calculator", tool_args="1/0"))
        bus.emit(None, ToolUsageErrorEvent(error="ZeroDivisionError"))
        bus.emit(None, TaskCompletedEvent(task=task, output="failed"))
        trace = listener._test_traces[0]
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].error is True
        assert "ZeroDivisionError" in trace.tools_used[0].tool_output
        assert trace.status == Status.ERROR

    def test_multiple_tools(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, ToolUsageStartedEvent(tool_name="search", tool_args="q1"))
        bus.emit(None, ToolUsageFinishedEvent(result="r1"))
        bus.emit(None, ToolUsageStartedEvent(tool_name="read", tool_args="q2"))
        bus.emit(None, ToolUsageFinishedEvent(result="r2"))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        assert len(listener._test_traces[0].tools_used) == 2

    def test_tool_args_dict_serialized(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        evt = ToolUsageStartedEvent.__new__(ToolUsageStartedEvent)
        evt.tool_name = "api_call"
        evt.tool_args = {"url": "https://example.com", "method": "GET"}
        bus.emit(None, evt)
        bus.emit(None, ToolUsageFinishedEvent(result="200 OK"))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        tool = listener._test_traces[0].tools_used[0]
        assert "example.com" in tool.tool_input
        assert tool.name == "api_call"


class TestLLMEvents:
    def test_token_usage_dict(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, LLMCallStartedEvent())
        bus.emit(
            None,
            LLMCallCompletedEvent(
                usage={"prompt_tokens": 500, "completion_tokens": 200},
                model="gpt-4o",
            ),
        )
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        trace = listener._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 500
        assert trace.token_usage.output_tokens == 200
        assert trace.model == "gpt-4o"

    def test_token_usage_from_response_dict(self, setup: tuple[Any, Any]) -> None:
        """Token usage extracted from response dict (real CrewAI behavior)."""
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, LLMCallStartedEvent())
        # Simulate real CrewAI: no top-level usage, but response is a dict
        evt = LLMCallCompletedEvent.__new__(LLMCallCompletedEvent)
        evt.usage = None
        evt.model = "gpt-4o-mini"
        evt.response = {
            "choices": [{"message": {"content": "Hello"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 45},
        }
        bus.emit(None, evt)
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        trace = listener._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 120
        assert trace.token_usage.output_tokens == 45

    def test_token_usage_accumulates(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        for _ in range(3):
            bus.emit(None, LLMCallStartedEvent())
            bus.emit(
                None,
                LLMCallCompletedEvent(
                    usage={"prompt_tokens": 100, "completion_tokens": 50},
                    model="gpt-4o",
                ),
            )
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        trace = listener._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 300
        assert trace.token_usage.output_tokens == 150

    def test_llm_call_count_as_turn_count(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, LLMCallStartedEvent())
        bus.emit(None, LLMCallCompletedEvent(model="claude"))
        bus.emit(None, LLMCallStartedEvent())
        bus.emit(None, LLMCallCompletedEvent(model="claude"))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        assert listener._test_traces[0].turn_count == 2

    def test_token_usage_object_attrs(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        usage_obj = SimpleNamespace(prompt_tokens=300, completion_tokens=100)
        evt = LLMCallCompletedEvent.__new__(LLMCallCompletedEvent)
        evt.usage = usage_obj
        evt.model = "claude-sonnet"
        evt.response = ""
        bus.emit(None, evt)
        bus.emit(None, TaskCompletedEvent(task=task, output="ok"))
        trace = listener._test_traces[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 300
        assert trace.token_usage.output_tokens == 100


class TestTags:
    def test_crewai_base_tag(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        assert "crewai" in listener._test_traces[0].tags

    def test_crew_name_in_tags(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        bus.emit(None, CrewKickoffStartedEvent(crew_name="analytics-crew"))
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        assert "analytics-crew" in listener._test_traces[0].tags

    def test_agent_role_in_tags(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        agent = _mock_agent("Researcher")
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, AgentExecutionStartedEvent(agent=agent))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        assert "Researcher" in listener._test_traces[0].tags


class TestKnowledgeAndMemory:
    def test_knowledge_retrieval_creates_search(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(
            None,
            KnowledgeRetrievalCompletedEvent(
                query="sales Q4", retrieved_knowledge="Revenue up 20%"
            ),
        )
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        trace = listener._test_traces[0]
        assert len(trace.searches) == 1
        assert trace.searches[0].query == "sales Q4"
        assert trace.searches[0].engine == "crewai-knowledge"
        assert trace.searches[0].results_count == 1

    def test_memory_retrieval_creates_context(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(
            None,
            MemoryRetrievalCompletedEvent(memory_content="Previous analysis found X"),
        )
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        trace = listener._test_traces[0]
        # context may also have backstory entries; filter to memory type
        mem_contexts = [c for c in trace.context if c.type == ContextType.MEMORY]
        assert len(mem_contexts) == 1
        assert mem_contexts[0].source == "crewai-memory"
        assert "Previous analysis" in mem_contexts[0].content


class TestMetadata:
    def test_crew_name_in_metadata(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        bus.emit(None, CrewKickoffStartedEvent(crew_name="analytics-crew"))
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, TaskCompletedEvent(task=task, output="done"))
        assert listener._test_traces[0].metadata["crew_name"] == "analytics-crew"


class TestCompletedTraces:
    def test_property_returns_copy(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, TaskCompletedEvent(task=task, output="ok"))
        r1 = listener.completed_traces
        r2 = listener.completed_traces
        assert r1 == r2
        assert r1 is not r2

    def test_session_id_set(self, setup: tuple[Any, Any]) -> None:
        listener, bus = setup
        task = _mock_task()
        bus.emit(None, TaskStartedEvent(task=task))
        bus.emit(None, TaskCompletedEvent(task=task, output="ok"))
        assert listener._test_traces[0].session_id.startswith("ses-")
