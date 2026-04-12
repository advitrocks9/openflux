"""Tests for tool efficiency analysis and session replay."""

import sqlite3

import pytest

from openflux._pricing import estimate_cost
from openflux.schema import Status, TokenUsage, ToolRecord, Trace
from openflux.sinks.sqlite import SQLiteSink
from openflux.waste import (
    _classify_bash,
    _classify_tool,
    _parse_output_summary,
    _parse_target,
    _session_redundancy,
    analyze_efficiency,
    replay_session,
)

# ── Pricing ────────────────────────────────────────────────────────────


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


# ── Tool classification ───────────────────────────────────────────────


class TestClassification:
    def test_bash_git_status(self) -> None:
        assert _classify_bash('{"command": "git status"}') == "git status"

    def test_bash_pytest(self) -> None:
        assert _classify_bash('{"command": "pytest tests/"}') == "Test (pytest)"

    def test_bash_ls(self) -> None:
        assert _classify_bash('{"command": "ls src/"}') == "Directory listing (ls)"

    def test_bash_cat(self) -> None:
        assert _classify_bash('{"command": "cat file.py"}') == "File read (cat)"

    def test_bash_head(self) -> None:
        assert _classify_bash('{"command": "head -20 file.py"}') == "File read (head)"

    def test_bash_other(self) -> None:
        assert _classify_bash('{"command": "whoami"}') == "Other"

    def test_overhead_tool(self) -> None:
        assert _classify_tool("TaskCreate", "{}").startswith("Overhead")

    def test_subagent(self) -> None:
        assert _classify_tool("Agent", "{}") == "Subagent"

    def test_regular_tool(self) -> None:
        assert _classify_tool("Read", "{}") == "Read"


# ── Redundancy detection ──────────────────────────────────────────────


class TestSessionRedundancy:
    def test_no_redundancy(self) -> None:
        tools = [
            ("Bash", '{"command": "ls src/"}'),
            ("Bash", '{"command": "cat file.py"}'),
            ("Bash", '{"command": "pytest"}'),
        ]
        result = _session_redundancy(tools)
        assert len(result) == 0

    def test_finds_repeated_command(self) -> None:
        tools = [
            ("Bash", '{"command": "git status"}'),
            ("Bash", '{"command": "git diff"}'),
            ("Bash", '{"command": "git status"}'),
        ]
        result = _session_redundancy(tools)
        assert len(result) >= 1
        assert any(p.redundant_calls >= 1 for p in result)

    def test_finds_repeated_file_read(self) -> None:
        tools = [
            ("Bash", '{"command": "cat src/main.py"}'),
            ("Bash", '{"command": "cat src/main.py"}'),
            ("Bash", '{"command": "cat src/main.py"}'),
        ]
        result = _session_redundancy(tools)
        assert len(result) >= 1
        total = sum(p.redundant_calls for p in result)
        assert total == 2  # 3 calls, 1 unique, 2 redundant

    def test_ignores_overhead(self) -> None:
        tools = [
            ("TaskCreate", "{}"),
            ("TaskCreate", "{}"),
            ("TaskUpdate", "{}"),
            ("TaskUpdate", "{}"),
        ]
        result = _session_redundancy(tools)
        assert len(result) == 0


# ── Target parsing ─────────────────────────────────────────────────────


class TestParseTarget:
    def test_bash_command(self) -> None:
        assert _parse_target("Bash", '{"command": "pytest tests/"}') == "pytest tests/"

    def test_read_file_path(self) -> None:
        assert _parse_target("Read", '{"file_path": "/src/main.py"}') == "/src/main.py"

    def test_grep_pattern(self) -> None:
        result = _parse_target("Grep", '{"pattern": "TODO", "path": "src/"}')
        assert result == '"TODO" in src/'

    def test_invalid_json(self) -> None:
        assert _parse_target("Bash", "not json") == "not json"

    def test_empty(self) -> None:
        assert _parse_target("Bash", "") == ""


class TestParseOutputSummary:
    def test_bash_failures(self) -> None:
        output = '{"stdout": "", "stderr": "FAILED test_a FAILED test_b"}'
        assert "2 failure" in _parse_output_summary("Bash", output, error=False)

    def test_read_size(self) -> None:
        result = _parse_output_summary("Read", "x" * 2048, error=False)
        assert "KB" in result or "B" in result

    def test_error_message(self) -> None:
        result = _parse_output_summary("Bash", "command not found", error=True)
        assert "command not found" in result


