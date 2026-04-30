"""Cost intelligence: cache efficiency, burn rate, budgets, anomaly detection."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# ── Data models ────────────────────────────────────────────────────────


@dataclass(slots=True)
class CostOverview:
    """Top-level cost intelligence for a time window."""

    total_sessions: int
    total_cost: float
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    # Cache efficiency: the metric people actually care about
    cache_hit_ratio: float  # cache_read / (cache_read + input), 0 to 1
    cost_without_cache: float  # what you'd have paid without caching
    cache_savings: float  # cost_without_cache - total_cost
    # Burn rate
    daily_burn_rate: float  # avg $/day over the window
    projected_monthly: float  # daily_burn_rate * 30
    # Breakdown
    by_model: list[ModelCost]
    by_day: list[DayCost]


@dataclass(slots=True)
class ModelCost:
    model: str
    cost: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cache_hit_ratio: float
    session_count: int


@dataclass(slots=True)
class DayCost:
    date: str
    cost: float
    sessions: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cache_hit_ratio: float


@dataclass(slots=True)
class SessionCost:
    """Per-session cost with cache efficiency.

    `uncached_input_cost` is the dollar amount paid at full input rate (the
    portion that didn't hit the cache). It's the actionable "cache pain"
    metric; cache_hit_ratio saturates near 100% on healthy Claude usage and
    is mostly informational.
    """

    trace_id: str
    task: str
    status: str
    model: str
    scope: str
    timestamp: str
    cost: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cache_hit_ratio: float
    uncached_input_cost: float
    duration_ms: int
    turn_count: int
    tool_count: int
    error_count: int


@dataclass(slots=True)
class BudgetStatus:
    """Budget tracking against a daily cap."""

    daily_budget: float
    spent_today: float
    remaining_today: float
    pct_used: float  # 0-100
    on_track: bool  # under budget
    projected_eod: float  # projected end-of-day spend
    sessions_today: int


@dataclass(slots=True)
class CostAnomaly:
    """A detected cost anomaly worth flagging."""

    type: str  # "loop", "cache_miss", "cost_spike", "error_storm"
    severity: str  # "warning", "critical"
    trace_id: str
    description: str
    cost: float
    details: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())


# ── Cost helpers ───────────────────────────────────────────────────────


_COST_COLS = (
    "id, timestamp, task, status, model, turn_count, duration_ms, scope, "
    "token_input, token_output, token_cache_read, token_cache_creation"
)

_C: dict[str, int] = {
    "id": 0,
    "timestamp": 1,
    "task": 2,
    "status": 3,
    "model": 4,
    "turn_count": 5,
    "duration_ms": 6,
    "scope": 7,
    "token_input": 8,
    "token_output": 9,
    "token_cache_read": 10,
    "token_cache_creation": 11,
}


def _row_cost(row: tuple[Any, ...]) -> float:
    from openflux._pricing import estimate_cost

    return estimate_cost(
        model=row[_C["model"]] or "",
        input_tokens=row[_C["token_input"]] or 0,
        output_tokens=row[_C["token_output"]] or 0,
        cache_read_tokens=row[_C["token_cache_read"]] or 0,
        cache_creation_tokens=row[_C["token_cache_creation"]] or 0,
    )


def _row_cost_without_cache(row: tuple[Any, ...]) -> float:
    """What this row would cost if every cache_read token was a full input token."""
    from openflux._pricing import estimate_cost

    input_tok = (row[_C["token_input"]] or 0) + (row[_C["token_cache_read"]] or 0)
    return estimate_cost(
        model=row[_C["model"]] or "",
        input_tokens=input_tok,
        output_tokens=row[_C["token_output"]] or 0,
        cache_read_tokens=0,
        cache_creation_tokens=row[_C["token_cache_creation"]] or 0,
    )


def _uncached_input_cost(model: str, input_tokens: int) -> float:
    """Dollar cost of input tokens billed at full (non-cache) rate.

    This is the "cache pain" metric: how much you paid full freight on
    input that didn't hit the cache. Unlike `cache_hit_ratio`, it doesn't
    saturate at the high end and stays actionable on healthy traffic.
    """
    from openflux._pricing import estimate_cost

    return estimate_cost(
        model=model or "",
        input_tokens=input_tokens or 0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
    )


def _cache_hit_ratio(cache_read: int, input_tokens: int) -> float:
    """Fraction of input tokens served from cache. Higher = better."""
    total = cache_read + input_tokens
    if total == 0:
        return 0.0
    return cache_read / total


def _build_filter(days: int | None, agent: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = ["1=1"]
    params: list[Any] = []
    if days is not None:
        clauses.append("timestamp >= datetime('now', ? || ' days')")
        params.append(f"-{days}")
    if agent:
        clauses.append("agent = ?")
        params.append(agent)
    return " AND ".join(clauses), params


# ── Public API ─────────────────────────────────────────────────────────


def _has_billable_messages(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='billable_messages'"
    ).fetchone()
    return row is not None


def _billable_filter(days: int | None, agent: str | None) -> tuple[str, list[Any]]:
    clauses: list[str] = ["1=1"]
    params: list[Any] = []
    if days is not None:
        clauses.append("timestamp >= datetime('now', ? || ' days')")
        params.append(f"-{days}")
    if agent:
        clauses.append("agent = ?")
        params.append(agent)
    return " AND ".join(clauses), params


def cost_overview(
    conn: sqlite3.Connection,
    days: int = 7,
    agent: str | None = None,
) -> CostOverview:
    """Compute cost across all agents.

    For sessions that have provider-level message records in
    `billable_messages` (claude-code, after transcript backfill), use
    those, since they're keyed on Anthropic message.id so the same API call
    appearing in multiple resumed/forked transcripts counts once. For
    sessions that don't, fall back to the per-trace aggregate (the
    correct unit for adapters that don't expose message ids).
    """
    if not _has_billable_messages(conn):
        return _cost_overview_from_traces(conn, days, agent)

    msg_overview = _cost_overview_from_messages(conn, days, agent)
    # Sessions covered by billable_messages: exclude them from the
    # legacy traces aggregate so we don't double-count.
    where, params = _billable_filter(days, agent)
    covered_rows = conn.execute(
        f"SELECT DISTINCT session_id FROM billable_messages WHERE {where}",
        params,
    ).fetchall()
    covered = {r[0] for r in covered_rows if r[0]}
    trace_overview = _cost_overview_from_traces(
        conn, days, agent, exclude_sessions=covered
    )
    return _merge_overviews(msg_overview, trace_overview, max(1, days))


def _merge_overviews(a: CostOverview, b: CostOverview, days: int) -> CostOverview:
    by_model: dict[str, ModelCost] = {}
    for m in (*a.by_model, *b.by_model):
        cur = by_model.get(m.model)
        if cur is None:
            by_model[m.model] = m
        else:
            by_model[m.model] = ModelCost(
                model=m.model,
                cost=cur.cost + m.cost,
                input_tokens=cur.input_tokens + m.input_tokens,
                output_tokens=cur.output_tokens + m.output_tokens,
                cache_read_tokens=cur.cache_read_tokens + m.cache_read_tokens,
                cache_creation_tokens=cur.cache_creation_tokens
                + m.cache_creation_tokens,
                cache_hit_ratio=_cache_hit_ratio(
                    cur.cache_read_tokens + m.cache_read_tokens,
                    cur.input_tokens + m.input_tokens,
                ),
                session_count=cur.session_count + m.session_count,
            )
    by_day: dict[str, DayCost] = {}
    for d in (*a.by_day, *b.by_day):
        cur = by_day.get(d.date)
        if cur is None:
            by_day[d.date] = d
        else:
            by_day[d.date] = DayCost(
                date=d.date,
                cost=cur.cost + d.cost,
                sessions=cur.sessions + d.sessions,
                input_tokens=cur.input_tokens + d.input_tokens,
                output_tokens=cur.output_tokens + d.output_tokens,
                cache_read_tokens=cur.cache_read_tokens + d.cache_read_tokens,
                cache_creation_tokens=cur.cache_creation_tokens
                + d.cache_creation_tokens,
                cache_hit_ratio=_cache_hit_ratio(
                    cur.cache_read_tokens + d.cache_read_tokens,
                    cur.input_tokens + d.input_tokens,
                ),
            )
    total_cost = a.total_cost + b.total_cost
    total_in = a.total_input_tokens + b.total_input_tokens
    total_cr = a.total_cache_read_tokens + b.total_cache_read_tokens
    return CostOverview(
        total_sessions=a.total_sessions + b.total_sessions,
        total_cost=total_cost,
        total_input_tokens=total_in,
        total_output_tokens=a.total_output_tokens + b.total_output_tokens,
        total_cache_read_tokens=total_cr,
        total_cache_creation_tokens=a.total_cache_creation_tokens
        + b.total_cache_creation_tokens,
        cache_hit_ratio=_cache_hit_ratio(total_cr, total_in),
        cost_without_cache=a.cost_without_cache + b.cost_without_cache,
        cache_savings=a.cache_savings + b.cache_savings,
        daily_burn_rate=total_cost / days,
        projected_monthly=(total_cost / days) * 30,
        by_model=sorted(by_model.values(), key=lambda x: x.cost, reverse=True),
        by_day=sorted(by_day.values(), key=lambda x: x.date),
    )


def _cost_overview_from_messages(
    conn: sqlite3.Connection, days: int, agent: str | None
) -> CostOverview:
    from openflux._pricing import estimate_cost

    where, params = _billable_filter(days, agent)
    rows = conn.execute(
        "SELECT model, timestamp, session_id, "
        "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens "
        f"FROM billable_messages WHERE {where}",
        params,
    ).fetchall()

    if not rows:
        return CostOverview(
            total_sessions=0,
            total_cost=0.0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_read_tokens=0,
            total_cache_creation_tokens=0,
            cache_hit_ratio=0.0,
            cost_without_cache=0.0,
            cache_savings=0.0,
            daily_burn_rate=0.0,
            projected_monthly=0.0,
            by_model=[],
            by_day=[],
        )

    total_in = total_out = total_cr = total_cc = 0
    total_cost = total_no_cache = 0.0
    sessions: set[str] = set()
    model_buckets: dict[str, dict[str, Any]] = {}
    day_buckets: dict[str, dict[str, Any]] = {}

    for model, ts, sid, i, o, cr, cc in rows:
        model = model or "(unknown)"
        i, o, cr, cc = int(i or 0), int(o or 0), int(cr or 0), int(cc or 0)
        cost = estimate_cost(model, i, o, cr, cc)
        cost_nc = estimate_cost(model, i + cr, o, 0, cc)
        total_in += i
        total_out += o
        total_cr += cr
        total_cc += cc
        total_cost += cost
        total_no_cache += cost_nc
        if sid:
            sessions.add(sid)

        b = model_buckets.setdefault(
            model,
            {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cc": 0, "sessions": set()},
        )
        b["cost"] += cost
        b["in"] += i
        b["out"] += o
        b["cr"] += cr
        b["cc"] += cc
        if sid:
            b["sessions"].add(sid)

        day = (ts or "")[:10]
        d = day_buckets.setdefault(
            day,
            {"cost": 0.0, "sessions": set(), "in": 0, "out": 0, "cr": 0, "cc": 0},
        )
        d["cost"] += cost
        if sid:
            d["sessions"].add(sid)
        d["in"] += i
        d["out"] += o
        d["cr"] += cr
        d["cc"] += cc

    by_model = sorted(
        [
            ModelCost(
                model=m,
                cost=b["cost"],
                input_tokens=b["in"],
                output_tokens=b["out"],
                cache_read_tokens=b["cr"],
                cache_creation_tokens=b["cc"],
                cache_hit_ratio=_cache_hit_ratio(b["cr"], b["in"]),
                session_count=len(b["sessions"]),
            )
            for m, b in model_buckets.items()
        ],
        key=lambda x: x.cost,
        reverse=True,
    )
    by_day = [
        DayCost(
            date=d,
            cost=b["cost"],
            sessions=len(b["sessions"]),
            input_tokens=b["in"],
            output_tokens=b["out"],
            cache_read_tokens=b["cr"],
            cache_creation_tokens=b["cc"],
            cache_hit_ratio=_cache_hit_ratio(b["cr"], b["in"]),
        )
        for d, b in sorted(day_buckets.items())
    ]

    active_days = max(1, days)
    daily_rate = total_cost / active_days
    return CostOverview(
        total_sessions=len(sessions),
        total_cost=total_cost,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_cache_read_tokens=total_cr,
        total_cache_creation_tokens=total_cc,
        cache_hit_ratio=_cache_hit_ratio(total_cr, total_in),
        cost_without_cache=total_no_cache,
        cache_savings=total_no_cache - total_cost,
        daily_burn_rate=daily_rate,
        projected_monthly=daily_rate * 30,
        by_model=by_model,
        by_day=by_day,
    )


def _cost_overview_from_traces(
    conn: sqlite3.Connection,
    days: int = 7,
    agent: str | None = None,
    exclude_sessions: set[str] | None = None,
) -> CostOverview:
    """Aggregate per-trace token totals.

    For adapters that emit one trace per agent run with token aggregates
    (everything other than claude-code today). claude-code sessions are
    excluded by passing them in `exclude_sessions` since their authoritative
    counts live in billable_messages.
    """
    where, params = _build_filter(days, agent)
    if exclude_sessions:
        placeholders = ",".join("?" * len(exclude_sessions))
        where += f" AND session_id NOT IN ({placeholders})"
        params.extend(exclude_sessions)

    rows = conn.execute(
        f"SELECT {_COST_COLS} FROM traces WHERE {where} ORDER BY timestamp",
        params,
    ).fetchall()

    if not rows:
        return CostOverview(
            total_sessions=0,
            total_cost=0.0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_cache_read_tokens=0,
            total_cache_creation_tokens=0,
            cache_hit_ratio=0.0,
            cost_without_cache=0.0,
            cache_savings=0.0,
            daily_burn_rate=0.0,
            projected_monthly=0.0,
            by_model=[],
            by_day=[],
        )

    # Totals
    total_cost = sum(_row_cost(r) for r in rows)
    total_no_cache = sum(_row_cost_without_cache(r) for r in rows)
    total_in = sum(r[_C["token_input"]] or 0 for r in rows)
    total_out = sum(r[_C["token_output"]] or 0 for r in rows)
    total_cr = sum(r[_C["token_cache_read"]] or 0 for r in rows)
    total_cc = sum(r[_C["token_cache_creation"]] or 0 for r in rows)

    # Burn rate
    active_days = max(1, days)
    daily_rate = total_cost / active_days

    # By model
    model_buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        model = r[_C["model"]] or "(unknown)"
        b = model_buckets.setdefault(
            model,
            {"cost": 0.0, "in": 0, "out": 0, "cr": 0, "cc": 0, "sessions": 0},
        )
        b["cost"] += _row_cost(r)
        b["in"] += r[_C["token_input"]] or 0
        b["out"] += r[_C["token_output"]] or 0
        b["cr"] += r[_C["token_cache_read"]] or 0
        b["cc"] += r[_C["token_cache_creation"]] or 0
        b["sessions"] += 1

    by_model = sorted(
        [
            ModelCost(
                model=m,
                cost=b["cost"],
                input_tokens=b["in"],
                output_tokens=b["out"],
                cache_read_tokens=b["cr"],
                cache_creation_tokens=b["cc"],
                cache_hit_ratio=_cache_hit_ratio(b["cr"], b["in"]),
                session_count=b["sessions"],
            )
            for m, b in model_buckets.items()
        ],
        key=lambda x: x.cost,
        reverse=True,
    )

    # By day
    day_buckets: dict[str, dict[str, Any]] = {}
    for r in rows:
        ts = r[_C["timestamp"]] or ""
        day = ts[:10]  # YYYY-MM-DD
        b = day_buckets.setdefault(
            day,
            {"cost": 0.0, "sessions": 0, "in": 0, "out": 0, "cr": 0, "cc": 0},
        )
        b["cost"] += _row_cost(r)
        b["sessions"] += 1
        b["in"] += r[_C["token_input"]] or 0
        b["out"] += r[_C["token_output"]] or 0
        b["cr"] += r[_C["token_cache_read"]] or 0
        b["cc"] += r[_C["token_cache_creation"]] or 0

    by_day = [
        DayCost(
            date=d,
            cost=b["cost"],
            sessions=b["sessions"],
            input_tokens=b["in"],
            output_tokens=b["out"],
            cache_read_tokens=b["cr"],
            cache_creation_tokens=b["cc"],
            cache_hit_ratio=_cache_hit_ratio(b["cr"], b["in"]),
        )
        for d, b in sorted(day_buckets.items())
    ]

    return CostOverview(
        total_sessions=len(rows),
        total_cost=total_cost,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_cache_read_tokens=total_cr,
        total_cache_creation_tokens=total_cc,
        cache_hit_ratio=_cache_hit_ratio(total_cr, total_in),
        cost_without_cache=total_no_cache,
        cache_savings=total_no_cache - total_cost,
        daily_burn_rate=daily_rate,
        projected_monthly=daily_rate * 30,
        by_model=by_model,
        by_day=by_day,
    )


def session_costs(
    conn: sqlite3.Connection,
    days: int = 7,
    agent: str | None = None,
    limit: int = 20,
    sort: str = "cost",
) -> list[SessionCost]:
    """Per-session cost breakdown, sorted by cost (most expensive first)."""
    where, params = _build_filter(days, agent)

    rows = conn.execute(
        f"SELECT {_COST_COLS} FROM traces WHERE {where}",
        params,
    ).fetchall()

    sessions: list[SessionCost] = []
    for r in rows:
        trace_id = r[_C["id"]]
        inp = r[_C["token_input"]] or 0
        out = r[_C["token_output"]] or 0
        cr = r[_C["token_cache_read"]] or 0
        cc = r[_C["token_cache_creation"]] or 0

        # Tool + error counts
        tool_row = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN error THEN 1 ELSE 0 END) "
            "FROM trace_tools WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        # SUM over zero rows returns NULL in SQLite, not 0. Guard both fields
        # so SessionCost.{tool_count,error_count} are always int.
        tool_count = (tool_row[0] if tool_row else 0) or 0
        error_count = (tool_row[1] if tool_row else 0) or 0

        sessions.append(
            SessionCost(
                trace_id=trace_id,
                task=(r[_C["task"]] or "")[:200],
                status=r[_C["status"]] or "completed",
                model=r[_C["model"]] or "",
                scope=r[_C["scope"]] or "",
                timestamp=r[_C["timestamp"]] or "",
                cost=_row_cost(r),
                input_tokens=inp,
                output_tokens=out,
                cache_read_tokens=cr,
                cache_creation_tokens=cc,
                cache_hit_ratio=_cache_hit_ratio(cr, inp),
                uncached_input_cost=_uncached_input_cost(r[_C["model"]] or "", inp),
                duration_ms=r[_C["duration_ms"]] or 0,
                turn_count=r[_C["turn_count"]] or 0,
                tool_count=tool_count,
                error_count=error_count,
            )
        )

    if sort == "cache":
        # "Cache pain" sort: surface the sessions paying the most full-rate
        # input first. cache_hit_ratio saturates at ~100% on healthy usage,
        # so an asc-by-ratio sort buries the actionable rows in noise.
        sessions.sort(key=lambda s: s.uncached_input_cost, reverse=True)
    elif sort == "time":
        sessions.sort(key=lambda s: s.timestamp, reverse=True)
    else:
        sessions.sort(key=lambda s: s.cost, reverse=True)

    return sessions[:limit]


def budget_status(
    conn: sqlite3.Connection,
    daily_budget: float,
) -> BudgetStatus:
    """Check today's spend against a daily budget."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    rows = conn.execute(
        f"SELECT {_COST_COLS} FROM traces WHERE DATE(timestamp) = ?",
        (today,),
    ).fetchall()

    spent = sum(_row_cost(r) for r in rows)
    remaining = max(0.0, daily_budget - spent)
    pct = (spent / daily_budget * 100) if daily_budget > 0 else 0.0

    # Project end-of-day based on current burn rate
    now = datetime.now(UTC)
    hours_elapsed = now.hour + now.minute / 60
    if hours_elapsed > 0:
        hourly_rate = spent / hours_elapsed
        projected_eod = hourly_rate * 24
    else:
        projected_eod = 0.0

    return BudgetStatus(
        daily_budget=daily_budget,
        spent_today=spent,
        remaining_today=remaining,
        pct_used=pct,
        on_track=spent <= daily_budget,
        projected_eod=projected_eod,
        sessions_today=len(rows),
    )


