"""Claude Code acceptance test — hooks-only, no API key needed.

Simulates exactly what Claude Code does: subprocess calls with JSON on stdin.
Also tests transcript parsing with a synthetic JSONL file.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from helpers import check_trace

from openflux._util import generate_session_id
from openflux.adapters._claude_code import (
    _parse_transcript,
    handle_post_tool_use,
    handle_post_tool_use_failure,
    handle_session_end,
    handle_session_start,
)


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "traces.db"


@pytest.fixture()
def session_id():
    return generate_session_id()


@pytest.fixture()
def openflux_dir(tmp_path):
    d = tmp_path / ".openflux"
    d.mkdir()
    return d


def _simulate_hook(handler, data, openflux_dir):
    """Call a hook handler with patched OPENFLUX_DIR to use tmp dir."""
    with patch("openflux.adapters._claude_code._OPENFLUX_DIR", openflux_dir):
        handler(data)


class TestClaudeCodeHookWorkflow:
    """A user installs OpenFlux hooks into Claude Code. Each tool call triggers a hook."""

    def test_full_session_with_tools(self, db_path, session_id, openflux_dir):
        """Simulate a session: start, multiple tool calls, end."""
        # Session start
        _simulate_hook(
            handle_session_start,
            {
                "session_id": session_id,
                "cwd": "/Users/dev/my-project",
                "permission_mode": "default",
                "model": "claude-sonnet-4-20250514",
            },
            openflux_dir,
        )

        # 1. Read — should produce source_read
        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "Read",
                "tool_input": {"file_path": "/Users/dev/my-project/src/auth.py"},
                "tool_response": "class AuthManager:\n    def login(self, user, pwd):\n        return True",
            },
            openflux_dir,
        )

        # 2. WebSearch — should produce search
        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "WebSearch",
                "tool_input": {"query": "python oauth2 best practices 2024"},
                "tool_response": "Result 1: OAuth2 PKCE flow\nResult 2: Token rotation\nResult 3: Secure storage",
            },
            openflux_dir,
        )

        # 3. Grep — should produce search + sources
        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "Grep",
                "tool_input": {"pattern": "password"},
                "tool_response": "src/auth.py:5:    password = hash(pwd)\nsrc/db.py:12:    store_password(h)",
            },
            openflux_dir,
        )

        # 4. Edit — should produce source + file_modified
        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "/Users/dev/my-project/src/auth.py",
                    "new_string": "def login(self, user, pwd):\n    return bcrypt.check(pwd, self.hash)",
                },
                "tool_response": "File edited successfully",
            },
            openflux_dir,
        )

        # 5. Write — should produce source + file_modified
        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/Users/dev/my-project/tests/test_auth.py",
                    "content": "def test_login():\n    assert auth.login('user', 'pass')",
                },
                "tool_response": "File written successfully",
            },
            openflux_dir,
        )

        # 6. Bash — should produce tool_used
        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "pytest tests/test_auth.py -v"},
                "tool_response": "1 passed in 0.5s",
            },
            openflux_dir,
        )

        # 7. WebFetch — should produce source
        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "WebFetch",
                "tool_input": {"url": "https://docs.python.org/3/library/hashlib.html"},
                "tool_response": "hashlib — Secure hashes and message digests...",
            },
            openflux_dir,
        )

        # 8. PostToolUseFailure — error event
        _simulate_hook(
            handle_post_tool_use_failure,
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf /protected"},
                "tool_response": "Permission denied",
            },
            openflux_dir,
        )

        # Session end — builds trace and writes to sink
        with patch.dict(os.environ, {"OPENFLUX_DB_PATH": str(db_path)}):
            _simulate_hook(
                handle_session_end,
                {"session_id": session_id},
                openflux_dir,
            )

        # Verify trace via check_trace
        trace, coverage = check_trace(
            db_path,
            required=[
                "id",
                "timestamp",
                "agent",
                "session_id",
                "model",
                "status",
                "sources_read",
                "tools_used",
                "files_modified",
                "tags",
                "duration_ms",
                "metadata",
                "schema_version",
                "searches",
                "turn_count",
            ],
            na=["parent_id", "correction", "context"],
        )

        # Verify specific field contents
        assert trace.agent == "claude-code"
        assert trace.model == "claude-sonnet-4-20250514"
        assert len(trace.sources_read) >= 4  # Read, Grep files, Edit, Write, WebFetch
        assert len(trace.files_modified) >= 2  # Edit + Write
        assert len(trace.searches) >= 2  # WebSearch + Grep
        assert len(trace.tools_used) >= 1  # Bash
        assert "code-edit" in trace.tags
        assert "web-research" in trace.tags
        assert "shell" in trace.tags
        assert "has-errors" in trace.tags
        assert trace.status == "error"  # because of the failure event


class TestClaudeCodeTranscriptParsing:
    """Test transcript parsing with a synthetic JSONL file."""

    def _make_transcript(self, path: Path):
        """Build a synthetic Claude Code JSONL transcript.

        Mirrors real transcript structure: agent-setting, user, assistant entries.
        System prompts are NOT in real transcripts (injected at API level).
        """
        t0 = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
        entries = [
            # First user message → task
            {
                "type": "user",
                "timestamp": t0.isoformat(),
                "cwd": "/Users/dev/my-project",
                "gitBranch": "feature/auth",
                "message": {
                    "content": "Fix the authentication bug in the login endpoint",
                },
            },
            # First assistant response
            {
                "type": "assistant",
                "timestamp": (t0 + timedelta(seconds=5)).isoformat(),
                "message": {
                    "model": "claude-sonnet-4-20250514",
                    "usage": {
                        "input_tokens": 5000,
                        "output_tokens": 1200,
                        "cache_read_input_tokens": 3000,
                        "cache_creation_input_tokens": 500,
                    },
                    "content": [
                        {
                            "type": "text",
                            "text": "I'll look at the auth module to find the bug.",
                        }
                    ],
                },
            },
            # Second user turn (correction)
            {
                "type": "user",
                "timestamp": (t0 + timedelta(seconds=30)).isoformat(),
                "message": {
                    "content": "No, that's not right. Actually, use bcrypt instead of sha256",
                },
            },
            # Second assistant response
            {
                "type": "assistant",
                "timestamp": (t0 + timedelta(seconds=35)).isoformat(),
                "message": {
                    "model": "claude-sonnet-4-20250514",
                    "usage": {
                        "input_tokens": 8000,
                        "output_tokens": 2000,
                        "cache_read_input_tokens": 6000,
                        "cache_creation_input_tokens": 800,
                    },
                    "content": [
                        {
                            "type": "text",
                            "text": "I've updated the login endpoint to use bcrypt for password hashing.",
                        }
                    ],
                },
            },
            # Third user turn
            {
                "type": "user",
                "timestamp": (t0 + timedelta(seconds=60)).isoformat(),
                "message": {
                    "content": "Great, now run the tests",
                },
            },
            # Final assistant response → decision
            {
                "type": "assistant",
                "timestamp": (t0 + timedelta(seconds=90)).isoformat(),
                "message": {
                    "model": "claude-sonnet-4-20250514",
                    "usage": {
                        "input_tokens": 3000,
                        "output_tokens": 800,
                        "cache_read_input_tokens": 2000,
                        "cache_creation_input_tokens": 300,
                    },
                    "content": [
                        {
                            "type": "text",
                            "text": "All 15 tests passing. The auth bug is fixed.",
                        }
                    ],
                },
            },
        ]

        with path.open("w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

    def test_transcript_fields(self, tmp_path):
        """Verify transcript parsing extracts task, decision, tokens, turns, scope, correction."""
        transcript_path = tmp_path / "transcript.jsonl"
        self._make_transcript(transcript_path)

        td = _parse_transcript(transcript_path)

        assert td.task == "Fix the authentication bug in the login endpoint"
        assert "All 15 tests passing" in td.decision
        assert td.model == "claude-sonnet-4-20250514"
        assert td.turn_count == 3  # 3 user messages
        assert td.token_usage is not None
        assert td.token_usage.input_tokens == 16000  # 5000 + 8000 + 3000
        assert td.token_usage.output_tokens == 4000  # 1200 + 2000 + 800
        assert td.token_usage.cache_read_tokens == 11000  # 3000 + 6000 + 2000
        assert td.token_usage.cache_creation_tokens == 1600  # 500 + 800 + 300
        assert td.duration_ms == 90000  # 90 seconds
        assert td.scope is not None
        assert "feature/auth" in td.scope
        assert td.correction is not None
        assert "correction" in td.correction.lower()
        # System prompts aren't recorded in real Claude Code transcripts
        assert td.context == []

    def test_transcript_integration_with_hooks(self, db_path, openflux_dir):
        """Full flow: hooks collect tool data, transcript provides session-level fields."""
        session_id = generate_session_id()

        # Create transcript
        transcript_path = openflux_dir / "transcript.jsonl"
        self._make_transcript(transcript_path)

        # Session start
        _simulate_hook(
            handle_session_start,
            {
                "session_id": session_id,
                "cwd": "/Users/dev/my-project",
                "model": "claude-sonnet-4-20250514",
            },
            openflux_dir,
        )

        # Tool calls covering every classification path
        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "Read",
                "tool_input": {"file_path": "src/auth.py"},
                "tool_response": "auth code here",
            },
            openflux_dir,
        )

        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "Grep",
                "tool_input": {"pattern": "bcrypt"},
                "tool_response": "src/auth.py:3: import bcrypt",
            },
            openflux_dir,
        )

        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "Bash",
                "tool_input": {"command": "pytest tests/ -q"},
                "tool_response": "15 passed",
            },
            openflux_dir,
        )

        _simulate_hook(
            handle_post_tool_use,
            {
                "session_id": session_id,
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "src/auth.py",
                    "new_string": "import bcrypt",
                },
                "tool_response": "OK",
            },
            openflux_dir,
        )

        # Session end with transcript_path
        with patch.dict(os.environ, {"OPENFLUX_DB_PATH": str(db_path)}):
            _simulate_hook(
                handle_session_end,
                {
                    "session_id": session_id,
                    "transcript_path": str(transcript_path),
                },
                openflux_dir,
            )

        trace, coverage = check_trace(
            db_path,
            required=[
                "id",
                "timestamp",
                "agent",
                "session_id",
                "model",
                "status",
                "sources_read",
                "tools_used",
                "searches",
                "files_modified",
                "tags",
                "metadata",
                "schema_version",
                "task",
                "decision",
                "token_usage",
                "turn_count",
                "scope",
                "correction",
            ],
            # context: system prompts aren't in real transcripts
            na=["parent_id", "context"],
        )

        assert "Fix the authentication" in trace.task
        assert "tests passing" in trace.decision
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 16000
        assert trace.turn_count == 3
        assert trace.scope is not None
        assert trace.correction is not None


class TestRealTranscript:
    """Parse a real Claude Code transcript from this machine — no fakes."""

    @staticmethod
    def _find_real_transcript() -> Path | None:
        """Find a completed transcript with at least one assistant response."""
        projects_dir = Path.home() / ".claude" / "projects"
        if not projects_dir.exists():
            return None
        # Walk all project dirs for any .jsonl with assistant entries
        for project in projects_dir.iterdir():
            if not project.is_dir():
                continue
            for jsonl in sorted(
                project.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
            ):
                has_user = False
                has_assistant = False
                with jsonl.open("r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if entry.get("type") == "user":
                            has_user = True
                        if entry.get("type") == "assistant":
                            has_assistant = True
                        if has_user and has_assistant:
                            return jsonl
        return None

    def test_real_transcript_parsing(self):
        """Parse a real transcript and verify structural fields are extracted."""
        path = self._find_real_transcript()
        if path is None:
            pytest.skip("No real Claude Code transcripts found on this machine")

        td = _parse_transcript(path)

        # A real transcript must have these — they come from the JSONL structure
        assert td.task, f"task should be non-empty from {path.name}"
        assert td.decision, f"decision should be non-empty from {path.name}"
        assert td.model, f"model should be non-empty from {path.name}"
        assert td.turn_count > 0, f"turn_count should be >0 from {path.name}"
        assert td.token_usage is not None, f"token_usage should exist from {path.name}"
        assert td.token_usage.input_tokens > 0
        assert td.token_usage.output_tokens > 0
        assert td.duration_ms >= 0
        # Context is structurally empty — system prompts aren't in transcripts
        assert td.context == []
