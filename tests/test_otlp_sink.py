from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from conftest import (
    make_context_record,
    make_search_record,
    make_source_record,
    make_tool_record,
    make_trace,
)

from openflux.schema import TokenUsage
from openflux.sinks.otlp import OTLPSink, _iso_to_nanos, _sha256_hex
from openflux.sinks.otlp import _kv as _make_kv


class TestTraceIdDeterminism:
    def test_same_session_same_trace(self) -> None:
        trace1 = _sha256_hex("ses-abc123", 16)
        trace2 = _sha256_hex("ses-abc123", 16)
        assert trace1 == trace2
        assert len(trace1) == 32

    def test_different_session_different_trace(self) -> None:
        assert _sha256_hex("ses-abc123", 16) != _sha256_hex("ses-xyz789", 16)

    def test_span_id_length(self) -> None:
        span = _sha256_hex("trc-aabbccddeeff", 8)
        assert len(span) == 16


class TestMakeKV:
    @pytest.mark.parametrize(
        ("value", "expected_key"),
        [
            ("hello", "stringValue"),
            (42, "intValue"),
            (True, "boolValue"),
            (["a", "b"], "arrayValue"),
        ],
    )
    def test_types(
        self, value: str | int | bool | list[str], expected_key: str
    ) -> None:
        kv = _make_kv("test", value)
        assert kv["key"] == "test"
        assert expected_key in kv["value"]

    def test_int_as_string(self) -> None:
        kv = _make_kv("count", 42)
        assert kv["value"]["intValue"] == "42"

    def test_array(self) -> None:
        kv = _make_kv("tags", ["a", "b"])
        values = kv["value"]["arrayValue"]["values"]
        assert len(values) == 2
        assert values[0]["stringValue"] == "a"


class TestSpanAttributes:
    def test_core_attributes(self) -> None:
        sink = OTLPSink(endpoint="http://localhost:4318")
        r = make_trace(
            agent="my-agent",
            model="gpt-4",
            task="fix bug",
            token_usage=TokenUsage(input_tokens=100, output_tokens=50),
            scope="backend",
            tags=["prod"],
            files_modified=["/a.py"],
            parent_id="trc-parent123456",
        )
        payload = sink._build_payload(r)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        attr_map = {a["key"]: a["value"] for a in span["attributes"]}
        assert attr_map["openflux.trace.id"]["stringValue"] == r.id
        assert attr_map["gen_ai.agent.name"]["stringValue"] == "my-agent"
        assert attr_map["gen_ai.request.model"]["stringValue"] == "gpt-4"
        assert attr_map["openflux.status"]["stringValue"] == "completed"
        assert attr_map["gen_ai.usage.input_tokens"]["intValue"] == "100"
        assert attr_map["openflux.scope"]["stringValue"] == "backend"
        assert attr_map["openflux.parent_id"]["stringValue"] == "trc-parent123456"
        assert attr_map["openflux.task"]["stringValue"] == "fix bug"

    def test_resource_attributes(self) -> None:
        sink = OTLPSink(endpoint="http://localhost:4318")
        r = make_trace(agent="test-agent")
        payload = sink._build_payload(r)
        resource = payload["resourceSpans"][0]["resource"]
        attr_map = {a["key"]: a["value"] for a in resource["attributes"]}
        assert attr_map["service.name"]["stringValue"] == "openflux"
        assert attr_map["openflux.agent"]["stringValue"] == "test-agent"


class TestSpanEvents:
    def test_decision(self) -> None:
        sink = OTLPSink(endpoint="http://localhost:4318")
        r = make_trace(decision="chose approach A")
        payload = sink._build_payload(r)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        decision_events = [
            e for e in span["events"] if e["name"] == "openflux.decision"
        ]
        assert len(decision_events) == 1
        attrs = {a["key"]: a["value"] for a in decision_events[0]["attributes"]}
        assert attrs["openflux.decision.text"]["stringValue"] == "chose approach A"

    def test_correction(self) -> None:
        sink = OTLPSink(endpoint="http://localhost:4318")
        r = make_trace(correction="wrong approach, switching")
        payload = sink._build_payload(r)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        correction_events = [
            e for e in span["events"] if e["name"] == "openflux.correction"
        ]
        assert len(correction_events) == 1

    def test_context(self) -> None:
        sink = OTLPSink(endpoint="http://localhost:4318")
        r = make_trace(context=[make_context_record(), make_context_record()])
        payload = sink._build_payload(r)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        ctx_events = [e for e in span["events"] if e["name"] == "openflux.context"]
        assert len(ctx_events) == 2

    def test_search(self) -> None:
        sink = OTLPSink(endpoint="http://localhost:4318")
        r = make_trace(searches=[make_search_record(query="find X")])
        payload = sink._build_payload(r)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        search_events = [e for e in span["events"] if e["name"] == "openflux.search"]
        assert len(search_events) == 1
        attrs = {a["key"]: a["value"] for a in search_events[0]["attributes"]}
        assert attrs["query"]["stringValue"] == "find X"

    def test_source(self) -> None:
        sink = OTLPSink(endpoint="http://localhost:4318")
        r = make_trace(sources_read=[make_source_record(path="/src/a.py")])
        payload = sink._build_payload(r)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        src_events = [e for e in span["events"] if e["name"] == "openflux.source_read"]
        assert len(src_events) == 1
        attrs = {a["key"]: a["value"] for a in src_events[0]["attributes"]}
        assert attrs["path"]["stringValue"] == "/src/a.py"

    def test_tool(self) -> None:
        sink = OTLPSink(endpoint="http://localhost:4318")
        r = make_trace(tools_used=[make_tool_record(name="Bash", tool_input="ls")])
        payload = sink._build_payload(r)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        tool_events = [e for e in span["events"] if e["name"] == "openflux.tool_use"]
        assert len(tool_events) == 1
        attrs = {a["key"]: a["value"] for a in tool_events[0]["attributes"]}
        assert attrs["name"]["stringValue"] == "Bash"


class TestTimestampConversion:
    def test_iso_to_nanos(self) -> None:
        nanos = _iso_to_nanos("2026-01-01T00:00:00Z")
        assert nanos == 1767225600 * 1_000_000_000

    def test_offset_equivalent(self) -> None:
        assert _iso_to_nanos("2026-01-01T00:00:00Z") == _iso_to_nanos(
            "2026-01-01T00:00:00+00:00"
        )


class TestHTTPPost:
    def test_posts_to_endpoint(self) -> None:
        sink = OTLPSink(endpoint="http://test-collector:4318")
        r = make_trace()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read = MagicMock(return_value=b"")
            mock_urlopen.return_value = mock_resp
            sink.write(r)
            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            assert req.full_url == "http://test-collector:4318/v1/traces"
            assert req.get_header("Content-type") == "application/json"

    def test_swallows_errors(self) -> None:
        sink = OTLPSink(endpoint="http://unreachable:4318")
        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            sink.write(make_trace())


class TestOTLPFidelity:
    def test_span_name_truncation(self) -> None:
        sink = OTLPSink(endpoint="http://localhost:4318")
        r = make_trace(task="x" * 200)
        payload = sink._build_payload(r)
        span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
        assert len(span["name"]) <= len("trace: ") + 80