def has_tool_coverage(
    conn: sqlite3.Connection, days: int | None, agent: str | None
) -> bool:
    """True if any trace in the window has trace_tools rows.

    Caller-side use: the `error_storm` and `loop` anomaly classes are
    no-ops when the window's traces all came from `openflux backfill`
    (transcript-only path, no tool capture). The CLI / dashboard should
    surface that explanation instead of silently emitting zero anomalies.
    """
    # Build the filter against `t` (the traces alias) explicitly so the
    # window predicate doesn't collide with trace_tools' own timestamp col.
    clauses: list[str] = ["1=1"]
    params: list[Any] = []
    if days is not None:
        clauses.append("t.timestamp >= datetime('now', ? || ' days')")
        params.append(f"-{days}")
    if agent:
        clauses.append("t.agent = ?")
        params.append(agent)
    where = " AND ".join(clauses)
    row = conn.execute(
        f"SELECT 1 FROM trace_tools tt "
        f"JOIN traces t ON t.id = tt.trace_id "
        f"WHERE {where} LIMIT 1",
        params,
    ).fetchone()
    return row is not None


def detect_anomalies(
    conn: sqlite3.Connection,
    days: int = 7,
    agent: str | None = None,
) -> list[CostAnomaly]:
    """Detect cost anomalies: loops, cache misses, cost spikes, error storms.

    `loops` and `error_storms` require per-tool data in `trace_tools`;
    they're silently skipped if the window has no tool coverage. Call
    `has_tool_coverage(conn, days, agent)` first if the caller needs to
    explain that to the user.
    """
    where, params = _build_filter(days, agent)
    anomalies: list[CostAnomaly] = []

    rows = conn.execute(
        f"SELECT {_COST_COLS} FROM traces WHERE {where}",
        params,
    ).fetchall()

    if not rows:
        return anomalies

    # Compute stats for spike detection
    costs = [_row_cost(r) for r in rows]
    avg_cost = sum(costs) / len(costs) if costs else 0
    # Use 3x average as spike threshold (simple but effective)
    spike_threshold = avg_cost * 3 if avg_cost > 0 else 0

    for r in rows:
        trace_id = r[_C["id"]]
        cost = _row_cost(r)

        # 1. Cost spike: session costs 3x+ the average
        if spike_threshold > 0 and cost > spike_threshold and cost > 0.10:
            anomalies.append(
                CostAnomaly(
                    type="cost_spike",
                    severity="warning" if cost < avg_cost * 5 else "critical",
                    trace_id=trace_id,
                    description=(
                        f"${cost:.2f}, {cost / avg_cost:.0f}x the average "
                        f"session cost of ${avg_cost:.2f}"
                    ),
                    cost=cost,
                    details={"avg_cost": avg_cost, "multiplier": cost / avg_cost},
                )
            )

        # 2. Cache miss: session has 0% cache hits but significant tokens
        inp = r[_C["token_input"]] or 0
        cr = r[_C["token_cache_read"]] or 0
        if inp > 10000 and cr == 0:
            anomalies.append(
                CostAnomaly(
                    type="cache_miss",
                    severity="warning",
                    trace_id=trace_id,
                    description=(
                        f"{inp:,} input tokens with 0% cache hits; "
                        f"${cost:.2f} could be much lower"
                    ),
                    cost=cost,
                    details={"input_tokens": inp, "cache_read_tokens": 0},
                )
            )

        # 3. Error storm: session has high error rate in tool calls
        tool_row = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN error THEN 1 ELSE 0 END) "
            "FROM trace_tools WHERE trace_id = ?",
            (trace_id,),
        ).fetchone()
        if tool_row and tool_row[0] >= 5:
            total_tools = tool_row[0]
            errors = tool_row[1] or 0
            error_rate = errors / total_tools
            if error_rate >= 0.5:
                anomalies.append(
                    CostAnomaly(
                        type="error_storm",
                        severity="critical" if error_rate > 0.7 else "warning",
                        trace_id=trace_id,
                        description=(
                            f"{errors}/{total_tools} tool calls failed "
                            f"({error_rate:.0%}); ${cost:.2f} likely wasted"
                        ),
                        cost=cost,
                        details={
                            "total_tools": total_tools,
                            "errors": errors,
                            "error_rate": error_rate,
                        },
                    )
                )

        # 4. Loop detection: same tool called 5+ times in a row
        _detect_loops(conn, trace_id, cost, anomalies)

    # Sort by cost impact (most expensive anomalies first)
    anomalies.sort(key=lambda a: a.cost, reverse=True)
    return anomalies


