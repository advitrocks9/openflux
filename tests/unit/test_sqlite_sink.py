from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    make_context_record,
    make_search_record,
    make_source_record,
    make_tool_record,
    make_trace,
)

from openflux.schema import ContextType, TokenUsage
from openflux.sinks.sqlite import SQLiteSink


@pytest.fixture()
def sink(sqlite_path: Path) -> SQLiteSink:
    s = SQLiteSink(path=sqlite_path)
    yield s
    s.close()


@pytest.mark.integration
class TestWriteRead:
    def test_roundtrip(self, sink: SQLiteSink) -> None:
        r = make_trace(
            token_usage=TokenUsage(input_tokens=100, output_tokens=50),
            tags=["test"],
            files_modified=["/a.py"],
        )
        sink.write(r)
        result = sink.get(r.id)
        assert result is not None
        assert result.id == r.id
        assert result.agent == r.agent
        assert result.session_id == r.session_id
        assert result.task == r.task
        assert result.tags == ["test"]
        assert result.files_modified == ["/a.py"]
        assert result.token_usage is not None
        assert result.token_usage.input_tokens == 100

    def test_get_nonexistent(self, sink: SQLiteSink) -> None:
        assert sink.get("trc-doesnotexist") is None

    def test_nested_records(self, sink: SQLiteSink) -> None:
        r = make_trace(
            context=[
                make_context_record(
                    type=ContextType.SYSTEM_PROMPT, source="sys.md", content="prompt"
                )
            ],
            searches=[
                make_search_record(query="find bugs", engine="Grep", results_count=3)
            ],
            sources_read=[
                make_source_record(path="/main.py", content="code", tool="Read")
            ],
            tools_used=[
                make_tool_record(
                    name="Bash", tool_input="ls", tool_output="a.py", duration_ms=10
                )
            ],
        )
        sink.write(r)
        result = sink.get(r.id)
        assert result is not None
        assert len(result.context) == 1
        assert result.context[0].type == ContextType.SYSTEM_PROMPT
        assert result.context[0].source == "sys.md"
        assert len(result.searches) == 1
        assert result.searches[0].query == "find bugs"
        assert len(result.sources_read) == 1
        assert result.sources_read[0].path == "/main.py"
        assert len(result.tools_used) == 1
        assert result.tools_used[0].name == "Bash"
        assert result.tools_used[0].duration_ms == 10


@pytest.mark.integration
class TestSearch:
    def test_by_task(self, sink: SQLiteSink) -> None:
        sink.write(make_trace(task="fix authentication bug"))
        sink.write(make_trace(task="add pagination feature"))
        results = sink.search("authentication")
        assert len(results) == 1
        assert results[0].task == "fix authentication bug"

    def test_by_decision(self, sink: SQLiteSink) -> None:
        sink.write(make_trace(decision="refactored the auth module"))
        assert len(sink.search("refactored")) == 1

    def test_no_results(self, sink: SQLiteSink) -> None:
        sink.write(make_trace(task="something else"))
        assert sink.search("nonexistent_term_xyz") == []

    def test_limit(self, sink: SQLiteSink) -> None:
        for i in range(10):
            sink.write(make_trace(task=f"deploy task {i}"))
        assert len(sink.search("deploy", limit=3)) == 3


@pytest.mark.integration
class TestRecent:
    def test_returns_latest(self, sink: SQLiteSink) -> None:
        for i in range(5):
            sink.write(make_trace(task=f"task {i}"))
        assert len(sink.recent(limit=3)) == 3

    def test_filter_by_agent(self, sink: SQLiteSink) -> None:
        sink.write(make_trace(agent="alpha", task="a"))
        sink.write(make_trace(agent="beta", task="b"))
        results = sink.recent(agent="alpha")
        assert len(results) == 1
        assert results[0].agent == "alpha"

    def test_filter_by_scope(self, sink: SQLiteSink) -> None:
        sink.write(make_trace(scope="backend", task="a"))
        sink.write(make_trace(scope="frontend", task="b"))
        results = sink.recent(scope="backend")
        assert len(results) == 1
        assert results[0].scope == "backend"

    def test_no_filters(self, sink: SQLiteSink) -> None:
        sink.write(make_trace())
        sink.write(make_trace())
        assert len(sink.recent()) == 2


