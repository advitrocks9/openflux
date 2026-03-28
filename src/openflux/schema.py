"""Core data models for OpenFlux"""

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Self

SCHEMA_VERSION = "0.2.0"

_ALWAYS_PRESENT_FIELDS: frozenset[str] = frozenset(
    {"id", "timestamp", "agent", "session_id", "status", "schema_version"}
)


class Status(StrEnum):
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class FidelityMode(StrEnum):
    FULL = "full"
    REDACTED = "redacted"


class SourceType(StrEnum):
    FILE = "file"
    URL = "url"
    TOOL_RESULT = "tool_result"
    API = "api"
    DOCUMENT = "document"


class ContextType(StrEnum):
    SYSTEM_PROMPT = "system_prompt"
    MEMORY = "memory"
    RAG_CHUNK = "rag_chunk"
    FILE_INJECTION = "file_injection"
    TOOL_CONTEXT = "tool_context"


@dataclass(slots=True)
class SearchRecord:
    query: str
    engine: str = ""
    results_count: int = 0
    timestamp: str = ""


@dataclass(slots=True)
class SourceRecord:
    type: str
    path: str = ""
    content_hash: str = ""
    content: str = ""
    tool: str = ""
    bytes_read: int = 0
    timestamp: str = ""


@dataclass(slots=True)
class ToolRecord:
    name: str
    tool_input: str = ""
    tool_output: str = ""
    duration_ms: int = 0
    error: bool = False
    timestamp: str = ""


@dataclass(slots=True)
class ContextRecord:
    type: str
    source: str = ""
    content_hash: str = ""
    content: str = ""
    bytes: int = 0
    timestamp: str = ""


@dataclass(slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass(slots=True)
class Trace:
    """The core telemetry primitive of OpenFlux."""

    id: str
    timestamp: str
    agent: str
    session_id: str
    parent_id: str | None = None
    model: str = ""
    task: str = ""
    decision: str = ""
    status: str = Status.COMPLETED
    correction: str | None = None
    scope: str | None = None
    tags: list[str] = field(default_factory=list)
    context: list[ContextRecord] = field(default_factory=list)
    searches: list[SearchRecord] = field(default_factory=list)
    sources_read: list[SourceRecord] = field(default_factory=list)
    tools_used: list[ToolRecord] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    turn_count: int = 0
    token_usage: TokenUsage | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, omitting None values and empty defaults."""
        return {
            k: v
            for k, v in asdict(self).items()
            if v is not None and (v or k in _ALWAYS_PRESENT_FIELDS)
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        context = [ContextRecord(**r) for r in data.get("context", [])]
        searches = [SearchRecord(**r) for r in data.get("searches", [])]
        sources_read = [SourceRecord(**r) for r in data.get("sources_read", [])]
        tools_used = [ToolRecord(**r) for r in data.get("tools_used", [])]

        token_data = data.get("token_usage")
        token_usage = TokenUsage(**token_data) if token_data else None

        return cls(
            id=data["id"],
            timestamp=data["timestamp"],
            agent=data["agent"],
            session_id=data["session_id"],
            parent_id=data.get("parent_id"),
            model=data.get("model", ""),
            task=data.get("task", ""),
            decision=data.get("decision", ""),
            status=data.get("status", Status.COMPLETED),
            correction=data.get("correction"),
            scope=data.get("scope"),
            tags=data.get("tags", []),
            context=context,
            searches=searches,
            sources_read=sources_read,
            tools_used=tools_used,
            files_modified=data.get("files_modified", []),
            turn_count=data.get("turn_count", 0),
            token_usage=token_usage,
            duration_ms=data.get("duration_ms", 0),
            metadata=data.get("metadata", {}),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )
