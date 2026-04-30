"""Tests for cost intelligence: cache efficiency, burn rate, budgets, anomalies."""

import sqlite3
from datetime import UTC, datetime

import pytest

from openflux._pricing import estimate_cost
from openflux.insights import (
    budget_status,
    cost_overview,
    detect_anomalies,
    session_costs,
)
from openflux.schema import Status, TokenUsage, ToolRecord, Trace
from openflux.sinks.sqlite import SQLiteSink

# ── Pricing (moved from test_waste.py) ────────────────────────────────


class TestPricing:
    def test_opus_input(self) -> None:
        cost = estimate_cost("claude-opus-4-6", input_tokens=1_000_000)
        assert cost == pytest.approx(15.0, rel=0.01)

    def test_opus_output(self) -> None:
        assert estimate_cost(
            "claude-opus-4-6", output_tokens=1_000_000
        ) == pytest.approx(75.0, rel=0.01)

    def test_opus_cache_read(self) -> None:
        assert estimate_cost(
            "claude-opus-4-6", cache_read_tokens=1_000_000
        ) == pytest.approx(1.5, rel=0.01)

    def test_sonnet(self) -> None:
        assert estimate_cost(
            "claude-sonnet-4-6", input_tokens=1_000_000
        ) == pytest.approx(3.0, rel=0.01)

    def test_haiku(self) -> None:
        assert estimate_cost(
            "claude-haiku-4-5", input_tokens=1_000_000
        ) == pytest.approx(0.25, rel=0.01)

    def test_unknown_uses_default(self) -> None:
        assert estimate_cost("mystery-model", input_tokens=1_000_000) == pytest.approx(
            1.0, rel=0.01
        )

    def test_zero_tokens(self) -> None:
        assert estimate_cost("claude-opus-4-6") == 0.0


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def cost_db(tmp_path):
    """DB with sessions that have varying cache efficiency and tool patterns."""
    db_path = tmp_path / "test.db"
    sink = SQLiteSink(path=str(db_path))

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    auth = '{"file_path": "src/auth.py"}'
    pytest_cmd = '{"command": "pytest"}'
    edit_input = '{"file_path": "src/main.py", "old_string": "x", "new_string": "y"}'

    # Session 1: Good cache efficiency
    sink.write(
        Trace(
            id="trc-good-cache",
            timestamp=now,
            agent="claude-code",
            session_id="sess-1",
            model="claude-opus-4-6",
            task="Build auth module",
            status=Status.COMPLETED,
            turn_count=15,
            duration_ms=60000,
            token_usage=TokenUsage(
                input_tokens=5000,
                output_tokens=3000,
                cache_read_tokens=45000,
                cache_creation_tokens=2000,
            ),
            tools_used=[
                ToolRecord(
                    name="Read",
                    tool_input=auth,
                    timestamp=now,
                ),
                ToolRecord(
                    name="Edit",
                    tool_input=auth,
                    timestamp=now,
                ),
                ToolRecord(
                    name="Bash",
                    tool_input='{"command": "pytest tests/"}',
                    timestamp=now,
                ),
            ],
        )
    )

    # Session 2: Zero cache (expensive)
    fail_tool = ToolRecord(
        name="Bash",
        tool_input=pytest_cmd,
        error=True,
        timestamp=now,
    )
    sink.write(
        Trace(
            id="trc-no-cache",
            timestamp=now,
            agent="claude-code",
            session_id="sess-2",
            model="claude-opus-4-6",
            task="Debug failing tests",
            status=Status.ERROR,
            turn_count=20,
            duration_ms=120000,
            token_usage=TokenUsage(
                input_tokens=50000,
                output_tokens=10000,
                cache_read_tokens=0,
                cache_creation_tokens=0,
            ),
            tools_used=[fail_tool] * 6,
        )
    )

    # Session 3: Agent stuck in a loop
    loop_tools = [
        ToolRecord(
            name="Edit",
            tool_input=edit_input,
            error=True,
            timestamp=now,
        )
        for _ in range(8)
    ]
    sink.write(
        Trace(
            id="trc-loop",
            timestamp=now,
            agent="claude-code",
            session_id="sess-3",
            model="claude-sonnet-4-6",
            task="Fix CSS issue",
            status=Status.ERROR,
            turn_count=12,
            duration_ms=90000,
            token_usage=TokenUsage(input_tokens=20000, output_tokens=5000),
            tools_used=loop_tools,
        )
    )

    sink.close()
    return str(db_path)


# ── Cost overview ─────────────────────────────────────────────────────


