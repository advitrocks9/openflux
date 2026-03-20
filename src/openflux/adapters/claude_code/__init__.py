"""Claude Code hooks adapter - subprocess-based, invoked via shell hooks."""

from openflux.adapters._claude_code import (
    CORRECTION_PATTERN,
    ClaudeCodeAdapter,
    handle_post_tool_use,
    handle_post_tool_use_failure,
    handle_session_end,
    handle_session_start,
    handle_subagent_start,
    main,
)

__all__ = [
    "CORRECTION_PATTERN",
    "ClaudeCodeAdapter",
    "handle_post_tool_use",
    "handle_post_tool_use_failure",
    "handle_session_end",
    "handle_session_start",
    "handle_subagent_start",
    "main",
]
