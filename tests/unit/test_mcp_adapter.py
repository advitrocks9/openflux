"""Unit tests for MCP adapter trace_record and trace_update tools."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


def _has_mcp() -> bool:
    try:
        import mcp.server.fastmcp  # noqa: F401

        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _has_mcp(), reason="MCP SDK not installed")


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "mcp_test.db"


class TestTraceUpdate:
    """trace_update should append records, merge tokens, and replace scalars."""

    def _create_trace(self, db_path: Path) -> str:
        """Create an initial trace and return its ID."""
        from openflux.adapters.mcp import MCPServerAdapter

        adapter = MCPServerAdapter(agent="test", db_path=str(db_path))

        async def run() -> str:
            result = await adapter.server.call_tool(
                "trace_record",
                {
                    "task": "Initial task",
                    "decision": "First decision",
                    "model": "gpt-4o",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "turn_count": 1,
                    "tools_used": [
                        {"name": "Bash", "tool_input": "ls", "tool_output": "a.py"},
                    ],
                },
            )
            # call_tool returns (content_list, metadata_dict)
            content_list = result[0]
            text = content_list[0].text
            return json.loads(text)["recorded"]

        return asyncio.run(run())

    def test_appends_tools(self, db_path: Path) -> None:
        trace_id = self._create_trace(db_path)

        from openflux.adapters.mcp import MCPServerAdapter

        adapter = MCPServerAdapter(agent="test", db_path=str(db_path))

        async def run() -> None:
            await adapter.server.call_tool(
                "trace_update",
                {
                    "trace_id": trace_id,
                    "tools_used": [
                        {"name": "Read", "tool_input": "/src/a.py"},
                    ],
                },
            )

        asyncio.run(run())

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=str(db_path))
        trace = sink.get(trace_id)
        sink.close()
        assert trace is not None
        assert len(trace.tools_used) == 2
        assert trace.tools_used[0].name == "Bash"
        assert trace.tools_used[1].name == "Read"

    def test_merges_tokens_additively(self, db_path: Path) -> None:
        trace_id = self._create_trace(db_path)

        from openflux.adapters.mcp import MCPServerAdapter

        adapter = MCPServerAdapter(agent="test", db_path=str(db_path))

        async def run() -> None:
            await adapter.server.call_tool(
                "trace_update",
                {
                    "trace_id": trace_id,
                    "input_tokens": 200,
                    "output_tokens": 75,
                },
            )

        asyncio.run(run())

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=str(db_path))
        trace = sink.get(trace_id)
        sink.close()
        assert trace is not None
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 300  # 100 + 200
        assert trace.token_usage.output_tokens == 125  # 50 + 75

    def test_replaces_decision(self, db_path: Path) -> None:
        trace_id = self._create_trace(db_path)

        from openflux.adapters.mcp import MCPServerAdapter

        adapter = MCPServerAdapter(agent="test", db_path=str(db_path))

        async def run() -> None:
            await adapter.server.call_tool(
                "trace_update",
                {
                    "trace_id": trace_id,
                    "decision": "Updated decision after review",
                },
            )

        asyncio.run(run())

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=str(db_path))
        trace = sink.get(trace_id)
        sink.close()
        assert trace is not None
        assert trace.decision == "Updated decision after review"

    def test_replaces_turn_count(self, db_path: Path) -> None:
        trace_id = self._create_trace(db_path)

        from openflux.adapters.mcp import MCPServerAdapter

        adapter = MCPServerAdapter(agent="test", db_path=str(db_path))

        async def run() -> None:
            await adapter.server.call_tool(
                "trace_update",
                {
                    "trace_id": trace_id,
                    "turn_count": 5,
                },
            )

        asyncio.run(run())

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=str(db_path))
        trace = sink.get(trace_id)
        sink.close()
        assert trace is not None
        assert trace.turn_count == 5

    def test_update_nonexistent_returns_error(self, db_path: Path) -> None:
        from openflux.adapters.mcp import MCPServerAdapter

        adapter = MCPServerAdapter(agent="test", db_path=str(db_path))

        async def run() -> str:
            result = await adapter.server.call_tool(
                "trace_update",
                {
                    "trace_id": "trc-doesnotexist",
                    "decision": "nope",
                },
            )
            return result[0][0].text

        text = asyncio.run(run())
        data = json.loads(text)
        assert "error" in data

    def test_appends_searches_and_sources(self, db_path: Path) -> None:
        trace_id = self._create_trace(db_path)

        from openflux.adapters.mcp import MCPServerAdapter

        adapter = MCPServerAdapter(agent="test", db_path=str(db_path))

        async def run() -> None:
            await adapter.server.call_tool(
                "trace_update",
                {
                    "trace_id": trace_id,
                    "searches": [
                        {"query": "find auth bugs", "engine": "grep"},
                    ],
                    "sources_read": [
                        {"type": "file", "path": "/src/auth.py", "tool": "Read"},
                    ],
                },
            )

        asyncio.run(run())

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=str(db_path))
        trace = sink.get(trace_id)
        sink.close()
        assert trace is not None
        assert len(trace.searches) == 1
        assert trace.searches[0].query == "find auth bugs"
        assert len(trace.sources_read) == 1
        assert trace.sources_read[0].path == "/src/auth.py"


class TestTraceRecord:
    def test_minimal_trace(self, db_path: Path) -> None:
        """trace_record with only required fields should succeed."""
        from openflux.adapters.mcp import MCPServerAdapter

        adapter = MCPServerAdapter(agent="test", db_path=str(db_path))

        async def run() -> str:
            result = await adapter.server.call_tool(
                "trace_record",
                {"task": "minimal task"},
            )
            return result[0][0].text

        text = asyncio.run(run())
        data = json.loads(text)
        assert "recorded" in data
        assert data["recorded"].startswith("trc-")

    def test_full_trace(self, db_path: Path) -> None:
        """trace_record with all fields should produce a complete trace."""
        from openflux.adapters.mcp import MCPServerAdapter

        adapter = MCPServerAdapter(agent="test", db_path=str(db_path))

        async def run() -> str:
            result = await adapter.server.call_tool(
                "trace_record",
                {
                    "task": "Full coverage test",
                    "decision": "All fields populated",
                    "agent": "custom-agent",
                    "model": "gpt-4o",
                    "status": "completed",
                    "scope": "testing",
                    "tags": ["test"],
                    "files_modified": ["/a.py"],
                    "correction": "Fixed approach",
                    "duration_ms": 1000,
                    "parent_id": "trc-parent123456",
                    "session_id": "ses-custom",
                    "input_tokens": 500,
                    "output_tokens": 200,
                    "turn_count": 3,
                    "tools_used": [{"name": "Bash", "tool_input": "echo hi"}],
                    "context": [{"type": "system_prompt", "content": "Be helpful"}],
                    "searches": [{"query": "find x", "engine": "grep"}],
                    "sources_read": [{"type": "file", "path": "/b.py"}],
                },
            )
            return result[0][0].text

        text = asyncio.run(run())
        trace_id = json.loads(text)["recorded"]

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=str(db_path))
        trace = sink.get(trace_id)
        sink.close()
        assert trace is not None
        assert trace.agent == "custom-agent"
        assert trace.parent_id == "trc-parent123456"
        assert trace.correction == "Fixed approach"
        assert trace.turn_count == 3
        assert trace.scope == "testing"
        assert len(trace.tools_used) == 1
        assert len(trace.context) == 1
        assert len(trace.searches) == 1
        assert len(trace.sources_read) == 1
