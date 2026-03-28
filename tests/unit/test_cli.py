from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import make_tool_record, make_trace

from openflux.cli import (
    AVAILABLE_ADAPTERS,
    CLAUDE_CODE_HOOKS,
    _bar,
    _estimate_cost,
    _relative_time,
    _truncate,
    main,
)
from openflux.schema import TokenUsage, Trace
from openflux.sinks.sqlite import SQLiteSink


def _run_cli(args: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["openflux", *args])
    main()


def _populated_db(db_path: Path, traces: list[Trace]) -> None:
    sink = SQLiteSink(path=db_path)
    for r in traces:
        sink.write(r)
    sink.close()


def _mock_sink(
    recent_results: list[Trace] | None = None,
    search_results: list[Trace] | None = None,
    get_result: Trace | None = None,
) -> MagicMock:
    sink = MagicMock()
    sink.recent.return_value = recent_results or []
    sink.search.return_value = search_results or []
    sink.get.return_value = get_result
    return sink


class TestRelativeTime:
    def test_just_now(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).isoformat()
        assert _relative_time(now) == "just now"

    def test_minutes_ago(self) -> None:
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        assert _relative_time(ts) == "5m ago"

    def test_hours_ago(self) -> None:
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        assert _relative_time(ts) == "3h ago"

    def test_days_ago(self) -> None:
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        assert _relative_time(ts) == "2d ago"

    def test_z_suffix(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _relative_time(now) == "just now"

    def test_invalid_timestamp(self) -> None:
        assert _relative_time("not-a-date") == "not-a-date"


class TestTruncate:
    def test_short_text(self) -> None:
        assert _truncate("hello", 50) == "hello"

    def test_long_text(self) -> None:
        result = _truncate("a" * 100, 50)
        assert len(result) == 50
        assert result.endswith("…")

    def test_empty(self) -> None:
        assert _truncate("", 50) == ""

    def test_newlines_stripped(self) -> None:
        assert "\n" not in _truncate("line1\nline2", 50)


class TestCmdRecent:
    def test_output(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trace = make_trace(agent="claude-code", task="Fix bug in parser")
        sink = _mock_sink(recent_results=[trace])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["recent"], monkeypatch)
        out = capsys.readouterr().out
        assert trace.id in out
        assert "claude-code" in out
        assert "1 trace(s) shown." in out

    def test_agent_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = _mock_sink(recent_results=[])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["recent", "--agent", "langchain"], monkeypatch)
        sink.recent.assert_called_once_with(limit=10, agent="langchain", scope=None)

    def test_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = _mock_sink(recent_results=[])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["recent", "--limit", "5"], monkeypatch)
        sink.recent.assert_called_once_with(limit=5, agent=None, scope=None)

    def test_scope_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = _mock_sink(recent_results=[])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["recent", "--scope", "unit-test"], monkeypatch)
        sink.recent.assert_called_once_with(limit=10, agent=None, scope="unit-test")

    def test_empty_db(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = _mock_sink(recent_results=[])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["recent"], monkeypatch)
        out = capsys.readouterr().out
        assert "No traces found." in out


class TestCmdSearch:
    def test_query(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trace = make_trace(task="Deploy to production")
        sink = _mock_sink(search_results=[trace])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["search", "deploy"], monkeypatch)
        out = capsys.readouterr().out
        assert trace.id in out
        assert "1 result(s) for 'deploy'." in out

    def test_search_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = _mock_sink(search_results=[])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["search", "foo", "--limit", "3"], monkeypatch)
        sink.search.assert_called_once_with("foo", limit=3)

    def test_no_results(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = _mock_sink(search_results=[])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["search", "nonexistent"], monkeypatch)
        out = capsys.readouterr().out
        assert "No traces found." in out
        assert "0 result(s)" in out


