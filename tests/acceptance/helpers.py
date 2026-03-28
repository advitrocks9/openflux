"""Shared acceptance test helpers (importable from test modules)."""

from pathlib import Path

from openflux.schema import TokenUsage, Trace
from openflux.sinks.sqlite import SQLiteSink

ALL_FIELDS = [
    "id",
    "timestamp",
    "agent",
    "session_id",
    "parent_id",
    "model",
    "task",
    "decision",
    "status",
    "correction",
    "scope",
    "tags",
    "context",
    "searches",
    "sources_read",
    "tools_used",
    "files_modified",
    "turn_count",
    "token_usage",
    "duration_ms",
    "metadata",
    "schema_version",
]


def is_populated(trace: Trace, field: str) -> bool:
    val = getattr(trace, field, None)
    if val is None:
        return False
    if isinstance(val, str):
        return len(val) > 0
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, dict):
        return len(val) > 0
    if isinstance(val, int):
        return val > 0
    if isinstance(val, TokenUsage):
        return val.input_tokens > 0 or val.output_tokens > 0
    return bool(val)


def check_trace(
    db_path: str | Path,
    required: list[str],
    na: list[str] | None = None,
):
    """Read latest trace from DB, assert required fields populated, report coverage."""
    na = na or []
    sink = SQLiteSink(path=str(db_path))
    traces = sink.recent(limit=1)
    assert len(traces) >= 1, "No trace was recorded in the database"
    trace = traces[0]

    results = {}
    for f in ALL_FIELDS:
        results[f] = is_populated(trace, f)

    failures = []
    for f in required:
        if not results[f]:
            failures.append(f)

    testable = [f for f in ALL_FIELDS if f not in na]
    populated = sum(1 for f in testable if results[f])
    coverage = populated / len(testable) * 100

    report = f"\nCoverage: {populated}/{len(testable)} ({coverage:.0f}%)\n"
    for f in ALL_FIELDS:
        status = "Y" if results[f] else ("-" if f in na else "X")
        report += f"  {status} {f}\n"

    if failures:
        raise AssertionError(f"Required fields EMPTY: {failures}\n{report}")

    print(report)
    sink.close()
    return trace, coverage
