from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Patch mcp.server.fastmcp before importing the adapter
_registered_tools: dict[str, Any] = {}
_registered_resources: dict[str, Any] = {}


class FakeFastMCP:
    """Minimal stand-in for FastMCP that captures registrations."""

    def __init__(self, name: str = "test", **kwargs: Any) -> None:
        self.name = name
        _registered_tools.clear()
        _registered_resources.clear()

    def tool(self) -> Any:
        def decorator(fn: Any) -> Any:
            _registered_tools[fn.__name__] = fn
            return fn

        return decorator

    def resource(self, uri: str) -> Any:
        def decorator(fn: Any) -> Any:
            _registered_resources[uri] = fn
            return fn

        return decorator

    def run(self, **kwargs: Any) -> None:
        pass


@pytest.fixture(autouse=True)
def _patch_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    # Create fake mcp module hierarchy
    mcp_mod = MagicMock()
    mcp_server = MagicMock()
    mcp_fastmcp = MagicMock()
    mcp_fastmcp.FastMCP = FakeFastMCP

    sys.modules["mcp"] = mcp_mod
    sys.modules["mcp.server"] = mcp_server
    sys.modules["mcp.server.fastmcp"] = mcp_fastmcp

    mod_name = "openflux.adapters.mcp"
    if mod_name in sys.modules:
        del sys.modules[mod_name]

    yield

    for mod in ["mcp", "mcp.server", "mcp.server.fastmcp"]:
        sys.modules.pop(mod, None)
    if mod_name in sys.modules:
        del sys.modules[mod_name]


@pytest.fixture()
def adapter(tmp_path: Path) -> Any:
    from openflux.adapters.mcp import MCPServerAdapter

    return MCPServerAdapter(agent="test-agent", db_path=tmp_path / "test.db")


@pytest.fixture()
def db_path(adapter: Any, tmp_path: Path) -> Path:
    return tmp_path / "test.db"


