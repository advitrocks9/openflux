from __future__ import annotations

import threading

from openflux.collector import TraceCollector
from openflux.schema import Trace
from openflux.sinks.base import Sink


class _SpySink(Sink):
    def __init__(self) -> None:
        self.written: list[Trace] = []

    def write(self, trace: Trace) -> None:
        self.written.append(trace)

    def close(self) -> None:
        pass


class TestRecordAndFlush:
    def test_basic(self) -> None:
        sink = _SpySink()
        c = TraceCollector(sinks=[sink], agent="test")
        c.record_event(
            "ses-1", {"type": "tool", "tool_name": "Bash", "tool_input": "ls"}
        )
        trace = c.flush("ses-1")
        assert trace.session_id == "ses-1"
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "Bash"
        assert len(sink.written) == 1

    def test_flush_clears_buffer(self) -> None:
        c = TraceCollector(agent="test")
        c.record_event("ses-1", {"type": "tool", "tool_name": "A"})
        c.flush("ses-1")
        trace = c.flush("ses-1")
        assert len(trace.tools_used) == 0

    def test_multiple_events(self) -> None:
        c = TraceCollector(agent="test")
        c.record_event("ses-1", {"type": "tool", "tool_name": "A"})
        c.record_event("ses-1", {"type": "tool", "tool_name": "B"})
        c.record_event("ses-1", {"type": "search", "query": "q"})
        trace = c.flush("ses-1")
        assert len(trace.tools_used) == 2
        assert len(trace.searches) == 1

    def test_separate_sessions(self) -> None:
        c = TraceCollector(agent="test")
        c.record_event("ses-1", {"type": "tool", "tool_name": "A"})
        c.record_event("ses-2", {"type": "tool", "tool_name": "B"})
        r1 = c.flush("ses-1")
        r2 = c.flush("ses-2")
        assert r1.tools_used[0].name == "A"
        assert r2.tools_used[0].name == "B"


class TestFlushAll:
    def test_basic(self) -> None:
        sink = _SpySink()
        c = TraceCollector(sinks=[sink], agent="test")
        c.record_event("ses-1", {"type": "tool", "tool_name": "A"})
        c.record_event("ses-2", {"type": "tool", "tool_name": "B"})
        traces = c.flush_all()
        assert len(traces) == 2
        assert len(sink.written) == 2

    def test_flush_all_empty(self) -> None:
        c = TraceCollector(agent="test")
        assert c.flush_all() == []


class TestFlushNonexistent:
    def test_produces_empty_trace(self) -> None:
        sink = _SpySink()
        c = TraceCollector(sinks=[sink], agent="test")
        trace = c.flush("ses-nonexistent")
        assert trace.session_id == "ses-nonexistent"
        assert len(trace.tools_used) == 0
        assert len(sink.written) == 1


class TestMultiSink:
    def test_writes_to_all(self) -> None:
        s1 = _SpySink()
        s2 = _SpySink()
        c = TraceCollector(sinks=[s1, s2], agent="test")
        c.record_event("ses-1", {"type": "tool", "tool_name": "A"})
        c.flush("ses-1")
        assert len(s1.written) == 1
        assert len(s2.written) == 1


class TestThreadSafety:
    def test_concurrent_writes(self) -> None:
        c = TraceCollector(agent="test")
        n_threads = 10
        events_per_thread = 50
        barrier = threading.Barrier(n_threads)

        def writer(thread_id: int) -> None:
            barrier.wait()
            for i in range(events_per_thread):
                c.record_event(
                    "ses-1", {"type": "tool", "tool_name": f"T{thread_id}-{i}"}
                )

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        trace = c.flush("ses-1")
        assert len(trace.tools_used) == n_threads * events_per_thread

    def test_concurrent_sessions(self) -> None:
        c = TraceCollector(agent="test")
        n_threads = 5
        barrier = threading.Barrier(n_threads)

        def writer(thread_id: int) -> None:
            barrier.wait()
            sid = f"ses-{thread_id}"
            for i in range(20):
                c.record_event(sid, {"type": "tool", "tool_name": f"T{i}"})

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        traces = c.flush_all()
        assert len(traces) == n_threads
        for r in traces:
            assert len(r.tools_used) == 20


class TestActiveSessions:
    def test_tracks_sessions(self) -> None:
        c = TraceCollector(agent="test")
        assert c.active_sessions == []
        c.record_event("ses-1", {"type": "tool", "tool_name": "A"})
        c.record_event("ses-2", {"type": "tool", "tool_name": "B"})
        assert sorted(c.active_sessions) == ["ses-1", "ses-2"]
        c.flush("ses-1")
        assert c.active_sessions == ["ses-2"]
