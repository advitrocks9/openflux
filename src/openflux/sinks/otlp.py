"""OTLP/HTTP sink for exporting Traces as OpenTelemetry spans"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.request
from datetime import UTC, datetime
from typing import Any, override

from openflux.schema import TokenUsage, Trace
from openflux.sinks.base import Sink

logger = logging.getLogger(__name__)

_SPAN_KIND_INTERNAL = 1
_TEXT_LIMIT = 500


def _sha256_hex(value: str, byte_len: int) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    return digest[:byte_len].hex()


def _iso_to_nanos(iso_ts: str) -> int:
    ts = iso_ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1_000_000_000)


def _trunc(text: str, limit: int = _TEXT_LIMIT) -> str:
    return text[:limit] if len(text) > limit else text


def _kv(key: str, value: str | int | bool | list[str]) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, list):
        return {
            "key": key,
            "value": {"arrayValue": {"values": [{"stringValue": v} for v in value]}},
        }
    return {"key": key, "value": {"stringValue": str(value)}}


def _event(
    name: str, attrs: list[dict[str, Any]], time_nanos: int = 0
) -> dict[str, Any]:
    ev: dict[str, Any] = {"name": name, "attributes": attrs}
    if time_nanos:
        ev["timeUnixNano"] = str(time_nanos)
    return ev


class OTLPSink(Sink):
    """Raw OTLP/HTTP export, no opentelemetry-sdk needed."""

    def __init__(self, endpoint: str | None = None) -> None:
        self._endpoint = (
            endpoint
            or os.environ.get("OPENFLUX_OTLP_ENDPOINT")
            or "http://localhost:4318"
        )

    @override
    def write(self, trace: Trace) -> None:
        payload = self._build_payload(trace)
        data = json.dumps(payload).encode("utf-8")
        url = f"{self._endpoint.rstrip('/')}/v1/traces"
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
        except Exception:
            logger.warning("OTLP export to %s failed", url, exc_info=True)

    @override
    def close(self) -> None:
        pass

    def _build_payload(self, trace: Trace) -> dict[str, Any]:
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            _kv("service.name", "openflux"),
                            _kv("openflux.agent", trace.agent),
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "openflux",
                                "version": trace.schema_version,
                            },
                            "spans": [self._build_span(trace)],
                        }
                    ],
                }
            ]
        }

    def _build_span(self, trace: Trace) -> dict[str, Any]:
        trace_id = _sha256_hex(trace.session_id, 16)
        span_id = _sha256_hex(trace.id, 8)
        start = _iso_to_nanos(trace.timestamp) if trace.timestamp else 0
        end = start + (trace.duration_ms * 1_000_000)

        span: dict[str, Any] = {
            "traceId": trace_id,
            "spanId": span_id,
            "name": f"trace: {trace.task[:80]}" if trace.task else "trace",
            "kind": _SPAN_KIND_INTERNAL,
            "startTimeUnixNano": str(start),
            "endTimeUnixNano": str(end),
            "attributes": self._build_attrs(trace),
            "events": self._build_events(trace),
            "status": {},
        }
        if trace.parent_id:
            span["parentSpanId"] = _sha256_hex(trace.parent_id, 8)
        return span

    def _build_attrs(self, trace: Trace) -> list[dict[str, Any]]:
        tok = trace.token_usage or TokenUsage()
        attrs = [
            _kv("openflux.trace.id", trace.id),
            _kv("openflux.schema_version", trace.schema_version),
            _kv("gen_ai.agent.name", trace.agent),
            _kv("gen_ai.conversation.id", trace.session_id),
            _kv("gen_ai.request.model", trace.model),
            _kv("openflux.status", trace.status),
            _kv("openflux.turn_count", trace.turn_count),
            _kv("gen_ai.usage.input_tokens", tok.input_tokens),
            _kv("gen_ai.usage.output_tokens", tok.output_tokens),
            _kv("openflux.duration_ms", trace.duration_ms),
            _kv("openflux.context_count", len(trace.context)),
            _kv("openflux.search_count", len(trace.searches)),
            _kv("openflux.source_count", len(trace.sources_read)),
            _kv("openflux.tool_count", len(trace.tools_used)),
            _kv("openflux.has_correction", trace.correction is not None),
        ]
        if trace.parent_id:
            attrs.append(_kv("openflux.parent_id", trace.parent_id))
        if trace.scope:
            attrs.append(_kv("openflux.scope", trace.scope))
        if trace.tags:
            attrs.append(_kv("openflux.tags", trace.tags))
        if trace.files_modified:
            attrs.append(_kv("openflux.files_modified", trace.files_modified))
        if trace.task:
            attrs.append(_kv("openflux.task", _trunc(trace.task)))
        return attrs

    def _build_events(self, trace: Trace) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        if trace.decision:
            events.append(
                _event(
                    "openflux.decision",
                    [_kv("openflux.decision.text", _trunc(trace.decision))],
                )
            )
        if trace.correction is not None:
            events.append(
                _event(
                    "openflux.correction",
                    [_kv("openflux.correction.text", _trunc(trace.correction))],
                )
            )

        for ctx in trace.context:
            ts = _iso_to_nanos(ctx.timestamp) if ctx.timestamp else 0
            events.append(
                _event(
                    "openflux.context",
                    [
                        _kv("type", ctx.type),
                        _kv("source", ctx.source),
                        _kv("content_hash", ctx.content_hash),
                        _kv("bytes", ctx.bytes),
                        _kv("timestamp", ctx.timestamp),
                    ],
                    time_nanos=ts,
                )
            )

        for s in trace.searches:
            ts = _iso_to_nanos(s.timestamp) if s.timestamp else 0
            events.append(
                _event(
                    "openflux.search",
                    [
                        _kv("query", _trunc(s.query)),
                        _kv("engine", s.engine),
                        _kv("results_count", s.results_count),
                        _kv("timestamp", s.timestamp),
                    ],
                    time_nanos=ts,
                )
            )

        for src in trace.sources_read:
            ts = _iso_to_nanos(src.timestamp) if src.timestamp else 0
            events.append(
                _event(
                    "openflux.source_read",
                    [
                        _kv("type", src.type),
                        _kv("path", src.path),
                        _kv("content_hash", src.content_hash),
                        _kv("tool", src.tool),
                        _kv("bytes_read", src.bytes_read),
                        _kv("timestamp", src.timestamp),
                    ],
                    time_nanos=ts,
                )
            )

        for t in trace.tools_used:
            ts = _iso_to_nanos(t.timestamp) if t.timestamp else 0
            events.append(
                _event(
                    "openflux.tool_use",
                    [
                        _kv("name", t.name),
                        _kv("tool_input", _trunc(t.tool_input)),
                        _kv("tool_output", _trunc(t.tool_output)),
                        _kv("duration_ms", t.duration_ms),
                        _kv("error", t.error),
                        _kv("timestamp", t.timestamp),
                    ],
                    time_nanos=ts,
                )
            )

        return events
