from __future__ import annotations

import re

from openflux._util import (
    content_hash,
    generate_session_id,
    generate_trace_id,
    matches_exclude_pattern,
    truncate_content,
    utc_now,
)


class TestContentHash:
    def test_str_input(self) -> None:
        h = content_hash("hello world")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_bytes_input(self) -> None:
        h = content_hash(b"hello world")
        assert h == content_hash("hello world")

    def test_empty_string(self) -> None:
        h = content_hash("")
        assert len(h) == 64

    def test_deterministic(self) -> None:
        assert content_hash("same") == content_hash("same")

    def test_different_inputs(self) -> None:
        assert content_hash("a") != content_hash("b")


class TestTruncateContent:
    def test_short_content_unchanged(self) -> None:
        assert truncate_content("hi", 100) == "hi"

    def test_exact_boundary(self) -> None:
        assert truncate_content("abc", 3) == "abc"

    def test_truncates_at_limit(self) -> None:
        result = truncate_content("hello world", 5)
        assert result == "hello"

    def test_multibyte_utf8_boundary(self) -> None:
        """Truncating mid-emoji drops the incomplete char rather than corrupting."""
        content = "Hello 🌍🌎🌏 World"
        truncated = truncate_content(content, 10)
        # Must be valid UTF-8 -- encode/decode should not raise
        truncated.encode("utf-8").decode("utf-8")
        assert len(truncated.encode("utf-8")) <= 10

    def test_cjk_characters(self) -> None:
        content = "ABC"
        truncated = truncate_content(content, 5)
        truncated.encode("utf-8").decode("utf-8")
        assert len(truncated.encode("utf-8")) <= 5


class TestGenerateIds:
    def test_trace_id_format(self) -> None:
        tid = generate_trace_id()
        assert tid.startswith("trc-")
        assert len(tid) == 16  # "trc-" + 12 hex chars
        assert re.fullmatch(r"trc-[0-9a-f]{12}", tid)

    def test_session_id_format(self) -> None:
        sid = generate_session_id()
        assert sid.startswith("ses-")
        assert len(sid) == 20  # "ses-" + 16 hex chars
        assert re.fullmatch(r"ses-[0-9a-f]{16}", sid)

    def test_uniqueness(self) -> None:
        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100

    def test_session_uniqueness(self) -> None:
        ids = {generate_session_id() for _ in range(100)}
        assert len(ids) == 100


class TestMatchesExcludePattern:
    def test_env_file(self) -> None:
        from openflux._util import DEFAULT_EXCLUDE_PATTERNS

        assert matches_exclude_pattern(".env", DEFAULT_EXCLUDE_PATTERNS)
        assert matches_exclude_pattern("/app/.env", DEFAULT_EXCLUDE_PATTERNS)
        assert matches_exclude_pattern(".env.local", DEFAULT_EXCLUDE_PATTERNS)

    def test_credentials(self) -> None:
        from openflux._util import DEFAULT_EXCLUDE_PATTERNS

        assert matches_exclude_pattern("credentials.json", DEFAULT_EXCLUDE_PATTERNS)
        assert matches_exclude_pattern(
            "/etc/credentials.yaml", DEFAULT_EXCLUDE_PATTERNS
        )

    def test_normal_file_not_excluded(self) -> None:
        from openflux._util import DEFAULT_EXCLUDE_PATTERNS

        assert not matches_exclude_pattern("main.py", DEFAULT_EXCLUDE_PATTERNS)
        assert not matches_exclude_pattern("/src/app.ts", DEFAULT_EXCLUDE_PATTERNS)

    def test_empty_path(self) -> None:
        from openflux._util import DEFAULT_EXCLUDE_PATTERNS

        assert not matches_exclude_pattern("", DEFAULT_EXCLUDE_PATTERNS)

    def test_pem_key_files(self) -> None:
        from openflux._util import DEFAULT_EXCLUDE_PATTERNS

        assert matches_exclude_pattern("server.pem", DEFAULT_EXCLUDE_PATTERNS)
        assert matches_exclude_pattern("private.key", DEFAULT_EXCLUDE_PATTERNS)

    def test_custom_patterns(self) -> None:
        patterns = ["*.log", "temp_*"]
        assert matches_exclude_pattern("debug.log", patterns)
        assert matches_exclude_pattern("temp_data.json", patterns)
        assert not matches_exclude_pattern("main.py", patterns)


class TestUtcNow:
    def test_iso_format(self) -> None:
        ts = utc_now()
        assert "T" in ts
        assert "-" in ts

    def test_ends_with_z(self) -> None:
        ts = utc_now()
        assert ts.endswith("Z")

    def test_parseable(self) -> None:
        """Timestamps must be parseable by datetime.fromisoformat."""
        from datetime import datetime

        ts = utc_now()
        # Replace Z with +00:00 for fromisoformat compatibility
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed.year >= 2024
