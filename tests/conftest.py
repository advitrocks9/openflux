from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from openflux._util import (
    content_hash,
    generate_session_id,
    generate_trace_id,
    utc_now,
)
from openflux.schema import (
    ContextRecord,
    ContextType,
    SearchRecord,
    SourceRecord,
    SourceType,
    TokenUsage,
    ToolRecord,
    Trace,
)


def make_trace(
    *,
    id: str | None = None,
    timestamp: str | None = None,
    agent: str = "test-agent",
    session_id: str | None = None,
    parent_id: str | None = None,
    model: str = "claude-sonnet-4-20250514",
    task: str = "test task",
    decision: str = "test decision",
    status: str = "completed",
    correction: str | None = None,
    scope: str | None = None,
    tags: list[str] | None = None,
    context: list[ContextRecord] | None = None,
    searches: list[SearchRecord] | None = None,
    sources_read: list[SourceRecord] | None = None,
    tools_used: list[ToolRecord] | None = None,
    files_modified: list[str] | None = None,
    turn_count: int = 0,
    token_usage: TokenUsage | None = None,
    duration_ms: int = 100,
    metadata: dict[str, Any] | None = None,
) -> Trace:
    return Trace(
        id=id or generate_trace_id(),
        timestamp=timestamp or utc_now(),
        agent=agent,
        session_id=session_id or generate_session_id(),
        parent_id=parent_id,
        model=model,
        task=task,
        decision=decision,
        status=status,
        correction=correction,
        scope=scope,
        tags=tags or [],
        context=context or [],
        searches=searches or [],
        sources_read=sources_read or [],
        tools_used=tools_used or [],
        files_modified=files_modified or [],
        turn_count=turn_count,
        token_usage=token_usage,
        duration_ms=duration_ms,
        metadata=metadata or {},
    )


def make_context_record(
    *,
    type: str = ContextType.SYSTEM_PROMPT,
    source: str = "test.md",
    content: str = "test context content",
    timestamp: str = "",
) -> ContextRecord:
    return ContextRecord(
        type=type,
        source=source,
        content_hash=content_hash(content) if content else "",
        content=content,
        bytes=len(content.encode("utf-8")) if content else 0,
        timestamp=timestamp or utc_now(),
    )


def make_search_record(
    *,
    query: str = "test query",
    engine: str = "Grep",
    results_count: int = 5,
    timestamp: str = "",
) -> SearchRecord:
    return SearchRecord(
        query=query,
        engine=engine,
        results_count=results_count,
        timestamp=timestamp or utc_now(),
    )


def make_source_record(
    *,
    type: str = SourceType.FILE,
    path: str = "/src/main.py",
    content: str = "def main(): pass",
    tool: str = "Read",
    timestamp: str = "",
) -> SourceRecord:
    return SourceRecord(
        type=type,
        path=path,
        content_hash=content_hash(content) if content else "",
        content=content,
        tool=tool,
        bytes_read=len(content.encode("utf-8")) if content else 0,
        timestamp=timestamp or utc_now(),
    )


def make_tool_record(
    *,
    name: str = "Bash",
    tool_input: str = "ls -la",
    tool_output: str = "file1.py\nfile2.py",
    duration_ms: int = 50,
    error: bool = False,
    timestamp: str = "",
) -> ToolRecord:
    return ToolRecord(
        name=name,
        tool_input=tool_input,
        tool_output=tool_output,
        duration_ms=duration_ms,
        error=error,
        timestamp=timestamp or utc_now(),
    )


@pytest.fixture()
def sample_trace() -> Trace:
    return make_trace(
        context=[make_context_record()],
        searches=[make_search_record()],
        sources_read=[make_source_record()],
        tools_used=[make_tool_record()],
        token_usage=TokenUsage(
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=200,
            cache_creation_tokens=100,
        ),
        tags=["test", "ci"],
        scope="unit-test",
        files_modified=["/src/main.py"],
        turn_count=3,
    )


@pytest.fixture()
def sqlite_path(tmp_path: Path) -> Path:
    return tmp_path / "test_traces.db"
