"""Framework-specific adapters for OpenFlux."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openflux.adapters.autogen import AutoGenStreamConsumer
    from openflux.adapters.bedrock import BedrockAdapter
    from openflux.adapters.claude_agent_sdk import ClaudeAgentSDKAdapter
    from openflux.adapters.google_adk import ADKCallbacks
    from openflux.adapters.langchain import OpenFluxCallbackHandler
    from openflux.adapters.mcp import MCPServerAdapter
    from openflux.adapters.openai_agents import OpenFluxProcessor

    from openflux.adapters.claude_code import ClaudeCodeAdapter


def get_bedrock_adapter(
    agent: str = "bedrock",
    on_trace: Any | None = None,
) -> BedrockAdapter:
    """Lazy import; requires boto3 extra."""
    from openflux.adapters.bedrock import BedrockAdapter

    return BedrockAdapter(agent=agent, on_trace=on_trace)


def get_claude_agent_sdk_adapter(
    agent: str = "claude-agent-sdk",
    on_trace: Any | None = None,
) -> ClaudeAgentSDKAdapter:
    """Lazy import; requires claude-agent-sdk extra."""
    from openflux.adapters.claude_agent_sdk import ClaudeAgentSDKAdapter

    return ClaudeAgentSDKAdapter(agent=agent, on_trace=on_trace)


def get_claude_code_adapter() -> ClaudeCodeAdapter:
    """Lazy import for the Claude Code subprocess adapter."""
    from openflux.adapters.claude_code import ClaudeCodeAdapter

    return ClaudeCodeAdapter()


def get_openai_processor(
    agent: str = "openai-agent",
    search_tools: set[str] | None = None,
) -> OpenFluxProcessor:
    """Lazy import; requires openai-agents extra."""
    from openflux.adapters.openai_agents import OpenFluxProcessor

    return OpenFluxProcessor(agent=agent, search_tools=search_tools)


def get_langchain_handler(
    agent: str = "langchain-agent",
) -> OpenFluxCallbackHandler:
    """Lazy import; requires langchain-core extra."""
    from openflux.adapters.langchain import OpenFluxCallbackHandler

    return OpenFluxCallbackHandler(agent=agent)


def get_autogen_consumer(
    agent: str = "autogen",
    search_tools: set[str] | None = None,
) -> AutoGenStreamConsumer:
    """Lazy import; requires autogen-agentchat extra."""
    from openflux.adapters.autogen import AutoGenStreamConsumer

    return AutoGenStreamConsumer(agent=agent, search_tools=search_tools)


def get_adk_callbacks(
    agent: str = "google-adk",
    search_tools: set[str] | None = None,
    on_trace: Any | None = None,
) -> ADKCallbacks:
    """Lazy import; requires google-adk extra."""
    from openflux.adapters.google_adk import create_adk_callbacks

    return create_adk_callbacks(
        agent=agent, search_tools=search_tools, on_trace=on_trace
    )


def get_mcp_server(
    agent: str = "mcp",
    db_path: str | None = None,
    name: str = "OpenFlux",
) -> MCPServerAdapter:
    """Lazy import; requires mcp extra."""
    from openflux.adapters.mcp import MCPServerAdapter

    return MCPServerAdapter(agent=agent, db_path=db_path, name=name)


__all__ = [
    "get_adk_callbacks",
    "get_autogen_consumer",
    "get_bedrock_adapter",
    "get_claude_agent_sdk_adapter",
    "get_claude_code_adapter",
    "get_langchain_handler",
    "get_mcp_server",
    "get_openai_processor",
]
