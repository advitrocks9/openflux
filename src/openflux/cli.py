from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from openflux._pricing import estimate_cost as _estimate_cost_full
from openflux.sinks.sqlite import SQLiteSink
from openflux.waste import EfficiencyReport, SessionReplay

DEFAULT_DB_PATH = Path.home() / ".openflux" / "traces.db"


def _hook_cmd(subcommand: str) -> str:
    return f"{sys.executable} -m openflux.adapters.claude_code {subcommand}"


CLAUDE_CODE_HOOKS: dict[str, str] = {
    "SessionStart": _hook_cmd("session_start"),
    "PostToolUse": _hook_cmd("post_tool_use"),
    "PostToolUseFailure": _hook_cmd("post_tool_use_failure"),
    "SubagentStart": _hook_cmd("subagent_start"),
    "Stop": _hook_cmd("session_end"),
    "SessionEnd": _hook_cmd("session_end"),
}

AVAILABLE_ADAPTERS: dict[str, str] = {
    "claude-code": "Claude Code hooks (auto-configures ~/.claude/settings.json)",
    "openai-agents": "OpenAI Agents SDK TracingProcessor (use Python API)",
    "langchain": "LangChain BaseCallbackHandler (use Python API)",
    "claude-agent-sdk": "Claude Agent SDK hooks (use Python API)",
    "autogen": "AutoGen v0.4 stream consumer (use Python API)",
    "crewai": "CrewAI event listener (use Python API)",
    "google-adk": "Google ADK callbacks (use Python API)",
    "mcp": "MCP server adapter (use Python API)",
    "bedrock": "Amazon Bedrock event processor (use Python API)",
}


def _get_db_path() -> Path:
    env = os.environ.get("OPENFLUX_DB_PATH", "")
    if env.strip():
        return Path(env)
    return DEFAULT_DB_PATH


def _require_db() -> Path:
    db_path = _get_db_path()
    if not db_path.exists():
        print(f"No database found at {db_path}", file=sys.stderr)
        print("Run an adapter first to start collecting traces.", file=sys.stderr)
        print("  Tip: openflux install claude-code", file=sys.stderr)
        sys.exit(1)
    return db_path


def _relative_time(iso_timestamp: str) -> str:
    try:
        ts = iso_timestamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        now = datetime.now(UTC)
        delta = now - dt
        seconds = int(delta.total_seconds())
    except (ValueError, TypeError):
        return iso_timestamp

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        mins = seconds // 60
        return f"{mins}m ago"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours}h ago"
    days = seconds // 86400
    return f"{days}d ago"


def _truncate(text: str, max_len: int = 50) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("No traces found.")
        return

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    header_line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(header_line)
    print("  ".join("\u2500" * w for w in widths))

    for row in rows:
        line = "  ".join(
            (row[i] if i < len(row) else "").ljust(widths[i])
            for i in range(len(headers))
        )
        print(line)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int = 0,
    cache_creation: int = 0,
) -> float:
    return _estimate_cost_full(
        model, input_tokens, output_tokens, cache_read, cache_creation
    )


def _bar(value: int, max_value: int, width: int = 12) -> str:
    """Render a proportional bar using block characters."""
    if max_value <= 0:
        return ""
    filled = max(1, round(value / max_value * width))
    return "\u2588" * filled


def _get_sink() -> SQLiteSink:
    db_path = _require_db()
    return SQLiteSink(path=db_path)


def _parse_duration(spec: str) -> int:
    """Parse '30d' into number of days. Only supports 'd' suffix."""
    match = re.fullmatch(r"(\d+)d", spec)
    if not match:
        print(f"Invalid duration: '{spec}'. Use format: 30d", file=sys.stderr)
        sys.exit(1)
    return int(match.group(1))


# ── recent ──────────────────────────────────────────────────────────────


def cmd_recent(args: argparse.Namespace) -> None:
    sink = _get_sink()
    try:
        traces = sink.recent(
            limit=args.limit,
            agent=args.agent,
            scope=args.scope,
        )
    finally:
        sink.close()

    rows: list[list[str]] = []
    for r in traces:
        rows.append(
            [
                r.id,
                _relative_time(r.timestamp),
                _truncate(r.agent, 20),
                _truncate(r.task, 40),
                r.status,
            ]
        )

    _print_table(["ID", "WHEN", "AGENT", "TASK", "STATUS"], rows)
    print(f"\n{len(traces)} trace(s) shown.")


# ── search ──────────────────────────────────────────────────────────────