class TestCmdTrace:
    def test_full_trace(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trace = make_trace(
            id="trc-aabbccddeeff",
            agent="claude-code",
            model="claude-sonnet-4-20250514",
            task="Refactor auth module",
            decision="Split into middleware",
            scope="refactor",
            tags=["auth", "cleanup"],
            files_modified=["/src/auth.py"],
            turn_count=5,
            duration_ms=3200,
            token_usage=TokenUsage(
                input_tokens=2000,
                output_tokens=800,
                cache_read_tokens=100,
                cache_creation_tokens=50,
            ),
            tools_used=[make_tool_record(name="Edit")],
        )
        sink = _mock_sink(get_result=trace)
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["trace", "trc-aabbccddeeff"], monkeypatch)
        out = capsys.readouterr().out
        assert "Trace: trc-aabbccddeeff" in out
        assert "claude-code" in out
        assert "claude-sonnet-4-20250514" in out
        assert "Refactor auth module" in out
        assert "Split into middleware" in out
        assert "auth, cleanup" in out
        assert "/src/auth.py" in out
        assert "2,000" in out  # formatted input tokens
        assert "800" in out
        assert "Edit" in out

    def test_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = _mock_sink(get_result=None)
        with (
            patch("openflux.cli._get_sink", return_value=sink),
            pytest.raises(SystemExit, match="1"),
        ):
            _run_cli(["trace", "trc-doesnotexist"], monkeypatch)

    def test_correction(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trace = make_trace(
            id="trc-correction01",
            correction="Reverted bad migration",
        )
        sink = _mock_sink(get_result=trace)
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["trace", "trc-correction01"], monkeypatch)
        out = capsys.readouterr().out
        assert "Reverted bad migration" in out

    def test_metadata(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trace = make_trace(
            id="trc-metadata001",
            metadata={"ci_run": "12345", "branch": "feature/x"},
        )
        sink = _mock_sink(get_result=trace)
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["trace", "trc-metadata001"], monkeypatch)
        out = capsys.readouterr().out
        assert "ci_run" in out
        assert "12345" in out


class TestCmdExport:
    def test_json(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trace = make_trace(agent="test-export")
        sink = _mock_sink(recent_results=[trace])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["export"], monkeypatch)
        out = capsys.readouterr().out
        data = json.loads(out.strip())
        assert data["agent"] == "test-export"

    def test_agent_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = _mock_sink(recent_results=[])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["export", "--agent", "langchain"], monkeypatch)
        sink.recent.assert_called_once_with(
            limit=10_000,
            agent="langchain",
            since=None,
        )

    def test_since_filter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = _mock_sink(recent_results=[])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["export", "--since", "2025-01-01T00:00:00Z"], monkeypatch)
        sink.recent.assert_called_once_with(
            limit=10_000,
            agent=None,
            since="2025-01-01T00:00:00Z",
        )

    def test_empty_db(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = _mock_sink(recent_results=[])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["export"], monkeypatch)
        out = capsys.readouterr().out
        assert out.strip() == ""

    def test_ndjson(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r1 = make_trace(agent="agent-1")
        r2 = make_trace(agent="agent-2")
        sink = _mock_sink(recent_results=[r1, r2])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["export"], monkeypatch)
        out = capsys.readouterr().out
        lines = [ln for ln in out.strip().split("\n") if ln]
        assert len(lines) == 2
        agents = {json.loads(ln)["agent"] for ln in lines}
        assert agents == {"agent-1", "agent-2"}


class TestCmdStatus:
    def test_counts(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(
            db_path,
            [
                make_trace(agent="claude-code"),
                make_trace(agent="claude-code"),
                make_trace(agent="langchain"),
            ],
        )
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["status"], monkeypatch)
        out = capsys.readouterr().out
        assert str(db_path) in out
        assert "3 trace(s)" in out
        assert "claude-code: 2" in out
        assert "langchain: 1" in out

    def test_missing_db(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(tmp_path / "missing.db"))
        _run_cli(["status"], monkeypatch)
        out = capsys.readouterr().out
        assert "No database" in out

    def test_empty(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "empty.db"
        _populated_db(db_path, [])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["status"], monkeypatch)
        out = capsys.readouterr().out
        assert "0 trace(s)" in out

    def test_status_breakdown(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(
            db_path,
            [
                make_trace(status="completed"),
                make_trace(status="error"),
            ],
        )
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["status"], monkeypatch)
        out = capsys.readouterr().out
        assert "completed: 1" in out
        assert "error: 1" in out


