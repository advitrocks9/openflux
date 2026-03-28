"""Tests for openflux serve JSON API handlers."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    make_context_record,
    make_search_record,
    make_source_record,
    make_tool_record,
    make_trace,
)

from openflux.schema import TokenUsage
from openflux.serve._api import handle_request
from openflux.sinks.sqlite import SQLiteSink


@pytest.fixture()
def sink(tmp_path: Path) -> SQLiteSink:
    return SQLiteSink(path=tmp_path / "test.db")


@pytest.fixture()
def populated_sink(sink: SQLiteSink) -> SQLiteSink:
    """Sink with 3 traces covering different agents, statuses, and models."""
    sink.write(
        make_trace(
            id="trc-aaaaaaaaaaaa",
            agent="claude-code",
            task="Fix auth bug",
            status="completed",
            model="claude-sonnet-4-20250514",
            duration_ms=45000,
            turn_count=5,
            token_usage=TokenUsage(input_tokens=12000, output_tokens=3200),
            tools_used=[make_tool_record(name="Read"), make_tool_record(name="Edit")],
            searches=[make_search_record(query="SQL injection")],
            sources_read=[make_source_record(path="/src/auth.py")],
            files_modified=["/src/auth.py", "/src/middleware.py"],
            context=[make_context_record()],
            tags=["security"],
            scope="backend",
        )
    )
    sink.write(
        make_trace(
            id="trc-bbbbbbbbbbbb",
            agent="langchain",
            task="Analyze Q3 data",
            status="error",
            model="gpt-4o-mini",
            duration_ms=12000,
            token_usage=TokenUsage(input_tokens=5000, output_tokens=1000),
            tools_used=[make_tool_record(name="python_repl")],
        )
    )
    sink.write(
        make_trace(
            id="trc-cccccccccccc",
            agent="claude-code",
            task="Refactor database layer",
            status="completed",
            model="claude-sonnet-4-20250514",
            duration_ms=90000,
            token_usage=TokenUsage(input_tokens=30000, output_tokens=8000),
            tools_used=[
                make_tool_record(name="Read"),
                make_tool_record(name="Write"),
                make_tool_record(name="Bash"),
            ],
            searches=[
                make_search_record(),
                make_search_record(query="SQLAlchemy patterns"),
            ],
            sources_read=[make_source_record(), make_source_record(path="/src/db.py")],
            files_modified=["/src/db.py"],
        )
    )
    return sink


class TestTracesListEmpty:
    def test_returns_empty_list(self, sink: SQLiteSink):
        status, body = handle_request("/api/traces", sink)
        assert status == 200
        assert body["traces"] == []
        assert body["total"] == 0
        assert body["limit"] == 50
        assert body["offset"] == 0

    def test_with_query_params(self, sink: SQLiteSink):
        status, body = handle_request("/api/traces?agent=foo&status=error", sink)
        assert status == 200
        assert body["traces"] == []


class TestTracesListPopulated:
    def test_default_pagination(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/traces", populated_sink)
        assert status == 200
        assert body["total"] == 3
        assert len(body["traces"]) == 3

    def test_limit_and_offset(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/traces?limit=1&offset=0", populated_sink)
        assert status == 200
        assert len(body["traces"]) == 1
        assert body["total"] == 3

        status, body = handle_request("/api/traces?limit=1&offset=2", populated_sink)
        assert len(body["traces"]) == 1

    def test_filter_by_agent(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/traces?agent=langchain", populated_sink)
        assert status == 200
        assert body["total"] == 1
        assert body["traces"][0]["agent"] == "langchain"

    def test_filter_by_status(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/traces?status=error", populated_sink)
        assert status == 200
        assert body["total"] == 1
        assert body["traces"][0]["status"] == "error"

    def test_sort_ascending(self, populated_sink: SQLiteSink):
        status, body = handle_request(
            "/api/traces?sort=duration_ms&order=asc", populated_sink
        )
        assert status == 200
        durations = [t["duration_ms"] for t in body["traces"]]
        assert durations == sorted(durations)

    def test_sort_descending(self, populated_sink: SQLiteSink):
        status, body = handle_request(
            "/api/traces?sort=duration_ms&order=desc", populated_sink
        )
        assert status == 200
        durations = [t["duration_ms"] for t in body["traces"]]
        assert durations == sorted(durations, reverse=True)

    def test_invalid_sort_falls_back(self, populated_sink: SQLiteSink):
        status, body = handle_request(
            "/api/traces?sort=DROP_TABLE&order=asc", populated_sink
        )
        assert status == 200
        assert body["total"] == 3

    def test_search(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/traces?search=auth", populated_sink)
        assert status == 200
        assert body["total"] >= 1
        ids = [t["id"] for t in body["traces"]]
        assert "trc-aaaaaaaaaaaa" in ids

    def test_trace_summary_fields(self, populated_sink: SQLiteSink):
        url = "/api/traces?limit=1&sort=id&order=asc"
        status, body = handle_request(url, populated_sink)
        trace = body["traces"][0]
        assert trace["id"] == "trc-aaaaaaaaaaaa"
        assert trace["agent"] == "claude-code"
        assert trace["task"] == "Fix auth bug"
        assert trace["status"] == "completed"
        assert trace["model"] == "claude-sonnet-4-20250514"
        assert trace["duration_ms"] == 45000
        assert trace["token_usage"]["input_tokens"] == 12000
        assert trace["token_usage"]["output_tokens"] == 3200
        assert trace["tool_count"] == 2
        assert trace["search_count"] == 1
        assert trace["source_count"] == 1
        assert trace["files_modified_count"] == 2


class TestTraceDetail:
    def test_found(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/traces/trc-aaaaaaaaaaaa", populated_sink)
        assert status == 200
        assert body["id"] == "trc-aaaaaaaaaaaa"
        assert body["agent"] == "claude-code"
        assert body["task"] == "Fix auth bug"
        assert len(body["tools_used"]) == 2
        assert len(body["searches"]) == 1
        assert len(body["sources_read"]) == 1
        assert body["files_modified"] == ["/src/auth.py", "/src/middleware.py"]
        assert len(body["context"]) == 1
        assert body["token_usage"]["input_tokens"] == 12000

    def test_not_found(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/traces/trc-nonexistent1", populated_sink)
        assert status == 404
        assert "error" in body

    def test_empty_db(self, sink: SQLiteSink):
        status, body = handle_request("/api/traces/trc-anything000", sink)
        assert status == 404


class TestStats:
    def test_empty_db(self, sink: SQLiteSink):
        status, body = handle_request("/api/stats", sink)
        assert status == 200
        assert body["total_traces"] == 0
        assert body["total_input_tokens"] == 0
        assert body["total_output_tokens"] == 0
        assert body["agents"] == []
        assert body["models"] == []
        assert body["statuses"] == []
        assert body["latest_timestamp"] is None

    def test_populated(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/stats", populated_sink)
        assert status == 200
        assert body["total_traces"] == 3
        assert body["total_input_tokens"] == 47000
        assert body["total_output_tokens"] == 12200
        assert body["latest_timestamp"] is not None

        agent_names = [a["name"] for a in body["agents"]]
        assert "claude-code" in agent_names
        assert "langchain" in agent_names

        model_names = [m["name"] for m in body["models"]]
        assert "claude-sonnet-4-20250514" in model_names
        assert "gpt-4o-mini" in model_names

        status_names = [s["name"] for s in body["statuses"]]
        assert "completed" in status_names
        assert "error" in status_names


class TestTimeline:
    def test_empty_db(self, sink: SQLiteSink):
        status, body = handle_request("/api/stats/timeline", sink)
        assert status == 200
        assert body["days"] == []

    def test_populated(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/stats/timeline?days=30", populated_sink)
        assert status == 200
        assert len(body["days"]) >= 1
        day = body["days"][0]
        assert "date" in day
        assert "traces" in day
        assert "input_tokens" in day
        assert "output_tokens" in day

    def test_custom_days(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/stats/timeline?days=1", populated_sink)
        assert status == 200
        assert isinstance(body["days"], list)


class TestNotFound:
    def test_unknown_api_route(self, sink: SQLiteSink):
        status, body = handle_request("/api/unknown", sink)
        assert status == 404
        assert "error" in body

    def test_trailing_slash(self, populated_sink: SQLiteSink):
        status, body = handle_request("/api/traces/", populated_sink)
        assert status == 200
        assert "traces" in body