def cmd_search(args: argparse.Namespace) -> None:
    sink = _get_sink()
    try:
        traces = sink.search(args.query, limit=args.limit)
    finally:
        sink.close()

    rows: list[list[str]] = []
    for r in traces:
        rows.append(
            [
                r.id,
                _relative_time(r.timestamp),
                _truncate(r.agent, 20),
                _truncate(r.task, 40),
                r.status,
            ]
        )

    _print_table(["ID", "WHEN", "AGENT", "TASK", "STATUS"], rows)
    print(f"\n{len(traces)} result(s) for '{args.query}'.")


# ── trace ───────────────────────────────────────────────────────────────


def _format_record_list(label: str, records: list[Any]) -> None:
    if not records:
        return
    print(f"\n  {label} ({len(records)}):")
    for i, rec in enumerate(records, 1):
        fields: dict[str, Any] = {k: getattr(rec, k) for k in rec.__dataclass_fields__}
        non_empty = {k: v for k, v in fields.items() if v}
        parts = [f"{k}={v!r}" for k, v in non_empty.items()]
        print(f"    [{i}] {', '.join(parts)}")


def cmd_trace(args: argparse.Namespace) -> None:
    sink = _get_sink()
    try:
        trace = sink.get(args.trace_id)
    finally:
        sink.close()

    if trace is None:
        print(f"Trace '{args.trace_id}' not found.", file=sys.stderr)
        sys.exit(1)

    print(f"Trace: {trace.id}")
    print(f"  timestamp:    {trace.timestamp}")
    print(f"  agent:        {trace.agent}")
    print(f"  session_id:   {trace.session_id}")
    if trace.parent_id:
        print(f"  parent_id:    {trace.parent_id}")
    print(f"  model:        {trace.model or '(none)'}")
    print(f"  status:       {trace.status}")
    print(f"  scope:        {trace.scope or '(none)'}")
    if trace.tags:
        print(f"  tags:         {', '.join(trace.tags)}")
    print(f"  turn_count:   {trace.turn_count}")
    print(f"  duration_ms:  {trace.duration_ms}")
    print(f"  schema:       {trace.schema_version}")

    if trace.token_usage:
        tu = trace.token_usage
        print("\n  Token Usage:")
        print(f"    input:          {tu.input_tokens:,}")
        print(f"    output:         {tu.output_tokens:,}")
        if tu.cache_read_tokens:
            print(f"    cache_read:     {tu.cache_read_tokens:,}")
        if tu.cache_creation_tokens:
            print(f"    cache_creation: {tu.cache_creation_tokens:,}")

    if trace.task:
        print(f"\n  Task:\n    {trace.task}")
    if trace.decision:
        print(f"\n  Decision:\n    {trace.decision}")
    if trace.correction:
        print(f"\n  Correction:\n    {trace.correction}")

    if trace.files_modified:
        print(f"\n  Files Modified ({len(trace.files_modified)}):")
        for f in trace.files_modified:
            print(f"    {f}")

    _format_record_list("Context", trace.context)
    _format_record_list("Searches", trace.searches)
    _format_record_list("Sources Read", trace.sources_read)
    _format_record_list("Tools Used", trace.tools_used)

    if trace.metadata:
        print("\n  Metadata:")
        print(f"    {json.dumps(trace.metadata, indent=4, default=str)}")


# ── export ──────────────────────────────────────────────────────────────


def cmd_export(args: argparse.Namespace) -> None:
    sink = _get_sink()
    try:
        traces = sink.recent(
            limit=10_000,
            agent=args.agent or None,
            since=args.since or None,
        )
    finally:
        sink.close()

    for trace in traces:
        print(json.dumps(trace.to_dict(), default=str))


# ── status ──────────────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> None:
    db_path = _get_db_path()

    print(f"DB path:    {db_path}")

    if not db_path.exists():
        print("Status:     No database (run an adapter to start collecting)")
        return

    print(f"DB size:    {_format_size(db_path.stat().st_size)}")

    sink = SQLiteSink(path=db_path)
    try:
        conn = sink.conn
        _print_status_counts(conn)
        _print_status_tokens(conn)
    finally:
        sink.close()


