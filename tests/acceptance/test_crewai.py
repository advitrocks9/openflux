"""Acceptance test: CrewAI crew with calculator tool.

User story: "CrewAI crew with calculator and search tools."
"""

import os

import pytest

from tests.acceptance.helpers import check_trace

pytestmark = [pytest.mark.acceptance]

REQUIRED = [
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
    "turn_count",
    "token_usage",
    "duration_ms",
    "metadata",
    "schema_version",
]
NA = ["parent_id", "correction", "files_modified"]


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "crewai_test.db")


def test_crewai_crew_with_tools(db_path):
    """Run a CrewAI crew with a calculator tool and verify the trace."""
    try:
        from crewai import Agent, Crew, Task
        from crewai.tools import tool
    except ImportError:
        pytest.skip("crewai not installed")

    try:
        from crewai.utilities.events import crewai_event_bus
    except ImportError:
        try:
            from crewai.events import crewai_event_bus
        except ImportError:
            pytest.skip("Cannot import crewai_event_bus")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        pytest.skip("OPENAI_API_KEY not set")

    from openflux.adapters.crewai import OpenFluxCrewListener
    from openflux.sinks.sqlite import SQLiteSink

    os.environ["OPENFLUX_DB_PATH"] = db_path

    sink = SQLiteSink(path=db_path)
    traces_captured = []

    listener = OpenFluxCrewListener(
        agent="math-crew",
        on_trace=lambda t: (traces_captured.append(t), sink.write(t)),
    )
    listener.setup_listeners(crewai_event_bus)

    @tool
    def calculator(expression: str) -> str:
        """Calculate a math expression."""
        return str(eval(expression))  # noqa: S307

    mathematician = Agent(
        role="Mathematician",
        goal="Solve math problems",
        backstory="Expert mathematician.",
        tools=[calculator],
        llm="gpt-4o-mini",
    )
    task = Task(
        description="Calculate 42 * 17.",
        expected_output="The number.",
        agent=mathematician,
    )
    crew = Crew(agents=[mathematician], tasks=[task])

    try:
        crew.kickoff()
    except Exception as e:
        if "429" in str(e) or "rate" in str(e).lower() or "quota" in str(e).lower():
            pytest.skip(f"API quota exceeded: {e}")
        raise

    assert len(traces_captured) >= 1, "No traces captured"

    sink.close()

    trace, coverage = check_trace(db_path, required=REQUIRED, na=NA)
    assert coverage >= 70
