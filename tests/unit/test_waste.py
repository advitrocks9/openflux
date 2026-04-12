"""Tests for waste detection and session replay."""

import sqlite3

import pytest

from openflux._pricing import estimate_cost
from openflux.schema import Status, TokenUsage, ToolRecord, Trace
from openflux.sinks.sqlite import SQLiteSink
from openflux.waste import (
    _detect_loop,
    _parse_output_summary,
    _parse_target,
    analyze_waste,
    replay_session,
)

# ── Pricing ────────────────────────────────────────────────────────────


class TestPricing:
    def test_opus_rates(self) -> None:
        cost = estimate_cost("claude-opus-4-6", input_tokens=1_000_000)
        assert cost == pytest.approx(15.0, rel=0.01)

    def test_opus_output(self) -> None:
        cost = estimate_cost("claude-opus-4-6", output_tokens=1_000_000)
        assert cost == pytest.approx(75.0, rel=0.01)

    def test_opus_cache_read(self) -> None:
        cost = estimate_cost("claude-opus-4-6", cache_read_tokens=1_000_000)
        assert cost == pytest.approx(1.5, rel=0.01)

    def test_sonnet_rates(self) -> None:
        cost = estimate_cost("claude-sonnet-4-6", input_tokens=1_000_000)
        assert cost == pytest.approx(3.0, rel=0.01)

    def test_haiku_rates(self) -> None:
        cost = estimate_cost("claude-haiku-4-5", input_tokens=1_000_000)
        assert cost == pytest.approx(0.25, rel=0.01)

    def test_gpt4o_mini(self) -> None:
        cost = estimate_cost("gpt-4o-mini", input_tokens=1_000_000)
        assert cost == pytest.approx(0.15, rel=0.01)

    def test_unknown_model_uses_default(self) -> None:
        cost = estimate_cost("some-unknown-model", input_tokens=1_000_000)
        assert cost == pytest.approx(1.0, rel=0.01)

    def test_zero_tokens(self) -> None:
        assert estimate_cost("claude-opus-4-6") == 0.0

    def test_combined(self) -> None:
        cost = estimate_cost(
            "claude-opus-4-6",
            input_tokens=100,
            output_tokens=200,
            cache_read_tokens=300,
            cache_creation_tokens=400,
        )
        expected = (100 * 15 + 200 * 75 + 300 * 1.5 + 400 * 18.75) / 1_000_000
        assert cost == pytest.approx(expected, rel=0.001)


# ── Loop detection ─────────────────────────────────────────────────────


class TestLoopDetection:
    def test_no_loop_in_clean_session(self) -> None:
        tools = [
            ("Read", False),
            ("Read", False),
            ("Edit", False),
            ("Bash", False),
        ]
        start, cycles = _detect_loop(tools)
        assert start is None
        assert cycles == 0

    def test_detects_three_cycle_loop(self) -> None:
        tools = [
            ("Read", False),
            ("Edit", False),
            ("Bash", True),
            ("Edit", False),
            ("Bash", True),
            ("Edit", False),
            ("Bash", True),
        ]
        start, cycles = _detect_loop(tools)
        assert start is not None
        assert cycles >= 3

    def test_no_loop_with_only_two_cycles(self) -> None:
        tools = [
            ("Edit", False),
            ("Bash", True),
            ("Edit", False),
            ("Bash", True),
            ("Read", False),
        ]
        start, cycles = _detect_loop(tools)
        assert start is None
        assert cycles == 0

    def test_detects_loop_with_write_tool(self) -> None:
        tools = [
            ("Write", False),
            ("Bash", True),
            ("Write", False),
            ("Bash", True),
            ("Write", False),
            ("Bash", True),
        ]
        start, cycles = _detect_loop(tools)
        assert start is not None
        assert cycles >= 3

    def test_no_loop_when_bash_succeeds(self) -> None:
        tools = [
            ("Edit", False),
            ("Bash", False),
            ("Edit", False),
            ("Bash", False),
            ("Edit", False),
            ("Bash", False),
        ]
        start, cycles = _detect_loop(tools)
        assert start is None

    def test_empty_sequence(self) -> None:
        start, cycles = _detect_loop([])
        assert start is None
        assert cycles == 0