def _print_status_counts(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
    print(f"Total:      {total} trace(s)")

    if total == 0:
        return

    latest = conn.execute("SELECT MAX(timestamp) FROM traces").fetchone()[0]
    print(f"Latest:     {latest} ({_relative_time(latest)})")

    agent_rows = conn.execute(
        "SELECT agent, COUNT(*) FROM traces GROUP BY agent ORDER BY COUNT(*) DESC"
    ).fetchall()
    if agent_rows:
        print("\nBy agent:")
        for agent, count in agent_rows:
            print(f"  {agent}: {count}")

    status_rows = conn.execute(
        "SELECT status, COUNT(*) FROM traces GROUP BY status ORDER BY COUNT(*) DESC"
    ).fetchall()
    if status_rows:
        print("\nBy status:")
        for status, count in status_rows:
            print(f"  {status}: {count}")


def _print_status_tokens(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT COALESCE(SUM(token_input), 0), COALESCE(SUM(token_output), 0) "
        "FROM traces"
    ).fetchone()
    total_in, total_out = row[0], row[1]
    if total_in == 0 and total_out == 0:
        return

    # Estimate cost across all models
    model_rows = conn.execute(
        "SELECT model, SUM(token_input), SUM(token_output), "
        "SUM(token_cache_read), SUM(token_cache_creation) "
        "FROM traces GROUP BY model"
    ).fetchall()
    total_cost = sum(
        _estimate_cost(m or "", ti or 0, to or 0, cr or 0, cc or 0)
        for m, ti, to, cr, cc in model_rows
    )

    print("\nToken usage (all time):")
    print(f"  Input:      {total_in:>12,} tokens")
    print(f"  Output:     {total_out:>12,} tokens")
    print(f"  Est. cost:  ${total_cost:,.2f}")


# ── cost ────────────────────────────────────────────────────────────────


def cmd_cost(args: argparse.Namespace) -> None:
    sink = _get_sink()
    try:
        days: int = args.days
        agent: str | None = args.agent or None

        summary = sink.token_summary(days=days, agent=agent)
        by_model = sink.token_by_model(days=days, agent=agent)
        by_agent = sink.token_by_agent(days=days, agent=agent)
        by_day = sink.token_by_day(days=days, agent=agent)
    finally:
        sink.close()

    _print_cost_header(days, summary)
    _print_cost_by_model(by_model)
    _print_cost_by_agent(by_agent)
    _print_cost_by_day(by_day)


def _print_cost_header(days: int, summary: dict[str, Any]) -> None:
    print(f"Token Usage (last {days} days)")
    print("\u2500" * 45)
    print(f"  Traces:     {summary['traces']:,}")
    print(f"  Input:      {summary['input']:>12,} tokens")
    print(f"  Output:     {summary['output']:>12,} tokens")
    print(f"  Total:      {summary['total']:>12,} tokens")

    # Cost needs per-model breakdown to apply correct rates
    # but we can estimate from total with a simple heuristic
    # (the by-model section will show accurate per-model costs)


def _print_cost_by_model(by_model: list[dict[str, Any]]) -> None:
    if not by_model:
        return
    print("\nBy model:")
    for row in by_model:
        total = row["input"] + row["output"]
        cost = _estimate_cost(
            row["model"],
            row["input"],
            row["output"],
            row.get("cache_read", 0),
            row.get("cache_creation", 0),
        )
        print(f"  {row['model']:30s} {total:>12,} tokens  ${cost:,.2f}")


def _print_cost_by_agent(by_agent: list[dict[str, Any]]) -> None:
    if not by_agent:
        return
    print("\nBy agent:")
    for row in by_agent:
        total = row["input"] + row["output"]
        print(f"  {row['agent']:30s} {row['traces']:>4} traces {total:>12,} tokens")


def _print_cost_by_day(by_day: list[dict[str, Any]]) -> None:
    if not by_day:
        return
    max_total = max((r["input"] + r["output"]) for r in by_day)

    print("\nDaily breakdown:")
    for row in by_day:
        total = row["input"] + row["output"]
        bar = _bar(total, max_total)
        # Format date as "Mar 27" style
        try:
            dt = datetime.strptime(row["date"], "%Y-%m-%d")
            label = dt.strftime("%b %d")
        except (ValueError, TypeError):
            label = str(row["date"])
        print(f"  {label}  {bar:12s}  {row['traces']:>3} traces {total:>12,} tokens")


# ── forget ──────────────────────────────────────────────────────────────


def cmd_forget(args: argparse.Namespace) -> None:
    if args.agent:
        _forget_by_agent(args.agent)
    elif args.trace_id:
        _forget_single(args.trace_id)
    else:
        print("Provide a trace ID or --agent flag.", file=sys.stderr)
        sys.exit(1)


def _forget_single(trace_id: str) -> None:
    sink = _get_sink()
    try:
        deleted = sink.forget(trace_id)
    finally:
        sink.close()
    if deleted:
        print(f"Deleted trace {trace_id}")
    else:
        print(f"Trace not found: {trace_id}")


def _forget_by_agent(agent: str) -> None:
    sink = _get_sink()
    try:
        count = sink.count_by_agent(agent)
        if count == 0:
            print(f"No traces found for agent '{agent}'")
            return

        response = input(f"Delete {count} traces for agent '{agent}'? [y/N] ")
        if response.strip().lower() != "y":
            print("Cancelled.")
            return

        deleted = sink.forget_by_agent(agent)
        print(f"Deleted {deleted} traces for agent '{agent}'")
    finally:
        sink.close()


# ── prune ───────────────────────────────────────────────────────────────


def cmd_prune(args: argparse.Namespace) -> None:
    days = _parse_duration(args.older_than)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()
    agent: str | None = args.agent or None

    sink = _get_sink()
    try:
        db_path = sink.path
        before_size = db_path.stat().st_size

        count = sink.count_before(cutoff_iso, agent=agent)
        if count == 0:
            print("No matching traces to prune.")
            return

        cutoff_display = cutoff.strftime("%Y-%m-%d")
        response = input(f"Delete {count} traces older than {cutoff_display}? [y/N] ")
        if response.strip().lower() != "y":
            print("Cancelled.")
            return

        deleted = sink.prune(cutoff_iso, agent=agent)
        after_size = db_path.stat().st_size
        print(
            f"Deleted {deleted} traces. "
            f"DB size: {_format_size(before_size)} -> {_format_size(after_size)}"
        )
    finally:
        sink.close()


# ── install ─────────────────────────────────────────────────────────────


def cmd_install(args: argparse.Namespace) -> None:
    if args.list:
        print("Available adapters:")
        for name, desc in AVAILABLE_ADAPTERS.items():
            print(f"  {name:20s} {desc}")
        return

    if not args.adapter:
        print("Usage: openflux install <adapter>")
        print("       openflux install --list")
        print("\nRun 'openflux install --list' to see available adapters.")
        return

    if args.adapter != "claude-code":
        print(f"Adapter '{args.adapter}' is installed via Python API, not CLI.")
        print("See: https://github.com/advitrocks9/openflux#adapter-status")
        return

    _install_claude_code()


def _hook_exists(event_hooks: list[dict[str, Any]], command: str) -> bool:
    for group in event_hooks:
        hooks: list[dict[str, Any]] = group.get("hooks", [])
        for h in hooks:
            if h.get("command") == command:
                return True
    return False


def _install_claude_code() -> None:
    settings_path = Path.home() / ".claude" / "settings.json"

    if settings_path.exists():
        try:
            settings: dict[str, Any] = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            print(f"Error: {settings_path} contains invalid JSON.", file=sys.stderr)
            print(
                "Fix the file manually or delete it and re-run this command.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings = {}

    hooks: dict[str, Any] = settings.setdefault("hooks", {})
    added: list[str] = []
    skipped: list[str] = []

    for event_name, command in CLAUDE_CODE_HOOKS.items():
        event_hooks: list[Any] = hooks.setdefault(event_name, [])

        if _hook_exists(event_hooks, command):
            skipped.append(event_name)
            continue

        event_hooks.append(
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": command}],
            }
        )
        added.append(event_name)

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    if added:
        print(f"Added hooks to {settings_path}:")
        for name in added:
            print(f"  \u2713 {name}")
    if skipped:
        print("\nAlready configured:")
        for name in skipped:
            print(f"  \u00b7 {name}")
    if not added and not skipped:
        print("No hooks to add.")

    print("\nOpenFlux will now capture Claude Code telemetry.")


def cmd_serve(args: argparse.Namespace) -> None:
    from openflux.serve import serve

    db = getattr(args, "db", None)
    serve(port=args.port, db_path=db)


# ── waste ──────────────────────────────────────────────────────────────


def cmd_waste(args: argparse.Namespace) -> None:
    from openflux.waste import analyze_efficiency

    sink = _get_sink()
    try:
        report = analyze_efficiency(sink.conn, days=args.days, agent=args.agent)
    finally:
        sink.close()

    _print_efficiency(report, args.days)


def _print_efficiency(r: EfficiencyReport, days: int) -> None:
    print(f"Tool Efficiency \u2014 last {days} days")
    print("\u2550" * 55)
    print()
    print(f"  Sessions:    {r.total_sessions}")
    print(f"  Tool calls:  {r.total_tool_calls:,}")
    print(f"  Est. cost:   ${r.total_cost:,.2f}")

    # Bash breakdown — what is the agent actually using Bash for
    if r.bash_breakdown:
        print()
        print("  What Bash is used for:")
        print("  " + "\u2500" * 53)
        for cat in r.bash_breakdown[:12]:
            bar_w = int(cat.pct * 0.3)
            bar = "\u2588" * bar_w if bar_w > 0 else ""
            print(f"    {cat.name:<28s} {cat.calls:>5,}  ({cat.pct:>4.1f}%)  {bar}")

    # Overhead
    if r.overhead_calls > 0:
        print()
        print(f"  Agent overhead:  {r.overhead_calls:,} calls  ({r.overhead_pct:.1f}%)")
        print("  " + "\u2500" * 53)
        print("  TaskCreate, ToolSearch, SendMessage, etc.")

    # Redundancy
    if r.total_redundant_calls > 0:
        print()
        print(
            f"  Redundant calls: {r.total_redundant_calls:,}"
            f"  ({r.redundancy_pct:.1f}% of all tool calls)"
        )
        print("  " + "\u2500" * 53)
        print("  Same command repeated in a session without changes between.")
        for pat in r.redundant_patterns[:8]:
            print(
                f"    {pat.pattern:<28s} {pat.redundant_calls:>4}"
                f" redundant / {pat.total_calls} total"
            )

    print()
    print("Run `openflux replay <id>` to see any session's tool sequence.")


# ── replay ─────────────────────────────────────────────────────────────


def cmd_replay(args: argparse.Namespace) -> None:
    from openflux.waste import replay_session

    sink = _get_sink()
    try:
        replay = replay_session(sink.conn, args.trace_id)
    finally:
        sink.close()

    if replay is None:
        print(f"Trace not found: {args.trace_id}", file=sys.stderr)
        sys.exit(1)

    _print_replay(replay)


def _fmt_duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    secs = ms / 1000
    if secs < 60:
        return f"{secs:.0f}s"
    mins = secs / 60
    return f"{mins:.0f}m"


def _print_replay(s: SessionReplay) -> None:
    dur = _fmt_duration(s.duration_ms)
    print(f'{s.trace_id} \u2014 "{s.task[:60]}"')
    print(
        f"{s.status} | {s.turn_count} turns | ${s.total_cost:.2f} | {dur} | {s.model}"
    )
    print("\u2500" * 65)

    # Tool sequence
    for step in s.tools:
        mark = "\u2717" if step.error else "\u2713"
        target = step.target[:45] if step.target else ""
        summary = step.output_summary
        suffix = f"  {summary}" if summary else ""
        print(f"  {step.index:>3}  {step.name:<14s} {target:<45s} {mark}{suffix}")

    # Per-session breakdown
    if s.tool_breakdown:
        print()
        print("  Breakdown:")
        for cat in s.tool_breakdown[:10]:
            print(f"    {cat.name:<30s} {cat.calls:>4}  ({cat.pct:.0f}%)")

    # Per-session redundancy
    if s.redundant_in_session:
        print()
        print("  Repeated calls:")
        for pat in s.redundant_in_session[:5]:
            print(
                f"    {pat.pattern:<30s} {pat.redundant_calls}"
                f" redundant / {pat.total_calls} total"
            )

    print()
    print(f"  Total cost: ${s.total_cost:.2f}")


# ── digest ─────────────────────────────────────────────────────────────


def cmd_digest(args: argparse.Namespace) -> None:
    from openflux.waste import analyze_efficiency

    sink = _get_sink()
    try:
        days: int = 7 if args.weekly else 1 if args.daily else 7
        report = analyze_efficiency(sink.conn, days=days, agent=args.agent)

        top = sink.conn.execute(
            "SELECT id, task, status, "
            "(token_input * 15.0 + token_output * 75.0 "
            "+ token_cache_read * 1.5 + token_cache_creation * 18.75) "
            "/ 1000000.0 as cost "
            "FROM traces "
            "WHERE timestamp >= datetime('now', ? || ' days') "
            + ("AND agent = ? " if args.agent else "")
            + "ORDER BY cost DESC LIMIT 5",
            ([f"-{days}"] + ([args.agent] if args.agent else [])),
        ).fetchall()
    finally:
        sink.close()

    period = "today" if days == 1 else f"last {days} days"
    print(f"OpenFlux Digest \u2014 {period}")
    print("\u2550" * 45)
    print(
        f"\n  {report.total_sessions} sessions"
        f" | {report.total_tool_calls:,} tool calls"
        f" | ${report.total_cost:,.2f}"
    )

    if report.overhead_pct > 0:
        print(f"  Overhead: {report.overhead_pct:.1f}%")
    if report.redundancy_pct > 0:
        print(f"  Redundancy: {report.redundancy_pct:.1f}%")

    if top:
        print("\n  Most expensive sessions:")
        for trace_id, task, status, cost in top:
            task_short = (task or "")[:50]
            mark = "\u2717" if status == "error" else "\u2713"
            print(f"    {mark} ${cost:>6.2f}  {trace_id}  {task_short}")

    print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openflux",
        description="OpenFlux - open standard for AI agent telemetry",
    )
    subs = parser.add_subparsers(dest="command")

    p_recent = subs.add_parser("recent", help="Show recent traces")
    p_recent.add_argument("--agent", help="Filter by agent name")
    p_recent.add_argument(
        "--limit", type=int, default=10, help="Max results (default: 10)"
    )
    p_recent.add_argument("--scope", help="Filter by scope")
    p_recent.set_defaults(func=cmd_recent)

    p_search = subs.add_parser("search", help="Full-text search across traces")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument(
        "--limit", type=int, default=10, help="Max results (default: 10)"
    )
    p_search.set_defaults(func=cmd_search)

    p_trace = subs.add_parser("trace", help="Show full trace detail")
    p_trace.add_argument("trace_id", help="Trace ID (e.g., trc-a1b2c3d4e5f6)")
    p_trace.set_defaults(func=cmd_trace)

    p_export = subs.add_parser("export", help="Export traces as NDJSON")
    p_export.add_argument("--agent", help="Filter by agent name")
    p_export.add_argument(
        "--since", help="ISO timestamp, export traces after this time"
    )
    p_export.set_defaults(func=cmd_export)

    p_status = subs.add_parser("status", help="Show database status")
    p_status.set_defaults(func=cmd_status)

    p_cost = subs.add_parser("cost", help="Show token spend analysis")
    p_cost.add_argument(
        "--days", type=int, default=7, help="Lookback window in days (default: 7)"
    )
    p_cost.add_argument("--agent", help="Filter by agent name")
    p_cost.set_defaults(func=cmd_cost)

    p_forget = subs.add_parser("forget", help="Delete traces")
    p_forget.add_argument("trace_id", nargs="?", default="", help="Trace ID to delete")
    p_forget.add_argument("--agent", help="Delete all traces for an agent")
    p_forget.set_defaults(func=cmd_forget)

    p_prune = subs.add_parser("prune", help="Delete old traces")
    p_prune.add_argument(
        "--older-than", required=True, help="Duration threshold (e.g., 30d)"
    )
    p_prune.add_argument("--agent", help="Scope to a specific agent")
    p_prune.set_defaults(func=cmd_prune)

    p_install = subs.add_parser("install", help="Install an adapter")
    p_install.add_argument(
        "adapter", nargs="?", default="", help="Adapter name (e.g., claude-code)"
    )
    p_install.add_argument(
        "--list", action="store_true", help="List available adapters"
    )
    p_install.set_defaults(func=cmd_install)

    p_serve = subs.add_parser("serve", help="Start local trace explorer UI")
    p_serve.add_argument("--port", type=int, default=5173, help="Port (default: 5173)")
    p_serve.add_argument("--db", help="Path to SQLite database")
    p_serve.set_defaults(func=cmd_serve)

    p_waste = subs.add_parser("waste", help="Analyze wasted spend")
    p_waste.add_argument(
        "--days", type=int, default=30, help="Lookback window (default: 30)"
    )
    p_waste.add_argument("--agent", help="Filter by agent name")
    p_waste.set_defaults(func=cmd_waste)

    p_replay = subs.add_parser("replay", help="Replay a session's tool sequence")
    p_replay.add_argument("trace_id", help="Trace ID to replay")
    p_replay.set_defaults(func=cmd_replay)

    p_digest = subs.add_parser("digest", help="Weekly/daily spending digest")
    p_digest.add_argument("--weekly", action="store_true", help="Last 7 days")
    p_digest.add_argument("--daily", action="store_true", help="Today only")
    p_digest.add_argument("--agent", help="Filter by agent name")
    p_digest.set_defaults(func=cmd_digest)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
