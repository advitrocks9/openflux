"""Thread-safe TraceCollector: adapter -> normalizer -> sinks"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from openflux.normalizer import Normalizer
from openflux.schema import FidelityMode, Trace

if TYPE_CHECKING:
    from openflux.sinks.base import Sink


class TraceCollector:
    """Collects raw events, normalizes them, and writes to sinks. Thread-safe."""

    def __init__(
        self,
        sinks: list[Sink] | None = None,
        agent: str = "",
        fidelity: FidelityMode | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._buf: dict[str, list[dict[str, Any]]] = {}
        self._sinks: list[Sink] = sinks or []
        self._normalizer = Normalizer(agent=agent, fidelity=fidelity)

    def record_event(self, session_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            self._buf.setdefault(session_id, []).append(event)

    def flush(self, session_id: str) -> Trace:
        with self._lock:
            events = self._buf.pop(session_id, [])

        trace = self._normalizer.normalize(events, session_id)
        for sink in self._sinks:
            sink.write(trace)
        return trace

    def flush_all(self) -> list[Trace]:
        with self._lock:
            session_ids = list(self._buf.keys())
        return [self.flush(sid) for sid in session_ids]

    @property
    def active_sessions(self) -> list[str]:
        with self._lock:
            return list(self._buf.keys())
