"""Tests for `openflux outcomes` CLI subcommand."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from openflux.cli import main


def _run_cli(args: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["openflux", *args])
    main()


def _mock_sink_with_outcomes(outcomes: list[dict]) -> MagicMock:
    sink = MagicMock()
    sink.list_outcomes.return_value = outcomes
    return sink


class TestCmdOutcomes:
    def test_empty_db_prints_install_hint(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sink = _mock_sink_with_outcomes([])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["outcomes"], monkeypatch)
        out = capsys.readouterr().out
        assert "No outcomes recorded yet" in out
        assert "openflux install claude-code" in out
        assert "OPENFLUX_TEST_CMD" in out

    def test_outcomes_table_passing_session(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        outcomes = [
            {
                "session_id": "sess-abc-123",
                "agent": "claude-code",
                "start_sha": "a3f2c1e9b8d7e6f5a4c3b2a1098765432109876f",
                "end_sha": "8b4d9f0c1e2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c",
                "lines_added": 127,
                "lines_removed": 34,
                "files_changed": 6,
                "tests_exit_code": 0,
                "tests_passed": True,
                "pr_url": None,
                "pr_merged": None,
                "captured_at": "2026-04-29T14:22:00Z",
            }
        ]
        sink = _mock_sink_with_outcomes(outcomes)
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["outcomes"], monkeypatch)
        out = capsys.readouterr().out
        assert "sess-abc-123" in out
        assert "+127/-34" in out
        assert "pass" in out
        assert "a3f2c1e..8b4d9f0" in out
        assert "1 outcome(s) shown." in out

    def test_outcomes_table_failing_session(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        outcomes = [
            {
                "session_id": "sess-fail",
                "agent": "claude-code",
                "start_sha": "deadbeef" + "0" * 32,
                "end_sha": "cafebabe" + "0" * 32,
                "lines_added": 89,
                "lines_removed": 12,
                "files_changed": 4,
                "tests_exit_code": 1,
                "tests_passed": False,
                "pr_url": None,
                "pr_merged": None,
                "captured_at": "2026-04-29T12:08:00Z",
            }
        ]
        sink = _mock_sink_with_outcomes(outcomes)
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["outcomes"], monkeypatch)
        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "+89/-12" in out

    def test_outcomes_no_tests_run(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        outcomes = [
            {
                "session_id": "sess-no-test",
                "agent": "claude-code",
                "start_sha": None,
                "end_sha": None,
                "lines_added": 0,
                "lines_removed": 0,
                "files_changed": 0,
                "tests_exit_code": None,
                "tests_passed": None,
                "pr_url": None,
                "pr_merged": None,
                "captured_at": "2026-04-29T10:55:00Z",
            }
        ]
        sink = _mock_sink_with_outcomes(outcomes)
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["outcomes"], monkeypatch)
        out = capsys.readouterr().out
        assert "sess-no-test" in out
        # Tests column placeholder for unconfigured test cmd
        assert "—" in out

    def test_limit_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = _mock_sink_with_outcomes([])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["outcomes", "--limit", "5"], monkeypatch)
        sink.list_outcomes.assert_called_once_with(limit=5)

    def test_default_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = _mock_sink_with_outcomes([])
        with patch("openflux.cli._get_sink", return_value=sink):
            _run_cli(["outcomes"], monkeypatch)
        sink.list_outcomes.assert_called_once_with(limit=20)
