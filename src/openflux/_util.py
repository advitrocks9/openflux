"""Hashing, ID generation, timestamps, and path exclusion helpers"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from datetime import UTC, datetime
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openflux.schema import Trace
    from openflux.sinks.sqlite import SQLiteSink

logger = logging.getLogger("openflux")

DEFAULT_EXCLUDE_PATTERNS: list[str] = [
    "*.env",
    "*.env.*",
    "*credentials*",
    "*secret*",
    "*password*",
    "*.pem",
    "*.key",
    "**/.*token*",
]


def content_hash(content: str | bytes) -> str:
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def truncate_content(content: str, max_bytes: int) -> str:
    """Truncate respecting UTF-8 char boundaries."""
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def generate_trace_id() -> str:
    return f"trc-{secrets.token_hex(6)}"


def generate_session_id() -> str:
    return f"ses-{secrets.token_hex(8)}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def matches_exclude_pattern(path: str, patterns: list[str]) -> bool:
    name = PurePosixPath(path).name
    return any(fnmatch(path, p) or fnmatch(name, p) for p in patterns)


def get_exclude_patterns() -> list[str]:
    import os

    env_val = os.environ.get("OPENFLUX_EXCLUDE_PATHS", "").strip()
    if not env_val:
        return DEFAULT_EXCLUDE_PATTERNS
    return [p.strip() for p in env_val.split(",") if p.strip()]


# Lazy singleton for the default SQLite sink so adapters don't open
# a new connection per trace.
_default_sink: SQLiteSink | None = None
_default_sink_lock = threading.Lock()


def _get_default_sink() -> SQLiteSink:
    """Return (and lazily create) the module-level default SQLiteSink."""
    global _default_sink  # noqa: PLW0603
    if _default_sink is None:
        with _default_sink_lock:
            if _default_sink is None:
                from openflux.sinks.sqlite import SQLiteSink

                _default_sink = SQLiteSink()
    return _default_sink  # type: ignore[return-value]


def write_trace_to_default_sink(trace: Trace) -> None:
    """Write a trace to the shared default SQLite sink.

    Recreates the sink if the connection was closed externally.
    """
    global _default_sink  # noqa: PLW0603
    try:
        sink = _get_default_sink()
        sink.write(trace)
    except Exception:
        # Connection may have been closed; reset and retry once
        with _default_sink_lock:
            _default_sink = None
        try:
            sink = _get_default_sink()
            sink.write(trace)
        except Exception:
            logger.warning(
                "OpenFlux: failed to write trace to default sink", exc_info=True
            )