class TestCostOverview:
    def test_session_count(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        overview = cost_overview(conn, days=30)
        conn.close()
        assert overview.total_sessions == 3

    def test_total_cost_positive(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        overview = cost_overview(conn, days=30)
        conn.close()
        assert overview.total_cost > 0

    def test_cache_hit_ratio(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        overview = cost_overview(conn, days=30)
        conn.close()
        # We have 45000 cache_read out of 75000 (5k+50k+20k) input
        # Ratio = 45000 / (45000 + 75000) = 0.375
        assert 0 < overview.cache_hit_ratio < 1

    def test_cache_savings_positive(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        overview = cost_overview(conn, days=30)
        conn.close()
        assert overview.cache_savings > 0
        assert overview.cost_without_cache > overview.total_cost

    def test_burn_rate(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        overview = cost_overview(conn, days=7)
        conn.close()
        assert overview.daily_burn_rate > 0
        assert overview.projected_monthly == pytest.approx(
            overview.daily_burn_rate * 30, rel=0.01
        )

    def test_by_model(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        overview = cost_overview(conn, days=30)
        conn.close()
        models = [m.model for m in overview.by_model]
        assert "claude-opus-4-6" in models

    def test_by_day(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        overview = cost_overview(conn, days=30)
        conn.close()
        assert len(overview.by_day) >= 1

    def test_agent_filter(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        overview = cost_overview(conn, days=30, agent="nonexistent")
        conn.close()
        assert overview.total_sessions == 0

    def test_empty_db(self, tmp_path) -> None:
        db_path = tmp_path / "empty.db"
        sink = SQLiteSink(path=str(db_path))
        conn = sink.conn
        overview = cost_overview(conn, days=7)
        sink.close()
        assert overview.total_sessions == 0
        assert overview.total_cost == 0.0
        assert overview.cache_hit_ratio == 0.0


# ── Session costs ─────────────────────────────────────────────────────


class TestSessionCosts:
    def test_returns_sessions(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        sessions = session_costs(conn, days=30)
        conn.close()
        assert len(sessions) == 3

    def test_sorted_by_cost(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        sessions = session_costs(conn, days=30, sort="cost")
        conn.close()
        costs = [s.cost for s in sessions]
        assert costs == sorted(costs, reverse=True)

    def test_sorted_by_cache(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        sessions = session_costs(conn, days=30, sort="cache")
        conn.close()
        ratios = [s.cache_hit_ratio for s in sessions]
        assert ratios == sorted(ratios)

    def test_per_session_cache_ratio(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        sessions = session_costs(conn, days=30)
        conn.close()
        by_id = {s.trace_id: s for s in sessions}
        assert by_id["trc-good-cache"].cache_hit_ratio > 0.5
        assert by_id["trc-no-cache"].cache_hit_ratio == 0.0

    def test_tool_and_error_counts(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        sessions = session_costs(conn, days=30)
        conn.close()
        by_id = {s.trace_id: s for s in sessions}
        assert by_id["trc-no-cache"].error_count == 6
        assert by_id["trc-good-cache"].tool_count == 3

    def test_limit(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        sessions = session_costs(conn, days=30, limit=1)
        conn.close()
        assert len(sessions) == 1


# ── Budget status ─────────────────────────────────────────────────────


class TestBudgetStatus:
    def test_under_budget(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        status = budget_status(conn, daily_budget=100.0)
        conn.close()
        assert status.on_track
        assert status.remaining_today >= 0

    def test_over_budget(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        status = budget_status(conn, daily_budget=0.001)
        conn.close()
        assert not status.on_track
        assert status.pct_used > 100

    def test_sessions_counted(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        status = budget_status(conn, daily_budget=50.0)
        conn.close()
        # All 3 sessions have today's date
        assert status.sessions_today == 3


# ── Anomaly detection ─────────────────────────────────────────────────


class TestAnomalyDetection:
    def test_detects_anomalies(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        anomalies = detect_anomalies(conn, days=30)
        conn.close()
        assert len(anomalies) > 0

    def test_detects_cache_miss(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        anomalies = detect_anomalies(conn, days=30)
        conn.close()
        cache_misses = [a for a in anomalies if a.type == "cache_miss"]
        assert len(cache_misses) >= 1
        assert any(a.trace_id == "trc-no-cache" for a in cache_misses)

    def test_detects_error_storm(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        anomalies = detect_anomalies(conn, days=30)
        conn.close()
        storms = [a for a in anomalies if a.type == "error_storm"]
        assert len(storms) >= 1

    def test_detects_loop(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        anomalies = detect_anomalies(conn, days=30)
        conn.close()
        loops = [a for a in anomalies if a.type == "loop"]
        assert len(loops) >= 1
        assert any(a.trace_id == "trc-loop" for a in loops)

    def test_sorted_by_cost(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        anomalies = detect_anomalies(conn, days=30)
        conn.close()
        costs = [a.cost for a in anomalies]
        assert costs == sorted(costs, reverse=True)

    def test_agent_filter(self, cost_db: str) -> None:
        conn = sqlite3.connect(cost_db)
        anomalies = detect_anomalies(conn, days=30, agent="nonexistent")
        conn.close()
        assert len(anomalies) == 0

    def test_empty_db_no_anomalies(self, tmp_path) -> None:
        db_path = tmp_path / "empty.db"
        sink = SQLiteSink(path=str(db_path))
        conn = sink.conn
        anomalies = detect_anomalies(conn, days=7)
        sink.close()
        assert len(anomalies) == 0