def _detect_loops(
    conn: sqlite3.Connection,
    trace_id: str,
    cost: float,
    anomalies: list[CostAnomaly],
) -> None:
    """Detect tool call loops within a session (same tool called repeatedly)."""
    tool_rows = conn.execute(
        "SELECT name, tool_input FROM trace_tools "
        "WHERE trace_id = ? ORDER BY timestamp",
        (trace_id,),
    ).fetchall()

    if len(tool_rows) < 5:
        return

    # Count consecutive runs of the same tool+input
    max_run = 1
    current_run = 1
    loop_tool = ""
    for i in range(1, len(tool_rows)):
        prev_name, prev_input = tool_rows[i - 1]
        curr_name, curr_input = tool_rows[i]
        if curr_name == prev_name and curr_input == prev_input:
            current_run += 1
            if current_run > max_run:
                max_run = current_run
                loop_tool = curr_name
        else:
            current_run = 1

    if max_run >= 4:
        anomalies.append(
            CostAnomaly(
                type="loop",
                severity="critical" if max_run >= 6 else "warning",
                trace_id=trace_id,
                description=(
                    f"{loop_tool} called {max_run}x consecutively "
                    f"with identical input; agent stuck in a loop"
                ),
                cost=cost,
                details={"tool": loop_tool, "consecutive_calls": max_run},
            )
        )

    # Also detect repeated commands (not necessarily consecutive)
    cmd_counts: dict[str, int] = {}
    for name, inp in tool_rows:
        key = f"{name}:{(inp or '')[:100]}"
        cmd_counts[key] = cmd_counts.get(key, 0) + 1

    for key, count in cmd_counts.items():
        if count >= 5:
            tool_name = key.split(":")[0]
            # Avoid double-reporting if already caught as consecutive loop
            if tool_name == loop_tool and max_run >= 4:
                continue
            anomalies.append(
                CostAnomaly(
                    type="loop",
                    severity="warning",
                    trace_id=trace_id,
                    description=(
                        f"{tool_name} called {count}x with same input "
                        f"within session, possible retry loop"
                    ),
                    cost=cost,
                    details={"tool": tool_name, "repeat_count": count},
                )
            )
