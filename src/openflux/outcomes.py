"""Capture git + test outcome for an AI coding session.

Pure functions over subprocess, no sink dependency. The adapter hook calls
``capture_outcome`` and passes the result to ``SQLiteSink.record_outcome``.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TypedDict


class OutcomeFields(TypedDict):
    start_sha: str | None
    end_sha: str | None
    lines_added: int
    lines_removed: int
    files_changed: int
    tests_exit_code: int | None
    tests_passed: bool | None


def head_sha(repo_dir: Path | str) -> str | None:
    if shutil.which("git") is None:
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def diff_stats(
    repo_dir: Path | str,
    start_sha: str,
    end_sha: str,
) -> tuple[int, int, int]:
    """Return (lines_added, lines_removed, files_changed) for start..end."""
    if shutil.which("git") is None:
        return 0, 0, 0
    try:
        result = subprocess.run(
            ["git", "diff", "--numstat", f"{start_sha}..{end_sha}"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return 0, 0, 0
    if result.returncode != 0:
        return 0, 0, 0

    added = removed = files = 0
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        a, r, _path = parts
        # binary files report "-\t-\t<path>"
        if a == "-" or r == "-":
            files += 1
            continue
        try:
            added += int(a)
            removed += int(r)
            files += 1
        except ValueError:
            continue
    return added, removed, files


def run_tests(
    test_cmd: str,
    repo_dir: Path | str,
    timeout: int = 600,
) -> tuple[int, bool]:
    """Run test command, return (exit_code, passed)."""
    try:
        result = subprocess.run(
            test_cmd,
            cwd=str(repo_dir),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, False
    except (subprocess.SubprocessError, OSError):
        return -1, False
    return result.returncode, result.returncode == 0


def capture_outcome(
    repo_dir: Path | str,
    start_sha: str | None,
    end_sha: str | None = None,
    test_cmd: str | None = None,
) -> OutcomeFields:
    """Build an outcome dict for a session with given start/end SHAs.

    If ``end_sha`` is None, captures current HEAD.
    If ``test_cmd`` is None, ``tests_exit_code`` and ``tests_passed`` stay None.
    """
    resolved_end = end_sha if end_sha is not None else head_sha(repo_dir)
    out: OutcomeFields = {
        "start_sha": start_sha,
        "end_sha": resolved_end,
        "lines_added": 0,
        "lines_removed": 0,
        "files_changed": 0,
        "tests_exit_code": None,
        "tests_passed": None,
    }
    if start_sha and resolved_end:
        added, removed, files = diff_stats(repo_dir, start_sha, resolved_end)
        out["lines_added"] = added
        out["lines_removed"] = removed
        out["files_changed"] = files
    if test_cmd:
        exit_code, passed = run_tests(test_cmd, repo_dir)
        out["tests_exit_code"] = exit_code
        out["tests_passed"] = passed
    return out
