"""Tool-level efficiency analysis and session replay."""

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
class CategoryBreakdown:
    name: str
    calls: int
    pct: float
    output_bytes: int


@dataclass(slots=True)
class RedundantPattern:
    pattern: str
    total_calls: int
    unique_calls: int
    redundant_calls: int
    sessions: int


@dataclass(slots=True)
class EfficiencyReport:
    total_sessions: int
    total_cost: float
    total_tool_calls: int
    # Tool call categories
    categories: list[CategoryBreakdown]
    # Overhead (agent meta-tools)
    overhead_calls: int
    overhead_pct: float
    # Redundancy within sessions
    redundant_patterns: list[RedundantPattern]
    total_redundant_calls: int
    redundancy_pct: float
    # Bash breakdown (what the agent uses Bash for)
    bash_breakdown: list[CategoryBreakdown]


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
    scope: str
    # Per-session analysis
    tool_breakdown: list[CategoryBreakdown]
    redundant_in_session: list[RedundantPattern]


# ── Cost helpers ───────────────────────────────────────────────────────


_TRACE_COST_COLS = (
    "id, task, status, model, turn_count, duration_ms, scope, "
    "token_input, token_output, token_cache_read, token_cache_creation"
)

_COL: dict[str, int] = {
    "id": 0, "task": 1, "status": 2, "model": 3, "turn_count": 4,
    "duration_ms": 5, "scope": 6, "token_input": 7, "token_output": 8,
    "token_cache_read": 9, "token_cache_creation": 10,
}


def _row_cost(row: tuple[Any, ...]) -> float:
    from openflux._pricing import estimate_cost
    return estimate_cost(
        model=row[_COL["model"]] or "",
        input_tokens=row[_COL["token_input"]] or 0,
        output_tokens=row[_COL["token_output"]] or 0,
        cache_read_tokens=row[_COL["token_cache_read"]] or 0,
        cache_creation_tokens=row[_COL["token_cache_creation"]] or 0,
    )


# ── Tool classification ───────────────────────────────────────────────

_OVERHEAD_TOOLS = frozenset({
    "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TaskStop",
    "TaskOutput", "ToolSearch", "SendMessage", "EnterPlanMode",
    "ExitPlanMode", "Skill",
})

_TOOL_CATEGORIES: list[tuple[str, str]] = [
    # (pattern in tool_input, category_name) — matched against Bash commands
    ("agent-browser", "Browser automation"),
    ("head ", "File read (head)"),
    ("| head", "File read (head)"),
    ("cat ", "File read (cat)"),
    ("git status", "git status"),
    ("git diff", "git diff"),
    ("git log", "git log"),
    ("git add", "git add"),
    ("git commit", "git commit"),
    ("git checkout", "git branch ops"),
    ("git switch", "git branch ops"),
    ("git push", "git push"),
    ("pytest", "Test (pytest)"),
    ("npm run", "Build (npm)"),
    ("pnpm ", "Build (pnpm)"),
    ("npm install", "Install (npm)"),
    ("pnpm install", "Install (pnpm)"),
    ("ruff ", "Lint (ruff)"),
    ("pyright", "Typecheck (pyright)"),
    ("grep ", "Search (grep)"),
    ("rg ", "Search (rg)"),
    ("find ", "File search (find)"),
    ("mkdir", "mkdir"),
    ("ls ", "Directory listing (ls)"),
    ("ls\n", "Directory listing (ls)"),
    ("curl ", "HTTP request (curl)"),
    ("echo ", "echo"),
    ("cd ", "cd (navigation)"),
]


def _classify_bash(tool_input: str) -> str:
    """Classify a Bash command into a human-readable category."""
    for pattern, category in _TOOL_CATEGORIES:
        if pattern in tool_input:
            return category
    return "Other"


def _classify_tool(name: str, tool_input: str) -> str:
    """Classify any tool call into a category."""
    if name in _OVERHEAD_TOOLS:
        return f"Overhead ({name})"
    if name == "Agent":
        return "Subagent"
    if name == "Bash":
        return _classify_bash(tool_input)
    if name.startswith("mcp__"):
        return f"MCP ({name.split('__')[1]})"
    return name


# ── Redundancy detection ──────────────────────────────────────────────


