"""Tests for /api/outcomes and /api/outcomes/<session_id>."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_trace

from openflux.serve._api import handle_request
from openflux.sinks.sqlite import SQLiteSink


@pytest.fixture
def sink(tmp_path: Path) -> SQLiteSink:
    return SQLiteSink(path=tmp_path / "test.db")


def test_outcomes_list_empty(sink: SQLiteSink) -> None:
    status, body = handle_request("/api/outcomes", sink)
    assert status == 200
    assert body == {"outcomes": [], "limit": 50, "count": 0}


def test_outcomes_list_returns_records(sink: SQLiteSink) -> None:
    sink.record_outcome(
        session_id="s1",
        agent="claude-code",
        captured_at="2026-04-29T12:00:00Z",
        start_sha="aaa",
        end_sha="bbb",
        lines_added=10,
        lines_removed=2,
        files_changed=1,
        tests_passed=True,
        tests_exit_code=0,
    )
    status, body = handle_request("/api/outcomes", sink)
    assert status == 200
    assert body["count"] == 1
    o = body["outcomes"][0]
    assert o["session_id"] == "s1"
    assert o["lines_added"] == 10
    assert o["tests_passed"] is True
    assert o["trace"] is None  # No trace row joined yet


def test_outcomes_list_joins_trace_summary(sink: SQLiteSink) -> None:
    trace = make_trace(
        agent="claude-code",
        session_id="joined",
        task="ship outcome view",
        model="claude-opus",
    )
    sink.write(trace)
    sink.record_outcome(
        session_id="joined",
        agent="claude-code",
        captured_at="2026-04-29T13:00:00Z",
        lines_added=5,
    )
    status, body = handle_request("/api/outcomes", sink)
    assert status == 200
    assert body["count"] == 1
    o = body["outcomes"][0]
    assert o["trace"] is not None
    assert o["trace"]["task"] == "ship outcome view"
    assert o["trace"]["model"] == "claude-opus"


def test_outcomes_list_limit(sink: SQLiteSink) -> None:
    for i in range(5):
        sink.record_outcome(
            session_id=f"s{i}",
            agent="claude-code",
            captured_at=f"2026-04-29T12:0{i}:00Z",
        )
    status, body = handle_request("/api/outcomes?limit=2", sink)
    assert status == 200
    assert body["limit"] == 2
    assert body["count"] == 2


def test_outcome_detail_found(sink: SQLiteSink) -> None:
    sink.record_outcome(
        session_id="detailed",
        agent="claude-code",
        captured_at="2026-04-29T14:00:00Z",
        lines_added=42,
        tests_passed=False,
        tests_exit_code=1,
    )
    status, body = handle_request("/api/outcomes/detailed", sink)
    assert status == 200
    assert body["session_id"] == "detailed"
    assert body["lines_added"] == 42
    assert body["tests_passed"] is False


def test_outcome_detail_missing(sink: SQLiteSink) -> None:
    status, body = handle_request("/api/outcomes/nope", sink)
    assert status == 404
    assert "error" in body


def test_outcome_detail_with_agent_query(sink: SQLiteSink) -> None:
    sink.record_outcome(
        session_id="multi",
        agent="cursor",
        captured_at="2026-04-29T15:00:00Z",
        lines_added=7,
    )
    status, body = handle_request("/api/outcomes/multi?agent=cursor", sink)
    assert status == 200
    assert body["lines_added"] == 7

    # Default agent claude-code → 404
    status, body = handle_request("/api/outcomes/multi", sink)
    assert status == 404
