"""Waste detection and session replay for Claude Code traces."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

# ── Data models ────────────────────────────────────────────────────────


@dataclass(slots=True)
class ToolStep:
    index: int
    name: str
    target: str
    error: bool
    output_summary: str
    timestamp: str


@dataclass(slots=True)
class LoopSession:
    trace_id: str
    task: str
    cost: float
    loop_start_index: int
    total_tools: int
    cycle_count: int
    productive_cost: float
    loop_cost: float


@dataclass(slots=True)
class ErrorSummary:
    total_cost: float
    total_count: int
    fast_errors: int
    fast_error_cost: float
    slow_errors: int
    slow_error_cost: float


@dataclass(slots=True)
class ReloadSummary:
    total_cost: float
    count: int


@dataclass(slots=True)
class WasteReport:
    total_sessions: int
    total_cost: float
    productive_cost: float
    loops: list[LoopSession]
    loop_cost: float
    errors: ErrorSummary
    reloads: ReloadSummary


@dataclass(slots=True)
class SessionReplay:
    trace_id: str
    task: str
    status: str
    model: str
    turn_count: int
    duration_ms: int
    total_cost: float
    tools: list[ToolStep]
    loop_start: int | None
    loop_cycles: int
    productive_cost: float
    loop_cost: float
    scope: str


# ── Cost helpers ───────────────────────────────────────────────────────


def _session_cost(row: sqlite3.Row | tuple[Any, ...], col_map: dict[str, int]) -> float:
    """Compute cost for a trace row using the shared pricing module."""
    from openflux._pricing import estimate_cost

    return estimate_cost(
        model=row[col_map["model"]] or "",
        input_tokens=row[col_map["token_input"]] or 0,
        output_tokens=row[col_map["token_output"]] or 0,
        cache_read_tokens=row[col_map["token_cache_read"]] or 0,
        cache_creation_tokens=row[col_map["token_cache_creation"]] or 0,
    )


_TRACE_COST_COLS = (
    "id, task, status, model, turn_count, duration_ms, scope, "
    "token_input, token_output, token_cache_read, token_cache_creation"
)

_TRACE_COL_MAP: dict[str, int] = {
    "id": 0,
    "task": 1,
    "status": 2,
    "model": 3,
    "turn_count": 4,
    "duration_ms": 5,
    "scope": 6,
    "token_input": 7,
    "token_output": 8,
    "token_cache_read": 9,
    "token_cache_creation": 10,
}


# ── Loop detection ─────────────────────────────────────────────────────

_RELOAD_OVERHEAD_FRAC = 0.10  # fraction of session cost attributed to context reloading
_EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit"})
_TEST_TOOL = "Bash"
_MIN_CYCLES = 3


def _detect_loop(tools: list[tuple[str, bool]]) -> tuple[int | None, int]:
    """Find edit→fail cycles in a tool sequence.

    Returns (loop_start_index, cycle_count). If no loop, returns (None, 0).
    Each "cycle" is an edit/write tool followed by a Bash error.
    """
    cycle_count = 0
    first_cycle_start: int | None = None

    i = 0
    while i < len(tools) - 1:
        name, _error = tools[i]
        next_name, next_error = tools[i + 1]

        if name in _EDIT_TOOLS and next_name == _TEST_TOOL and next_error:
            if cycle_count == 0:
                first_cycle_start = i
            cycle_count += 1
            i += 2
        elif cycle_count > 0 and cycle_count < _MIN_CYCLES:
            # Reset if we haven't hit the threshold and the pattern broke
            if name != _TEST_TOOL or not _error:
                cycle_count = 0
                first_cycle_start = None
            i += 1
        else:
            i += 1

    if cycle_count >= _MIN_CYCLES:
        return first_cycle_start, cycle_count
    return None, 0


# ── Tool step extraction ──────────────────────────────────────────────


def _parse_target(name: str, tool_input: str) -> str:
    """Extract a human-readable target from tool_input JSON."""
    try:
        data = json.loads(tool_input) if tool_input else {}
    except (json.JSONDecodeError, TypeError):
        return tool_input[:60] if tool_input else ""

    if not isinstance(data, dict):
        return str(data)[:60]

    match name:
        case "Bash":
            cmd = data.get("command", "")
            return cmd[:60] if cmd else ""
        case "Read" | "Edit" | "Write" | "MultiEdit":
            return data.get("file_path", data.get("path", ""))[:80]
        case "Grep":
            pattern = data.get("pattern", "")
            path = data.get("path", "")
            return f'"{pattern}" in {path}' if path else f'"{pattern}"'
        case "Glob":
            return data.get("pattern", "")[:60]
        case "Agent":
            prompt = data.get("prompt", data.get("description", ""))
            return prompt[:60] if prompt else ""
        case _:
            # For MCP tools, skills, etc — show first interesting key
            for key in ("query", "prompt", "skill", "command", "url"):
                if val := data.get(key):
                    return str(val)[:60]
            return ""


def _parse_output_summary(name: str, tool_output: str, error: bool) -> str:
    """Generate a short summary of tool output."""
    if error:
        # Try to extract error message
        try:
            data = json.loads(tool_output) if tool_output else {}
            if isinstance(data, dict):
                err = data.get("stderr", data.get("error", ""))
                if err:
                    return str(err)[:50]
        except (json.JSONDecodeError, TypeError):
            pass
        return tool_output[:50] if tool_output else "error"

    if not tool_output:
        return ""

    match name:
        case "Read":
            size = len(tool_output)
            if size > 1024:
                return f"{size / 1024:.1f} KB"
            return f"{size} B"
        case "Edit" | "Write" | "MultiEdit":
            return ""
        case "Grep":
            lines = tool_output.count("\n")
            return f"{lines} match{'es' if lines != 1 else ''}" if lines else ""
        case "Bash":
            try:
                data = json.loads(tool_output)
                if isinstance(data, dict):
                    stdout = data.get("stdout", "")
                    stderr = data.get("stderr", "")
                    if "FAILED" in stderr or "FAILED" in stdout:
                        # Count test failures
                        text = stderr + stdout
                        count = text.count("FAILED")
                        return f"{count} failure{'s' if count != 1 else ''}"
                    if "error" in stderr.lower():
                        return stderr[:50]
                    if stdout:
                        lines = stdout.count("\n")
                        return f"{lines} line{'s' if lines != 1 else ''}"
            except (json.JSONDecodeError, TypeError):
                pass
            return ""
        case _:
            return ""


def _build_tool_steps(conn: sqlite3.Connection, trace_id: str) -> list[ToolStep]:
    """Load tool sequence for a session and build ToolStep list."""
    rows = conn.execute(
        "SELECT name, tool_input, tool_output, error, timestamp "
        "FROM trace_tools WHERE trace_id = ? ORDER BY timestamp ASC",
        (trace_id,),
    ).fetchall()

    steps: list[ToolStep] = []
    for i, (name, tool_input, tool_output, error, ts) in enumerate(rows):
        steps.append(
            ToolStep(
                index=i + 1,
                name=name,
                target=_parse_target(name, tool_input),
                error=bool(error),
                output_summary=_parse_output_summary(name, tool_output, bool(error)),
                timestamp=ts or "",
            )
        )
    return steps


# ── Public API ─────────────────────────────────────────────────────────


def analyze_waste(
    conn: sqlite3.Connection,
    days: int = 30,
    agent: str | None = None,
) -> WasteReport:
    """Analyze waste patterns across sessions."""
    # Build filter
    clauses = ["1=1"]
    params: list[Any] = []
    if days:
        clauses.append("timestamp >= datetime('now', ? || ' days')")
        params.append(f"-{days}")
    if agent:
        clauses.append("agent = ?")
        params.append(agent)
    where = " AND ".join(clauses)

    # Load all sessions with cost data
    rows = conn.execute(
        f"SELECT {_TRACE_COST_COLS} FROM traces WHERE {where} ORDER BY timestamp DESC",
        params,
    ).fetchall()

    total_cost = 0.0
    session_costs: dict[str, float] = {}
    for row in rows:
        cost = _session_cost(row, _TRACE_COL_MAP)
        session_costs[row[0]] = cost
        total_cost += cost

    # 1. Detect loops — find sessions with 3+ bash errors, then verify cycle pattern
    loop_candidates = conn.execute(
        "SELECT tr.id FROM traces tr "
        "JOIN trace_tools t ON t.trace_id = tr.id "
        f"WHERE {where.replace('timestamp', 'tr.timestamp')} "
        "AND t.name = 'Bash' AND t.error = 1 "
        "GROUP BY tr.id HAVING COUNT(*) >= 3",
        params,
    ).fetchall()

    loops: list[LoopSession] = []
    loop_total_cost = 0.0
    loop_trace_ids: set[str] = set()

    for (trace_id,) in loop_candidates:
        tool_rows = conn.execute(
            "SELECT name, error FROM trace_tools WHERE trace_id = ? ORDER BY timestamp",
            (trace_id,),
        ).fetchall()
        tool_seq = [(r[0], bool(r[1])) for r in tool_rows]
        loop_start, cycles = _detect_loop(tool_seq)

        if loop_start is not None:
            cost = session_costs.get(trace_id, 0.0)
            total_tools = len(tool_seq)
            # Proportional cost split
            loop_frac = (
                (total_tools - loop_start) / total_tools if total_tools > 0 else 0
            )
            loop_cost = cost * loop_frac
            productive = cost - loop_cost

            # Get task text
            task_row = conn.execute(
                "SELECT task FROM traces WHERE id = ?", (trace_id,)
            ).fetchone()
            task = (task_row[0] or "")[:100] if task_row else ""

            loops.append(
                LoopSession(
                    trace_id=trace_id,
                    task=task,
                    cost=cost,
                    loop_start_index=loop_start,
                    total_tools=total_tools,
                    cycle_count=cycles,
                    productive_cost=productive,
                    loop_cost=loop_cost,
                )
            )
            loop_total_cost += loop_cost
            loop_trace_ids.add(trace_id)

    loops.sort(key=lambda s: s.loop_cost, reverse=True)

    # 2. Error sessions (excluding those already counted as loops)
    error_total = 0.0
    fast_errors = 0
    fast_cost = 0.0
    slow_errors = 0
    slow_cost = 0.0
    error_count = 0

    for row in rows:
        if row[_TRACE_COL_MAP["status"]] != "error":
            continue
        trace_id = row[_TRACE_COL_MAP["id"]]
        if trace_id in loop_trace_ids:
            continue  # already counted under loops
        cost = session_costs[trace_id]
        turns = row[_TRACE_COL_MAP["turn_count"]] or 0
        error_count += 1
        error_total += cost
        if turns <= 5:
            fast_errors += 1
            fast_cost += cost
        elif turns > 20:
            slow_errors += 1
            slow_cost += cost

    # 3. Context reloads — same scope within 10 min
    reload_rows = conn.execute(
        "WITH ordered AS ("
        f"  SELECT id, scope, timestamp FROM traces WHERE {where} "
        "  AND scope IS NOT NULL AND scope != ''"
        ") "
        "SELECT a.id, a.scope "
        "FROM ordered a "
        "JOIN ordered b ON a.scope = b.scope AND a.id != b.id "
        "WHERE (julianday(a.timestamp) - julianday(b.timestamp)) * 24 * 60 "
        "  BETWEEN 0 AND 10 "
        "AND a.timestamp > b.timestamp "
        "GROUP BY a.id",
        params,
    ).fetchall()

    reload_cost = 0.0
    reload_ids: set[str] = set()
    for r_id, _ in reload_rows:
        if r_id not in loop_trace_ids and r_id not in reload_ids:
            reload_ids.add(r_id)
            reload_cost += session_costs.get(r_id, 0.0) * _RELOAD_OVERHEAD_FRAC

    # Compute productive cost
    waste = loop_total_cost + error_total + reload_cost
    productive = total_cost - waste

    return WasteReport(
        total_sessions=len(rows),
        total_cost=total_cost,
        productive_cost=max(0.0, productive),
        loops=loops,
        loop_cost=loop_total_cost,
        errors=ErrorSummary(
            total_cost=error_total,
            total_count=error_count,
            fast_errors=fast_errors,
            fast_error_cost=fast_cost,
            slow_errors=slow_errors,
            slow_error_cost=slow_cost,
        ),
        reloads=ReloadSummary(
            total_cost=reload_cost,
            count=len(reload_ids),
        ),
    )


def replay_session(conn: sqlite3.Connection, trace_id: str) -> SessionReplay | None:
    """Build a detailed replay of a single session's tool sequence."""
    row = conn.execute(
        f"SELECT {_TRACE_COST_COLS} FROM traces WHERE id = ?",
        (trace_id,),
    ).fetchone()
    if row is None:
        return None

    cost = _session_cost(row, _TRACE_COL_MAP)
    tools = _build_tool_steps(conn, trace_id)

    # Detect loops in this session
    tool_seq = [(t.name, t.error) for t in tools]
    loop_start, cycles = _detect_loop(tool_seq)

    # Cost attribution
    loop_cost = 0.0
    productive_cost = cost
    if loop_start is not None and len(tools) > 0:
        loop_frac = (len(tools) - loop_start) / len(tools)
        loop_cost = cost * loop_frac
        productive_cost = cost - loop_cost

    return SessionReplay(
        trace_id=trace_id,
        task=(row[_TRACE_COL_MAP["task"]] or "")[:200],
        status=row[_TRACE_COL_MAP["status"]] or "completed",
        model=row[_TRACE_COL_MAP["model"]] or "",
        turn_count=row[_TRACE_COL_MAP["turn_count"]] or 0,
        duration_ms=row[_TRACE_COL_MAP["duration_ms"]] or 0,
        total_cost=cost,
        tools=tools,
        loop_start=loop_start,
        loop_cycles=cycles,
        productive_cost=productive_cost,
        loop_cost=loop_cost,
        scope=row[_TRACE_COL_MAP["scope"]] or "",
    )