class TestCmdInstall:
    def test_creates_settings(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        with patch("openflux.cli.Path.home", return_value=tmp_path):
            _run_cli(["install", "claude-code"], monkeypatch)
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        hooks = settings["hooks"]
        for event, cmd in CLAUDE_CODE_HOOKS.items():
            assert event in hooks
            cmds = [h["command"] for g in hooks[event] for h in g.get("hooks", [])]
            assert cmd in cmds
        out = capsys.readouterr().out
        assert "Added hooks" in out

    def test_preserves_existing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        existing = {"theme": "dark", "hooks": {}}
        settings_path.write_text(json.dumps(existing))
        with patch("openflux.cli.Path.home", return_value=tmp_path):
            _run_cli(["install", "claude-code"], monkeypatch)
        settings = json.loads(settings_path.read_text())
        assert settings["theme"] == "dark"
        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]

    def test_skips_duplicates(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        cmd = CLAUDE_CODE_HOOKS["SessionStart"]
        existing = {"hooks": {"SessionStart": [{
            "matcher": "",
            "hooks": [{"type": "command", "command": cmd}],
        }]}}
        settings_path.write_text(json.dumps(existing))
        with patch("openflux.cli.Path.home", return_value=tmp_path):
            _run_cli(["install", "claude-code"], monkeypatch)
        out = capsys.readouterr().out
        assert "Already configured" in out
        settings = json.loads(settings_path.read_text())
        session_hooks = settings["hooks"]["SessionStart"]
        cmds = [h["command"] for g in session_hooks for h in g.get("hooks", [])]
        assert cmds.count(CLAUDE_CODE_HOOKS["SessionStart"]) == 1

    def test_list_adapters(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _run_cli(["install", "--list"], monkeypatch)
        out = capsys.readouterr().out
        assert "Available adapters:" in out
        for name in AVAILABLE_ADAPTERS:
            assert name in out

    def test_non_cli_adapter(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _run_cli(["install", "langchain"], monkeypatch)
        out = capsys.readouterr().out
        assert "installed via Python API" in out


class TestCmdCost:
    def test_cost_output(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(
            db_path,
            [
                make_trace(
                    agent="claude-code",
                    model="claude-sonnet-4-20250514",
                    token_usage=TokenUsage(input_tokens=100_000, output_tokens=25_000),
                ),
                make_trace(
                    agent="langchain-rag",
                    model="gpt-4o-mini",
                    token_usage=TokenUsage(input_tokens=50_000, output_tokens=10_000),
                ),
            ],
        )
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["cost", "--days", "7"], monkeypatch)
        out = capsys.readouterr().out

        assert "Token Usage (last 7 days)" in out
        assert "Traces:" in out
        assert "Input:" in out
        assert "Output:" in out
        assert "Total:" in out
        assert "By model:" in out
        assert "claude-sonnet-4-20250514" in out
        assert "gpt-4o-mini" in out
        assert "By agent:" in out
        assert "claude-code" in out
        assert "langchain-rag" in out

    def test_cost_agent_filter(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(
            db_path,
            [
                make_trace(
                    agent="claude-code",
                    model="claude-sonnet-4-20250514",
                    token_usage=TokenUsage(input_tokens=100_000, output_tokens=25_000),
                ),
                make_trace(
                    agent="other-agent",
                    model="gpt-4o-mini",
                    token_usage=TokenUsage(input_tokens=50_000, output_tokens=10_000),
                ),
            ],
        )
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["cost", "--agent", "claude-code"], monkeypatch)
        out = capsys.readouterr().out

        # Only claude-code agent should appear
        assert "claude-code" in out
        assert "other-agent" not in out

    def test_cost_empty_db(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(db_path, [])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["cost"], monkeypatch)
        out = capsys.readouterr().out
        assert "Traces:" in out
        assert "0" in out

    def test_cost_token_values(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify exact token sums with known values."""
        db_path = tmp_path / "traces.db"
        _populated_db(
            db_path,
            [
                make_trace(
                    agent="a",
                    model="claude-sonnet-4-20250514",
                    token_usage=TokenUsage(input_tokens=1_000, output_tokens=500),
                ),
                make_trace(
                    agent="a",
                    model="claude-sonnet-4-20250514",
                    token_usage=TokenUsage(input_tokens=2_000, output_tokens=1_000),
                ),
            ],
        )
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["cost"], monkeypatch)
        out = capsys.readouterr().out
        # Input: 3,000, Output: 1,500, Total: 4,500
        assert "3,000" in out
        assert "1,500" in out
        assert "4,500" in out


class TestCmdForget:
    def test_forget_single(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        trace = make_trace(id="trc-deleteme00000")
        _populated_db(db_path, [trace, make_trace()])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["forget", "trc-deleteme00000"], monkeypatch)
        out = capsys.readouterr().out
        assert "Deleted trace trc-deleteme00000" in out

        # Verify it's actually gone
        sink = SQLiteSink(path=db_path)
        assert sink.get("trc-deleteme00000") is None
        remaining = sink.recent(limit=100)
        assert len(remaining) == 1
        sink.close()

    def test_forget_not_found(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(db_path, [make_trace()])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["forget", "trc-nonexistent00"], monkeypatch)
        out = capsys.readouterr().out
        assert "Trace not found" in out

    def test_forget_by_agent(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(
            db_path,
            [
                make_trace(agent="old-agent"),
                make_trace(agent="old-agent"),
                make_trace(agent="keep-agent"),
            ],
        )
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        # Simulate user typing "y" to confirm
        monkeypatch.setattr("builtins.input", lambda _: "y")
        _run_cli(["forget", "--agent", "old-agent"], monkeypatch)
        out = capsys.readouterr().out
        assert "Deleted 2 traces" in out

        sink = SQLiteSink(path=db_path)
        remaining = sink.recent(limit=100)
        assert len(remaining) == 1
        assert remaining[0].agent == "keep-agent"
        sink.close()

    def test_forget_by_agent_cancelled(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(db_path, [make_trace(agent="my-agent")])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        monkeypatch.setattr("builtins.input", lambda _: "n")
        _run_cli(["forget", "--agent", "my-agent"], monkeypatch)
        out = capsys.readouterr().out
        assert "Cancelled" in out

        # Trace should still exist
        sink = SQLiteSink(path=db_path)
        assert len(sink.recent(limit=100)) == 1
        sink.close()

    def test_forget_by_agent_none_found(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(db_path, [make_trace(agent="other")])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["forget", "--agent", "ghost"], monkeypatch)
        out = capsys.readouterr().out
        assert "No traces found" in out


class TestCmdPrune:
    def test_prune_by_date(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        new_ts = datetime.now(UTC).isoformat()
        _populated_db(
            db_path,
            [
                make_trace(timestamp=old_ts, agent="old"),
                make_trace(timestamp=old_ts, agent="old"),
                make_trace(timestamp=new_ts, agent="new"),
            ],
        )
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        monkeypatch.setattr("builtins.input", lambda _: "y")
        _run_cli(["prune", "--older-than", "30d"], monkeypatch)
        out = capsys.readouterr().out
        assert "Deleted 2 traces" in out
        assert "DB size:" in out

        sink = SQLiteSink(path=db_path)
        remaining = sink.recent(limit=100)
        assert len(remaining) == 1
        assert remaining[0].agent == "new"
        sink.close()

    def test_prune_with_agent_scope(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        _populated_db(
            db_path,
            [
                make_trace(timestamp=old_ts, agent="target"),
                make_trace(timestamp=old_ts, agent="keep"),
            ],
        )
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        monkeypatch.setattr("builtins.input", lambda _: "y")
        _run_cli(["prune", "--older-than", "30d", "--agent", "target"], monkeypatch)
        out = capsys.readouterr().out
        assert "Deleted 1 traces" in out

        sink = SQLiteSink(path=db_path)
        remaining = sink.recent(limit=100)
        assert len(remaining) == 1
        assert remaining[0].agent == "keep"
        sink.close()

    def test_prune_cancelled(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        old_ts = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        _populated_db(db_path, [make_trace(timestamp=old_ts)])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        monkeypatch.setattr("builtins.input", lambda _: "n")
        _run_cli(["prune", "--older-than", "30d"], monkeypatch)
        out = capsys.readouterr().out
        assert "Cancelled" in out

    def test_prune_nothing_to_delete(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        new_ts = datetime.now(UTC).isoformat()
        _populated_db(db_path, [make_trace(timestamp=new_ts)])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["prune", "--older-than", "30d"], monkeypatch)
        out = capsys.readouterr().out
        assert "No matching traces" in out

    def test_prune_invalid_duration(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(db_path, [make_trace()])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        with pytest.raises(SystemExit, match="1"):
            _run_cli(["prune", "--older-than", "bad"], monkeypatch)


class TestStatusTokens:
    def test_status_shows_token_totals(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(
            db_path,
            [
                make_trace(
                    model="claude-sonnet-4-20250514",
                    token_usage=TokenUsage(
                        input_tokens=1_000_000, output_tokens=250_000
                    ),
                ),
                make_trace(
                    model="gpt-4o-mini",
                    token_usage=TokenUsage(input_tokens=500_000, output_tokens=100_000),
                ),
            ],
        )
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["status"], monkeypatch)
        out = capsys.readouterr().out
        assert "Token usage (all time):" in out
        assert "1,500,000" in out
        assert "350,000" in out
        assert "Est. cost:" in out
        assert "$" in out

    def test_status_no_tokens(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No token usage section when all token counts are zero."""
        db_path = tmp_path / "traces.db"
        _populated_db(db_path, [make_trace()])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        _run_cli(["status"], monkeypatch)
        out = capsys.readouterr().out
        assert "Token usage" not in out


class TestCostHelpers:
    @pytest.mark.parametrize(
        ("model", "expected_min"),
        [
            ("claude-sonnet-4-20250514", 3.0),
            ("gpt-4o-mini", 0.15),
            ("gpt-4o-2024-08-06", 2.5),
            ("gemini-2.0-flash", 0.075),
            ("unknown-model", 1.0),
        ],
    )
    def test_estimate_cost_rates(self, model: str, expected_min: float) -> None:
        # 1M input tokens, 0 output -> should match input rate exactly
        cost = _estimate_cost(model, 1_000_000, 0)
        assert abs(cost - expected_min) < 0.01

    def test_bar_proportional(self) -> None:
        full = _bar(100, 100, width=10)
        half = _bar(50, 100, width=10)
        assert len(full) == 10
        assert len(half) == 5

    def test_bar_zero_max(self) -> None:
        assert _bar(0, 0, width=10) == ""

    def test_bar_minimum_one(self) -> None:
        # Even tiny values should show at least 1 block
        bar = _bar(1, 1_000_000, width=12)
        assert len(bar) >= 1


class TestErrorCases:
    def test_no_subcommand(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with pytest.raises(SystemExit, match="0"):
            _run_cli([], monkeypatch)
        out = capsys.readouterr().out
        assert "openflux" in out.lower() or "usage" in out.lower()

    def test_missing_db(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(tmp_path / "nope.db"))
        with pytest.raises(SystemExit, match="1"):
            _run_cli(["recent"], monkeypatch)

    def test_search_missing_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _run_cli(["search"], monkeypatch)

    def test_trace_missing_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _run_cli(["trace"], monkeypatch)

    def test_forget_no_args(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "traces.db"
        _populated_db(db_path, [make_trace()])
        monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
        with pytest.raises(SystemExit, match="1"):
            _run_cli(["forget"], monkeypatch)


class TestHelp:
    def test_main_help(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with pytest.raises(SystemExit, match="0"):
            _run_cli(["--help"], monkeypatch)
        out = capsys.readouterr().out
        assert "openflux" in out.lower()

    @pytest.mark.parametrize(
        "subcommand",
        [
            "recent",
            "search",
            "trace",
            "export",
            "status",
            "cost",
            "forget",
            "prune",
            "install",
        ],
    )
    def test_subcommand_help(
        self,
        subcommand: str,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        with pytest.raises(SystemExit, match="0"):
            _run_cli([subcommand, "--help"], monkeypatch)
        out = capsys.readouterr().out
        assert subcommand in out.lower() or "usage" in out.lower()
