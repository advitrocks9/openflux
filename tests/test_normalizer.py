from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from openflux._util import content_hash
from openflux.normalizer import (
    _REDACTED_PREVIEW,
    Normalizer,
)
from openflux.schema import ContextType, FidelityMode, SourceType


class TestEventClassification:
    def test_context(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [
                {
                    "type": "context",
                    "context_type": "system_prompt",
                    "content": "you are helpful",
                    "source": "sys.md",
                }
            ],
            "ses-001",
        )
        assert len(trace.context) == 1
        assert trace.context[0].type == ContextType.SYSTEM_PROMPT
        assert trace.context[0].source == "sys.md"

    def test_search(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [
                {
                    "type": "search",
                    "query": "find bugs",
                    "engine": "Grep",
                    "results_count": 3,
                }
            ],
            "ses-001",
        )
        assert len(trace.searches) == 1
        assert trace.searches[0].query == "find bugs"
        assert trace.searches[0].results_count == 3

    def test_source(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [
                {
                    "type": "source",
                    "path": "/main.py",
                    "content": "code",
                    "source_type": "file",
                }
            ],
            "ses-001",
        )
        assert len(trace.sources_read) == 1
        assert trace.sources_read[0].path == "/main.py"
        assert trace.sources_read[0].type == SourceType.FILE

    def test_tool(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [
                {
                    "type": "tool",
                    "tool_name": "Bash",
                    "tool_input": "ls",
                    "tool_output": "a.py",
                    "duration_ms": 10,
                }
            ],
            "ses-001",
        )
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "Bash"
        assert trace.tools_used[0].duration_ms == 10

    def test_meta(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [
                {
                    "type": "meta",
                    "model": "gpt-4",
                    "task": "fix bug",
                    "decision": "refactor",
                    "status": "error",
                    "duration_ms": 5000,
                    "parent_id": "trc-parent",
                    "scope": "backend",
                    "tags": ["urgent"],
                }
            ],
            "ses-001",
        )
        assert trace.model == "gpt-4"
        assert trace.task == "fix bug"
        assert trace.decision == "refactor"
        assert trace.status == "error"
        assert trace.duration_ms == 5000
        assert trace.parent_id == "trc-parent"
        assert trace.scope == "backend"
        assert "urgent" in trace.tags

    def test_meta_token_usage(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [
                {
                    "type": "meta",
                    "token_usage": {"input_tokens": 100, "output_tokens": 50},
                }
            ],
            "ses-001",
        )
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 100
        assert trace.token_usage.output_tokens == 50


