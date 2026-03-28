"""Local web UI for browsing OpenFlux traces."""

from __future__ import annotations

from openflux.serve._server import run_server
from openflux.sinks.sqlite import SQLiteSink


def serve(port: int = 5173, db_path: str | None = None) -> None:
    """Start the OpenFlux trace explorer on localhost."""
    sink = SQLiteSink(path=db_path) if db_path else SQLiteSink()
    run_server(port, sink)
