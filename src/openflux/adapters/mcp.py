"""MCP server adapter - exposes OpenFlux via MCP tools and resources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openflux._util import generate_session_id, generate_trace_id, utc_now
from openflux.schema import (
    ContextRecord,
    SearchRecord,
    SourceRecord,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

try:
    import mcp.server.fastmcp  # noqa: F401

    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False

_DEFAULT_RECENT_LIMIT = 10
_DEFAULT_SEARCH_LIMIT = 10


def _parse_records[T](items: list[dict[str, Any]] | None, cls: type[T]) -> list[T]:
    """Convert list of dicts into typed dataclass instances."""
    if not items:
        return []
    return [cls(**item) for item in items]


def _build_token_usage(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_creation_tokens: int,
) -> TokenUsage | None:
    """Build TokenUsage if any value is non-zero."""
    if input_tokens or output_tokens or cache_read_tokens or cache_creation_tokens:
        return TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        )
    return None


def _get_sink(db_path: Path | str | None = None) -> Any:
    from openflux.sinks.sqlite import SQLiteSink

    return SQLiteSink(path=db_path)


def _trace_to_summary(trace: Trace) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": trace.id,
        "timestamp": trace.timestamp,
        "agent": trace.agent,
        "session_id": trace.session_id,
        "status": trace.status,
    }
    if trace.model:
        d["model"] = trace.model
    if trace.task:
        d["task"] = trace.task
    if trace.decision:
        d["decision"] = trace.decision
    if trace.scope:
        d["scope"] = trace.scope
    if trace.tags:
        d["tags"] = trace.tags
    if trace.tools_used:
        d["tools_used"] = [t.name for t in trace.tools_used]
    if trace.files_modified:
        d["files_modified"] = trace.files_modified
    if trace.token_usage:
        d["token_usage"] = {
            "input_tokens": trace.token_usage.input_tokens,
            "output_tokens": trace.token_usage.output_tokens,
        }
    if trace.duration_ms:
        d["duration_ms"] = trace.duration_ms
    if trace.parent_id:
        d["parent_id"] = trace.parent_id
    if trace.correction:
        d["correction"] = trace.correction
    if trace.turn_count:
        d["turn_count"] = trace.turn_count
    return d


class MCPServerAdapter:
    """MCP server exposing trace_record, trace_search tools and trace:// resources."""

    def __init__(
        self,
        agent: str = "mcp",
        db_path: Path | str | None = None,
        name: str = "OpenFlux",
    ) -> None:
        if not _HAS_MCP:
            msg = "MCP SDK not installed. Install with: pip install openflux[mcp]"
            raise ImportError(msg)

        from mcp.server.fastmcp import FastMCP

        self._agent = agent
        self._db_path = db_path
        self._server = FastMCP(name)
        self._register_tools()
        self._register_resources()

    @property
    def server(self) -> Any:
        return self._server

    def run(self, transport: str = "stdio", **kwargs: Any) -> None:
        self._server.run(transport=transport, **kwargs)

    def _register_tools(self) -> None:
        @self._server.tool()
        def trace_record(
            task: str,
            decision: str = "",
            agent: str = "",
            model: str = "",
            status: str = "completed",
            scope: str = "",
            tags: list[str] | None = None,
            files_modified: list[str] | None = None,
            correction: str = "",
            duration_ms: int = 0,
            metadata: dict[str, Any] | None = None,
            session_id: str = "",
            parent_id: str = "",
            input_tokens: int = 0,
            output_tokens: int = 0,
            cache_read_tokens: int = 0,
            cache_creation_tokens: int = 0,
            tools_used: list[dict[str, Any]] | None = None,
            context: list[dict[str, Any]] | None = None,
            searches: list[dict[str, Any]] | None = None,
            sources_read: list[dict[str, Any]] | None = None,
            turn_count: int = 0,
        ) -> str:
            """Record what the agent just did. Creates and stores a Trace.

            Args:
                task: What the agent was trying to do.
                decision: What the agent decided or concluded.
                agent: Agent identifier (defaults to server agent name).
                model: Model used (e.g. claude-sonnet-4-20250514).
                status: completed | error | timeout | cancelled.
                scope: Logical grouping (e.g. "refactor", "debug").
                tags: Freeform tags for categorization.
                files_modified: Paths modified during this action.
                correction: If the agent corrected itself, what changed.
                duration_ms: How long the action took.
                metadata: Arbitrary key-value pairs.
                session_id: Session to associate with (auto-generated if empty).
                parent_id: Parent trace ID for linking sub-traces.
                input_tokens: LLM input tokens consumed.
                output_tokens: LLM output tokens generated.
                cache_read_tokens: Tokens read from prompt cache.
                cache_creation_tokens: Tokens written to prompt cache.
                tools_used: Tool calls as dicts (keys: name,
                    tool_input, tool_output, duration_ms, error).
                context: Context records as dicts (keys: type,
                    source, content_hash, content, bytes).
                searches: Search records as dicts (keys: query,
                    engine, results_count).
                sources_read: Source records as dicts (keys: type,
                    path, content_hash, content, tool, bytes_read).
                turn_count: Number of conversation turns in this trace.
            """
            trace = Trace(
                id=generate_trace_id(),
                timestamp=utc_now(),
                agent=agent or self._agent,
                session_id=session_id or generate_session_id(),
                parent_id=parent_id or None,
                model=model,
                task=task,
                decision=decision,
                status=status
                if status in {s.value for s in Status}
                else Status.COMPLETED,
                scope=scope or None,
                tags=tags or [],
                files_modified=files_modified or [],
                correction=correction or None,
                duration_ms=duration_ms,
                metadata=metadata if metadata else {"source": "mcp"},
                token_usage=_build_token_usage(
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_creation_tokens,
                ),
                tools_used=_parse_records(tools_used, ToolRecord),
                context=_parse_records(context, ContextRecord),
                searches=_parse_records(searches, SearchRecord),
                sources_read=_parse_records(sources_read, SourceRecord),
                turn_count=turn_count,
            )

            sink = _get_sink(self._db_path)
            try:
                sink.write(trace)
            finally:
                sink.close()

            return json.dumps({"recorded": trace.id, "timestamp": trace.timestamp})

        @self._server.tool()
        def trace_update(
            trace_id: str,
            tools_used: list[dict[str, Any]] | None = None,
            context: list[dict[str, Any]] | None = None,
            searches: list[dict[str, Any]] | None = None,
            sources_read: list[dict[str, Any]] | None = None,
            turn_count: int | None = None,
            input_tokens: int = 0,
            output_tokens: int = 0,
            cache_read_tokens: int = 0,
            cache_creation_tokens: int = 0,
            status: str = "",
            decision: str = "",
            duration_ms: int | None = None,
        ) -> str:
            """Append records to an existing trace (for multi-turn sessions).

            Args:
                trace_id: ID of the trace to update.
                tools_used: Additional tool calls to append.
                context: Additional context records to append.
                searches: Additional search records to append.
                sources_read: Additional source records to append.
                turn_count: Updated turn count (replaces existing).
                input_tokens: Additional input tokens to add.
                output_tokens: Additional output tokens to add.
                cache_read_tokens: Additional cache read tokens to add.
                cache_creation_tokens: Additional cache creation tokens to add.
                status: Updated status (if non-empty, replaces existing).
                decision: Updated decision (if non-empty, replaces existing).
                duration_ms: Updated duration (if provided, replaces existing).
            """
            sink = _get_sink(self._db_path)
            try:
                trace = sink.get(trace_id)
                if trace is None:
                    return json.dumps({"error": f"trace {trace_id} not found"})

                # Append nested records
                trace.tools_used.extend(_parse_records(tools_used, ToolRecord))
                trace.context.extend(_parse_records(context, ContextRecord))
                trace.searches.extend(_parse_records(searches, SearchRecord))
                trace.sources_read.extend(_parse_records(sources_read, SourceRecord))

                # Merge token usage (additive)
                new_usage = _build_token_usage(
                    input_tokens,
                    output_tokens,
                    cache_read_tokens,
                    cache_creation_tokens,
                )
                if new_usage:
                    if trace.token_usage:
                        trace.token_usage.input_tokens += new_usage.input_tokens
                        trace.token_usage.output_tokens += new_usage.output_tokens
                        trace.token_usage.cache_read_tokens += (
                            new_usage.cache_read_tokens
                        )
                        trace.token_usage.cache_creation_tokens += (
                            new_usage.cache_creation_tokens
                        )
                    else:
                        trace.token_usage = new_usage

                # Replace scalar fields if provided
                if turn_count is not None:
                    trace.turn_count = turn_count
                if status and status in {s.value for s in Status}:
                    trace.status = status
                if decision:
                    trace.decision = decision
                if duration_ms is not None:
                    trace.duration_ms = duration_ms

                # Delete then re-insert (sink uses INSERT, not upsert)
                sink.forget(trace_id)
                sink.write(trace)
            finally:
                sink.close()

            return json.dumps({"updated": trace_id})

        @self._server.tool()
        def trace_search(
            query: str,
            limit: int = _DEFAULT_SEARCH_LIMIT,
            agent: str = "",
            scope: str = "",
        ) -> str:
            """Search past traces using full-text search.

            Args:
                query: FTS5 search query (supports AND, OR, NOT, phrases).
                limit: Max results to return.
                agent: Filter by agent name.
                scope: Filter by scope.
            """
            sink = _get_sink(self._db_path)
            try:
                results = sink.search(query, limit=limit)
                if agent:
                    results = [r for r in results if r.agent == agent]
                if scope:
                    results = [r for r in results if r.scope == scope]
                summaries = [_trace_to_summary(r) for r in results]
            finally:
                sink.close()

            return json.dumps(summaries, default=str)

    def _register_resources(self) -> None:
        @self._server.resource("trace://recent")
        def recent_traces() -> str:
            """Recent traces for session context injection."""
            sink = _get_sink(self._db_path)
            try:
                traces = sink.recent(limit=_DEFAULT_RECENT_LIMIT)
                summaries = [_trace_to_summary(r) for r in traces]
            finally:
                sink.close()

            return json.dumps(summaries, default=str)

        @self._server.resource("trace://context/{topic}")
        def context_traces(topic: str) -> str:
            """Past traces relevant to a topic (FTS5 search)."""
            sink = _get_sink(self._db_path)
            try:
                traces = sink.search(topic, limit=_DEFAULT_RECENT_LIMIT)
                summaries = [_trace_to_summary(r) for r in traces]
            finally:
                sink.close()

            return json.dumps(summaries, default=str)
