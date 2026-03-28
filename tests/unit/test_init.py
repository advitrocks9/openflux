from __future__ import annotations

from pathlib import Path

import openflux
from openflux.collector import TraceCollector
from openflux.sinks.json import JSONSink
from openflux.sinks.sqlite import SQLiteSink


class TestInit:
    def test_returns_collector(self, tmp_path: Path) -> None:
        collector = openflux.init(
            agent="test",
            sinks=[SQLiteSink(path=tmp_path / "t.db")],
        )
        assert isinstance(collector, TraceCollector)

    def test_default_sink_is_sqlite(self) -> None:
        """When no sinks given, init() creates a SQLiteSink at the default path."""
        collector = openflux.init(agent="test")
        assert len(collector._sinks) == 1
        assert isinstance(collector._sinks[0], SQLiteSink)
        collector._sinks[0].close()

    def test_custom_sinks_override_default(self) -> None:
        """Passing explicit sinks should not create a SQLiteSink."""
        json_sink = JSONSink()
        collector = openflux.init(agent="test", sinks=[json_sink])
        assert len(collector._sinks) == 1
        assert isinstance(collector._sinks[0], JSONSink)

    def test_agent_propagated(self, tmp_path: Path) -> None:
        collector = openflux.init(
            agent="my-agent",
            sinks=[SQLiteSink(path=tmp_path / "t.db")],
        )
        assert collector._normalizer._agent == "my-agent"
