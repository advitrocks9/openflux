"""JSON API handlers for the trace explorer."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any
from urllib.parse import parse_qs, urlparse

from openflux.sinks.sqlite import SQLiteSink

# Try to use the project's authoritative pricing module if available.
# Falls back to a minimal table if it isn't on this branch yet (the
# parallel cost-intelligence WIP introduces openflux._pricing). When
# branches merge, this conditional collapses to the import path.
try:
    from openflux._pricing import estimate_cost as _estimate_cost  # type: ignore[import-not-found,no-redef]  # noqa: I001  # pyright: ignore[reportMissingImports, reportUnknownVariableType]
except ImportError:
    _FALLBACK_RATES: list[tuple[str, float, float]] = [
        ("opus", 15.00, 75.00),
        ("sonnet", 3.00, 15.00),
        ("haiku", 0.25, 1.25),
        ("claude-", 3.00, 15.00),
        ("gpt-4o-mini", 0.15, 0.60),
        ("gpt-4o", 2.50, 10.00),
        ("o3", 10.00, 40.00),
        ("o1", 15.00, 60.00),
        ("gemini", 0.075, 0.30),
    ]
    _FALLBACK_DEFAULT = (1.00, 3.00)

    def _estimate_cost(  # type: ignore[no-redef]
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ) -> float:
        # Read env override once per call; rare and small enough that the
        # cost of re-parsing isn't worth caching.
        override = os.environ.get("OPENFLUX_RATES_JSON")
        if override:
            try:
                rates = json.loads(override)
                rate = rates.get(model.lower())
                if rate and len(rate) >= 2:
                    in_r, out_r = float(rate[0]), float(rate[1])
                    return (input_tokens * in_r + output_tokens * out_r) / 1_000_000
            except (ValueError, TypeError):
                pass

        model_lower = model.lower()
        for prefix, in_r, out_r in _FALLBACK_RATES:
            if prefix in model_lower:
                # Cache tokens at half the input rate as a rough approximation.
                cache_blended = (cache_read_tokens + cache_creation_tokens) * in_r * 0.5
                return (
                    input_tokens * in_r + output_tokens * out_r + cache_blended
                ) / 1_000_000
        in_r, out_r = _FALLBACK_DEFAULT
        return (input_tokens * in_r + output_tokens * out_r) / 1_000_000


# Valid sort columns to prevent SQL injection
_SORT_COLUMNS = frozenset(
    {
        "id",
        "timestamp",
        "agent",
        "task",
        "status",
        "model",
        "duration_ms",
        "turn_count",
        "token_input",
        "token_output",
    }
)


def handle_request(path: str, sink: SQLiteSink) -> tuple[int, dict[str, Any]]:
    """Route an API request and return (status_code, json_body)."""
    parsed = urlparse(path)
    qs = parse_qs(parsed.query)
    clean_path = parsed.path.rstrip("/")

    if clean_path == "/api/traces":
        return _handle_traces_list(qs, sink)
    if clean_path == "/api/stats":
        return _handle_stats(sink)
    if clean_path == "/api/stats/timeline":
        return _handle_timeline(qs, sink)
    if clean_path.startswith("/api/traces/"):
        trace_id = clean_path[len("/api/traces/") :]
        return _handle_trace_detail(trace_id, sink)
    if clean_path == "/api/outcomes":
        return _handle_outcomes_list(qs, sink)
    if clean_path.startswith("/api/outcomes/"):
        # Path: /api/outcomes/<session_id>?agent=<agent>
        session_id = clean_path[len("/api/outcomes/") :]
        agent = _qs_str(qs, "agent") or "claude-code"
        return _handle_outcome_detail(session_id, agent, sink)

    return 404, {"error": "Not found"}


def _qs_int(qs: dict[str, list[str]], key: str, default: int) -> int:
    vals = qs.get(key, [])
    if vals and vals[0].isdigit():
        return int(vals[0])
    return default


def _qs_str(qs: dict[str, list[str]], key: str) -> str:
    vals = qs.get(key, [])
    return vals[0] if vals else ""


def _handle_traces_list(
    qs: dict[str, list[str]], sink: SQLiteSink
) -> tuple[int, dict[str, Any]]:
    limit = min(_qs_int(qs, "limit", 50), 500)
    offset = _qs_int(qs, "offset", 0)
    agent = _qs_str(qs, "agent")
    status = _qs_str(qs, "status")
    search = _qs_str(qs, "search")
    sort = _qs_str(qs, "sort") or "timestamp"
    order = _qs_str(qs, "order") or "desc"

    if sort not in _SORT_COLUMNS:
        sort = "timestamp"
    if order not in ("asc", "desc"):
        order = "desc"

    conn = sink.conn
    if search:
        return _search_traces(conn, search, agent, status, sort, order, limit, offset)
    return _filter_traces(conn, agent, status, sort, order, limit, offset)


def _build_where(agent: str, status: str) -> tuple[str, list[str]]:
    clauses: list[str] = []
    params: list[str] = []
    if agent:
        clauses.append("agent = ?")
        params.append(agent)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _filter_traces(
    conn: sqlite3.Connection,
    agent: str,
    status: str,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> tuple[int, dict[str, Any]]:
    where, params = _build_where(agent, status)

    total_row = conn.execute(f"SELECT COUNT(*) FROM traces{where}", params).fetchone()
    total = total_row[0] if total_row else 0

    rows = conn.execute(
        f"SELECT id, timestamp, agent, task, status, model, duration_ms, "
        f"token_input, token_output, turn_count "
        f"FROM traces{where} ORDER BY {sort} {order} LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()

    traces = [_summary_row(row, conn) for row in rows]
    return 200, {"traces": traces, "total": total, "limit": limit, "offset": offset}


def _search_traces(
    conn: sqlite3.Connection,
    search: str,
    agent: str,
    status: str,
    sort: str,
    order: str,
    limit: int,
    offset: int,
) -> tuple[int, dict[str, Any]]:
    escaped = '"' + search.replace('"', '""') + '"'
    where_parts = ["traces_fts MATCH ?"]
    params: list[Any] = [escaped]
    if agent:
        where_parts.append("r.agent = ?")
        params.append(agent)
    if status:
        where_parts.append("r.status = ?")
        params.append(status)
    where = " WHERE " + " AND ".join(where_parts)

    total_row = conn.execute(
        f"SELECT COUNT(*) FROM traces r "
        f"JOIN traces_fts ON r.rowid = traces_fts.rowid{where}",
        params,
    ).fetchone()
    total = total_row[0] if total_row else 0

    rows = conn.execute(
        f"SELECT r.id, r.timestamp, r.agent, r.task, r.status, r.model, "
        f"r.duration_ms, r.token_input, r.token_output, r.turn_count "
        f"FROM traces r JOIN traces_fts ON r.rowid = traces_fts.rowid{where} "
        f"ORDER BY r.{sort} {order} LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()

    traces = [_summary_row(row, conn) for row in rows]
    return 200, {"traces": traces, "total": total, "limit": limit, "offset": offset}


def _summary_row(row: tuple[Any, ...], conn: sqlite3.Connection) -> dict[str, Any]:
    """Build a trace summary dict from a SELECT row."""
    trace_id = row[0]
    counts = _nested_counts(conn, trace_id)
    return {
        "id": trace_id,
        "timestamp": row[1],
        "agent": row[2],
        "task": row[3],
        "status": row[4],
        "model": row[5],
        "duration_ms": row[6],
        "token_usage": {"input_tokens": row[7], "output_tokens": row[8]},
        "turn_count": row[9],
        **counts,
    }


def _nested_counts(conn: sqlite3.Connection, trace_id: str) -> dict[str, int]:
    """Count nested records for a trace without loading full content."""
    tool_count = conn.execute(
        "SELECT COUNT(*) FROM trace_tools WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    search_count = conn.execute(
        "SELECT COUNT(*) FROM trace_searches WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    source_count = conn.execute(
        "SELECT COUNT(*) FROM trace_sources WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    file_row = conn.execute(
        "SELECT files_modified FROM traces WHERE id = ?", (trace_id,)
    ).fetchone()
    files: list[str] = json.loads(file_row[0]) if file_row and file_row[0] else []
    return {
        "tool_count": tool_count[0] if tool_count else 0,
        "search_count": search_count[0] if search_count else 0,
        "source_count": source_count[0] if source_count else 0,
        "files_modified_count": len(files),
    }


def _handle_trace_detail(trace_id: str, sink: SQLiteSink) -> tuple[int, dict[str, Any]]:
    trace = sink.get(trace_id)
    if trace is None:
        return 404, {"error": f"Trace '{trace_id}' not found"}
    return 200, trace.to_dict()


def _handle_stats(sink: SQLiteSink) -> tuple[int, dict[str, Any]]:
    conn = sink.conn
    row = conn.execute(
        "SELECT COUNT(*), "
        "COALESCE(SUM(token_input), 0), "
        "COALESCE(SUM(token_output), 0), "
        "MAX(timestamp) "
        "FROM traces"
    ).fetchone()
    total = row[0] if row else 0

    agents = [
        {"name": r[0], "count": r[1]}
        for r in conn.execute(
            "SELECT agent, COUNT(*) FROM traces GROUP BY agent ORDER BY COUNT(*) DESC"
        ).fetchall()
    ]
    models = [
        {"name": r[0], "count": r[1]}
        for r in conn.execute(
            "SELECT model, COUNT(*) FROM traces GROUP BY model ORDER BY COUNT(*) DESC"
        ).fetchall()
    ]
    statuses = [
        {"name": r[0], "count": r[1]}
        for r in conn.execute(
            "SELECT status, COUNT(*) FROM traces GROUP BY status ORDER BY COUNT(*) DESC"
        ).fetchall()
    ]

    return 200, {
        "total_traces": total,
        "total_input_tokens": row[1] if row else 0,
        "total_output_tokens": row[2] if row else 0,
        "agents": agents,
        "models": models,
        "statuses": statuses,
        "latest_timestamp": row[3] if row else None,
    }


def _handle_outcomes_list(
    qs: dict[str, list[str]], sink: SQLiteSink
) -> tuple[int, dict[str, Any]]:
    limit = min(_qs_int(qs, "limit", 50), 500)
    rows = sink.list_outcomes(limit=limit)
    enriched = [_attach_trace_summary(row, sink.conn) for row in rows]
    return 200, {"outcomes": enriched, "limit": limit, "count": len(enriched)}


def _handle_outcome_detail(
    session_id: str, agent: str, sink: SQLiteSink
) -> tuple[int, dict[str, Any]]:
    outcome = sink.get_outcome(session_id, agent)
    if outcome is None:
        return 404, {"error": f"Outcome '{session_id}/{agent}' not found"}
    return 200, _attach_trace_summary(outcome, sink.conn)


def _attach_trace_summary(
    outcome: dict[str, Any], conn: sqlite3.Connection
) -> dict[str, Any]:
    """Join an outcome with its session's trace token totals + cost basis."""
    row = conn.execute(
        "SELECT id, task, model, duration_ms, "
        "COALESCE(token_input, 0), COALESCE(token_output, 0), "
        "COALESCE(token_cache_read, 0), COALESCE(token_cache_creation, 0) "
        "FROM traces WHERE session_id = ? AND agent = ? "
        "ORDER BY timestamp DESC LIMIT 1",
        (outcome["session_id"], outcome["agent"]),
    ).fetchone()
    trace_summary: dict[str, Any] | None = None
    if row:
        cost_usd = _estimate_cost(
            model=row[2] or "",
            input_tokens=row[4],
            output_tokens=row[5],
            cache_read_tokens=row[6],
            cache_creation_tokens=row[7],
        )
        trace_summary = {
            "trace_id": row[0],
            "task": row[1],
            "model": row[2],
            "duration_ms": row[3],
            "token_input": row[4],
            "token_output": row[5],
            "token_cache_read": row[6],
            "token_cache_creation": row[7],
            "cost_usd": round(cost_usd, 4),
        }
    return {**outcome, "trace": trace_summary}


def _handle_timeline(
    qs: dict[str, list[str]], sink: SQLiteSink
) -> tuple[int, dict[str, Any]]:
    days = min(_qs_int(qs, "days", 30), 365)
    conn = sink.conn
    rows = conn.execute(
        "SELECT DATE(timestamp) as day, COUNT(*), "
        "COALESCE(SUM(token_input), 0), "
        "COALESCE(SUM(token_output), 0) "
        "FROM traces "
        "WHERE timestamp >= datetime('now', ? || ' days') "
        "GROUP BY day ORDER BY day",
        (f"-{days}",),
    ).fetchall()

    return 200, {
        "days": [
            {
                "date": r[0],
                "traces": r[1],
                "input_tokens": r[2],
                "output_tokens": r[3],
            }
            for r in rows
        ],
    }