def _detect_redundancy(
    conn: sqlite3.Connection,
    where: str,
    params: list[Any],
) -> tuple[list[RedundantPattern], int]:
    """Find commands repeated within sessions."""
    # Get per-session command repetitions
    rows = conn.execute(
        "SELECT t.trace_id, t.name, t.tool_input, COUNT(*) as times "
        "FROM trace_tools t "
        "JOIN traces tr ON t.trace_id = tr.id "
        f"WHERE {where.replace('timestamp', 'tr.timestamp')} "
        "GROUP BY t.trace_id, t.name, t.tool_input "
        "HAVING times >= 2",
        params,
    ).fetchall()

    # Aggregate across sessions by command pattern
    pattern_stats: dict[str, dict[str, int]] = {}
    for _trace_id, name, tool_input, times in rows:
        key = _classify_tool(name, tool_input or "")
        if key.startswith("Overhead"):
            continue  # overhead repetition is expected
        if key in ("Subagent",):
            continue
        stats = pattern_stats.setdefault(key, {
            "total": 0, "unique": 0, "redundant": 0, "sessions": 0,
        })
        stats["total"] += times
        stats["unique"] += 1  # each (trace, input) pair is one unique
        stats["redundant"] += times - 1
        stats["sessions"] += 1

    patterns = [
        RedundantPattern(
            pattern=k,
            total_calls=v["total"],
            unique_calls=v["unique"],
            redundant_calls=v["redundant"],
            sessions=v["sessions"],
        )
        for k, v in pattern_stats.items()
        if v["redundant"] > 0
    ]
    patterns.sort(key=lambda p: p.redundant_calls, reverse=True)
    total_redundant = sum(p.redundant_calls for p in patterns)
    return patterns, total_redundant


# ── Session-level analysis ────────────────────────────────────────────


def _session_redundancy(
    tools: list[tuple[str, str]],
) -> list[RedundantPattern]:
    """Find repeated tool calls within a single session's tool sequence."""
    counts: dict[str, int] = {}
    for name, tool_input in tools:
        key = _classify_tool(name, tool_input)
        if key.startswith("Overhead"):
            continue
        # Use (category, input) as the dedup key
        full_key = f"{key}::{tool_input}"
        counts[full_key] = counts.get(full_key, 0) + 1

    patterns: list[RedundantPattern] = []
    # Aggregate by category
    cat_stats: dict[str, dict[str, int]] = {}
    for full_key, total in counts.items():
        if total < 2:
            continue
        cat = full_key.split("::")[0]
        stats = cat_stats.setdefault(cat, {"total": 0, "redundant": 0, "unique": 0})
        stats["total"] += total
        stats["redundant"] += total - 1
        stats["unique"] += 1

    for cat, stats in cat_stats.items():
        if stats["redundant"] > 0:
            patterns.append(RedundantPattern(
                pattern=cat,
                total_calls=stats["total"],
                unique_calls=stats["unique"],
                redundant_calls=stats["redundant"],
                sessions=1,
            ))
    patterns.sort(key=lambda p: p.redundant_calls, reverse=True)
    return patterns


# ── Target / output parsing (for replay) ──────────────────────────────


def _parse_target(name: str, tool_input: str) -> str:
    try:
        data = json.loads(tool_input) if tool_input else {}
    except (json.JSONDecodeError, TypeError):
        return tool_input[:60] if tool_input else ""
    if not isinstance(data, dict):
        return str(data)[:60]
    match name:
        case "Bash":
            return (data.get("command", "") or "")[:60]
        case "Read" | "Edit" | "Write" | "MultiEdit":
            return (data.get("file_path", "") or data.get("path", "") or "")[:80]
        case "Grep":
            p = data.get("pattern", "")
            path = data.get("path", "")
            return f'"{p}" in {path}' if path else f'"{p}"'
        case "Glob":
            return (data.get("pattern", "") or "")[:60]
        case "Agent":
            return (data.get("prompt", "") or data.get("description", "") or "")[:60]
        case _:
            for key in ("query", "prompt", "skill", "command", "url"):
                if val := data.get(key):
                    return str(val)[:60]
            return ""


def _parse_output_summary(name: str, tool_output: str, error: bool) -> str:
    if error:
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
            return f"{size / 1024:.1f} KB" if size > 1024 else f"{size} B"
        case "Edit" | "Write" | "MultiEdit":
            return ""
        case "Bash":
            try:
                data = json.loads(tool_output)
                if isinstance(data, dict):
                    stdout = data.get("stdout", "")
                    stderr = data.get("stderr", "")
                    if "FAILED" in stderr or "FAILED" in stdout:
                        count = (stderr + stdout).count("FAILED")
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


def _build_tool_steps(
    conn: sqlite3.Connection, trace_id: str,
) -> list[ToolStep]:
    rows = conn.execute(
        "SELECT name, tool_input, tool_output, error, timestamp "
        "FROM trace_tools WHERE trace_id = ? ORDER BY timestamp ASC",
        (trace_id,),
    ).fetchall()
    return [
        ToolStep(
            index=i + 1,
            name=name,
            target=_parse_target(name, tool_input or ""),
            error=bool(error),
            output_summary=_parse_output_summary(name, tool_output or "", bool(error)),
            timestamp=ts or "",
        )
        for i, (name, tool_input, tool_output, error, ts) in enumerate(rows)
    ]


# ── Public API ─────────────────────────────────────────────────────────