# ── Target parsing ─────────────────────────────────────────────────────


class TestParseTarget:
    def test_bash_command(self) -> None:
        result = _parse_target("Bash", '{"command": "pytest tests/"}')
        assert result == "pytest tests/"

    def test_read_file_path(self) -> None:
        result = _parse_target("Read", '{"file_path": "/src/main.py"}')
        assert result == "/src/main.py"

    def test_grep_pattern(self) -> None:
        result = _parse_target("Grep", '{"pattern": "TODO", "path": "src/"}')
        assert result == '"TODO" in src/'

    def test_invalid_json(self) -> None:
        result = _parse_target("Bash", "not json")
        assert result == "not json"

    def test_empty_input(self) -> None:
        result = _parse_target("Bash", "")
        assert result == ""


class TestParseOutputSummary:
    def test_bash_with_failures(self) -> None:
        output = '{"stdout": "", "stderr": "FAILED test_a FAILED test_b"}'
        result = _parse_output_summary("Bash", output, error=False)
        assert "2 failure" in result

    def test_read_shows_size(self) -> None:
        result = _parse_output_summary("Read", "x" * 2048, error=False)
        assert "KB" in result or "B" in result

    def test_edit_empty_summary(self) -> None:
        result = _parse_output_summary("Edit", "ok", error=False)
        assert result == ""

    def test_error_shows_message(self) -> None:
        result = _parse_output_summary("Bash", "command not found", error=True)
        assert "command not found" in result


# ── Integration: analyze_waste + replay ────────────────────────────────


@pytest.fixture()
def waste_db(tmp_path):
    """Create a DB with traces that have known waste patterns."""
    db_path = tmp_path / "waste_test.db"
    sink = SQLiteSink(path=str(db_path))

    # Session 1: clean session (no waste)
    clean = Trace(
        id="trc-clean001",
        timestamp="2026-04-10T10:00:00Z",
        agent="claude-code",
        session_id="sess-clean",
        model="claude-opus-4-6",
        task="Fix the auth bug",
        status=Status.COMPLETED,
        scope="myproject",
        turn_count=5,
        token_usage=TokenUsage(input_tokens=1000, output_tokens=2000),
        tools_used=[
            ToolRecord(
                name="Read",
                tool_input='{"file_path": "auth.py"}',
                tool_output="x" * 500,
                timestamp="2026-04-10T10:00:01Z",
            ),
            ToolRecord(
                name="Edit",
                tool_input='{"file_path": "auth.py"}',
                timestamp="2026-04-10T10:00:02Z",
            ),
            ToolRecord(
                name="Bash",
                tool_input='{"command": "pytest"}',
                tool_output='{"stdout": "1 passed", "stderr": ""}',
                timestamp="2026-04-10T10:00:03Z",
            ),
        ],
    )
    sink.write(clean)

    # Session 2: loop session (edit→bash fail cycle)
    loop_tools = []
    ts_base = "2026-04-10T11:00:"
    loop_tools.append(
        ToolRecord(
            name="Read",
            tool_input='{"file_path": "app.py"}',
            tool_output="x" * 300,
            timestamp=f"{ts_base}01Z",
        )
    )
    for i in range(4):
        loop_tools.append(
            ToolRecord(
                name="Edit",
                tool_input='{"file_path": "app.py"}',
                timestamp=f"{ts_base}{10 + i * 2:02d}Z",
            )
        )
        loop_tools.append(
            ToolRecord(
                name="Bash",
                tool_input='{"command": "pytest"}',
                tool_output='{"stdout": "", "stderr": "FAILED test_x"}',
                error=True,
                timestamp=f"{ts_base}{11 + i * 2:02d}Z",
            )
        )

    loop_trace = Trace(
        id="trc-loop001",
        timestamp="2026-04-10T11:00:00Z",
        agent="claude-code",
        session_id="sess-loop",
        model="claude-opus-4-6",
        task="Refactor the database layer",
        status=Status.ERROR,
        scope="myproject",
        turn_count=20,
        token_usage=TokenUsage(input_tokens=5000, output_tokens=10000),
        tools_used=loop_tools,
    )
    sink.write(loop_trace)

    # Session 3: error session (fast error, ≤5 turns)
    fast_err = Trace(
        id="trc-fasterr",
        timestamp="2026-04-10T12:00:00Z",
        agent="claude-code",
        session_id="sess-fasterr",
        model="claude-opus-4-6",
        task="Quick fix",
        status=Status.ERROR,
        scope="myproject",
        turn_count=2,
        token_usage=TokenUsage(input_tokens=100, output_tokens=200),
    )
    sink.write(fast_err)

    # Session 4: context reload (same scope within 10 min of session 1)
    reload_trace = Trace(
        id="trc-reload1",
        timestamp="2026-04-10T10:05:00Z",
        agent="claude-code",
        session_id="sess-reload",
        model="claude-opus-4-6",
        task="Continue auth work",
        status=Status.COMPLETED,
        scope="myproject",
        turn_count=3,
        token_usage=TokenUsage(input_tokens=800, output_tokens=1500),
    )
    sink.write(reload_trace)

    sink.close()
    return str(db_path)


