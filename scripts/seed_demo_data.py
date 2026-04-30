#!/usr/bin/env python3
"""Seed a demo SQLite database with realistic Claude Code sessions
+ outcomes so the dashboard screenshots have content to show.

Usage:
    OPENFLUX_DB_PATH=/tmp/demo-traces.db uv run scripts/seed_demo_data.py

Then start the server pointed at the same path and capture:
    OPENFLUX_DB_PATH=/tmp/demo-traces.db uv run scripts/capture_assets.py
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openflux.schema import TokenUsage, Trace
from openflux.sinks.sqlite import SQLiteSink

SESSIONS = [
    {
        "task": "fix flaky retry logic in payment webhook",
        "model": "claude-opus-4-7",
        "in_tok": 142_000,
        "out_tok": 18_500,
        "dur_ms": 1_240_000,
        "lines_added": 127,
        "lines_removed": 34,
        "files_changed": 5,
        "tests_exit_code": 0,
        "tests_passed": 1,
    },
    {
        "task": "add pagination to /api/users endpoint",
        "model": "claude-sonnet-4-6",
        "in_tok": 41_000,
        "out_tok": 6_200,
        "dur_ms": 480_000,
        "lines_added": 89,
        "lines_removed": 12,
        "files_changed": 3,
        "tests_exit_code": 1,
        "tests_passed": 0,
    },
    {
        "task": "migrate Postgres connection pool to pgbouncer",
        "model": "claude-opus-4-7",
        "in_tok": 218_000,
        "out_tok": 24_400,
        "dur_ms": 2_100_000,
        "lines_added": 312,
        "lines_removed": 89,
        "files_changed": 11,
        "tests_exit_code": 0,
        "tests_passed": 1,
    },
    {
        "task": "rename UserService methods to snake_case",
        "model": "claude-haiku-4-5-20251001",
        "in_tok": 28_000,
        "out_tok": 3_100,
        "dur_ms": 180_000,
        "lines_added": 47,
        "lines_removed": 47,
        "files_changed": 8,
        "tests_exit_code": 0,
        "tests_passed": 1,
    },
    {
        "task": "implement OAuth refresh token rotation",
        "model": "claude-opus-4-7",
        "in_tok": 187_000,
        "out_tok": 22_800,
        "dur_ms": 1_680_000,
        "lines_added": 203,
        "lines_removed": 56,
        "files_changed": 7,
        "tests_exit_code": 1,
        "tests_passed": 0,
    },
    {
        "task": "fix race condition in WebSocket reconnect",
        "model": "claude-sonnet-4-6",
        "in_tok": 67_000,
        "out_tok": 8_900,
        "dur_ms": 720_000,
        "lines_added": 64,
        "lines_removed": 28,
        "files_changed": 2,
        "tests_exit_code": 0,
        "tests_passed": 1,
    },
    {
        "task": "add rate limiting to auth endpoints",
        "model": "claude-sonnet-4-6",
        "in_tok": 52_000,
        "out_tok": 7_400,
        "dur_ms": 540_000,
        "lines_added": 78,
        "lines_removed": 8,
        "files_changed": 4,
        "tests_exit_code": 0,
        "tests_passed": 1,
    },
    {
        "task": "refactor CartService to use DI container",
        "model": "claude-opus-4-7",
        "in_tok": 156_000,
        "out_tok": 19_200,
        "dur_ms": 1_440_000,
        "lines_added": 244,
        "lines_removed": 178,
        "files_changed": 14,
        "tests_exit_code": 1,
        "tests_passed": 0,
    },
]


def seed() -> None:
    db_path = os.environ.get("OPENFLUX_DB_PATH")
    if not db_path:
        msg = "set OPENFLUX_DB_PATH first"
        raise SystemExit(msg)

    target = Path(db_path)
    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)

    sink = SQLiteSink(path=target)
    base = datetime.now(UTC) - timedelta(days=2)

    for i, s in enumerate(SESSIONS):
        ts = base + timedelta(hours=i * 5, minutes=secrets.randbelow(30))
        session_id = f"sess-{secrets.token_hex(8)}"
        trace = Trace(
            id=f"trc-{secrets.token_hex(6)}",
            timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            agent="claude-code",
            session_id=session_id,
            task=s["task"],
            model=s["model"],
            duration_ms=s["dur_ms"],
            turn_count=12 + secrets.randbelow(40),
            token_usage=TokenUsage(
                input_tokens=s["in_tok"],
                output_tokens=s["out_tok"],
            ),
            status="completed",
        )
        sink.write(trace)
        sink.record_outcome(
            session_id=session_id,
            agent="claude-code",
            captured_at=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            start_sha=secrets.token_hex(20),
            end_sha=secrets.token_hex(20),
            lines_added=s["lines_added"],
            lines_removed=s["lines_removed"],
            files_changed=s["files_changed"],
            tests_exit_code=s["tests_exit_code"],
            tests_passed=bool(s["tests_passed"]),
        )

    sink.close()
    print(f"seeded {len(SESSIONS)} sessions + outcomes into {target}")


if __name__ == "__main__":
    seed()
