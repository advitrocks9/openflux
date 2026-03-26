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


def _make_subagent_stop(
    session_id: str = "ses-abc",
    agent_id: str = "sub-001",
    agent_type: str = "Explore",
    agent_transcript_path: str = "/tmp/transcript.jsonl",
) -> dict:
    return {
        "hook_event_name": "subagent_stop",
        "session_id": session_id,
        "cwd": "/tmp/test",
        "agent_id": agent_id,
        "agent_type": agent_type,
        "agent_transcript_path": agent_transcript_path,
        "stop_hook_active": False,
    }


def _make_user_prompt_submit(
    session_id: str = "ses-abc",
    prompt: str = "Read the file and explain it",
) -> dict:
    return {
        "hook_event_name": "user_prompt_submit",
        "session_id": session_id,
        "cwd": "/tmp/test",
        "prompt": prompt,
    }


def _run(coro):
    return asyncio.run(coro)


class TestClaudeAgentSDKAdapter:
    def test_basic_tool_and_stop(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(agent="test-agent", on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        assert len(captured) == 1
        trace = captured[0]
        assert trace.agent == "test-agent"
        assert trace.status == Status.COMPLETED
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "Bash"
        assert trace.turn_count == 1
        assert trace.id.startswith("trc-")

    def test_tool_failure_defaults_completed(self) -> None:
        """Tool failures alone don't mark trace as ERROR (agent may recover)."""
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
        adapter.finalize()

        trace = captured[0]
        # Status defaults to COMPLETED; caller can override via record_usage(status=...)
        assert trace.status == Status.COMPLETED
        assert trace.tools_used[0].error is True
        assert "command not found" in trace.tools_used[0].tool_output
        # Tool error count preserved in metadata for observability
        assert trace.metadata["tool_errors_count"] == 1

    def test_explicit_error_status_via_record_usage(self) -> None:
        """Caller can explicitly set ERROR status via record_usage."""
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.record_usage(
            "ses-abc",
            {"input_tokens": 100, "output_tokens": 50},
            status=Status.ERROR,
        )

        trace = captured[0]
        assert trace.status == Status.ERROR

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
        adapter.finalize()

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
        adapter.finalize()

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
        adapter.finalize()

        trace = captured[0]
        assert trace.metadata["subagents"] == [
            {"agent_id": "sub-001", "agent_type": "Explore"},
        ]

    def test_record_usage_patches_completed_trace(self) -> None:
        """record_usage called after stop patches the trace and triggers on_trace."""
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))

        # Simulate ResultMessage arriving after Stop hook
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

        assert len(captured) == 1
        trace = captured[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 1000
        assert trace.token_usage.output_tokens == 500
        assert trace.token_usage.cache_read_tokens == 200
        assert trace.token_usage.cache_creation_tokens == 50
        assert trace.model == "claude-sonnet-4-6"

    def test_record_usage_before_stop(self) -> None:
        """record_usage called before stop stores data on accumulator."""
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        adapter.record_usage(
            "ses-abc",
            {"input_tokens": 100, "output_tokens": 50},
            model="claude-haiku-4-5-20251001",
        )
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 100
        assert trace.model == "claude-haiku-4-5-20251001"

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
        adapter.finalize()

        assert len(captured) == 2
        r1, r2 = captured
        assert r1.session_id == "ses-1"
        assert len(r1.tools_used) == 1
        assert r2.session_id == "ses-2"
        assert len(r2.tools_used) == 2

    def test_stop_without_events_creates_trace(self) -> None:
        """Stop with no prior tool events still creates a minimal trace."""
        adapter = ClaudeAgentSDKAdapter()

        _run(adapter._on_stop(_make_stop(session_id="ses-none"), None, None))
        adapter.finalize()

        assert len(adapter.completed_traces) == 1
        assert adapter.completed_traces[0].session_id == "ses-none"
        assert len(adapter.completed_traces[0].tools_used) == 0

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

        assert "UserPromptSubmit" in hooks
        assert "PreToolUse" in hooks
        assert "PostToolUse" in hooks
        assert "PostToolUseFailure" in hooks
        assert "SubagentStart" in hooks
        assert "SubagentStop" in hooks
        assert "Stop" in hooks
        assert len(hooks) == 7

    def test_completed_traces_property(self) -> None:
        adapter = ClaudeAgentSDKAdapter()

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))

        assert len(adapter.completed_traces) == 1
        assert adapter.completed_traces[0].session_id == "ses-abc"

    def test_cwd_stored_in_metadata(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

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
        adapter.finalize()

        trace = captured[0]
        assert len(trace.sources_read) == 1
        assert trace.sources_read[0].type == "url"
        assert trace.sources_read[0].path == "https://example.com/api"

    def test_user_prompt_submit_sets_task(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_user_prompt_submit(
                _make_user_prompt_submit(prompt="Fix the bug in main.py"),
                None,
                None,
            )
        )
        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert trace.task == "Fix the bug in main.py"

    def test_record_usage_wires_duration_and_decision(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_post_tool_use(_make_post_tool_use(), "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))

        adapter.record_usage(
            "ses-abc",
            {"input_tokens": 500, "output_tokens": 200},
            model="claude-haiku-4-5-20251001",
            duration_ms=3500,
            result="The bug was in line 42.",
            num_turns=3,
        )

        trace = captured[0]
        assert trace.duration_ms == 3500
        assert trace.decision == "The bug was in line 42."
        assert trace.turn_count == 3

    def test_record_usage_before_stop_wires_duration(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        adapter.record_usage(
            "ses-abc",
            {"input_tokens": 100, "output_tokens": 50},
            duration_ms=2000,
            result="Done.",
            num_turns=1,
        )
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert trace.duration_ms == 2000
        assert trace.decision == "Done."
        assert trace.turn_count == 1

    def test_subagent_stop_updates_existing_entry(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(adapter._on_subagent_start(_make_subagent_start(), "tu-005", None))
        _run(
            adapter._on_subagent_stop(
                _make_subagent_stop(agent_transcript_path="/tmp/sub-transcript.jsonl"),
                None,
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        subs = trace.metadata["subagents"]
        assert len(subs) == 1
        assert subs[0]["agent_id"] == "sub-001"
        assert subs[0]["transcript_path"] == "/tmp/sub-transcript.jsonl"

    def test_subagent_stop_without_start(self) -> None:
        """SubagentStop without prior SubagentStart still records."""
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_subagent_stop(
                _make_subagent_stop(agent_id="sub-new"),
                None,
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        subs = trace.metadata["subagents"]
        assert len(subs) == 1
        assert subs[0]["agent_id"] == "sub-new"
        assert subs[0]["transcript_path"] == "/tmp/transcript.jsonl"

    def test_search_tool_creates_search_record(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use(
                    tool_name="Grep",
                    tool_input={"pattern": "def main", "path": "/tmp"},
                    tool_response="/tmp/foo.py:1:def main():\n"
                    "/tmp/bar.py:5:def main():",
                ),
                "tu-007",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert len(trace.searches) == 1
        assert trace.searches[0].query == "def main"
        assert trace.searches[0].engine == "Grep"
        assert trace.searches[0].results_count == 2

    def test_websearch_creates_search_record(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use(
                    tool_name="WebSearch",
                    tool_input={"query": "python asyncio tutorial"},
                    tool_response="Result 1\nResult 2\nResult 3",
                ),
                "tu-008",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert len(trace.searches) == 1
        assert trace.searches[0].query == "python asyncio tutorial"
        assert trace.searches[0].engine == "WebSearch"

    def test_glob_creates_search_record(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use(
                    tool_name="Glob",
                    tool_input={"pattern": "**/*.py"},
                    tool_response="a.py\nb.py",
                ),
                "tu-009",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert len(trace.searches) == 1
        assert trace.searches[0].query == "**/*.py"
        assert trace.searches[0].engine == "Glob"

    def test_failed_search_not_recorded(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        _run(
            adapter._on_post_tool_use_failure(
                _make_post_tool_use_failure(
                    tool_name="Grep",
                    tool_input={"pattern": "missing"},
                    error="no matches",
                ),
                "tu-010",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert len(trace.searches) == 0

    def test_scope_and_tags_set_on_trace(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(
            on_trace=captured.append,
            scope="coding",
            tags=["bugfix", "urgent"],
        )

        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert trace.scope == "coding"
        assert trace.tags == ["bugfix", "urgent"]

    def test_system_prompt_creates_context_record(self) -> None:
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(
            on_trace=captured.append,
            system_prompt="You are a helpful assistant.",
        )

        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert len(trace.context) == 1
        ctx = trace.context[0]
        assert ctx.type == "system_prompt"
        assert ctx.content == "You are a helpful assistant."
        assert ctx.content_hash  # non-empty SHA-256

    def test_dict_tool_response_serialized_as_json(self) -> None:
        """Dict tool_response should be json.dumps'd, not str()."""
        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        event = _make_post_tool_use(tool_response='{"key": "val"}')
        # Simulate a dict response (SDK returns Any)
        event["tool_response"] = {"key": "val"}
        _run(adapter._on_post_tool_use(event, "tu-001", None))
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        output = trace.tools_used[0].tool_output
        # Should be valid JSON, not Python repr
        assert '"key"' in output
        assert "'" not in output  # no Python single-quote repr

    def test_pre_tool_use_enables_duration(self) -> None:
        """PreToolUse → PostToolUse computes non-zero duration_ms."""
        import time as _time

        captured: list[Trace] = []
        adapter = ClaudeAgentSDKAdapter(on_trace=captured.append)

        pre_event = {
            "session_id": "ses-abc",
            "tool_use_id": "tu-dur",
            "tool_name": "Bash",
        }
        _run(adapter._on_pre_tool_use(pre_event, "tu-dur", None))
        _time.sleep(0.01)  # 10ms minimum
        _run(
            adapter._on_post_tool_use(
                _make_post_tool_use() | {"tool_use_id": "tu-dur"},
                "tu-dur",
                None,
            )
        )
        _run(adapter._on_stop(_make_stop(), None, None))
        adapter.finalize()

        trace = captured[0]
        assert trace.tools_used[0].duration_ms >= 10


class TestCreateOpenfluxHooks:
    def test_factory_returns_hooks_and_adapter(self) -> None:
        from openflux.adapters.claude_agent_sdk import create_openflux_hooks

        hooks, adapter = create_openflux_hooks(agent="factory-test")
        assert "PostToolUse" in hooks
        assert "Stop" in hooks
        assert isinstance(adapter, ClaudeAgentSDKAdapter)

    def test_hooks_are_callable(self) -> None:
        from openflux.adapters.claude_agent_sdk import create_openflux_hooks

        hooks, _adapter = create_openflux_hooks()
        for matchers in hooks.values():
            for matcher in matchers:
                for hook in matcher.hooks:
                    assert callable(hook)
