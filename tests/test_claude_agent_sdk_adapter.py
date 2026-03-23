from __future__ import annotations

import asyncio

from openflux.adapters.claude_agent_sdk import ClaudeAgentSDKAdapter
from openflux.schema import Status, Trace


def _make_post_tool_use(
    session_id: str = "ses-abc",
    tool_name: str = "Bash",
    tool_input: dict | None = None,
    tool_response: str = "ok",
) -> dict:
    return {
        "hook_event_name": "post_tool_use",
        "session_id": session_id,
        "cwd": "/tmp/test",
        "tool_name": tool_name,
        "tool_input": tool_input or {"command": "echo hello"},
        "tool_response": tool_response,
        "tool_use_id": "tu-001",
    }


def _make_post_tool_use_failure(
    session_id: str = "ses-abc",
    tool_name: str = "Bash",
    tool_input: dict | None = None,
    error: str = "command not found",
) -> dict:
    return {
        "hook_event_name": "post_tool_use_failure",
        "session_id": session_id,
        "cwd": "/tmp/test",
        "tool_name": tool_name,
        "tool_input": tool_input or {"command": "bad_cmd"},
        "error": error,
        "tool_use_id": "tu-002",
        "is_interrupt": False,
    }


def _make_stop(session_id: str = "ses-abc") -> dict:
    return {
        "hook_event_name": "stop",
        "session_id": session_id,
        "cwd": "/tmp/test",
        "stop_hook_active": False,
    }


def _make_subagent_start(
    session_id: str = "ses-abc",
    agent_id: str = "sub-001",
    agent_type: str = "Explore",
) -> dict:
    return {
        "hook_event_name": "subagent_start",
        "session_id": session_id,
        "cwd": "/tmp/test",
        "agent_id": agent_id,
        "agent_type": agent_type,
    }


def _run(coro):
    return asyncio.run(coro)


class TestClaudeAgentSDKAdapter:
    def test_basic_tool_and_stop(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(agent="test-agent", on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))

        assert len(captured) == 1
        trace = captured[0]
        assert trace.agent == "test-agent"
        assert trace.status == Status.COMPLETED
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "Bash"
        assert trace.turn_count == 1
        assert trace.id.startswith("trc-")

    def test_tool_failure_sets_error_status(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_post_tool_use_failure(
                _make_post_tool_use_failure(),
                "tu-002",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))

        trace = captured[0]
        assert trace.status == Status.ERROR
        assert trace.tools_used[0].error is True
        assert "command not found" in trace.tools_used[0].tool_output

    def test_read_tool_creates_source_record(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use(
                    tool_name="Read",
                    tool_input={"file_path": "/tmp/foo.py"},
                    tool_response="def main(): pass",
                ),
                "tu-003",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))

        trace = captured[0]
        assert len(trace.sources_read) == 1
        src = trace.sources_read[0]
        assert src.type == "file"
        assert src.path == "/tmp/foo.py"
        assert src.tool == "Read"
        assert src.content_hash  # non-empty SHA-256

    def test_write_tool_tracks_files_modified(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use(
                    tool_name="Write",
                    tool_input={"file_path": "/tmp/out.py", "content": "x = 1"},
                    tool_response="",
                ),
                "tu-004",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))

        trace = captured[0]
        assert "/tmp/out.py" in trace.files_modified

    def test_subagent_start_recorded(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_subagent_start(
                _make_subagent_start(),
                "tu-005",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))

        trace = captured[0]
        assert trace.metadata["subagents"] == [
            {"agent_id": "sub-001", "agent_type": "Explore"},
        ]

    def test_record_usage(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        adapter.record_usage(
            "ses-abc",
            {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 50,
            },
            model="claude-sonnet-4-6",
        )
        _run(adapter._on_stop(_make_stop(), None, None))

        trace = captured[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 1000
        assert trace.token_usage.output_tokens == 500
        assert trace.token_usage.cache_read_tokens == 200
        assert trace.token_usage.cache_creation_tokens == 50
        assert trace.model == "claude-sonnet-4-6"

    def test_multiple_sessions_independent(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use(session_id="ses-1"),
                "tu-1",
                None,
            )
        )
        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use(session_id="ses-2"),
                "tu-2",
                None,
            )
        )
        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use(session_id="ses-2"),
                "tu-3",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(session_id="ses-1"), None, None))
        _run(adapter._on_stop(_make_stop(session_id="ses-2"), None, None))

        assert len(captured) == 2
        r1, r2 = captured
        assert r1.session_id == "ses-1"
        assert len(r1.tools_used) == 1
        assert r2.session_id == "ses-2"
        assert len(r2.tools_used) == 2

    def test_stop_without_events_produces_nothing(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_stop(_make_stop(session_id="ses-none"), None, None))
        assert len(captured) == 0

    def test_empty_session_id_ignored(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        event = _make_post_tool_use()
        event["session_id"] = ""
        _run(adapter._on_post_tool_use(event, None, None))

        assert len(adapter._sessions) == 0

    def test_create_hooks_returns_correct_keys(self) -> None:
        adapter = ClaudeAgentSDKAdapter()
        hooks = adapter.create_hooks()

        assert "PostToolUse" in hooks
        assert "PostToolUseFailure" in hooks
        assert "SubagentStart" in hooks
        assert "Stop" in hooks
        assert len(hooks) == 4

    def test_completed_traces_property(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))

        assert len(adapter.completed_traces) == 1
        assert adapter.completed_traces[0].session_id == "ses-abc"

    def test_cwd_stored_in_metadata(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))

        trace = captured[0]
        assert trace.metadata["environment"]["cwd"] == "/tmp/test"

    def test_webfetch_creates_url_source(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use(
                    tool_name="WebFetch",
                    tool_input={"url": "https://example.com/api"},
                    tool_response='{"data": 1}',
                ),
                "tu-006",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))

        trace = captured[0]
        assert len(trace.sources_read) == 1
        assert trace.sources_read[0].type == "url"
        assert trace.sources_read[0].path == "https://example.com/api"


class TestCreateOpenfluxHooks:
    def test_factory_returns_hooks_dict(self) -> None:
        from openflux.adapters.claude_agent_sdk import create_openflux_hooks

        hooks = create_openflux_hooks(agent="factory-test")
        assert "PostToolUse" in hooks
        assert "Stop" in hooks

    def test_hooks_are_callable(self) -> None:
        from openflux.adapters.claude_agent_sdk import create_openflux_hooks

        hooks = create_openflux_hooks()
        for matchers in hooks.values():
            for matcher in matchers:
                for hook in matcher.hooks:
                    assert callable(hook)
