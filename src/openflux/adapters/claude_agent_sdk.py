"""Claude Agent SDK adapter - hooks-based telemetry capture."""

from __future__ import annotations

import importlib.util
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from openflux._util import (
    content_hash,
    generate_trace_id,
    utc_now,
    write_trace_to_default_sink,
)
from openflux.schema import (
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

logger = logging.getLogger("openflux")

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


@dataclass(slots=True)
class _SessionAccumulator:
    session_id: str
    started_at: str = ""
    tools: list[ToolRecord] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    subagents: list[dict[str, str]] = field(default_factory=list)
    has_error: bool = False
    model: str = ""
    cwd: str = ""
    token_usage: TokenUsage | None = None


class ClaudeAgentSDKAdapter:
    """Accumulates tool events during a session, builds a Trace on Stop."""

    def __init__(
        self,
        agent: str = "claude-agent-sdk",
        on_trace: Any | None = None,
    ) -> None:
        self._agent = agent
        self._on_trace = on_trace
        self._lock = threading.Lock()
        self._sessions: dict[str, _SessionAccumulator] = {}
        self._completed: list[Trace] = []

    def _get_or_create(self, session_id: str) -> _SessionAccumulator:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionAccumulator(
                session_id=session_id,
                started_at=utc_now(),
            )
        return self._sessions[session_id]

    async def _on_post_tool_use(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        try:
            self._record_tool(input_data, error=False)
        except Exception:
            logger.warning("OpenFlux: error in post_tool_use hook", exc_info=True)
        return {}

    async def _on_post_tool_use_failure(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        try:
            self._record_tool(input_data, error=True)
        except Exception:
            logger.warning(
                "OpenFlux: error in post_tool_use_failure hook", exc_info=True
            )
        return {}

    async def _on_subagent_start(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        try:
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
        except Exception:
            logger.warning("OpenFlux: error in subagent_start hook", exc_info=True)
        return {}

    async def _on_stop(
        self,
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: Any,
    ) -> dict[str, Any]:
        try:
            session_id = input_data.get("session_id", "")
            if not session_id:
                return {}

            with self._lock:
                acc = self._sessions.pop(session_id, None)
            if acc is None:
                return {}

            trace = self._build_trace(acc)
            with self._lock:
                self._completed.append(trace)

            if self._on_trace:
                self._on_trace(trace)
            else:
                self._write_default_sink(trace)
        except Exception:
            logger.warning("OpenFlux: error in stop hook", exc_info=True)

        return {}

    def _record_tool(self, input_data: dict[str, Any], *, error: bool) -> None:
        session_id = input_data.get("session_id", "")
        if not session_id:
            return

        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        tool_output = input_data.get("tool_response", input_data.get("error", ""))

        input_str = (
            json.dumps(tool_input, default=str)
            if isinstance(tool_input, dict)
            else str(tool_input)
        )
        output_str = str(tool_output) if tool_output else ""
        timestamp = utc_now()

        record = ToolRecord(
            name=tool_name,
            tool_input=input_str[:4096],
            tool_output=output_str[:16384],
            error=error,
            timestamp=timestamp,
        )

        with self._lock:
            acc = self._get_or_create(session_id)
            acc.cwd = input_data.get("cwd", acc.cwd)
            acc.tools.append(record)

            if error:
                acc.has_error = True

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
    ) -> None:
        """Feed token usage from a ResultMessage into the accumulator."""
        with self._lock:
            acc = self._get_or_create(session_id)
            acc.token_usage = TokenUsage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            )
            if model:
                acc.model = model

    def _build_trace(self, acc: _SessionAccumulator) -> Trace:
        metadata: dict[str, Any] = {}
        if acc.cwd:
            metadata["environment"] = {"cwd": acc.cwd}
        if acc.subagents:
            metadata["subagents"] = acc.subagents

        return Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or utc_now(),
            agent=self._agent,
            session_id=acc.session_id,
            model=acc.model,
            status=Status.ERROR if acc.has_error else Status.COMPLETED,
            tools_used=acc.tools,
            sources_read=acc.sources,
            files_modified=acc.files_modified,
            token_usage=acc.token_usage,
            turn_count=len(acc.tools),
            metadata=metadata,
        )

    def _write_default_sink(self, trace: Trace) -> None:
        write_trace_to_default_sink(trace)

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)

    def create_hooks(self) -> dict[str, list[Any]]:
        """Return a hooks dict for ClaudeAgentOptions(hooks=...)."""
        return {
            "PostToolUse": [HookMatcher(hooks=[self._on_post_tool_use])],
            "PostToolUseFailure": [HookMatcher(hooks=[self._on_post_tool_use_failure])],
            "SubagentStart": [HookMatcher(hooks=[self._on_subagent_start])],
            "Stop": [HookMatcher(hooks=[self._on_stop])],
        }


def create_openflux_hooks(
    agent: str = "claude-agent-sdk",
    on_trace: Any | None = None,
) -> dict[str, list[Any]]:
    adapter = ClaudeAgentSDKAdapter(agent=agent, on_trace=on_trace)
    return adapter.create_hooks()
