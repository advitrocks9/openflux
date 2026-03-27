"""Acceptance test: Claude Agent SDK with tools.

User story: "Claude Agent SDK with Bash, Read, Glob tools."
"""

import os
import tempfile

import pytest

from tests.acceptance.helpers import check_trace

pytestmark = [pytest.mark.acceptance, pytest.mark.asyncio]

REQUIRED = [
    "id", "timestamp", "agent", "session_id", "model", "task", "decision",
    "status", "scope", "tags", "context", "searches", "sources_read",
    "tools_used", "turn_count", "token_usage", "duration_ms", "metadata",
    "schema_version",
]
NA = ["parent_id", "correction", "files_modified"]


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "claude_sdk_test.db")


async def test_claude_agent_sdk_with_tools(db_path):
    """Run Claude Agent SDK with file tools and verify the trace."""
    try:
        from claude_agent_sdk import (
            ClaudeAgentOptions,
            ResultMessage,
            query,
        )
    except ImportError:
        pytest.skip("claude-agent-sdk not installed")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    from openflux.adapters.claude_agent_sdk import create_openflux_hooks
    from openflux.sinks.sqlite import SQLiteSink

    os.environ["OPENFLUX_DB_PATH"] = db_path

    sink = SQLiteSink(path=db_path)
    traces_captured = []

    def capture_trace(t):
        traces_captured.append(t)
        sink.write(t)

    hooks, adapter = create_openflux_hooks(
        agent="my-claude-agent",
        scope="integration-test",
        tags=["test", "acceptance"],
        system_prompt="You are a helpful coding assistant.",
        on_trace=capture_trace,
    )

    # Create a temp .py file so there's something to find and read
    with tempfile.NamedTemporaryFile(
        suffix=".py", prefix="openflux_test_", dir="/tmp",
        mode="w", delete=False,
    ) as f:
        f.write("# OpenFlux test file\ndef hello():\n    return 'world'\n")
        test_file = f.name

    result_msg = None
    try:
        async for msg in query(
            prompt=f"List Python files in /tmp that start with 'openflux_test_', read {test_file}, and tell me what it does. Be brief.",
            options=ClaudeAgentOptions(
                hooks=hooks,
                allowed_tools=["Bash", "Read", "Glob", "Grep"],
                permission_mode="bypassPermissions",
                model="claude-haiku-4-5-20251001",
                max_turns=5,
            ),
        ):
            if isinstance(msg, ResultMessage):
                result_msg = msg
    except Exception as e:
        err_str = str(e).lower()
        if "429" in str(e) or "rate" in err_str or "quota" in err_str or "credit" in err_str:
            pytest.skip(f"API quota exceeded: {e}")
        raise
    finally:
        # Clean up temp file
        try:
            os.unlink(test_file)
        except OSError:
            pass

    # Feed ResultMessage data back to adapter for late-binding
    if result_msg:
        adapter.record_usage(
            session_id=result_msg.session_id,
            usage=result_msg.usage or {},
            model="claude-haiku-4-5-20251001",
            duration_ms=result_msg.duration_ms,
            result=result_msg.result or "",
            num_turns=result_msg.num_turns,
        )
    else:
        adapter.finalize()

    assert len(adapter.completed_traces) >= 1, "No traces captured"

    sink.close()

    trace, coverage = check_trace(db_path, required=REQUIRED, na=NA)
    assert coverage >= 70
