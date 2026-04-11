"""Acceptance test: Google ADK adapter with real Gemini API call."""

import asyncio
import os

import pytest

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(
        not os.environ.get("GOOGLE_API_KEY"), reason="GOOGLE_API_KEY not set"
    ),
]


def test_google_adk_full_telemetry(tmp_path):
    """User story: Google ADK agent with weather, search, and file read tools."""
    db_path = tmp_path / "traces.db"
    os.environ["OPENFLUX_DB_PATH"] = str(db_path)

    from google.adk.agents import LlmAgent
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    from openflux.adapters.google_adk import create_adk_callbacks

    callbacks = create_adk_callbacks(agent="adk-research-bot")

    def get_weather(city: str) -> dict:
        """Get current weather for a city."""
        return {"city": city, "temp": "72F", "condition": "sunny"}

    def search_web(query: str) -> str:
        """Search the web for information."""
        return f"Results for '{query}': Gemini is Google's AI model family."

    def read_file(filename: str) -> str:
        """Read a file's contents."""
        return f"Contents of {filename}: config_version=2.0"

    agent = LlmAgent(
        name="research_assistant",
        model="gemini-2.5-flash",
        instruction="You are a helpful research assistant. Use your tools. Get weather first, then search, then read the config file. Be concise.",
        tools=[get_weather, search_web, read_file],
        before_model_callback=callbacks.before_model,
        after_model_callback=callbacks.after_model,
        before_tool_callback=callbacks.before_tool,
        after_tool_callback=callbacks.after_tool,
    )

    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name="test_app", session_service=session_service)

    async def create_session():
        return await session_service.create_session(
            app_name="test_app", user_id="test_user"
        )

    session = asyncio.run(create_session())

    from google.genai import types

    user_msg = types.Content(
        role="user",
        parts=[
            types.Part(
                text="Get weather in London, search for Gemini AI features, and read config.yaml. Be concise."
            )
        ],
    )
    events = list(
        runner.run(
            user_id="test_user",
            session_id=session.id,
            new_message=user_msg,
        )
    )
    assert len(events) > 0

    traces = callbacks._adapter.flush()
    assert len(traces) >= 1

    # flush() writes to default sink via OPENFLUX_DB_PATH
    from tests.acceptance.helpers import check_trace

    required = [
        "id",
        "timestamp",
        "agent",
        "session_id",
        "model",
        "task",
        "decision",
        "status",
        "scope",
        "tags",
        "context",
        "tools_used",
        "sources_read",
        "token_usage",
        "duration_ms",
        "turn_count",
        "metadata",
        "schema_version",
    ]
    # searches depends on model calling search_web - non-deterministic
    na = ["parent_id", "correction", "files_modified", "searches"]

    trace, coverage = check_trace(db_path, required=required, na=na)
    assert coverage >= 80
