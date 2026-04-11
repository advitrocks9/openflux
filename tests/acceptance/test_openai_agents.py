"""Acceptance test: OpenAI Agents SDK adapter with real API call."""

import os

import pytest

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"
    ),
]


def test_openai_agents_full_telemetry(tmp_path):
    """User story: OpenAI agent with search, file read, file write, and weather tools."""
    db_path = tmp_path / "traces.db"
    os.environ["OPENFLUX_DB_PATH"] = str(db_path)

    from agents import Agent, Runner, function_tool
    from agents.tracing import add_trace_processor

    from openflux.adapters.openai_agents import OpenFluxProcessor

    processor = OpenFluxProcessor(agent="research-bot", parent_id="parent-001")
    add_trace_processor(processor)

    @function_tool
    def search_web(query: str) -> str:
        """Search the web."""
        return f"Results for '{query}': Python 3.12 released..."

    @function_tool
    def read_file(filename: str) -> str:
        """Read a file."""
        return f"Contents of {filename}: import asyncio"

    @function_tool
    def write_file(filename: str, content: str) -> str:
        """Write to a file."""
        return f"Wrote {len(content)} bytes to {filename}"

    @function_tool
    def get_weather(city: str) -> str:
        """Get weather."""
        return f"72F sunny in {city}"

    agent = Agent(
        name="research-assistant",
        instructions="Search first, read config.yaml, write summary to output.md, then get weather.",
        tools=[search_web, read_file, write_file, get_weather],
        model="gpt-4o-mini",
    )
    try:
        result = Runner.run_sync(
            agent,
            "Search for Python 3.12 features, read config.yaml, write summary to output.md, and get weather in London",
        )
    except Exception as e:
        if "insufficient_quota" in str(e) or "429" in str(e):
            pytest.skip("OpenAI API quota exceeded")
        raise

    assert result.final_output is not None

    from tests.acceptance.helpers import check_trace

    required = [
        "id",
        "timestamp",
        "agent",
        "session_id",
        "parent_id",
        "model",
        "task",
        "decision",
        "status",
        "scope",
        "tags",
        "context",
        "searches",
        "sources_read",
        "tools_used",
        "files_modified",
        "turn_count",
        "token_usage",
        "duration_ms",
        "metadata",
        "schema_version",
    ]
    na = ["correction"]

    trace, coverage = check_trace(db_path, required=required, na=na)
    assert coverage >= 80
