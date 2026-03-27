"""Acceptance test: LangChain adapter with real Gemini API call."""

import os

import pytest

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(
        not os.environ.get("GOOGLE_API_KEY"), reason="GOOGLE_API_KEY not set"
    ),
]


def test_langchain_gemini_full_telemetry(tmp_path):
    """User story: LangChain agent with Gemini, calculator, search, read, write tools."""
    db_path = tmp_path / "traces.db"
    os.environ["OPENFLUX_DB_PATH"] = str(db_path)

    from langchain_core.tools import tool
    from langchain_google_genai import ChatGoogleGenerativeAI

    try:
        from langchain.agents import create_agent as create_react_agent
    except ImportError:
        from langgraph.prebuilt import create_react_agent

    from openflux.adapters.langchain import OpenFluxCallbackHandler

    handler = OpenFluxCallbackHandler(
        agent="langchain-gemini-bot",
        search_tools={"search_web"},
        file_read_tools={"read_file"},
        file_write_tools={"write_file"},
    )

    @tool
    def calculator(expression: str) -> str:
        """Evaluate a math expression."""
        try:
            return str(eval(expression))  # noqa: S307
        except Exception as e:
            return f"Error: {e}"

    @tool
    def search_web(query: str) -> str:
        """Search the web for information."""
        return f"Results for '{query}': Python is a programming language created by Guido van Rossum."

    @tool
    def read_file(filename: str) -> str:
        """Read a file's contents."""
        return f"Contents of {filename}: x = 42\ny = x * 2"

    @tool
    def write_file(filename: str, content: str) -> str:
        """Write content to a file."""
        return f"Wrote {len(content)} bytes to {filename}"

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
    agent = create_react_agent(
        model=llm,
        tools=[calculator, search_web, read_file, write_file],
        prompt="You are a helpful assistant. Use tools to answer questions. Search first, read data.txt, compute 6*7, then write result to output.txt.",
    )

    result = agent.invoke(
        {"messages": [("human", "Search for Python info, read data.txt, compute 6*7, write the result to output.txt")]},
        config={"callbacks": [handler]},
    )

    assert result is not None

    from tests.acceptance.conftest import check_trace

    required = [
        "id",
        "timestamp",
        "agent",
        "session_id",
        "model",
        "task",
        "decision",
        "status",
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
    na = ["parent_id", "correction"]

    trace, coverage = check_trace(db_path, required=required, na=na)
    assert coverage >= 80
