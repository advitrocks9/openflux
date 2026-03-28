"""SQLite sink with FTS5 full-text search"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, override

from openflux.schema import TokenUsage, Trace
from openflux.sinks.base import Sink

_DEFAULT_DB_PATH = Path.home() / ".openflux" / "traces.db"

_SCHEMA_VERSION = 2

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS traces (
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

CREATE TABLE IF NOT EXISTS trace_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    source TEXT DEFAULT '',
    content_hash TEXT DEFAULT '',
    content TEXT DEFAULT '',
    bytes INTEGER DEFAULT 0,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS trace_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    engine TEXT DEFAULT '',
    results_count INTEGER DEFAULT 0,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS trace_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    path TEXT DEFAULT '',
    content_hash TEXT DEFAULT '',
    content TEXT DEFAULT '',
    tool TEXT DEFAULT '',
    bytes_read INTEGER DEFAULT 0,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS trace_tools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    tool_input TEXT DEFAULT '',
    tool_output TEXT DEFAULT '',
    duration_ms INTEGER DEFAULT 0,
    error BOOLEAN DEFAULT 0,
    timestamp TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS traces_fts USING fts5(
    task, decision, correction, scope,
    agent, model, session_id, files_modified,
    content=traces, content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS traces_fts_insert AFTER INSERT ON traces BEGIN
    INSERT INTO traces_fts(rowid, task, decision, correction, scope,
                           agent, model, session_id, files_modified)
    VALUES (new.rowid, new.task, new.decision, new.correction, new.scope,
            new.agent, new.model, new.session_id, new.files_modified);
END;

CREATE TRIGGER IF NOT EXISTS traces_fts_delete AFTER DELETE ON traces BEGIN
    INSERT INTO traces_fts(traces_fts, rowid, task, decision, correction, scope,
                           agent, model, session_id, files_modified)
    VALUES ('delete', old.rowid, old.task, old.decision, old.correction, old.scope,
            old.agent, old.model, old.session_id, old.files_modified);
END;

CREATE INDEX IF NOT EXISTS idx_traces_timestamp ON traces(timestamp);
CREATE INDEX IF NOT EXISTS idx_traces_agent ON traces(agent);
CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
CREATE INDEX IF NOT EXISTS idx_traces_parent ON traces(parent_id);
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status);
CREATE INDEX IF NOT EXISTS idx_traces_scope ON traces(scope);
CREATE INDEX IF NOT EXISTS idx_traces_model ON traces(model);
CREATE INDEX IF NOT EXISTS idx_trace_context_trace ON trace_context(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_searches_trace ON trace_searches(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_sources_trace ON trace_sources(trace_id);
CREATE INDEX IF NOT EXISTS idx_trace_tools_trace ON trace_tools(trace_id);
"""

_TRACE_COLS = [
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
    "files_modified",
    "turn_count",
    "token_input",
    "token_output",
    "token_cache_read",
    "token_cache_creation",
    "duration_ms",
    "metadata",
    "schema_version",
]