# ── Integration ────────────────────────────────────────────────────────


@pytest.fixture()
def test_db(tmp_path):
    db_path = tmp_path / "test.db"
    sink = SQLiteSink(path=str(db_path))

    # Session with repeated commands
    tools = [
        ToolRecord(
            name="Bash",
            tool_input='{"command": "ls src/"}',
            tool_output='{"stdout": "main.py", "stderr": ""}',
            timestamp="2026-04-10T10:00:01Z",
        ),
        ToolRecord(
            name="Bash",
            tool_input='{"command": "cat src/main.py"}',
            tool_output='{"stdout": "print(1)", "stderr": ""}',
            timestamp="2026-04-10T10:00:02Z",
        ),
        ToolRecord(
            name="Bash",
            tool_input='{"command": "git status"}',
            tool_output='{"stdout": "clean", "stderr": ""}',
            timestamp="2026-04-10T10:00:03Z",
        ),
        ToolRecord(
            name="Bash",
            tool_input='{"command": "cat src/main.py"}',
            tool_output='{"stdout": "print(1)", "stderr": ""}',
            timestamp="2026-04-10T10:00:04Z",
        ),
        ToolRecord(
            name="Bash",
            tool_input='{"command": "git status"}',
            tool_output='{"stdout": "clean", "stderr": ""}',
            timestamp="2026-04-10T10:00:05Z",
        ),
        ToolRecord(
            name="TaskCreate",
            tool_input="{}",
            timestamp="2026-04-10T10:00:06Z",
        ),
        ToolRecord(
            name="TaskUpdate",
            tool_input="{}",
            timestamp="2026-04-10T10:00:07Z",
        ),
    ]
    trace = Trace(
        id="trc-test001",
        timestamp="2026-04-10T10:00:00Z",
        agent="claude-code",
        session_id="sess-1",
        model="claude-opus-4-6",
        task="Fix the bug",
        status=Status.COMPLETED,
        turn_count=10,
        token_usage=TokenUsage(input_tokens=1000, output_tokens=2000),
        tools_used=tools,
    )
    sink.write(trace)
    sink.close()
    return str(db_path)


class TestAnalyzeEfficiency:
    def test_counts_sessions(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        report = analyze_efficiency(conn, days=30)
        conn.close()
        assert report.total_sessions == 1

    def test_counts_tools(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        report = analyze_efficiency(conn, days=30)
        conn.close()
        assert report.total_tool_calls == 7

    def test_finds_overhead(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        report = analyze_efficiency(conn, days=30)
        conn.close()
        assert report.overhead_calls == 2

    def test_finds_redundancy(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        report = analyze_efficiency(conn, days=30)
        conn.close()
        # cat src/main.py and git status each repeated once
        assert report.total_redundant_calls >= 2

    def test_bash_breakdown(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        report = analyze_efficiency(conn, days=30)
        conn.close()
        assert len(report.bash_breakdown) > 0
        names = [b.name for b in report.bash_breakdown]
        assert "git status" in names

    def test_agent_filter(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        report = analyze_efficiency(conn, days=30, agent="nonexistent")
        conn.close()
        assert report.total_sessions == 0


class TestReplaySession:
    def test_replay_exists(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        replay = replay_session(conn, "trc-test001")
        conn.close()
        assert replay is not None
        assert len(replay.tools) == 7

    def test_replay_breakdown(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        replay = replay_session(conn, "trc-test001")
        conn.close()
        assert replay is not None
        assert len(replay.tool_breakdown) > 0

    def test_replay_redundancy(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        replay = replay_session(conn, "trc-test001")
        conn.close()
        assert replay is not None
        assert len(replay.redundant_in_session) >= 1

    def test_replay_nonexistent(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        assert replay_session(conn, "trc-nope") is None
        conn.close()

    def test_tool_targets(self, test_db: str) -> None:
        conn = sqlite3.connect(test_db)
        replay = replay_session(conn, "trc-test001")
        conn.close()
        assert replay is not None
        assert "ls src/" in replay.tools[0].target