@pytest.mark.integration
class TestForget:
    def test_deletes(self, sink: SQLiteSink) -> None:
        r = make_trace()
        sink.write(r)
        assert sink.get(r.id) is not None
        assert sink.forget(r.id) is True
        assert sink.get(r.id) is None

    def test_cascades_nested(self, sink: SQLiteSink) -> None:
        r = make_trace(
            context=[make_context_record()],
            searches=[make_search_record()],
            sources_read=[make_source_record()],
            tools_used=[make_tool_record()],
        )
        sink.write(r)
        sink.forget(r.id)
        conn = sink._conn
        for table in [
            "trace_context",
            "trace_searches",
            "trace_sources",
            "trace_tools",
        ]:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE trace_id = ?", (r.id,)
            ).fetchone()[0]
            assert count == 0, f"Expected 0 rows in {table}, got {count}"

    def test_nonexistent(self, sink: SQLiteSink) -> None:
        assert sink.forget("trc-doesnotexist") is False


@pytest.mark.integration
class TestFKCascade:
    def test_sql_delete_cascades(self, sink: SQLiteSink) -> None:
        r = make_trace(
            context=[make_context_record()],
            tools_used=[make_tool_record()],
        )
        sink.write(r)
        sink._conn.execute("DELETE FROM traces WHERE id = ?", (r.id,))
        sink._conn.commit()
        ctx_count = sink._conn.execute(
            "SELECT COUNT(*) FROM trace_context WHERE trace_id = ?", (r.id,)
        ).fetchone()[0]
        tool_count = sink._conn.execute(
            "SELECT COUNT(*) FROM trace_tools WHERE trace_id = ?", (r.id,)
        ).fetchone()[0]
        assert ctx_count == 0
        assert tool_count == 0


@pytest.mark.integration
class TestSourcesSummary:
    def test_most_accessed_first(self, sink: SQLiteSink) -> None:
        for _ in range(3):
            sink.write(
                make_trace(
                    sources_read=[
                        make_source_record(
                            path="/hot_file.py", timestamp="2026-03-20T00:00:00Z"
                        )
                    ]
                )
            )
        sink.write(
            make_trace(
                sources_read=[
                    make_source_record(
                        path="/cold_file.py", timestamp="2026-03-20T00:00:00Z"
                    )
                ]
            )
        )
        summary = sink.sources_summary(days=30)
        assert len(summary) >= 2
        assert summary[0]["path"] == "/hot_file.py"
        assert summary[0]["access_count"] == 3


@pytest.mark.integration
class TestSchemaMigration:
    def test_version_stored(self, sink: SQLiteSink) -> None:
        row = sink._conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        assert row is not None
        assert row[0] >= 1

    def test_reopen_preserves_data(self, sqlite_path: Path) -> None:
        s1 = SQLiteSink(path=sqlite_path)
        s1.write(make_trace(task="persisted"))
        s1.close()
        s2 = SQLiteSink(path=sqlite_path)
        results = s2.recent()
        assert len(results) == 1
        assert results[0].task == "persisted"
        s2.close()


@pytest.mark.integration
class TestExportJson:
    def test_export_all(self, sink: SQLiteSink) -> None:
        sink.write(make_trace(task="first"))
        sink.write(make_trace(task="second"))
        exported = sink.export_json()
        assert len(exported) == 2
        assert {e.task for e in exported} == {"first", "second"}

    def test_export_empty(self, sink: SQLiteSink) -> None:
        assert sink.export_json() == []