class SQLiteSink(Sink):
    def __init__(self, path: Path | str | None = None) -> None:
        if path is not None:
            self._path = Path(path)
        else:
            import os

            env_path = os.environ.get("OPENFLUX_DB_PATH", "")
            self._path = Path(env_path) if env_path else _DEFAULT_DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), timeout=10)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type='table' AND name='schema_version'"
        )
        current_version = 0
        if cur.fetchone():
            row = cur.execute("SELECT MAX(version) FROM schema_version").fetchone()
            current_version = (row[0] or 0) if row else 0
            if current_version >= _SCHEMA_VERSION:
                return

        if current_version < 1:
            self._conn.executescript(_SCHEMA_SQL)
        if current_version == 1:
            self._migrate_fts_v2()

        self._conn.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (_SCHEMA_VERSION,),
        )
        self._conn.commit()

    def _migrate_fts_v2(self) -> None:
        """Upgrade FTS index from v1 (4 fields) to v2 (8 fields)."""
        self._conn.executescript("""
            DROP TRIGGER IF EXISTS traces_fts_insert;
            DROP TRIGGER IF EXISTS traces_fts_delete;
            DROP TABLE IF EXISTS traces_fts;

            CREATE VIRTUAL TABLE traces_fts USING fts5(
                task, decision, correction, scope,
                agent, model, session_id, files_modified,
                content=traces, content_rowid=rowid
            );

            CREATE TRIGGER traces_fts_insert AFTER INSERT ON traces BEGIN
                INSERT INTO traces_fts(rowid, task, decision, correction, scope,
                                       agent, model, session_id, files_modified)
                VALUES (new.rowid, new.task, new.decision, new.correction, new.scope,
                        new.agent, new.model, new.session_id, new.files_modified);
            END;

            CREATE TRIGGER traces_fts_delete AFTER DELETE ON traces BEGIN
                INSERT INTO traces_fts(traces_fts, rowid, task, decision, correction,
                                       scope, agent, model, session_id, files_modified)
                VALUES ('delete', old.rowid, old.task, old.decision, old.correction,
                        old.scope, old.agent, old.model, old.session_id,
                        old.files_modified);
            END;
        """)
        # Rebuild FTS index for pre-existing rows
        self._conn.execute(
            "INSERT INTO traces_fts(rowid, task, decision, correction, scope, "
            "agent, model, session_id, files_modified) "
            "SELECT rowid, task, decision, correction, scope, "
            "agent, model, session_id, files_modified FROM traces"
        )

    @override
    def write(self, trace: Trace) -> None:
        tok = trace.token_usage or TokenUsage()
        cur = self._conn.cursor()
        cur.execute("BEGIN")
        try:
            self._insert_trace(cur, trace, tok)
            self._insert_context(cur, trace)
            self._insert_searches(cur, trace)
            self._insert_sources(cur, trace)
            self._insert_tools(cur, trace)
            cur.execute("COMMIT")
        except Exception:
            cur.execute("ROLLBACK")
            raise

    def _insert_trace(self, cur: sqlite3.Cursor, trace: Trace, tok: TokenUsage) -> None:
        cur.execute(
            "INSERT INTO traces "
            "(id, timestamp, agent, session_id, parent_id, model, task, decision, "
            "status, correction, scope, tags, files_modified, turn_count, "
            "token_input, token_output, token_cache_read, token_cache_creation, "
            "duration_ms, metadata, schema_version) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trace.id,
                trace.timestamp,
                trace.agent,
                trace.session_id,
                trace.parent_id,
                trace.model,
                trace.task,
                trace.decision,
                trace.status,
                trace.correction,
                trace.scope,
                json.dumps(trace.tags),
                json.dumps(trace.files_modified),
                trace.turn_count,
                tok.input_tokens,
                tok.output_tokens,
                tok.cache_read_tokens,
                tok.cache_creation_tokens,
                trace.duration_ms,
                json.dumps(trace.metadata),
                trace.schema_version,
            ),
        )

    def _insert_context(self, cur: sqlite3.Cursor, trace: Trace) -> None:
        for ctx in trace.context:
            cur.execute(
                "INSERT INTO trace_context "
                "(trace_id, type, source, content_hash, content, bytes, timestamp) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    trace.id,
                    ctx.type,
                    ctx.source,
                    ctx.content_hash,
                    ctx.content,
                    ctx.bytes,
                    ctx.timestamp,
                ),
            )

    def _insert_searches(self, cur: sqlite3.Cursor, trace: Trace) -> None:
        for s in trace.searches:
            cur.execute(
                "INSERT INTO trace_searches "
                "(trace_id, query, engine, results_count, timestamp) "
                "VALUES (?,?,?,?,?)",
                (trace.id, s.query, s.engine, s.results_count, s.timestamp),
            )

    def _insert_sources(self, cur: sqlite3.Cursor, trace: Trace) -> None:
        for src in trace.sources_read:
            cur.execute(
                "INSERT INTO trace_sources "
                "(trace_id, type, path, content_hash,"
                " content, tool, bytes_read, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    trace.id,
                    src.type,
                    src.path,
                    src.content_hash,
                    src.content,
                    src.tool,
                    src.bytes_read,
                    src.timestamp,
                ),
            )

    def _insert_tools(self, cur: sqlite3.Cursor, trace: Trace) -> None:
        for t in trace.tools_used:
            cur.execute(
                "INSERT INTO trace_tools "
                "(trace_id, name, tool_input, tool_output,"
                " duration_ms, error, timestamp) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    trace.id,
                    t.name,
                    t.tool_input,
                    t.tool_output,
                    t.duration_ms,
                    t.error,
                    t.timestamp,
                ),
            )

    def search(self, query: str, limit: int = 10) -> list[Trace]:
        # Wrap in double quotes so FTS5 treats dots/hyphens as literals
        escaped = '"' + query.replace('"', '""') + '"'
        rows = self._conn.execute(
            "SELECT r.* FROM traces r "
            "JOIN traces_fts ON r.rowid = traces_fts.rowid "
            "WHERE traces_fts MATCH ? ORDER BY rank LIMIT ?",
            (escaped, limit),
        ).fetchall()
        return [self._row_to_trace(row) for row in rows]

    def recent(
        self,
        limit: int = 20,
        agent: str | None = None,
        scope: str | None = None,
        since: str | None = None,
    ) -> list[Trace]:
        sql = "SELECT * FROM traces WHERE 1=1"
        params: list[Any] = []
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        if since:
            sql += " AND timestamp >= ?"
            params.append(since)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_trace(row) for row in rows]

    def get(self, trace_id: str) -> Trace | None:
        row = self._conn.execute(
            "SELECT * FROM traces WHERE id = ?", (trace_id,)
        ).fetchone()
        return self._row_to_trace(row) if row else None

    def sources_summary(self, days: int = 30) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT path, type, COUNT(*) as access_count,"
            " MAX(timestamp) as last_accessed "
            "FROM trace_sources "
            "WHERE timestamp >= datetime('now', ?||' days') "
            "GROUP BY path, type ORDER BY access_count DESC",
            (f"-{days}",),
        ).fetchall()
        return [
            {"path": r[0], "type": r[1], "access_count": r[2], "last_accessed": r[3]}
            for r in rows
        ]

    def forget(self, trace_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM traces WHERE id = ?", (trace_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def forget_by_agent(self, agent: str) -> int:
        cur = self._conn.execute("DELETE FROM traces WHERE agent = ?", (agent,))
        self._conn.commit()
        return cur.rowcount

    def count_by_agent(self, agent: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM traces WHERE agent = ?", (agent,)
        ).fetchone()
        return row[0] if row else 0

    def prune(self, before_timestamp: str, agent: str | None = None) -> int:
        sql = "DELETE FROM traces WHERE timestamp < ?"
        params: list[str] = [before_timestamp]
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        return cur.rowcount

    def count_before(self, before_timestamp: str, agent: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM traces WHERE timestamp < ?"
        params: list[str] = [before_timestamp]
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        row = self._conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def token_summary(
        self,
        days: int | None = None,
        agent: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate token stats, optionally filtered by days and agent."""
        where, params = self._build_filter(days, agent)
        return self._query_token_summary(where, params)

    def token_by_model(
        self,
        days: int | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        where, params = self._build_filter(days, agent)
        rows = self._conn.execute(
            "SELECT model, SUM(token_input), SUM(token_output) "
            f"FROM traces WHERE {where} "
            "GROUP BY model ORDER BY SUM(token_input) + SUM(token_output) DESC",
            params,
        ).fetchall()
        return [
            {"model": r[0] or "(unknown)", "input": r[1], "output": r[2]} for r in rows
        ]

    def token_by_agent(
        self,
        days: int | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        where, params = self._build_filter(days, agent)
        rows = self._conn.execute(
            "SELECT agent, COUNT(*), SUM(token_input), SUM(token_output) "
            f"FROM traces WHERE {where} "
            "GROUP BY agent ORDER BY SUM(token_input) + SUM(token_output) DESC",
            params,
        ).fetchall()
        return [
            {"agent": r[0], "traces": r[1], "input": r[2], "output": r[3]} for r in rows
        ]

    def token_by_day(
        self,
        days: int | None = None,
        agent: str | None = None,
    ) -> list[dict[str, Any]]:
        where, params = self._build_filter(days, agent)
        rows = self._conn.execute(
            "SELECT DATE(timestamp), COUNT(*), "
            "SUM(token_input), SUM(token_output) "
            f"FROM traces WHERE {where} "
            "GROUP BY DATE(timestamp) ORDER BY DATE(timestamp) DESC",
            params,
        ).fetchall()
        return [
            {"date": r[0], "traces": r[1], "input": r[2], "output": r[3]} for r in rows
        ]

    def _build_filter(
        self, days: int | None, agent: str | None
    ) -> tuple[str, list[str]]:
        clauses: list[str] = ["1=1"]
        params: list[str] = []
        if days is not None:
            clauses.append("timestamp >= datetime('now', ?||' days')")
            params.append(f"-{days}")
        if agent:
            clauses.append("agent = ?")
            params.append(agent)
        return " AND ".join(clauses), params

    def _query_token_summary(self, where: str, params: list[str]) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT COUNT(*), "
            "COALESCE(SUM(token_input), 0), "
            "COALESCE(SUM(token_output), 0) "
            f"FROM traces WHERE {where}",
            params,
        ).fetchone()
        return {
            "traces": row[0],
            "input": row[1],
            "output": row[2],
            "total": row[1] + row[2],
        }

    def export_json(self) -> list[Trace]:
        rows = self._conn.execute("SELECT * FROM traces ORDER BY timestamp").fetchall()
        return [self._row_to_trace(row) for row in rows]

    @override
    def close(self) -> None:
        self._conn.close()

    def _row_to_trace(self, row: tuple[Any, ...]) -> Trace:
        return Trace.from_dict(self._row_to_dict(row))

    def _row_to_dict(self, row: tuple[Any, ...]) -> dict[str, Any]:
        d: dict[str, Any] = dict(zip(_TRACE_COLS, row, strict=False))
        rid = d["id"]
        d["tags"] = json.loads(d["tags"])
        d["files_modified"] = json.loads(d["files_modified"])
        d["metadata"] = json.loads(d["metadata"])
        # Only construct token_usage when at least one value is non-zero,
        # otherwise Trace.from_dict creates TokenUsage(0,0,0,0) instead of None
        ti = d.pop("token_input")
        to = d.pop("token_output")
        tcr = d.pop("token_cache_read")
        tcc = d.pop("token_cache_creation")
        if ti or to or tcr or tcc:
            d["token_usage"] = {
                "input_tokens": ti,
                "output_tokens": to,
                "cache_read_tokens": tcr,
                "cache_creation_tokens": tcc,
            }
        else:
            d["token_usage"] = None
        d["context"] = self._load_nested(
            "SELECT type, source, content_hash, content, bytes, timestamp "
            "FROM trace_context WHERE trace_id = ?",
            rid,
            ["type", "source", "content_hash", "content", "bytes", "timestamp"],
        )
        d["searches"] = self._load_nested(
            "SELECT query, engine, results_count, timestamp "
            "FROM trace_searches WHERE trace_id = ?",
            rid,
            ["query", "engine", "results_count", "timestamp"],
        )
        d["sources_read"] = self._load_nested(
            "SELECT type, path, content_hash, content, tool, bytes_read, timestamp "
            "FROM trace_sources WHERE trace_id = ?",
            rid,
            [
                "type",
                "path",
                "content_hash",
                "content",
                "tool",
                "bytes_read",
                "timestamp",
            ],
        )
        d["tools_used"] = self._load_nested(
            "SELECT name, tool_input, tool_output, duration_ms, error, timestamp "
            "FROM trace_tools WHERE trace_id = ?",
            rid,
            ["name", "tool_input", "tool_output", "duration_ms", "error", "timestamp"],
        )
        for t in d["tools_used"]:
            t["error"] = bool(t["error"])
        return d

    def _load_nested(
        self, sql: str, trace_id: str, cols: list[str]
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(sql, (trace_id,)).fetchall()
        return [dict(zip(cols, r, strict=False)) for r in rows]
