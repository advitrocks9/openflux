"""Tests for the outcome capture module — exercises real git subprocess."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from openflux.outcomes import (
    capture_outcome,
    diff_stats,
    head_sha,
    run_tests,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Tester")
    (r / "a.txt").write_text("alpha\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "initial")
    return r


def test_head_sha_in_real_repo(repo: Path) -> None:
    sha = head_sha(repo)
    assert sha is not None
    assert len(sha) == 40


def test_head_sha_outside_repo(tmp_path: Path) -> None:
    assert head_sha(tmp_path) is None


def test_diff_stats_addition(repo: Path) -> None:
    start = head_sha(repo)
    assert start is not None
    (repo / "b.txt").write_text("one\ntwo\nthree\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add b")
    end = head_sha(repo)
    assert end is not None

    added, removed, files = diff_stats(repo, start, end)
    assert added == 3
    assert removed == 0
    assert files == 1


def test_diff_stats_modification_and_deletion(repo: Path) -> None:
    start = head_sha(repo)
    assert start is not None
    (repo / "a.txt").write_text("alpha\nbeta\ngamma\n")
    (repo / "c.txt").write_text("hello\nworld\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "modify and add")
    end = head_sha(repo)
    assert end is not None

    added, removed, files = diff_stats(repo, start, end)
    # a.txt: +2 (added beta, gamma; alpha unchanged); c.txt: +2
    assert added == 4
    assert removed == 0
    assert files == 2


def test_diff_stats_invalid_sha_returns_zeros(repo: Path) -> None:
    added, removed, files = diff_stats(repo, "deadbeef", "cafebabe")
    assert (added, removed, files) == (0, 0, 0)


def test_run_tests_pass(repo: Path) -> None:
    exit_code, passed = run_tests("true", repo)
    assert exit_code == 0
    assert passed is True


def test_run_tests_fail(repo: Path) -> None:
    exit_code, passed = run_tests("false", repo)
    assert exit_code == 1
    assert passed is False


def test_run_tests_timeout(repo: Path) -> None:
    exit_code, passed = run_tests("sleep 5", repo, timeout=1)
    assert exit_code == 124
    assert passed is False


def test_capture_outcome_full_flow(repo: Path) -> None:
    start = head_sha(repo)
    assert start is not None
    (repo / "b.txt").write_text("x\ny\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add b")

    out = capture_outcome(repo, start_sha=start, test_cmd="true")
    assert out["start_sha"] == start
    assert out["end_sha"] is not None
    assert out["end_sha"] != start
    assert out["lines_added"] == 2
    assert out["lines_removed"] == 0
    assert out["files_changed"] == 1
    assert out["tests_exit_code"] == 0
    assert out["tests_passed"] is True


def test_capture_outcome_no_test_cmd(repo: Path) -> None:
    start = head_sha(repo)
    out = capture_outcome(repo, start_sha=start)
    assert out["tests_exit_code"] is None
    assert out["tests_passed"] is None


def test_capture_outcome_no_changes(repo: Path) -> None:
    start = head_sha(repo)
    out = capture_outcome(repo, start_sha=start)
    assert out["start_sha"] == start
    assert out["end_sha"] == start
    assert out["lines_added"] == 0
    assert out["lines_removed"] == 0
    assert out["files_changed"] == 0


def test_capture_outcome_failing_tests_recorded(repo: Path) -> None:
    start = head_sha(repo)
    out = capture_outcome(repo, start_sha=start, test_cmd="false")
    assert out["tests_exit_code"] == 1
    assert out["tests_passed"] is False


def test_capture_outcome_no_start_sha_skips_diff(repo: Path) -> None:
    out = capture_outcome(repo, start_sha=None, test_cmd="true")
    assert out["start_sha"] is None
    assert out["lines_added"] == 0
    assert out["files_changed"] == 0
    assert out["tests_passed"] is True
