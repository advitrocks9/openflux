"""End-to-end: SessionStart → tool events → SessionEnd writes an outcomes row."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from openflux.adapters import _claude_code as cc
from openflux.sinks.sqlite import SQLiteSink


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repo_with_history(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@e.com")
    _git(r, "config", "user.name", "T")
    (r / "a.txt").write_text("alpha\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "initial")
    return r


@pytest.fixture
def isolated_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    openflux_dir = tmp_path / ".openflux"
    db_path = openflux_dir / "traces.db"
    monkeypatch.setattr(cc, "_OPENFLUX_DIR", openflux_dir)
    monkeypatch.setenv("OPENFLUX_DB_PATH", str(db_path))
    return db_path


def test_session_start_records_head_sha(
    repo_with_history: Path,
    isolated_env: Path,
) -> None:
    cc.handle_session_start(
        {
            "session_id": "sess-A",
            "cwd": str(repo_with_history),
            "model": "claude-sonnet",
        }
    )
    meta_path = cc._meta_path("sess-A")
    assert meta_path.exists()
    import json

    meta = json.loads(meta_path.read_text())
    assert meta["start_sha"] is not None
    assert len(meta["start_sha"]) == 40


def test_session_end_writes_outcome_row(
    repo_with_history: Path,
    isolated_env: Path,
) -> None:
    cc.handle_session_start(
        {
            "session_id": "sess-B",
            "cwd": str(repo_with_history),
            "model": "claude-sonnet",
        }
    )

    # Simulate a tool event (otherwise session_end early-returns)
    cc.handle_post_tool_use(
        {
            "session_id": "sess-B",
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi"},
            "tool_response": "hi",
        }
    )

    # Mutate the repo (simulating Claude editing files mid-session)
    (repo_with_history / "b.txt").write_text("one\ntwo\nthree\n")
    _git(repo_with_history, "add", "-A")
    _git(repo_with_history, "commit", "-q", "-m", "mid-session change")

    cc.handle_session_end({"session_id": "sess-B"})

    sink = SQLiteSink()
    try:
        outcome = sink.get_outcome("sess-B", "claude-code")
    finally:
        sink.close()

    assert outcome is not None
    assert outcome["start_sha"] is not None
    assert outcome["end_sha"] is not None
    assert outcome["start_sha"] != outcome["end_sha"]
    assert outcome["lines_added"] == 3
    assert outcome["lines_removed"] == 0
    assert outcome["files_changed"] == 1
    assert outcome["tests_exit_code"] is None
    assert outcome["tests_passed"] is None


def test_session_end_with_test_cmd_passing(
    repo_with_history: Path,
    isolated_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENFLUX_TEST_CMD", "true")

    cc.handle_session_start(
        {
            "session_id": "sess-C",
            "cwd": str(repo_with_history),
        }
    )
    cc.handle_post_tool_use(
        {
            "session_id": "sess-C",
            "tool_name": "Read",
            "tool_input": {"file_path": "/x"},
            "tool_response": "ok",
        }
    )
    cc.handle_session_end({"session_id": "sess-C"})

    sink = SQLiteSink()
    try:
        outcome = sink.get_outcome("sess-C", "claude-code")
    finally:
        sink.close()

    assert outcome is not None
    assert outcome["tests_exit_code"] == 0
    assert outcome["tests_passed"] is True


def test_session_end_with_test_cmd_failing(
    repo_with_history: Path,
    isolated_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENFLUX_TEST_CMD", "false")

    cc.handle_session_start(
        {
            "session_id": "sess-D",
            "cwd": str(repo_with_history),
        }
    )
    cc.handle_post_tool_use(
        {
            "session_id": "sess-D",
            "tool_name": "Read",
            "tool_input": {"file_path": "/x"},
            "tool_response": "ok",
        }
    )
    cc.handle_session_end({"session_id": "sess-D"})

    sink = SQLiteSink()
    try:
        outcome = sink.get_outcome("sess-D", "claude-code")
    finally:
        sink.close()

    assert outcome is not None
    assert outcome["tests_exit_code"] == 1
    assert outcome["tests_passed"] is False


def test_session_outside_git_repo_skips_outcome(
    tmp_path: Path,
    isolated_env: Path,
) -> None:
    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()

    cc.handle_session_start(
        {
            "session_id": "sess-E",
            "cwd": str(non_repo),
        }
    )
    cc.handle_post_tool_use(
        {
            "session_id": "sess-E",
            "tool_name": "Read",
            "tool_input": {"file_path": "/x"},
            "tool_response": "ok",
        }
    )
    cc.handle_session_end({"session_id": "sess-E"})

    sink = SQLiteSink()
    try:
        outcome = sink.get_outcome("sess-E", "claude-code")
    finally:
        sink.close()

    assert outcome is None
