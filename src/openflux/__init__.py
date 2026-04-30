"""OpenFlux - the open standard for AI agent telemetry"""

from __future__ import annotations

from typing import TYPE_CHECKING

from openflux.collector import TraceCollector
from openflux.schema import (
    SCHEMA_VERSION,
    ContextRecord,
    ContextType,
    FidelityMode,
    SearchRecord,
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

if TYPE_CHECKING:
    from openflux.adapters.langchain import OpenFluxCallbackHandler
    from openflux.sinks.base import Sink

__version__ = "0.5.0"

__all__ = [
    "SCHEMA_VERSION",
    "ContextRecord",
    "ContextType",
    "FidelityMode",
    "Trace",
    "TraceCollector",
    "SearchRecord",
    "SourceRecord",
    "SourceType",
    "Status",
    "TokenUsage",
    "ToolRecord",
    "init",
    "langchain_handler",
]


def init(
    agent: str = "",
    sinks: list[Sink] | None = None,
    fidelity: FidelityMode | None = None,
) -> TraceCollector:
    if sinks is None:
        from openflux.sinks.sqlite import SQLiteSink

        sinks = [SQLiteSink()]
    return TraceCollector(sinks=sinks, agent=agent, fidelity=fidelity)


def langchain_handler(agent: str = "") -> OpenFluxCallbackHandler:
    """Lazy-imports langchain-core."""
    from openflux.adapters.langchain import OpenFluxCallbackHandler

    return OpenFluxCallbackHandler(agent=agent)