def analyze_efficiency(
    conn: sqlite3.Connection,
    days: int = 30,
    agent: str | None = None,
) -> EfficiencyReport:
    """Analyze tool usage patterns and redundancy."""
    clauses = ["1=1"]
    params: list[Any] = []
    if days:
        clauses.append("timestamp >= datetime('now', ? || ' days')")
        params.append(f"-{days}")
    if agent:
        clauses.append("agent = ?")
        params.append(agent)
    where = " AND ".join(clauses)

    # Total sessions and cost
    rows = conn.execute(
        f"SELECT {_TRACE_COST_COLS} FROM traces WHERE {where}", params,
    ).fetchall()
    total_cost = sum(_row_cost(r) for r in rows)

    # Tool call categories
    tool_rows = conn.execute(
        "SELECT t.name, t.tool_input, LENGTH(t.tool_output) "
        "FROM trace_tools t "
        "JOIN traces tr ON t.trace_id = tr.id "
        f"WHERE {where.replace('timestamp', 'tr.timestamp')}",
        params,
    ).fetchall()

    total_tools = len(tool_rows)
    cat_counts: dict[str, dict[str, int]] = {}
    overhead_count = 0
    bash_counts: dict[str, dict[str, int]] = {}

    for name, tool_input, output_len in tool_rows:
        cat = _classify_tool(name, tool_input or "")
        stats = cat_counts.setdefault(cat, {"calls": 0, "bytes": 0})
        stats["calls"] += 1
        stats["bytes"] += output_len or 0

        if name in _OVERHEAD_TOOLS:
            overhead_count += 1

        if name == "Bash":
            bash_cat = _classify_bash(tool_input or "")
            bstats = bash_counts.setdefault(bash_cat, {"calls": 0, "bytes": 0})
            bstats["calls"] += 1
            bstats["bytes"] += output_len or 0

    categories = sorted(
        [
            CategoryBreakdown(
                name=k, calls=v["calls"],
                pct=v["calls"] / total_tools * 100 if total_tools else 0,
                output_bytes=v["bytes"],
            )
            for k, v in cat_counts.items()
        ],
        key=lambda c: c.calls, reverse=True,
    )

    bash_breakdown = sorted(
        [
            CategoryBreakdown(
                name=k, calls=v["calls"],
                pct=v["calls"] / total_tools * 100 if total_tools else 0,
                output_bytes=v["bytes"],
            )
            for k, v in bash_counts.items()
        ],
        key=lambda c: c.calls, reverse=True,
    )

    # Redundancy
    redundant_patterns, total_redundant = _detect_redundancy(conn, where, params)

    return EfficiencyReport(
        total_sessions=len(rows),
        total_cost=total_cost,
        total_tool_calls=total_tools,
        categories=categories,
        overhead_calls=overhead_count,
        overhead_pct=overhead_count / total_tools * 100 if total_tools else 0,
        redundant_patterns=redundant_patterns[:15],
        total_redundant_calls=total_redundant,
        redundancy_pct=total_redundant / total_tools * 100 if total_tools else 0,
        bash_breakdown=bash_breakdown,
    )


def replay_session(conn: sqlite3.Connection, trace_id: str) -> SessionReplay | None:
    """Build a detailed replay of a session's tool sequence with analysis."""
    row = conn.execute(
        f"SELECT {_TRACE_COST_COLS} FROM traces WHERE id = ?", (trace_id,),
    ).fetchone()
    if row is None:
        return None

    cost = _row_cost(row)
    tools = _build_tool_steps(conn, trace_id)

    # Per-session tool breakdown
    cat_counts: dict[str, int] = {}
    tool_inputs: list[tuple[str, str]] = []
    for step in tools:
        # Recover tool_input for classification
        raw = conn.execute(
            "SELECT tool_input FROM trace_tools WHERE trace_id = ? "
            "ORDER BY timestamp ASC LIMIT 1 OFFSET ?",
            (trace_id, step.index - 1),
        ).fetchone()
        tool_input = raw[0] if raw else ""
        cat = _classify_tool(step.name, tool_input)
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        tool_inputs.append((step.name, tool_input))

    total = len(tools)
    breakdown = sorted(
        [
            CategoryBreakdown(
                name=k, calls=v,
                pct=v / total * 100 if total else 0,
                output_bytes=0,
            )
            for k, v in cat_counts.items()
        ],
        key=lambda c: c.calls, reverse=True,
    )

    redundant = _session_redundancy(tool_inputs)

    return SessionReplay(
        trace_id=trace_id,
        task=(row[_COL["task"]] or "")[:200],
        status=row[_COL["status"]] or "completed",
        model=row[_COL["model"]] or "",
        turn_count=row[_COL["turn_count"]] or 0,
        duration_ms=row[_COL["duration_ms"]] or 0,
        total_cost=cost,
        tools=tools,
        scope=row[_COL["scope"]] or "",
        tool_breakdown=breakdown,
        redundant_in_session=redundant,
    )
