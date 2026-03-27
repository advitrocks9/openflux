"""Claude Agent SDK adapter - hooks-based telemetry capture."""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from openflux._util import (
    content_hash,
    generate_trace_id,
    utc_now,
)
from openflux.schema import (
    ContextRecord,
    ContextType,
    SearchRecord,
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

_HAS_SDK = importlib.util.find_spec("claude_agent_sdk") is not None

if _HAS_SDK:
    from claude_agent_sdk import HookMatcher
else:

    @dataclass
    class HookMatcher:
        matcher: str | None = None
        hooks: list[Any] = field(default_factory=list)
        timeout: float | None = None


_READ_TOOLS: set[str] = {"Read", "WebFetch"}
_WRITE_TOOLS: set[str] = {"Write", "Edit"}
_SEARCH_TOOLS: dict[str, str] = {
    "WebSearch": "query",
    "Grep": "pattern",
    "Glob": "pattern",
}


@dataclass(slots=True)
class _SessionAccumulator:
    session_id: str
    started_at: str = ""
    task: str = ""
    decision: str = ""
    status: Status | None = None
    tools: list[ToolRecord] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    searches: list[SearchRecord] = field(default_factory=list)
    context: list[ContextRecord] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    subagents: list[dict[str, str]] = field(default_factory=list)
    tool_errors_count: int = 0
    model: str = ""
    cwd: str = ""
    token_usage: TokenUsage | None = None
    duration_ms: int = 0
    num_turns: int | None = None


class ClaudeAgentSDKAdapter:
    """Accumulates tool events during a session, builds a Trace on Stop."""

    def __init__(
        self,
        agent: str = "claude-agent-sdk",
        on_trace: Any | None = None,
        *,
        scope: str | None = None,
        tags: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self._agent = agent
        self._on_trace = on_trace
        self._scope = scope
        self._tags = tags or []
        self._system_prompt = system_prompt
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionAccumulator] = {}
        self._completed: list[Trace] = []
        # Maps session_id → index in _completed for late-binding usage data
        self._trace_index: dict[str, int] = {}
        # Maps tool_use_id → monotonic start time for duration tracking
        self._tool_start_times: dict[str, float] = {}

    def _get_or_create(self, session_id: str) -> _SessionAccumulator:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionAccumulator(
                session_id=session_id,
                started_at=utc_now(),
            )
        return self._sessions[session_id]

    async def _on_user_prompt_submit(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        session_id = input_data.get("session_id", "")
        prompt = input_data.get("prompt", "")
        if not session_id or not prompt:
            return {}
        with self._lock:
            acc = self._get_or_create(session_id)
            acc.task = prompt[:4096]
        return {}

    async def _on_pre_tool_use(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        """Record tool start time for duration calculation."""
        tuid = input_data.get("tool_use_id", "")
        if tuid:
            self._tool_start_times[tuid] = time.monotonic()
        return {}

    async def _on_post_tool_use(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        self._record_tool(input_data, error=False)
        return {}

    async def _on_post_tool_use_failure(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        self._record_tool(input_data, error=True)
        return {}

    async def _on_subagent_start(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        session_id = input_data.get("session_id", "")
        if not session_id:
            return {}
        with self._lock:
            acc = self._get_or_create(session_id)
            acc.subagents.append(
                {
                    "agent_id": input_data.get("agent_id", ""),
                    "agent_type": input_data.get("agent_type", ""),
                }
            )
        return {}

    async def _on_subagent_stop(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        session_id = input_data.get("session_id", "")
        if not session_id:
            return {}
        agent_id = input_data.get("agent_id", "")
        with self._lock:
            acc = self._get_or_create(session_id)
            # Update existing subagent entry with stop data
            for sub in acc.subagents:
                if sub.get("agent_id") == agent_id:
                    sub["transcript_path"] = input_data.get("agent_transcript_path", "")
                    return {}
            # If SubagentStart was missed, record anyway
            acc.subagents.append(
                {
                    "agent_id": agent_id,
                    "agent_type": input_data.get("agent_type", ""),
                    "transcript_path": input_data.get("agent_transcript_path", ""),
                }
            )
        return {}

    async def _on_stop(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        session_id = input_data.get("session_id", "")
        if not session_id:
            return {}

        with self._lock:
            acc = self._sessions.pop(session_id, None)
            if acc is None:
                acc = _SessionAccumulator(
                    session_id=session_id,
                    started_at=utc_now(),
                )
            acc.cwd = input_data.get("cwd", acc.cwd)

        trace = self._build_trace(acc)
        with self._lock:
            self._trace_index[session_id] = len(self._completed)
            self._completed.append(trace)

        # Don't write to sink yet — wait for record_usage() to patch in
        # token data from ResultMessage, which arrives after Stop.
        # If no record_usage() call comes, finalize() flushes to sink.

        return {}

    def _record_tool(self, input_data: dict[str, Any], *, error: bool) -> None:
        session_id = input_data.get("session_id", "")
        if not session_id:
            return

        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        # Error responses use "error" key, success uses "tool_response"
        if error:
            raw_output = input_data.get("error", "")
            output_str = str(raw_output) if raw_output else ""
        else:
            raw_output = input_data.get("tool_response", "")
            output_str = (
                json.dumps(raw_output, default=str)
                if isinstance(raw_output, dict)
                else str(raw_output)
                if raw_output
                else ""
            )

        input_str = (
            json.dumps(tool_input, default=str)
            if isinstance(tool_input, dict)
            else str(tool_input)
        )
        timestamp = utc_now()

        # Duration = PreToolUse start → PostToolUse end
        tuid = input_data.get("tool_use_id", "")
        start = self._tool_start_times.pop(tuid, None) if tuid else None
        duration_ms = int((time.monotonic() - start) * 1000) if start else 0

        record = ToolRecord(
            name=tool_name,
            tool_input=input_str[:4096],
            tool_output=output_str[:16384],
            duration_ms=duration_ms,
            error=error,
            timestamp=timestamp,
        )

        with self._lock:
            acc = self._get_or_create(session_id)
            acc.cwd = input_data.get("cwd", acc.cwd)
            acc.tools.append(record)

            if error:
                acc.tool_errors_count += 1

            if tool_name in _READ_TOOLS and not error:
                path = tool_input.get("file_path", "") or tool_input.get("url", "")
                src_type = SourceType.URL if "://" in path else SourceType.FILE
                acc.sources.append(
                    SourceRecord(
                        type=src_type,
                        path=path,
                        content_hash=content_hash(output_str) if output_str else "",
                        tool=tool_name,
                        bytes_read=len(output_str.encode("utf-8")) if output_str else 0,
                        timestamp=timestamp,
                    )
                )

            if tool_name in _SEARCH_TOOLS and not error:
                query_key = _SEARCH_TOOLS[tool_name]
                query_val = tool_input.get(query_key, "")
                acc.searches.append(
                    SearchRecord(
                        query=str(query_val)[:1024],
                        engine=tool_name,
                        results_count=output_str.count("\n") + 1 if output_str else 0,
                        timestamp=timestamp,
                    )
                )

            if tool_name in _WRITE_TOOLS:
                path = tool_input.get("file_path", "")
                if path and path not in acc.files_modified:
                    acc.files_modified.append(path)

    def record_usage(
        self,
        session_id: str,
        usage: dict[str, int],
        *,
        model: str = "",
        duration_ms: int = 0,
        result: str = "",
        num_turns: int = 0,
        status: Status | None = None,
    ) -> None:
        """Feed ResultMessage data and flush trace to sink.

        Called after the query loop with data from ResultMessage.
        Patches the already-completed trace with token counts, duration,
        decision text, model, and status, then writes to sink.
        """
        token_usage = TokenUsage(
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
        )

        with self._lock:
            idx = self._trace_index.pop(session_id, None)
            if idx is not None and idx < len(self._completed):
                trace = self._completed[idx]
                trace.token_usage = token_usage
                if model:
                    trace.model = model
                if duration_ms:
                    trace.duration_ms = duration_ms
                if result:
                    trace.decision = result[:4096]
                if num_turns:
                    trace.turn_count = num_turns
                if status is not None:
                    trace.status = status
            else:
                # Stop hook hasn't fired yet — store on accumulator
                acc = self._get_or_create(session_id)
                acc.token_usage = token_usage
                if model:
                    acc.model = model
                if duration_ms:
                    acc.duration_ms = duration_ms
                if result:
                    acc.decision = result[:4096]
                if num_turns:
                    acc.num_turns = num_turns
                if status is not None:
                    acc.status = status
                return

        if self._on_trace:
            self._on_trace(trace)
        else:
            self._write_default_sink(trace)

    def _build_trace(self, acc: _SessionAccumulator) -> Trace:
        metadata: dict[str, Any] = {}
        if acc.cwd:
            metadata["environment"] = {"cwd": acc.cwd}
        if acc.subagents:
            metadata["subagents"] = acc.subagents
        if acc.tool_errors_count:
            metadata["tool_errors_count"] = acc.tool_errors_count

        # Tool failures alone don't mark the trace as ERROR — only explicit status does
        status = acc.status if acc.status is not None else Status.COMPLETED

        # Attach system prompt so context field is populated
        context = list(acc.context)
        if self._system_prompt:
            context.append(
                ContextRecord(
                    type=ContextType.SYSTEM_PROMPT,
                    content=self._system_prompt[:4096],
                    content_hash=content_hash(self._system_prompt),
                )
            )

        return Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or utc_now(),
            agent=self._agent,
            session_id=acc.session_id,
            model=acc.model,
            task=acc.task,
            decision=acc.decision,
            status=status,
            scope=self._scope,
            tags=list(self._tags),
            context=context,
            tools_used=acc.tools,
            sources_read=acc.sources,
            searches=acc.searches,
            files_modified=acc.files_modified,
            token_usage=acc.token_usage,
            turn_count=acc.num_turns if acc.num_turns is not None else len(acc.tools),
            duration_ms=acc.duration_ms,
            metadata=metadata,
        )

    def _write_default_sink(self, trace: Trace) -> None:
        import os

        try:
            from openflux.sinks.sqlite import SQLiteSink

            db_path_str = os.environ.get("OPENFLUX_DB_PATH")
            sink = SQLiteSink(path=db_path_str) if db_path_str else SQLiteSink()
            sink.write(trace)
            sink.close()
        except Exception:
            pass

    def finalize(self) -> None:
        """Flush any traces that weren't patched by record_usage()."""
        with self._lock:
            unflushed = list(self._trace_index.items())
            self._trace_index.clear()

        for _session_id, idx in unflushed:
            with self._lock:
                if idx < len(self._completed):
                    trace = self._completed[idx]
                else:
                    continue
            if self._on_trace:
                self._on_trace(trace)
            else:
                self._write_default_sink(trace)

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)

    def create_hooks(self) -> dict[str, list[Any]]:
        """Return a hooks dict for ClaudeAgentOptions(hooks=...)."""
        return {
            "UserPromptSubmit": [HookMatcher(hooks=[self._on_user_prompt_submit])],
            "PreToolUse": [HookMatcher(hooks=[self._on_pre_tool_use])],
            "PostToolUse": [HookMatcher(hooks=[self._on_post_tool_use])],
            "PostToolUseFailure": [HookMatcher(hooks=[self._on_post_tool_use_failure])],
            "SubagentStart": [HookMatcher(hooks=[self._on_subagent_start])],
            "SubagentStop": [HookMatcher(hooks=[self._on_subagent_stop])],
            "Stop": [HookMatcher(hooks=[self._on_stop])],
        }


def create_openflux_hooks(
    agent: str = "claude-agent-sdk",
    on_trace: Any | None = None,
    *,
    scope: str | None = None,
    tags: list[str] | None = None,
    system_prompt: str | None = None,
) -> tuple[dict[str, list[Any]], ClaudeAgentSDKAdapter]:
    """Create hooks dict and return the adapter for record_usage/finalize.

    Returns:
        A tuple of (hooks_dict, adapter). Pass hooks_dict to
        ClaudeAgentOptions(hooks=...) and call adapter.record_usage()
        with ResultMessage.usage after the query loop.
    """
    adapter = ClaudeAgentSDKAdapter(
        agent=agent,
        on_trace=on_trace,
        scope=scope,
        tags=tags,
        system_prompt=system_prompt,
    )
    return adapter.create_hooks(), adapter
