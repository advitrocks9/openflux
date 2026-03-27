"""Acceptance test: AutoGen v0.4 multi-agent team.

User story: "Multi-agent AutoGen team. I want to see what happened."
"""

import os
import uuid

import pytest

from tests.acceptance.helpers import check_trace

pytestmark = [pytest.mark.acceptance, pytest.mark.asyncio]

REQUIRED = [
    "id", "timestamp", "agent", "session_id", "model", "task", "decision",
    "status", "scope", "tags", "context", "turn_count", "token_usage",
    "duration_ms", "metadata", "schema_version",
]
NA = ["parent_id", "correction", "searches", "sources_read", "tools_used", "files_modified"]


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "autogen_test.db")


async def test_autogen_multi_agent_team(db_path):
    """Run a RoundRobinGroupChat and verify the trace captures everything."""
    try:
        from autogen_agentchat.agents import AssistantAgent
        from autogen_agentchat.conditions import TextMentionTermination
        from autogen_agentchat.teams import RoundRobinGroupChat
        from autogen_ext.models.openai import OpenAIChatCompletionClient
    except ImportError:
        pytest.skip("autogen-agentchat not installed")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")

    from openflux.adapters.autogen import AutoGenStreamConsumer
    from openflux.schema import ContextRecord, ContextType
    from openflux.sinks.sqlite import SQLiteSink

    os.environ["OPENFLUX_DB_PATH"] = db_path

    sink = SQLiteSink(path=db_path)
    traces_captured = []

    consumer = AutoGenStreamConsumer(
        agent="research-team",
        model="gpt-4o-mini",
        scope="acceptance-test",
        tags=["test", "multi-agent"],
        context=[
            ContextRecord(
                type=ContextType.SYSTEM_PROMPT,
                content="Research team",
            ),
        ],
        on_trace=lambda t: (traces_captured.append(t), sink.write(t)),
    )

    client = OpenAIChatCompletionClient(model="gpt-4o-mini", api_key=api_key)
    researcher = AssistantAgent(
        "researcher", model_client=client,
        system_message="Research briefly. One sentence.",
    )
    writer = AssistantAgent(
        "writer", model_client=client,
        system_message="Summarize briefly. Say TERMINATE when done.",
    )
    team = RoundRobinGroupChat(
        [researcher, writer],
        termination_condition=TextMentionTermination("TERMINATE"),
    )

    try:
        async for msg in team.run_stream(task="What is the capital of France?"):
            consumer.process(msg)
    except Exception as e:
        if "429" in str(e) or "rate" in str(e).lower() or "quota" in str(e).lower():
            pytest.skip(f"API quota exceeded: {e}")
        raise

    # flush() may return None if TaskResult already auto-flushed
    trace = consumer.flush()
    if trace is None and traces_captured:
        trace = traces_captured[-1]

    assert trace is not None, "No trace was produced"

    sink.close()

    trace, coverage = check_trace(db_path, required=REQUIRED, na=NA)
    assert coverage >= 70
