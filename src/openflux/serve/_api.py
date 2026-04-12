"""JSON API handlers for the trace explorer."""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from urllib.parse import parse_qs, urlparse

from openflux.sinks.sqlite import SQLiteSink

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
    if clean_path == "/api/waste":
        return _handle_waste(qs, sink)
    if clean_path.startswith("/api/replay/"):
        trace_id = clean_path[len("/api/replay/") :]
        return _handle_replay(trace_id, sink)
    if clean_path.startswith("/api/traces/"):
        trace_id = clean_path[len("/api/traces/") :]
        return _handle_trace_detail(trace_id, sink)

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


def _handle_waste(
    qs: dict[str, list[str]], sink: SQLiteSink
) -> tuple[int, dict[str, Any]]:
    from dataclasses import asdict

    from openflux.waste import analyze_efficiency

    days = min(_qs_int(qs, "days", 30), 365)
    agent = _qs_str(qs, "agent")
    report = analyze_efficiency(sink.conn, days=days, agent=agent or None)
    return 200, asdict(report)


def _handle_replay(trace_id: str, sink: SQLiteSink) -> tuple[int, dict[str, Any]]:
    from dataclasses import asdict

    from openflux.waste import replay_session

    replay = replay_session(sink.conn, trace_id)
    if replay is None:
        return 404, {"error": f"Trace '{trace_id}' not found"}
    return 200, asdict(replay)
