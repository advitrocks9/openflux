from __future__ import annotations

import re
from typing import Any

import pytest
from conftest import (
    make_context_record,
    make_search_record,
    make_source_record,
    make_tool_record,
    make_trace,
)

from openflux.schema import (
    SCHEMA_VERSION,
    ContextType,
    FidelityMode,
    SourceType,
    Status,
    TokenUsage,
    Trace,
)


class TestTraceId:
    def test_format(self) -> None:
        r = make_trace()
        assert re.fullmatch(r"trc-[0-9a-f]{12}", r.id)

    def test_unique(self) -> None:
        ids = {make_trace().id for _ in range(100)}
        assert len(ids) == 100


class TestEnums:
    @pytest.mark.parametrize(
        ("enum_cls", "expected"),
        [
            (Status, {"completed", "error", "timeout", "cancelled"}),
            (FidelityMode, {"full", "redacted"}),
            (SourceType, {"file", "url", "tool_result", "api", "document"}),
            (
                ContextType,
                {
                    "system_prompt",
                    "memory",
                    "rag_chunk",
                    "file_injection",
                    "tool_context",
                },
            ),
        ],
    )
    def test_values(self, enum_cls: type, expected: set[str]) -> None:
        assert {m.value for m in enum_cls} == expected


class TestTraceDefaults:
    def test_minimal(self) -> None:
        r = Trace(
            id="trc-aabbccddeeff",
            timestamp="2026-01-01T00:00:00Z",
            agent="a",
            session_id="ses-abc",
        )
        assert r.status == Status.COMPLETED
        assert r.model == ""
        assert r.task == ""
        assert r.tags == []
        assert r.context == []
        assert r.searches == []
        assert r.sources_read == []
        assert r.tools_used == []
        assert r.files_modified == []
        assert r.turn_count == 0
        assert r.token_usage is None
        assert r.duration_ms == 0
        assert r.metadata == {}
        assert r.schema_version == SCHEMA_VERSION


class TestTokenUsage:
    def test_defaults(self) -> None:
        t = TokenUsage()
        assert t.input_tokens == 0
        assert t.output_tokens == 0
        assert t.cache_read_tokens == 0
        assert t.cache_creation_tokens == 0


class TestSerialization:
    def test_to_dict_omits_none(self) -> None:
        r = make_trace(parent_id=None, correction=None, scope=None)
        d = r.to_dict()
        assert "parent_id" not in d
        assert "correction" not in d
        assert "scope" not in d

    def test_to_dict_keeps_values(self) -> None:
        r = make_trace(
            parent_id="trc-parent123456", correction="fixed it", scope="deploy"
        )
        d = r.to_dict()
        assert d["parent_id"] == "trc-parent123456"
        assert d["correction"] == "fixed it"
        assert d["scope"] == "deploy"

    def test_roundtrip_minimal(self) -> None:
        original = make_trace()
        restored = Trace.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.agent == original.agent
        assert restored.session_id == original.session_id
        assert restored.task == original.task
        assert restored.status == original.status

    def test_roundtrip_nested(self) -> None:
        original = make_trace(
            context=[make_context_record()],
            searches=[make_search_record()],
            sources_read=[make_source_record()],
            tools_used=[make_tool_record()],
            token_usage=TokenUsage(input_tokens=500, output_tokens=200),
            tags=["a", "b"],
            files_modified=["/foo.py"],
        )
        restored = Trace.from_dict(original.to_dict())

        assert len(restored.context) == 1
        assert restored.context[0].type == original.context[0].type
        assert restored.context[0].content == original.context[0].content
        assert len(restored.searches) == 1
        assert restored.searches[0].query == original.searches[0].query
        assert len(restored.sources_read) == 1
        assert restored.sources_read[0].path == original.sources_read[0].path
        assert len(restored.tools_used) == 1
        assert restored.tools_used[0].name == original.tools_used[0].name
        assert restored.token_usage is not None
        assert restored.token_usage.input_tokens == 500
        assert restored.token_usage.output_tokens == 200
        assert restored.tags == ["a", "b"]
        assert restored.files_modified == ["/foo.py"]

    def test_from_dict_missing_optionals(self) -> None:
        minimal: dict[str, Any] = {
            "id": "trc-000000000000",
            "timestamp": "2026-01-01T00:00:00Z",
            "agent": "a",
            "session_id": "ses-abc",
        }
        r = Trace.from_dict(minimal)
        assert r.model == ""
        assert r.tags == []
        assert r.token_usage is None


class TestNestedRecords:
    def test_context_record(self) -> None:
        c = make_context_record(
            type=ContextType.MEMORY, source="mem.md", content="hello"
        )
        assert c.type == "memory"
        assert c.source == "mem.md"
        assert c.content == "hello"
        assert c.bytes == 5
        assert c.content_hash != ""

    def test_search_record(self) -> None:
        s = make_search_record(query="find me", engine="WebSearch", results_count=10)
        assert s.query == "find me"
        assert s.engine == "WebSearch"
        assert s.results_count == 10

    def test_source_record(self) -> None:
        src = make_source_record(
            type=SourceType.URL, path="https://example.com", content="<html>"
        )
        assert src.type == "url"
        assert src.path == "https://example.com"
        assert src.bytes_read == 6

    def test_tool_record(self) -> None:
        t = make_tool_record(
            name="Edit", tool_input="old", tool_output="new", error=True
        )
        assert t.name == "Edit"
        assert t.error is True