class TestAutoClassification:
    @pytest.mark.parametrize(
        "tool_name", ["WebSearch", "Grep", "Glob", "vector_search", "retriever"]
    )
    def test_search_tools(self, tool_name: str) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize([{"tool_name": tool_name, "query": "q"}], "ses-001")
        assert len(trace.searches) == 1

    @pytest.mark.parametrize("tool_name", ["Read", "WebFetch", "ReadFile", "read_file"])
    def test_source_tools(self, tool_name: str) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [{"tool_name": tool_name, "path": "/f.py", "content": "x"}], "ses-001"
        )
        assert len(trace.sources_read) == 1

    def test_unknown_tool(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [{"tool_name": "CustomTool", "tool_input": "in"}], "ses-001"
        )
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "CustomTool"

    def test_empty_event_skipped(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize([{}], "ses-001")
        assert len(trace.tools_used) == 0
        assert len(trace.searches) == 0
        assert len(trace.sources_read) == 0
        assert len(trace.context) == 0

    def test_write_tool_extracts_file_mod(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [
                {
                    "type": "tool",
                    "tool_name": "Edit",
                    "path": "/src/foo.py",
                    "tool_input": "x",
                    "tool_output": "y",
                }
            ],
            "ses-001",
        )
        assert "/src/foo.py" in trace.files_modified


class TestContentHashing:
    def test_context_hash(self) -> None:
        n = Normalizer(agent="test")
        content = "important context"
        trace = n.normalize([{"type": "context", "content": content}], "ses-001")
        assert trace.context[0].content_hash == content_hash(content)

    def test_source_hash(self) -> None:
        n = Normalizer(agent="test")
        content = "file contents here"
        trace = n.normalize(
            [{"type": "source", "content": content, "path": "/f.py"}], "ses-001"
        )
        assert trace.sources_read[0].content_hash == content_hash(content)

    def test_empty_content(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [{"type": "source", "content": "", "path": "/f.py"}], "ses-001"
        )
        assert trace.sources_read[0].content_hash == ""


class TestFidelityModes:
    def test_full_preserves_content(self) -> None:
        n = Normalizer(agent="test", fidelity=FidelityMode.FULL)
        content = "short content"
        trace = n.normalize(
            [{"type": "source", "content": content, "path": "/f.py"}], "ses-001"
        )
        assert trace.sources_read[0].content == content

    def test_full_truncates_large_source(self) -> None:
        n = Normalizer(agent="test", fidelity=FidelityMode.FULL, source_content_max=100)
        trace = n.normalize(
            [{"type": "source", "content": "x" * 200, "path": "/f.py"}], "ses-001"
        )
        assert len(trace.sources_read[0].content) <= 100

    def test_full_url_gets_larger_limit(self) -> None:
        n = Normalizer(agent="test", fidelity=FidelityMode.FULL, source_content_max=100)
        trace = n.normalize(
            [
                {
                    "type": "source",
                    "content": "x" * 500,
                    "path": "https://example.com/data",
                }
            ],
            "ses-001",
        )
        assert len(trace.sources_read[0].content) == 500

    def test_redacted_blanks_source(self) -> None:
        n = Normalizer(agent="test", fidelity=FidelityMode.REDACTED)
        trace = n.normalize(
            [{"type": "source", "content": "secret stuff", "path": "/f.py"}], "ses-001"
        )
        assert trace.sources_read[0].content == ""
        assert trace.sources_read[0].content_hash == content_hash("secret stuff")

    def test_redacted_blanks_context(self) -> None:
        n = Normalizer(agent="test", fidelity=FidelityMode.REDACTED)
        trace = n.normalize(
            [{"type": "context", "content": "system prompt text"}], "ses-001"
        )
        assert trace.context[0].content == ""
        assert trace.context[0].content_hash != ""

    def test_redacted_truncates_tool_io(self) -> None:
        n = Normalizer(agent="test", fidelity=FidelityMode.REDACTED)
        content = "x" * 1000
        trace = n.normalize(
            [
                {
                    "type": "tool",
                    "tool_name": "Bash",
                    "tool_input": content,
                    "tool_output": content,
                }
            ],
            "ses-001",
        )
        assert len(trace.tools_used[0].tool_input) <= _REDACTED_PREVIEW
        assert len(trace.tools_used[0].tool_output) <= _REDACTED_PREVIEW

    def test_fidelity_from_env(self) -> None:
        with patch.dict(os.environ, {"OPENFLUX_FIDELITY": "redacted"}):
            n = Normalizer(agent="test")
            trace = n.normalize([{"type": "context", "content": "secret"}], "ses-001")
            assert trace.context[0].content == ""


class TestPathExclusion:
    def test_excluded_path_blanks_content(self) -> None:
        n = Normalizer(agent="test", fidelity=FidelityMode.FULL)
        trace = n.normalize(
            [{"type": "source", "content": "API_KEY=secret", "path": "/app/.env"}],
            "ses-001",
        )
        assert trace.sources_read[0].content == ""
        assert trace.sources_read[0].content_hash == content_hash("API_KEY=secret")
        assert trace.sources_read[0].path == "/app/.env"

    @pytest.mark.parametrize(
        "path",
        [
            "/app/.env",
            "/config/.env.local",
            "/secrets/credentials.json",
            "/keys/server.pem",
            "/ssh/id_rsa.key",
        ],
    )
    def test_default_patterns(self, path: str) -> None:
        n = Normalizer(agent="test", fidelity=FidelityMode.FULL)
        trace = n.normalize(
            [{"type": "source", "content": "sensitive", "path": path}],
            "ses-001",
        )
        assert trace.sources_read[0].content == ""

    def test_non_excluded_keeps_content(self) -> None:
        n = Normalizer(agent="test", fidelity=FidelityMode.FULL)
        trace = n.normalize(
            [{"type": "source", "content": "normal code", "path": "/src/main.py"}],
            "ses-001",
        )
        assert trace.sources_read[0].content == "normal code"

    def test_custom_patterns_from_env(self) -> None:
        with patch.dict(os.environ, {"OPENFLUX_EXCLUDE_PATHS": "*.secret,*.private"}):
            n = Normalizer(agent="test", fidelity=FidelityMode.FULL)
            trace = n.normalize(
                [{"type": "source", "content": "data", "path": "/app/config.secret"}],
                "ses-001",
            )
            assert trace.sources_read[0].content == ""


class TestEmptyEvents:
    def test_empty_list(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize([], "ses-001")
        assert trace.session_id == "ses-001"
        assert trace.agent == "test"
        assert trace.turn_count == 0

    def test_turn_count_matches_tools(self) -> None:
        n = Normalizer(agent="test")
        trace = n.normalize(
            [
                {"type": "tool", "tool_name": "A"},
                {"type": "tool", "tool_name": "B"},
                {"type": "tool", "tool_name": "C"},
            ],
            "ses-001",
        )
        assert trace.turn_count == 3
