from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from openflux.sinks.sqlite import SQLiteSink

DEFAULT_DB_PATH = Path.home() / ".openflux" / "traces.db"


def _hook_cmd(subcommand: str) -> str:
    return f"{sys.executable} -m openflux.adapters._claude_code {subcommand}"


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
    return text[: max_len - 1] + "…"


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
    print("  ".join("─" * w for w in widths))

    for row in rows:
        line = "  ".join(
            (row[i] if i < len(row) else "").ljust(widths[i])
            for i in range(len(headers))
        )
        print(line)


def _get_sink() -> SQLiteSink:
    db_path = _require_db()
    return SQLiteSink(path=db_path)


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


def cmd_status(args: argparse.Namespace) -> None:
    db_path = _get_db_path()

    print(f"DB path:    {db_path}")

    if not db_path.exists():
        print("Status:     No database (run an adapter to start collecting)")
        return

    size_bytes = db_path.stat().st_size
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    print(f"DB size:    {size_str}")

    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM traces")
        total = cur.fetchone()[0]
        print(f"Total:      {total} trace(s)")

        if total == 0:
            return

        cur.execute("SELECT MAX(timestamp) FROM traces")
        latest = cur.fetchone()[0]
        print(f"Latest:     {latest} ({_relative_time(latest)})")

        cur.execute(
            "SELECT agent, COUNT(*) FROM traces GROUP BY agent ORDER BY COUNT(*) DESC"
        )
        agent_rows = cur.fetchall()
        if agent_rows:
            print("\nBy agent:")
            for agent, count in agent_rows:
                print(f"  {agent}: {count}")

        cur.execute(
            "SELECT status, COUNT(*) FROM traces GROUP BY status ORDER BY COUNT(*) DESC"
        )
        status_rows = cur.fetchall()
        if status_rows:
            print("\nBy status:")
            for status, count in status_rows:
                print(f"  {status}: {count}")

    finally:
        conn.close()


def cmd_install(args: argparse.Namespace) -> None:
    if args.list:
        print("Available adapters:")
        for name, desc in AVAILABLE_ADAPTERS.items():
            print(f"  {name:20s} {desc}")
        return

    if args.adapter != "claude-code":
        print(f"Adapter '{args.adapter}' is installed via Python API, not CLI.")
        print("See: https://github.com/advitrocks9/openflux#adapters")
        return

    _install_claude_code()


def _hook_exists(event_hooks: list[Any], command: str) -> bool:
    for group in event_hooks:
        if not isinstance(group, dict):
            continue
        for h in cast(list[Any], group.get("hooks", [])):
            if isinstance(h, dict) and h.get("command") == command:
                return True
    return False


def _install_claude_code() -> None:
    settings_path = Path.home() / ".claude" / "settings.json"

    if settings_path.exists():
        settings: dict[str, Any] = json.loads(settings_path.read_text())
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
            print(f"  ✓ {name}")
    if skipped:
        print("\nAlready configured:")
        for name in skipped:
            print(f"  · {name}")
    if not added and not skipped:
        print("No hooks to add.")

    print("\nOpenFlux will now capture Claude Code telemetry.")


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
    p_export.add_argument(
        "--format", default="json", help="Output format (default: json)"
    )
    p_export.add_argument("--agent", help="Filter by agent name")
    p_export.add_argument(
        "--since", help="ISO timestamp, export traces after this time"
    )
    p_export.set_defaults(func=cmd_export)

    p_status = subs.add_parser("status", help="Show database status")
    p_status.set_defaults(func=cmd_status)

    p_install = subs.add_parser("install", help="Install an adapter")
    p_install.add_argument(
        "adapter", nargs="?", default="", help="Adapter name (e.g., claude-code)"
    )
    p_install.add_argument(
        "--list", action="store_true", help="List available adapters"
    )
    p_install.set_defaults(func=cmd_install)

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