@pytest.mark.integration
class TestAll22FieldsRoundtrip:
    """Write a Trace with ALL 22 fields populated → SQLite → read back → compare."""

    def test_every_field_survives_roundtrip(self, sink: SQLiteSink) -> None:
        original = make_trace(
            agent="roundtrip-agent",
            parent_id="trc-parent-abc123",
            model="claude-sonnet-4-20250514",
            task="Implement OAuth2 PKCE flow",
            decision="Added PKCE to auth module, all tests pass",
            status="completed",
            correction="Initially used implicit flow, switched to PKCE",
            scope="auth-service",
            tags=["security", "auth", "pkce"],
            context=[
                make_context_record(
                    type=ContextType.SYSTEM_PROMPT,
                    source="system.md",
                    content="You are a security-focused developer.",
                )
            ],
            searches=[
                make_search_record(
                    query="OAuth2 PKCE best practices",
                    engine="web_search",
                    results_count=7,
                )
            ],
            sources_read=[
                make_source_record(
                    path="/src/auth/oauth.py",
                    content="class OAuthHandler: ...",
                    tool="Read",
                )
            ],
            tools_used=[
                make_tool_record(
                    name="Bash",
                    tool_input="pytest tests/ -v",
                    tool_output="12 passed",
                    duration_ms=3400,
                )
            ],
            files_modified=["/src/auth/oauth.py", "/tests/test_oauth.py"],
            turn_count=5,
            token_usage=TokenUsage(
                input_tokens=15000,
                output_tokens=3200,
                cache_read_tokens=5000,
                cache_creation_tokens=1200,
            ),
            duration_ms=45000,
            metadata={"environment": "ci", "commit": "abc123"},
        )

        sink.write(original)
        loaded = sink.get(original.id)
        assert loaded is not None

        # Scalar fields
        assert loaded.id == original.id
        assert loaded.timestamp == original.timestamp
        assert loaded.agent == "roundtrip-agent"
        assert loaded.session_id == original.session_id
        assert loaded.parent_id == "trc-parent-abc123"
        assert loaded.model == "claude-sonnet-4-20250514"
        assert loaded.task == "Implement OAuth2 PKCE flow"
        assert loaded.decision == "Added PKCE to auth module, all tests pass"
        assert loaded.status == "completed"
        assert loaded.correction == "Initially used implicit flow, switched to PKCE"
        assert loaded.scope == "auth-service"
        assert loaded.schema_version == original.schema_version
        assert loaded.turn_count == 5
        assert loaded.duration_ms == 45000

        # List fields
        assert loaded.tags == ["security", "auth", "pkce"]
        assert loaded.files_modified == [
            "/src/auth/oauth.py",
            "/tests/test_oauth.py",
        ]

        # Token usage
        assert loaded.token_usage is not None
        assert loaded.token_usage.input_tokens == 15000
        assert loaded.token_usage.output_tokens == 3200
        assert loaded.token_usage.cache_read_tokens == 5000
        assert loaded.token_usage.cache_creation_tokens == 1200

        # Nested records
        assert len(loaded.context) == 1
        assert loaded.context[0].type == ContextType.SYSTEM_PROMPT
        assert loaded.context[0].source == "system.md"
        assert "security-focused" in loaded.context[0].content

        assert len(loaded.searches) == 1
        assert loaded.searches[0].query == "OAuth2 PKCE best practices"
        assert loaded.searches[0].engine == "web_search"
        assert loaded.searches[0].results_count == 7

        assert len(loaded.sources_read) == 1
        assert loaded.sources_read[0].path == "/src/auth/oauth.py"
        assert loaded.sources_read[0].tool == "Read"

        assert len(loaded.tools_used) == 1
        assert loaded.tools_used[0].name == "Bash"
        assert loaded.tools_used[0].duration_ms == 3400
        assert loaded.tools_used[0].tool_output == "12 passed"

        # Metadata
        assert loaded.metadata == {"environment": "ci", "commit": "abc123"}
