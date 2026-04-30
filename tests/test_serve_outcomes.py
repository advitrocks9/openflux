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
    from openflux.schema import TokenUsage

    trace = make_trace(
        agent="claude-code",
        session_id="joined",
        task="ship outcome view",
        model="claude-opus",
        token_usage=TokenUsage(input_tokens=1_000_000, output_tokens=100_000),
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
    # Opus pricing: $15/M in + $75/M out → 1M*15 + 100k*75 = 15.00 + 7.50 = 22.50
    assert o["trace"]["cost_usd"] == 22.50


def test_outcomes_cost_for_sonnet(sink: SQLiteSink) -> None:
    from conftest import make_trace

    from openflux.schema import TokenUsage

    trace = make_trace(
        agent="claude-code",
        session_id="sonnet-sess",
        model="claude-sonnet-4-20250514",
        token_usage=TokenUsage(input_tokens=1_000_000, output_tokens=100_000),
    )
    sink.write(trace)
    sink.record_outcome(
        session_id="sonnet-sess",
        agent="claude-code",
        captured_at="2026-04-29T13:30:00Z",
    )
    _, body = handle_request("/api/outcomes", sink)
    o = body["outcomes"][0]
    # Sonnet: $3/M in + $15/M out → 3.00 + 1.50 = 4.50
    assert o["trace"]["cost_usd"] == 4.50


def test_outcomes_cost_for_unknown_model_uses_default(sink: SQLiteSink) -> None:
    from conftest import make_trace

    from openflux.schema import TokenUsage

    trace = make_trace(
        agent="claude-code",
        session_id="unknown-sess",
        model="some-future-model-99",
        token_usage=TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000),
    )
    sink.write(trace)
    sink.record_outcome(
        session_id="unknown-sess",
        agent="claude-code",
        captured_at="2026-04-29T14:00:00Z",
    )
    _, body = handle_request("/api/outcomes", sink)
    o = body["outcomes"][0]
    # Default: $1/M in + $3/M out → 1.00 + 3.00 = 4.00
    assert o["trace"]["cost_usd"] == 4.00


def test_outcomes_cost_env_override(
    sink: SQLiteSink,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from conftest import make_trace

    from openflux.schema import TokenUsage

    monkeypatch.setenv(
        "OPENFLUX_RATES_JSON",
        '{"my-custom-model": [10.0, 20.0]}',
    )
    trace = make_trace(
        agent="claude-code",
        session_id="custom",
        model="my-custom-model",
        token_usage=TokenUsage(input_tokens=1_000_000, output_tokens=500_000),
    )
    sink.write(trace)
    sink.record_outcome(
        session_id="custom",
        agent="claude-code",
        captured_at="2026-04-29T15:00:00Z",
    )
    _, body = handle_request("/api/outcomes", sink)
    o = body["outcomes"][0]
    # Custom: $10/M in + $20/M out → 10.00 + 10.00 = 20.00
    assert o["trace"]["cost_usd"] == 20.00


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
