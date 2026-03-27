"""MCP acceptance test — proves the MCP server adapter works exactly as a user would use it."""

import asyncio

import pytest
from helpers import check_trace


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "traces.db"


class TestMCPUserWorkflow:
    """A user exposes OpenFlux as an MCP server. Other agents record traces through it."""

    def test_record_full_trace(self, db_path):
        from openflux.adapters.mcp import MCPServerAdapter

        async def run():
            adapter = MCPServerAdapter(agent="mcp-hub", db_path=str(db_path))
            server = adapter.server
            await server.call_tool(
                "trace_record",
                {
                    "task": "Analyze authentication module for security issues",
                    "decision": "Found 3 vulnerabilities: SQL injection, XSS, CSRF",
                    "agent": "security-scanner",
                    "model": "gpt-4o",
                    "status": "completed",
                    "scope": "security-audit",
                    "tags": ["security", "auth", "critical"],
                    "files_modified": ["src/auth.py", "src/middleware.py"],
                    "duration_ms": 45000,
                    "input_tokens": 15000,
                    "output_tokens": 3200,
                    "cache_read_tokens": 5000,
                    "cache_creation_tokens": 1200,
                    "context": [
                        {
                            "type": "system_prompt",
                            "source": "security-policy",
                            "content": "Follow OWASP Top 10",
                        },
                    ],
                    "searches": [
                        {
                            "query": "SQL injection patterns",
                            "engine": "codebase-search",
                            "results_count": 5,
                        },
                    ],
                    "sources_read": [
                        {
                            "type": "file",
                            "path": "src/auth.py",
                            "tool": "read_file",
                            "bytes_read": 4200,
                        },
                    ],
                    "tools_used": [
                        {
                            "name": "semgrep",
                            "tool_input": "--config auto",
                            "tool_output": "3 findings",
                            "duration_ms": 8000,
                        },
                    ],
                },
            )

        asyncio.run(run())

        # MCP can populate ALL 22 fields
        trace, coverage = check_trace(
            db_path,
            required=[
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
                "searches",
                "sources_read",
                "tools_used",
                "files_modified",
                "token_usage",
                "duration_ms",
                "metadata",
                "schema_version",
            ],
            na=[],
        )
        assert coverage >= 85

    def test_search_finds_trace(self, db_path):
        from openflux.adapters.mcp import MCPServerAdapter

        async def run():
            adapter = MCPServerAdapter(agent="test", db_path=str(db_path))
            server = adapter.server
            await server.call_tool("trace_record", {"task": "Find authentication bugs"})
            result = await server.call_tool("trace_search", {"query": "authentication"})
            return result

        result = asyncio.run(run())
        assert result is not None