class TestTraceRecord:
    def test_record_returns_id(self, adapter: Any) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(fn(task="deployed v2"))
        assert result["recorded"].startswith("trc-")
        assert "timestamp" in result

    def test_record_persists_to_sqlite(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(fn(task="ran migrations", decision="all passed"))

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert trace.task == "ran migrations"
        assert trace.decision == "all passed"
        assert trace.agent == "test-agent"

    def test_record_custom_agent(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(fn(task="fix bug", agent="custom-agent"))

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert trace.agent == "custom-agent"

    def test_record_all_fields(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(
            fn(
                task="refactor auth",
                decision="extracted middleware",
                model="claude-sonnet-4-20250514",
                status="completed",
                scope="auth",
                tags=["refactor", "security"],
                files_modified=["src/auth.py"],
                correction="fixed import order",
                duration_ms=1500,
                metadata={"pr": "123"},
            )
        )

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert trace.model == "claude-sonnet-4-20250514"
        assert trace.scope == "auth"
        assert trace.tags == ["refactor", "security"]
        assert trace.files_modified == ["src/auth.py"]
        assert trace.correction == "fixed import order"
        assert trace.duration_ms == 1500

    def test_record_invalid_status_defaults(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(fn(task="bad status", status="bogus"))

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert trace.status == "completed"

    def test_record_token_usage(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(
            fn(
                task="summarize docs",
                input_tokens=1500,
                output_tokens=800,
                cache_read_tokens=200,
                cache_creation_tokens=100,
            )
        )

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 1500
        assert trace.token_usage.output_tokens == 800
        assert trace.token_usage.cache_read_tokens == 200
        assert trace.token_usage.cache_creation_tokens == 100

    def test_record_no_token_usage_when_zero(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(fn(task="no tokens"))

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        # SQLite sink stores zeros and reconstructs TokenUsage on read,
        # so we verify the values are all zero
        if trace.token_usage is not None:
            assert trace.token_usage.input_tokens == 0
            assert trace.token_usage.output_tokens == 0

    def test_record_tools_used(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(
            fn(
                task="debug issue",
                tools_used=[
                    {"name": "bash", "tool_input": "ls", "duration_ms": 50},
                    {"name": "read", "tool_input": "src/main.py"},
                ],
            )
        )

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert len(trace.tools_used) == 2
        assert trace.tools_used[0].name == "bash"
        assert trace.tools_used[0].duration_ms == 50
        assert trace.tools_used[1].name == "read"

    def test_record_context(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(
            fn(
                task="answer question",
                context=[
                    {"type": "system_prompt", "source": "CLAUDE.md", "bytes": 2048}
                ],
            )
        )

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert len(trace.context) == 1
        assert trace.context[0].type == "system_prompt"
        assert trace.context[0].source == "CLAUDE.md"

    def test_record_searches(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(
            fn(
                task="research topic",
                searches=[
                    {"query": "python async", "engine": "google", "results_count": 10}
                ],
            )
        )

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert len(trace.searches) == 1
        assert trace.searches[0].query == "python async"

    def test_record_sources_read(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(
            fn(
                task="review code",
                sources_read=[
                    {"type": "file", "path": "src/main.py", "bytes_read": 4096}
                ],
            )
        )

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert len(trace.sources_read) == 1
        assert trace.sources_read[0].path == "src/main.py"

    def test_record_turn_count(self, adapter: Any, db_path: Path) -> None:
        fn = _registered_tools["trace_record"]
        result = json.loads(fn(task="multi-turn chat", turn_count=5))

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(result["recorded"])
        sink.close()

        assert trace is not None
        assert trace.turn_count == 5


class TestTraceUpdate:
    def test_update_appends_tools(self, adapter: Any, db_path: Path) -> None:
        record_fn = _registered_tools["trace_record"]
        result = json.loads(
            record_fn(
                task="multi-step",
                tools_used=[{"name": "bash", "tool_input": "ls"}],
            )
        )
        trace_id = result["recorded"]

        update_fn = _registered_tools["trace_update"]
        update_result = json.loads(
            update_fn(
                trace_id=trace_id,
                tools_used=[{"name": "read", "tool_input": "file.py"}],
            )
        )
        assert update_result["updated"] == trace_id

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(trace_id)
        sink.close()

        assert trace is not None
        assert len(trace.tools_used) == 2
        assert trace.tools_used[0].name == "bash"
        assert trace.tools_used[1].name == "read"

    def test_update_merges_token_usage(self, adapter: Any, db_path: Path) -> None:
        record_fn = _registered_tools["trace_record"]
        result = json.loads(record_fn(task="chat", input_tokens=100, output_tokens=50))
        trace_id = result["recorded"]

        update_fn = _registered_tools["trace_update"]
        update_fn(trace_id=trace_id, input_tokens=200, output_tokens=150)

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(trace_id)
        sink.close()

        assert trace is not None
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 300
        assert trace.token_usage.output_tokens == 200

    def test_update_adds_token_usage_when_none(
        self, adapter: Any, db_path: Path
    ) -> None:
        record_fn = _registered_tools["trace_record"]
        result = json.loads(record_fn(task="no tokens initially"))
        trace_id = result["recorded"]

        update_fn = _registered_tools["trace_update"]
        update_fn(trace_id=trace_id, input_tokens=500, output_tokens=250)

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(trace_id)
        sink.close()

        assert trace is not None
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 500

    def test_update_replaces_turn_count(self, adapter: Any, db_path: Path) -> None:
        record_fn = _registered_tools["trace_record"]
        result = json.loads(record_fn(task="session", turn_count=1))
        trace_id = result["recorded"]

        update_fn = _registered_tools["trace_update"]
        update_fn(trace_id=trace_id, turn_count=3)

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(trace_id)
        sink.close()

        assert trace is not None
        assert trace.turn_count == 3

    def test_update_replaces_status_and_decision(
        self, adapter: Any, db_path: Path
    ) -> None:
        record_fn = _registered_tools["trace_record"]
        result = json.loads(record_fn(task="in progress work"))
        trace_id = result["recorded"]

        update_fn = _registered_tools["trace_update"]
        update_fn(trace_id=trace_id, status="error", decision="failed due to timeout")

        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        trace = sink.get(trace_id)
        sink.close()

        assert trace is not None
        assert trace.status == "error"
        assert trace.decision == "failed due to timeout"

    def test_update_not_found(self, adapter: Any) -> None:
        update_fn = _registered_tools["trace_update"]
        result = json.loads(update_fn(trace_id="trc-nonexistent"))
        assert "error" in result


class TestTraceSearch:
    def _seed(self, db_path: Path) -> None:
        from openflux._util import generate_trace_id, utc_now
        from openflux.schema import Trace
        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        for i, (task, scope) in enumerate(
            [
                ("deploy api server", "infra"),
                ("fix auth bug in login", "auth"),
                ("refactor database queries", "db"),
            ]
        ):
            sink.write(
                Trace(
                    id=generate_trace_id(),
                    timestamp=utc_now(),
                    agent="test-agent",
                    session_id=f"ses-seed-{i}",
                    task=task,
                    scope=scope,
                )
            )
        sink.close()

    def test_search_finds_match(self, adapter: Any, db_path: Path) -> None:
        self._seed(db_path)
        fn = _registered_tools["trace_search"]
        results = json.loads(fn(query="auth bug"))
        assert len(results) >= 1
        assert any("auth" in r["task"] for r in results)

    def test_search_empty_results(self, adapter: Any, db_path: Path) -> None:
        self._seed(db_path)
        fn = _registered_tools["trace_search"]
        results = json.loads(fn(query="nonexistent_xyzzy_thing"))
        assert results == []

    def test_search_filter_by_scope(self, adapter: Any, db_path: Path) -> None:
        self._seed(db_path)
        fn = _registered_tools["trace_search"]
        results = json.loads(fn(query="deploy OR fix OR refactor", scope="infra"))
        assert all(r.get("scope") == "infra" for r in results)


class TestResources:
    def _seed(self, db_path: Path, count: int = 3) -> None:
        from openflux._util import generate_trace_id, utc_now
        from openflux.schema import Trace
        from openflux.sinks.sqlite import SQLiteSink

        sink = SQLiteSink(path=db_path)
        for i in range(count):
            sink.write(
                Trace(
                    id=generate_trace_id(),
                    timestamp=utc_now(),
                    agent="test-agent",
                    session_id=f"ses-res-{i}",
                    task=f"task number {i}",
                    decision=f"decided {i}",
                )
            )
        sink.close()

    def test_recent_resource(self, adapter: Any, db_path: Path) -> None:
        self._seed(db_path, count=5)
        fn = _registered_resources["trace://recent"]
        results = json.loads(fn())
        assert len(results) == 5
        assert all("task" in r for r in results)

    def test_recent_empty_db(self, adapter: Any) -> None:
        fn = _registered_resources["trace://recent"]
        results = json.loads(fn())
        assert results == []

    def test_context_resource(self, adapter: Any, db_path: Path) -> None:
        self._seed(db_path)
        fn = _registered_resources["trace://context/{topic}"]
        results = json.loads(fn(topic="decided"))
        assert len(results) >= 1


class TestServerProperties:
    def test_server_property(self, adapter: Any) -> None:
        assert isinstance(adapter.server, FakeFastMCP)
        assert adapter.server.name == "OpenFlux"

    def test_run_delegates(self, adapter: Any) -> None:
        # Just verify it doesn't crash
        adapter.run(transport="stdio")


class TestImportGuard:
    def test_missing_mcp_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import importlib
        import sys

        for mod in ["mcp", "mcp.server", "mcp.server.fastmcp"]:
            sys.modules.pop(mod, None)
        mod_name = "openflux.adapters.mcp"
        sys.modules.pop(mod_name, None)

        monkeypatch.setitem(sys.modules, "mcp", None)
        monkeypatch.setitem(sys.modules, "mcp.server", None)
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
        sys.modules.pop(mod_name, None)

        import openflux.adapters.mcp as mcp_mod

        importlib.reload(mcp_mod)

        with pytest.raises(ImportError, match="MCP SDK not installed"):
            mcp_mod.MCPServerAdapter()
