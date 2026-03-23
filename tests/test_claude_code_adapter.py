from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from openflux.adapters._claude_code import (
    CORRECTION_PATTERN,
    ClaudeCodeAdapter,
    SessionMeta,
    _append_event,
    _buffer_path,
    _build_trace,
    _classify_tool,
    _cleanup,
    _meta_path,
    _read_buffer,
    handle_post_tool_use,
    handle_post_tool_use_failure,
    handle_session_end,
    handle_session_start,
)
from openflux.schema import FidelityMode, SourceType, Status


@pytest.fixture()
def session_id() -> str:
    return "test-session-001"


@pytest.fixture()
def _patch_openflux_dir(tmp_path: Path) -> Any:
    with patch("openflux.adapters._claude_code._OPENFLUX_DIR", tmp_path):
        yield tmp_path


@pytest.fixture()
def fidelity() -> FidelityMode:
    return FidelityMode.FULL


@pytest.fixture()
def exclude_patterns() -> list[str]:
    return []


class TestClassifyTool:
    def test_read(self, fidelity: FidelityMode, exclude_patterns: list[str]) -> None:
        result = _classify_tool(
            "Read",
            {"file_path": "/src/main.py"},
            "print('hello')",
            error=False,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        assert len(result["sources"]) == 1
        src = result["sources"][0]
        assert src["type"] == SourceType.FILE
        assert src["path"] == "/src/main.py"
        assert src["tool"] == "Read"
        assert src["content_hash"] != ""
        assert result["searches"] == []
        assert result["tools"] == []

    def test_web_search(
        self, fidelity: FidelityMode, exclude_patterns: list[str]
    ) -> None:
        result = _classify_tool(
            "WebSearch",
            {"query": "python dataclasses"},
            "result1\nresult2\nresult3",
            error=False,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        assert len(result["searches"]) == 1
        assert result["searches"][0]["query"] == "python dataclasses"
        assert result["searches"][0]["engine"] == "web_search"
        assert result["searches"][0]["results_count"] == 3
        assert result["sources"] == []

    def test_web_fetch(
        self, fidelity: FidelityMode, exclude_patterns: list[str]
    ) -> None:
        result = _classify_tool(
            "WebFetch",
            {"url": "https://example.com/docs"},
            "<html>content</html>",
            error=False,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        assert len(result["sources"]) == 1
        assert result["sources"][0]["type"] == SourceType.URL
        assert result["sources"][0]["path"] == "https://example.com/docs"
        assert result["sources"][0]["tool"] == "WebFetch"

    def test_bash(self, fidelity: FidelityMode, exclude_patterns: list[str]) -> None:
        result = _classify_tool(
            "Bash",
            {"command": "ls -la"},
            "total 0\ndrwxr-xr-x",
            error=False,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "Bash"
        assert result["sources"] == []
        assert result["searches"] == []

    @pytest.mark.parametrize("tool_name", ["Grep", "Glob"])
    def test_grep_glob(
        self,
        tool_name: str,
        fidelity: FidelityMode,
        exclude_patterns: list[str],
    ) -> None:
        result = _classify_tool(
            tool_name,
            {"pattern": "TODO"},
            "src/a.py:10:TODO fix\nsrc/b.py:20:TODO refactor",
            error=False,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        assert len(result["searches"]) == 1
        assert result["searches"][0]["query"] == "TODO"
        assert result["searches"][0]["engine"] == tool_name.lower()
        assert len(result["sources"]) == 2

    @pytest.mark.parametrize("tool_name", ["Edit", "Write"])
    def test_edit_write(
        self,
        tool_name: str,
        fidelity: FidelityMode,
        exclude_patterns: list[str],
    ) -> None:
        result = _classify_tool(
            tool_name,
            {"file_path": "/src/app.py", "content": "new content"},
            "OK",
            error=False,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        assert len(result["sources"]) == 1
        assert result["sources"][0]["type"] == SourceType.FILE
        assert result["sources"][0]["tool"] == tool_name
        assert "/src/app.py" in result["files_modified"]

    def test_unknown_tool(
        self, fidelity: FidelityMode, exclude_patterns: list[str]
    ) -> None:
        result = _classify_tool(
            "CustomTool",
            {"arg": "val"},
            "output",
            error=False,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        assert len(result["tools"]) == 1
        assert result["tools"][0]["name"] == "CustomTool"

    def test_exclude_pattern_blanks_content(self) -> None:
        result = _classify_tool(
            "Read",
            {"file_path": "/secrets/.env"},
            "SECRET_KEY=abc123",
            error=False,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=FidelityMode.FULL,
            exclude_patterns=["*.env"],
        )
        src = result["sources"][0]
        assert src["content"] == ""
        assert src["content_hash"] != ""

    def test_redacted_blanks_content(self) -> None:
        result = _classify_tool(
            "Read",
            {"file_path": "/src/main.py"},
            "print('hello')",
            error=False,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=FidelityMode.REDACTED,
            exclude_patterns=[],
        )
        assert result["sources"][0]["content"] == ""

    def test_error_flag(
        self, fidelity: FidelityMode, exclude_patterns: list[str]
    ) -> None:
        result = _classify_tool(
            "Bash",
            {"command": "false"},
            "command failed",
            error=True,
            timestamp="2026-01-01T00:00:00Z",
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        assert result["tools"][0]["error"] is True


class TestBufferIO:
    def test_append_and_read(self, session_id: str, _patch_openflux_dir: Any) -> None:
        _append_event(session_id, {"tool_name": "Read", "timestamp": "t1"})
        _append_event(session_id, {"tool_name": "Bash", "timestamp": "t2"})
        events = _read_buffer(session_id)
        assert len(events) == 2
        assert events[0]["tool_name"] == "Read"
        assert events[1]["tool_name"] == "Bash"

    def test_ndjson_format(self, session_id: str, _patch_openflux_dir: Any) -> None:
        _append_event(session_id, {"a": 1})
        _append_event(session_id, {"b": 2})
        buf = _buffer_path(session_id)
        lines = buf.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            json.loads(line)

    def test_read_empty(self, session_id: str, _patch_openflux_dir: Any) -> None:
        assert _read_buffer(session_id) == []

    def test_cleanup(self, session_id: str, _patch_openflux_dir: Any) -> None:
        _append_event(session_id, {"x": 1})
        meta = _meta_path(session_id)
        meta.write_text("{}", encoding="utf-8")
        assert _buffer_path(session_id).exists()
        assert meta.exists()
        _cleanup(session_id)
        assert not _buffer_path(session_id).exists()
        assert not meta.exists()


class TestFileLocking:
    def test_lock_on_append(self, session_id: str, _patch_openflux_dir: Any) -> None:
        mock_lock = MagicMock()
        mock_unlock = MagicMock()
        with (
            patch("openflux.adapters._claude_code._lock_file", mock_lock),
            patch("openflux.adapters._claude_code._unlock_file", mock_unlock),
        ):
            _append_event(session_id, {"test": True})
            assert mock_lock.call_count == 1
            assert mock_unlock.call_count == 1

    def test_lock_on_read(self, session_id: str, _patch_openflux_dir: Any) -> None:
        _append_event(session_id, {"test": True})
        mock_lock = MagicMock()
        mock_unlock = MagicMock()
        with (
            patch("openflux.adapters._claude_code._lock_file", mock_lock),
            patch("openflux.adapters._claude_code._unlock_file", mock_unlock),
        ):
            _read_buffer(session_id)
            assert mock_lock.call_count == 1
            assert mock_unlock.call_count == 1


class TestSessionLifecycle:
    def test_start_creates_files(self, _patch_openflux_dir: Any) -> None:
        handle_session_start(
            {
                "session_id": "ses-abc123",
                "cwd": "/project",
                "model": "claude-sonnet-4-20250514",
            }
        )
        assert _buffer_path("ses-abc123").exists()
        meta = _meta_path("ses-abc123")
        assert meta.exists()
        meta_data = json.loads(meta.read_text(encoding="utf-8"))
        assert meta_data["cwd"] == "/project"
        assert meta_data["model"] == "claude-sonnet-4-20250514"

    def test_tool_use_appends(self, _patch_openflux_dir: Any) -> None:
        sid = "ses-tool-test"
        handle_session_start({"session_id": sid})
        handle_post_tool_use(
            {
                "session_id": sid,
                "tool_name": "Read",
                "tool_input": {"file_path": "/a.py"},
                "tool_response": "content",
            }
        )
        events = _read_buffer(sid)
        assert len(events) == 1
        assert events[0]["tool_name"] == "Read"

    def test_failure_marks_error(self, _patch_openflux_dir: Any) -> None:
        sid = "ses-fail-test"
        handle_session_start({"session_id": sid})
        handle_post_tool_use_failure(
            {
                "session_id": sid,
                "tool_name": "Bash",
                "tool_input": {"command": "exit 1"},
                "tool_response": "command failed",
            }
        )
        events = _read_buffer(sid)
        assert len(events) == 1
        assert events[0]["error"] is True

    def test_full_lifecycle(self, _patch_openflux_dir: Any) -> None:
        sid = "ses-lifecycle"
        handle_session_start({"session_id": sid, "model": "claude-sonnet-4-20250514"})
        handle_post_tool_use(
            {
                "session_id": sid,
                "tool_name": "Read",
                "tool_input": {"file_path": "/main.py"},
                "tool_response": "code",
            }
        )
        handle_post_tool_use(
            {
                "session_id": sid,
                "tool_name": "Edit",
                "tool_input": {"file_path": "/main.py", "new_string": "new code"},
                "tool_response": "OK",
            }
        )
        with patch("openflux.adapters._claude_code._write_to_sinks") as mock_sink:
            handle_session_end({"session_id": sid})
            assert mock_sink.call_count == 1
            trace = mock_sink.call_args[0][0]
            assert trace.agent == "claude-code"
            assert trace.session_id == sid
            assert trace.model == "claude-sonnet-4-20250514"
            assert len(trace.sources_read) == 2
            assert "/main.py" in trace.files_modified
            assert trace.status == Status.COMPLETED

    def test_error_status(self, _patch_openflux_dir: Any) -> None:
        sid = "ses-err"
        handle_session_start({"session_id": sid})
        handle_post_tool_use_failure(
            {
                "session_id": sid,
                "tool_name": "Bash",
                "tool_input": {"command": "false"},
                "error": "failed",
            }
        )
        with patch("openflux.adapters._claude_code._write_to_sinks") as mock_sink:
            handle_session_end({"session_id": sid})
            trace = mock_sink.call_args[0][0]
            assert trace.status == Status.ERROR

    def test_empty_session_cleans_up(self, _patch_openflux_dir: Any) -> None:
        sid = "ses-empty"
        handle_session_start({"session_id": sid})
        with patch("openflux.adapters._claude_code._write_to_sinks") as mock_sink:
            handle_session_end({"session_id": sid})
            mock_sink.assert_not_called()
        assert not _buffer_path(sid).exists()

    def test_missing_session_id_noop(self, _patch_openflux_dir: Any) -> None:
        handle_post_tool_use({"tool_name": "Read"})
        handle_post_tool_use_failure({"tool_name": "Bash"})
        handle_session_end({})

    def test_files_modified_deduped(self, _patch_openflux_dir: Any) -> None:
        sid = "ses-dedup"
        handle_session_start({"session_id": sid})
        for _ in range(3):
            handle_post_tool_use(
                {
                    "session_id": sid,
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "/same.py", "new_string": "x"},
                    "tool_response": "OK",
                }
            )
        with patch("openflux.adapters._claude_code._write_to_sinks") as mock_sink:
            handle_session_end({"session_id": sid})
            trace = mock_sink.call_args[0][0]
            assert trace.files_modified.count("/same.py") == 1


class TestErrorHandling:
    def test_dict_response(self, _patch_openflux_dir: Any) -> None:
        sid = "ses-dict-resp"
        handle_session_start({"session_id": sid})
        handle_post_tool_use(
            {
                "session_id": sid,
                "tool_name": "Bash",
                "tool_input": {"command": "echo hi"},
                "tool_response": {"output": "hi"},
            }
        )
        assert len(_read_buffer(sid)) == 1

    def test_empty_tool_name(self, _patch_openflux_dir: Any) -> None:
        sid = "ses-empty-tool"
        handle_session_start({"session_id": sid})
        handle_post_tool_use(
            {
                "session_id": sid,
                "tool_name": "",
                "tool_input": {},
                "tool_response": "",
            }
        )
        assert len(_read_buffer(sid)) == 1

    def test_missing_tool_input_fields(
        self, fidelity: FidelityMode, exclude_patterns: list[str]
    ) -> None:
        result = _classify_tool(
            "Read",
            {},
            "",
            error=False,
            timestamp="t",
            fidelity=fidelity,
            exclude_patterns=exclude_patterns,
        )
        assert len(result["sources"]) == 1
        assert result["sources"][0]["path"] == ""


class TestCorrectionPattern:
    @pytest.mark.parametrize(
        "text",
        [
            "no, that's not right",
            "No, that's wrong",
            "actually, use pathlib instead",
            "don't do that",
            "stop",
            "undo the last change",
            "revert that",
            "I said use pytest",
            "I meant the other file",
            "instead of os.path, use pathlib",
        ],
    )
    def test_detected(self, text: str) -> None:
        assert CORRECTION_PATTERN.search(text) is not None

    @pytest.mark.parametrize(
        "text",
        [
            "looks good",
            "great job",
            "please continue",
            "read the file",
            "run the tests",
        ],
    )
    def test_not_detected(self, text: str) -> None:
        assert CORRECTION_PATTERN.search(text) is None

    def test_transcript_detection(
        self, tmp_path: Path, _patch_openflux_dir: Any
    ) -> None:
        transcript = tmp_path / "transcript.txt"
        transcript.write_text(
            "user: no, that's wrong\nuser: actually, use the other approach\n",
            encoding="utf-8",
        )
        sid = "ses-corrections"
        handle_session_start({"session_id": sid})
        handle_post_tool_use(
            {
                "session_id": sid,
                "tool_name": "Read",
                "tool_input": {"file_path": "/a.py"},
                "tool_response": "x",
            }
        )
        with patch("openflux.adapters._claude_code._write_to_sinks") as mock_sink:
            handle_session_end({"session_id": sid, "transcript_path": str(transcript)})
            trace = mock_sink.call_args[0][0]
            assert trace.correction is not None
            assert "correction" in trace.correction.lower()


class TestBuildTrace:
    def test_turn_count(self) -> None:
        events: list[dict[str, Any]] = [
            {
                "tool_name": "Bash",
                "timestamp": "t1",
                "classified": {
                    "searches": [],
                    "sources": [],
                    "tools": [
                        {
                            "name": "Bash",
                            "tool_input": "",
                            "tool_output": "",
                            "duration_ms": 0,
                            "error": False,
                            "timestamp": "t1",
                        }
                    ],
                    "files_modified": [],
                },
            },
            {
                "tool_name": "Bash",
                "timestamp": "t2",
                "classified": {
                    "searches": [],
                    "sources": [],
                    "tools": [
                        {
                            "name": "Bash",
                            "tool_input": "",
                            "tool_output": "",
                            "duration_ms": 0,
                            "error": False,
                            "timestamp": "t2",
                        }
                    ],
                    "files_modified": [],
                },
            },
        ]
        meta = SessionMeta(session_id="s1", started_at="2026-01-01T00:00:00Z")
        trace = _build_trace(events, meta, {})
        assert trace.turn_count == 2
        assert len(trace.tools_used) == 2

    def test_environment_metadata(self) -> None:
        meta = SessionMeta(
            session_id="s1",
            cwd="/project",
            permission_mode="default",
            started_at="2026-01-01T00:00:00Z",
        )
        trace = _build_trace([], meta, {})
        env = trace.metadata.get("environment", {})
        assert env["cwd"] == "/project"
        assert env["permission_mode"] == "default"


class TestClaudeCodeAdapter:
    def test_hook_config_subcommands(self) -> None:
        config = ClaudeCodeAdapter().hook_config()
        hooks = config["hooks"]
        for key in [
            "SessionStart",
            "PostToolUse",
            "PostToolUseFailure",
            "SubagentStart",
            "Stop",
            "SessionEnd",
        ]:
            assert key in hooks

    def test_hook_commands_use_module_path(self) -> None:
        config = ClaudeCodeAdapter.hook_config()
        for hook_list in config["hooks"].values():
            for hook in hook_list:
                assert "openflux.adapters.claude_code" in hook["command"]