class TestAnalyzeWaste:
    def test_finds_all_sessions(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        report = analyze_waste(conn, days=30)
        conn.close()
        assert report.total_sessions == 4

    def test_detects_loops(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        report = analyze_waste(conn, days=30)
        conn.close()
        assert len(report.loops) >= 1
        loop = report.loops[0]
        assert loop.trace_id == "trc-loop001"
        assert loop.cycle_count >= 3

    def test_detects_errors(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        report = analyze_waste(conn, days=30)
        conn.close()
        # fast_err has ≤5 turns, loop session is counted under loops
        assert report.errors.fast_errors >= 1

    def test_detects_reloads(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        report = analyze_waste(conn, days=30)
        conn.close()
        assert report.reloads.count >= 1

    def test_waste_less_than_total(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        report = analyze_waste(conn, days=30)
        conn.close()
        waste = report.loop_cost + report.errors.total_cost + report.reloads.total_cost
        assert waste <= report.total_cost

    def test_productive_cost_nonnegative(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        report = analyze_waste(conn, days=30)
        conn.close()
        assert report.productive_cost >= 0

    def test_agent_filter(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        report = analyze_waste(conn, days=30, agent="nonexistent-agent")
        conn.close()
        assert report.total_sessions == 0


class TestReplaySession:
    def test_replay_clean_session(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        replay = replay_session(conn, "trc-clean001")
        conn.close()
        assert replay is not None
        assert replay.trace_id == "trc-clean001"
        assert len(replay.tools) == 3
        assert replay.loop_start is None

    def test_replay_loop_session(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        replay = replay_session(conn, "trc-loop001")
        conn.close()
        assert replay is not None
        assert replay.loop_start is not None
        assert replay.loop_cycles >= 3
        assert replay.loop_cost > 0

    def test_replay_nonexistent(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        replay = replay_session(conn, "trc-doesnotexist")
        conn.close()
        assert replay is None

    def test_tool_steps_have_targets(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        replay = replay_session(conn, "trc-clean001")
        conn.close()
        assert replay is not None
        read_step = replay.tools[0]
        assert read_step.name == "Read"
        assert "auth.py" in read_step.target

    def test_tool_steps_ordered_by_index(self, waste_db: str) -> None:
        conn = sqlite3.connect(waste_db)
        replay = replay_session(conn, "trc-loop001")
        conn.close()
        assert replay is not None
        indices = [t.index for t in replay.tools]
        assert indices == list(range(1, len(replay.tools) + 1))
