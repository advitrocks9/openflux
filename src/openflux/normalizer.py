"""Event classification, content hashing, and fidelity truncation"""

from __future__ import annotations

import os
from typing import Any

from openflux._util import (
    content_hash,
    generate_trace_id,
    get_exclude_patterns,
    matches_exclude_pattern,
    truncate_content,
    utc_now,
)
from openflux.schema import (
    ContextRecord,
    ContextType,
    FidelityMode,
    SearchRecord,
    SourceRecord,
    SourceType,
    TokenUsage,
    ToolRecord,
    Trace,
)

_SOURCE_MAX = 4096
_URL_MAX = 16384
_TOOL_IN_MAX = 4096
_TOOL_OUT_MAX = 16384
_CTX_MAX = 4096
_REDACTED_PREVIEW = 500

_SEARCH_TOOLS = frozenset({"WebSearch", "Grep", "Glob", "vector_search", "retriever"})
_SOURCE_TOOLS = frozenset({"Read", "WebFetch", "ReadFile", "read_file"})


class Normalizer:
    def __init__(
        self,
        agent: str = "",
        fidelity: FidelityMode | None = None,
        source_content_max: int = _SOURCE_MAX,
    ) -> None:
        env_fidelity = os.environ.get("OPENFLUX_FIDELITY", "full")
        self._fidelity = fidelity or FidelityMode(env_fidelity)
        self._agent = agent
        self._source_max = source_content_max
        self._exclude = get_exclude_patterns()

    def normalize(
        self,
        events: list[dict[str, Any]],
        session_id: str,
    ) -> Trace:
        trace = Trace(
            id=generate_trace_id(),
            timestamp=utc_now(),
            agent=self._agent,
            session_id=session_id,
        )
        for event in events:
            self._classify(event, trace)
        trace.turn_count = len(trace.tools_used)
        return trace

    def _classify(self, event: dict[str, Any], trace: Trace) -> None:
        match event.get("type", ""):
            case "context":
                self._handle_context(event, trace)
            case "search":
                self._handle_search(event, trace)
            case "source":
                self._handle_source(event, trace)
            case "tool":
                self._handle_tool(event, trace)
            case "meta":
                self._handle_meta(event, trace)
            case _:
                self._auto_classify(event, trace)

    def _handle_context(self, event: dict[str, Any], trace: Trace) -> None:
        raw = event.get("content", "")
        trace.context.append(
            ContextRecord(
                type=event.get("context_type", ContextType.TOOL_CONTEXT),
                source=event.get("source", ""),
                content_hash=content_hash(raw) if raw else "",
                content=self._fidelity_ctx(raw),
                bytes=len(raw.encode("utf-8")) if raw else 0,
                timestamp=event.get("timestamp", ""),
            )
        )

    def _handle_search(self, event: dict[str, Any], trace: Trace) -> None:
        trace.searches.append(
            SearchRecord(
                query=event.get("query", ""),
                engine=event.get("engine", event.get("tool_name", "")),
                results_count=event.get("results_count", 0),
                timestamp=event.get("timestamp", ""),
            )
        )

    def _handle_source(self, event: dict[str, Any], trace: Trace) -> None:
        raw = event.get("content", "")
        path = event.get("path", "")
        excluded = matches_exclude_pattern(path, self._exclude)
        trace.sources_read.append(
            SourceRecord(
                type=event.get("source_type", SourceType.FILE),
                path=path,
                content_hash=content_hash(raw) if raw else "",
                content="" if excluded else self._fidelity_src(raw, path),
                tool=event.get("tool_name", ""),
                bytes_read=len(raw.encode("utf-8")) if raw else 0,
                timestamp=event.get("timestamp", ""),
            )
        )

    def _handle_tool(self, event: dict[str, Any], trace: Trace) -> None:
        trace.tools_used.append(
            ToolRecord(
                name=event.get("tool_name", ""),
                tool_input=self._fidelity_tool(
                    event.get("tool_input", ""), _TOOL_IN_MAX
                ),
                tool_output=self._fidelity_tool(
                    event.get("tool_output", ""), _TOOL_OUT_MAX
                ),
                duration_ms=event.get("duration_ms", 0),
                error=event.get("error", False),
                timestamp=event.get("timestamp", ""),
            )
        )
        tool_name = event.get("tool_name", "")
        if tool_name in {"Edit", "Write", "WriteFile"} and "path" in event:
            trace.files_modified.append(event["path"])

    def _handle_meta(self, event: dict[str, Any], trace: Trace) -> None:
        if "model" in event:
            trace.model = event["model"]
        if "task" in event:
            trace.task = event["task"]
        if "decision" in event:
            trace.decision = event["decision"]
        if "status" in event:
            trace.status = event["status"]
        if "token_usage" in event:
            trace.token_usage = TokenUsage(**event["token_usage"])
        if "duration_ms" in event:
            trace.duration_ms = event["duration_ms"]
        if "parent_id" in event:
            trace.parent_id = event["parent_id"]
        if "scope" in event:
            trace.scope = event["scope"]
        if "tags" in event:
            trace.tags.extend(event["tags"])

    def _auto_classify(self, event: dict[str, Any], trace: Trace) -> None:
        tool_name = event.get("tool_name", "")
        if not tool_name:
            return
        if tool_name in _SEARCH_TOOLS:
            self._handle_search(event, trace)
        elif tool_name in _SOURCE_TOOLS:
            self._handle_source(event, trace)
        else:
            self._handle_tool(event, trace)

    def _fidelity_src(self, content: str, path: str) -> str:
        if not content:
            return ""
        match self._fidelity:
            case FidelityMode.FULL:
                limit = _URL_MAX if "://" in path else self._source_max
                return truncate_content(content, limit)
            case FidelityMode.REDACTED:
                return ""

    def _fidelity_ctx(self, content: str) -> str:
        if not content:
            return ""
        match self._fidelity:
            case FidelityMode.FULL:
                return truncate_content(content, _CTX_MAX)
            case FidelityMode.REDACTED:
                return ""

    def _fidelity_tool(self, content: str, max_bytes: int) -> str:
        if not content:
            return ""
        match self._fidelity:
            case FidelityMode.FULL:
                return truncate_content(content, max_bytes)
            case FidelityMode.REDACTED:
                return truncate_content(content, _REDACTED_PREVIEW)
