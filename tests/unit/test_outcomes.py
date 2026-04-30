"""Tests for outcomes table: session_id + agent → git diff + test result."""

from __future__ import annotations

from pathlib import Path

import pytest

from openflux.sinks.sqlite import SQLiteSink


@pytest.fixture
def sink(tmp_path: Path) -> SQLiteSink:
    return SQLiteSink(path=tmp_path / "outcomes.db")


def test_record_and_get_minimal(sink: SQLiteSink) -> None:
    sink.record_outcome(
        session_id="sess-1",
        agent="claude_code",
        captured_at="2026-04-29T12:00:00Z",
    )
    got = sink.get_outcome("sess-1", "claude_code")
    assert got is not None
    assert got["session_id"] == "sess-1"
    assert got["agent"] == "claude_code"
    assert got["lines_added"] == 0
    assert got["tests_passed"] is None
    assert got["pr_merged"] is None


def test_record_full_outcome(sink: SQLiteSink) -> None:
    sink.record_outcome(
        session_id="sess-2",
        agent="claude_code",
        captured_at="2026-04-29T13:00:00Z",
        start_sha="abc123",
        end_sha="def456",
        lines_added=42,
        lines_removed=7,
        files_changed=3,
        tests_exit_code=0,
        tests_passed=True,
        pr_url="https://github.com/x/y/pull/1",
        pr_merged=False,
    )
    got = sink.get_outcome("sess-2", "claude_code")
    assert got is not None
    assert got["start_sha"] == "abc123"
    assert got["end_sha"] == "def456"
    assert got["lines_added"] == 42
    assert got["lines_removed"] == 7
    assert got["files_changed"] == 3
    assert got["tests_exit_code"] == 0
    assert got["tests_passed"] is True
    assert got["pr_url"] == "https://github.com/x/y/pull/1"
    assert got["pr_merged"] is False


def test_failing_tests_recorded(sink: SQLiteSink) -> None:
    sink.record_outcome(
        session_id="sess-3",
        agent="claude_code",
        captured_at="2026-04-29T14:00:00Z",
        tests_exit_code=1,
        tests_passed=False,
    )
    got = sink.get_outcome("sess-3", "claude_code")
    assert got is not None
    assert got["tests_passed"] is False
    assert got["tests_exit_code"] == 1


def test_get_missing_returns_none(sink: SQLiteSink) -> None:
    assert sink.get_outcome("nope", "claude_code") is None


def test_record_replaces_on_conflict(sink: SQLiteSink) -> None:
    sink.record_outcome(
        session_id="sess-4",
        agent="claude_code",
        captured_at="2026-04-29T15:00:00Z",
        lines_added=10,
    )
    sink.record_outcome(
        session_id="sess-4",
        agent="claude_code",
        captured_at="2026-04-29T15:30:00Z",
        lines_added=99,
    )
    got = sink.get_outcome("sess-4", "claude_code")
    assert got is not None
    assert got["lines_added"] == 99


def test_same_session_different_agents_isolated(sink: SQLiteSink) -> None:
    sink.record_outcome(
        session_id="shared",
        agent="claude_code",
        captured_at="2026-04-29T16:00:00Z",
        lines_added=5,
    )
    sink.record_outcome(
        session_id="shared",
        agent="cursor",
        captured_at="2026-04-29T16:00:00Z",
        lines_added=20,
    )
    cc = sink.get_outcome("shared", "claude_code")
    cur = sink.get_outcome("shared", "cursor")
    assert cc is not None
    assert cur is not None
    assert cc["lines_added"] == 5
    assert cur["lines_added"] == 20


def test_list_outcomes_orders_by_captured_at(sink: SQLiteSink) -> None:
    sink.record_outcome(
        session_id="a", agent="claude_code", captured_at="2026-04-29T10:00:00Z"
    )
    sink.record_outcome(
        session_id="b", agent="claude_code", captured_at="2026-04-29T12:00:00Z"
    )
    sink.record_outcome(
        session_id="c", agent="claude_code", captured_at="2026-04-29T11:00:00Z"
    )
    listed = sink.list_outcomes()
    ids = [r["session_id"] for r in listed]
    assert ids == ["b", "c", "a"]


def test_migration_from_v2_db(tmp_path: Path) -> None:
    """A v2 db (no outcomes table) should auto-migrate when reopened with v3."""
    import sqlite3

    db_path = tmp_path / "v2.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        INSERT INTO schema_version (version) VALUES (2);
        CREATE TABLE traces (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            agent TEXT NOT NULL,
            session_id TEXT NOT NULL,
            parent_id TEXT,
            model TEXT DEFAULT '',
            task TEXT DEFAULT '',
            decision TEXT DEFAULT '',
            status TEXT DEFAULT 'completed',
            correction TEXT,
            scope TEXT,
            tags TEXT DEFAULT '[]',
            files_modified TEXT DEFAULT '[]',
            turn_count INTEGER DEFAULT 0,
            token_input INTEGER DEFAULT 0,
            token_output INTEGER DEFAULT 0,
            token_cache_read INTEGER DEFAULT 0,
            token_cache_creation INTEGER DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}',
            schema_version TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()

    sink = SQLiteSink(path=db_path)
    sink.record_outcome(
        session_id="post-mig",
        agent="claude_code",
        captured_at="2026-04-29T17:00:00Z",
        lines_added=1,
    )
    got = sink.get_outcome("post-mig", "claude_code")
    assert got is not None
    assert got["lines_added"] == 1
    sink.close()
