"""Amazon Bedrock Agents adapter."""

from __future__ import annotations

import importlib.util
import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from openflux._util import (
    content_hash,
    generate_session_id,
    generate_trace_id,
    utc_now,
)
from openflux.schema import (
    ContextRecord,
    ContextType,
    SearchRecord,
    SourceRecord,
    SourceType,
    Status,
    TokenUsage,
    ToolRecord,
    Trace,
)

_HAS_BOTO3 = importlib.util.find_spec("boto3") is not None


@dataclass(slots=True)
class _TraceAccumulator:
    session_id: str
    started_at: str = ""
    model: str = ""
    task: str = ""
    scope: str | None = None
    tags: list[str] = field(default_factory=list)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    tools: list[ToolRecord] = field(default_factory=list)
    searches: list[SearchRecord] = field(default_factory=list)
    context: list[ContextRecord] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    decision: str = ""
    correction: str | None = None
    parent_id: str | None = None
    has_error: bool = False
    failure_reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _safe_get(d: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _extract_usage(model_output: dict[str, Any], acc: _TraceAccumulator) -> None:
    usage = _safe_get(model_output, "metadata", "usage")
    if not isinstance(usage, dict):
        return
    acc.token_usage.input_tokens += usage.get("inputTokens", 0)
    acc.token_usage.output_tokens += usage.get("outputTokens", 0)


def _extract_model(model_input: dict[str, Any], acc: _TraceAccumulator) -> None:
    if model := model_input.get("foundationModel", ""):
        acc.model = model


def _handle_preprocessing(trace: dict[str, Any], acc: _TraceAccumulator) -> None:
    model_input = trace.get("modelInvocationInput", {})
    model_output = trace.get("modelInvocationOutput", {})

    _extract_model(model_input, acc)

    if prompt_text := model_input.get("text", ""):
        acc.context.append(
            ContextRecord(
                type=ContextType.SYSTEM_PROMPT,
                source="bedrock:preprocessing",
                content_hash=content_hash(prompt_text),
                content=prompt_text[:4096],
                bytes=len(prompt_text.encode("utf-8")),
                timestamp=utc_now(),
            )
        )

    _extract_usage(model_output, acc)


def _handle_orchestration(trace: dict[str, Any], acc: _TraceAccumulator) -> None:
    model_input = trace.get("modelInvocationInput", {})
    model_output = trace.get("modelInvocationOutput", {})

    _extract_model(model_input, acc)
    _extract_usage(model_output, acc)

    rationale = model_output.get("rationale", {})
    if isinstance(rationale, dict) and rationale.get("text"):
        acc.metadata.setdefault("rationales", []).append(rationale["text"])

    # invocationInput and observation are siblings at the orchestrationTrace level,
    # not nested inside modelInvocationOutput
    invocation = trace.get("invocationInput", {})
    observation = trace.get("observation", {})
    obs_type = observation.get("type", "")

    ag_input = invocation.get("actionGroupInvocationInput", {})
    if isinstance(ag_input, dict) and ag_input.get("actionGroupName"):
        tool_name = ag_input["actionGroupName"]
        input_str = json.dumps(
            {
                "apiPath": ag_input.get("apiPath", ""),
                "verb": ag_input.get("verb", ""),
                "parameters": ag_input.get("parameters", []),
            },
            default=str,
        )

        ag_output = observation.get("actionGroupInvocationOutput", {})
        output_str = ag_output.get("text", "") if isinstance(ag_output, dict) else ""

        acc.tools.append(
            ToolRecord(
                name=tool_name,
                tool_input=input_str[:4096],
                tool_output=output_str[:16384],
                error=obs_type == "REPROMPT",
                timestamp=utc_now(),
            )
        )

        # REPROMPT indicates the agent had to self-correct
        if obs_type == "REPROMPT" and output_str:
            acc.correction = f"REPROMPT on {tool_name}: {output_str[:300]}"

    kb_input = invocation.get("knowledgeBaseLookupInput", {})
    if isinstance(kb_input, dict) and kb_input.get("text"):
        kb_id = kb_input.get("knowledgeBaseId", "")
        query_text = kb_input["text"]

        kb_output = observation.get("knowledgeBaseLookupOutput", {})
        refs = (
            kb_output.get("retrievedReferences", [])
            if isinstance(kb_output, dict)
            else []
        )

        acc.searches.append(
            SearchRecord(
                query=query_text[:500],
                engine=f"bedrock-kb:{kb_id}" if kb_id else "bedrock-kb",
                results_count=len(refs),
                timestamp=utc_now(),
            )
        )

        for ref in refs:
            ref_content = _safe_get(ref, "content", "text") or ""
            ref_uri = _safe_get(ref, "location", "s3Location", "uri") or ""
            acc.sources.append(
                SourceRecord(
                    type=SourceType.DOCUMENT,
                    path=ref_uri,
                    content_hash=content_hash(ref_content) if ref_content else "",
                    content=ref_content[:4096],
                    bytes_read=len(ref_content.encode("utf-8")) if ref_content else 0,
                    timestamp=utc_now(),
                )
            )

    collab_input = invocation.get("agentCollaboratorInvocationInput", {})
    if isinstance(collab_input, dict) and collab_input.get("agentCollaboratorName"):
        collab_name = collab_input["agentCollaboratorName"]
        collab_text = _safe_get(collab_input, "input", "text") or ""
        collab_output = observation.get("agentCollaboratorInvocationOutput", {})
        collab_resp = (
            _safe_get(collab_output, "output", "text") or ""
            if isinstance(collab_output, dict)
            else ""
        )

        acc.tools.append(
            ToolRecord(
                name=f"collaborator:{collab_name}",
                tool_input=collab_text[:4096],
                tool_output=collab_resp[:16384],
                timestamp=utc_now(),
            )
        )

    final = observation.get("finalResponse", {})
    if isinstance(final, dict) and final.get("text"):
        acc.decision = final["text"]


def _handle_postprocessing(trace: dict[str, Any], acc: _TraceAccumulator) -> None:
    model_input = trace.get("modelInvocationInput", {})
    model_output = trace.get("modelInvocationOutput", {})

    _extract_model(model_input, acc)
    _extract_usage(model_output, acc)

    parsed = model_output.get("parsedResponse", {})
    if isinstance(parsed, dict) and parsed.get("text"):
        acc.decision = parsed["text"]


def _handle_failure(trace: dict[str, Any], acc: _TraceAccumulator) -> None:
    acc.has_error = True
    acc.failure_reason = trace.get("failureReason", "unknown")


def _handle_guardrail(trace: dict[str, Any], acc: _TraceAccumulator) -> None:
    action = trace.get("action", "")
    if action == "GUARDRAIL_INTERVENED":
        acc.has_error = True
    acc.metadata["guardrail_action"] = action


def _process_trace_event(trace_data: dict[str, Any], acc: _TraceAccumulator) -> None:
    if "preProcessingTrace" in trace_data:
        _handle_preprocessing(trace_data["preProcessingTrace"], acc)
    elif "orchestrationTrace" in trace_data:
        _handle_orchestration(trace_data["orchestrationTrace"], acc)
    elif "postProcessingTrace" in trace_data:
        _handle_postprocessing(trace_data["postProcessingTrace"], acc)
    elif "failureTrace" in trace_data:
        _handle_failure(trace_data["failureTrace"], acc)
    elif "guardrailTrace" in trace_data:
        _handle_guardrail(trace_data["guardrailTrace"], acc)


def _parse_iso_ms(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp to datetime for duration computation."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _derive_tags(acc: _TraceAccumulator) -> list[str]:
    """Auto-derive tags from accumulated trace state."""
    tags: list[str] = []
    if acc.searches:
        tags.append("kb-lookup")
    has_collaborator = any(t.name.startswith("collaborator:") for t in acc.tools)
    has_action_group = any(not t.name.startswith("collaborator:") for t in acc.tools)
    if has_action_group:
        tags.append("action-group")
    if has_collaborator:
        tags.append("collaborator")
    if "guardrail_action" in acc.metadata:
        tags.append("guardrail")
    if acc.has_error:
        tags.append("failure")
    return tags


class BedrockAdapter:
    def __init__(
        self,
        agent: str = "bedrock",
        on_trace: Any | None = None,
    ) -> None:
        self._agent = agent
        self._on_trace = on_trace
        self._lock = threading.Lock()
        self._completed: list[Trace] = []

    def parse_invoke_agent_response(
        self,
        event_stream: Any,
        session_id: str | None = None,
        task: str = "",
        scope: str | None = None,
        tags: list[str] | None = None,
        started_at: str | None = None,
        parent_id: str | None = None,
    ) -> Trace:
        """Parse a Bedrock InvokeAgent response event stream into a Trace.

        Args:
            event_stream: Iterable of Bedrock event dicts from invoke_agent().
            session_id: Session ID for trace continuity. Auto-generated if omitted.
            task: The user's input text (inputText). Bedrock streams don't echo it
                back, so the caller must provide it for the task field to be populated.
            scope: Category/scope label. Not available from Bedrock natively —
                caller must provide it.
            tags: User-defined tags. Auto-derived tags (kb-lookup, action-group,
                collaborator, guardrail, failure) are appended automatically.
            started_at: ISO 8601 timestamp of when invoke_agent() was called.
                Enables accurate duration_ms. If omitted, duration measures only
                parse time (effectively 0).
            parent_id: Parent trace ID for sub-agent or multi-step workflows.
        """
        acc = _TraceAccumulator(
            session_id=session_id or generate_session_id(),
            started_at=started_at or utc_now(),
            task=task,
            scope=scope,
            tags=list(tags) if tags else [],
            parent_id=parent_id,
        )

        for event in event_stream:
            trace_wrapper = event.get("trace", {})
            trace_data = trace_wrapper.get("trace", {})
            if trace_data:
                _process_trace_event(trace_data, acc)

            if not acc.metadata.get("agent_id") and (
                agent_id := trace_wrapper.get("agentId", "")
            ):
                acc.metadata["agent_id"] = agent_id
                acc.metadata["agent_alias_id"] = trace_wrapper.get("agentAliasId", "")

        trace = self._build_trace(acc)
        with self._lock:
            self._completed.append(trace)

        if self._on_trace:
            self._on_trace(trace)

        return trace

    def parse_trace_dict(
        self,
        trace_data: dict[str, Any],
        session_id: str | None = None,
        task: str = "",
        scope: str | None = None,
        tags: list[str] | None = None,
        started_at: str | None = None,
        parent_id: str | None = None,
    ) -> Trace:
        """Parse a single trace dict, e.g. from CloudWatch logs.

        Args:
            trace_data: A Bedrock trace dict containing one of the known trace
                types (preProcessingTrace, orchestrationTrace, etc.).
            session_id: Session ID for trace continuity. Auto-generated if omitted.
            task: The user's input text. Bedrock traces don't include the original
                query — caller must provide it.
            scope: Category/scope label. Not available from Bedrock natively —
                caller must provide it.
            tags: User-defined tags. Auto-derived tags are appended automatically.
            started_at: ISO 8601 timestamp of when the request was initiated.
                Enables accurate duration_ms. If omitted, duration measures only
                parse time (effectively 0).
            parent_id: Parent trace ID for sub-agent or multi-step workflows.
        """
        acc = _TraceAccumulator(
            session_id=session_id or generate_session_id(),
            started_at=started_at or utc_now(),
            task=task,
            scope=scope,
            tags=list(tags) if tags else [],
            parent_id=parent_id,
        )
        _process_trace_event(trace_data, acc)

        trace = self._build_trace(acc)
        with self._lock:
            self._completed.append(trace)

        if self._on_trace:
            self._on_trace(trace)

        return trace

    def cloudwatch_ingester(
        self,
        agent_id: str,
        region: str | None = None,
        boto3_session: Any | None = None,
    ) -> BedrockCloudWatchIngester:
        return BedrockCloudWatchIngester(
            adapter=self,
            agent_id=agent_id,
            region=region,
            boto3_session=boto3_session,
        )

    @property
    def completed_traces(self) -> list[Trace]:
        with self._lock:
            return list(self._completed)

    def _build_trace(self, acc: _TraceAccumulator) -> Trace:
        if acc.failure_reason:
            acc.metadata["failure_reason"] = acc.failure_reason

        # Compute duration from started_at to now (minimum 1ms when started_at provided)
        duration_ms = 0
        if acc.started_at:
            start = _parse_iso_ms(acc.started_at)
            end = datetime.now(UTC)
            duration_ms = max(1, int((end - start).total_seconds() * 1000))

        # Merge auto-derived tags with user-provided tags (dedup)
        auto_tags = _derive_tags(acc)
        all_tags = list(dict.fromkeys(acc.tags + auto_tags))

        return Trace(
            id=generate_trace_id(),
            timestamp=acc.started_at or utc_now(),
            agent=self._agent,
            session_id=acc.session_id,
            parent_id=acc.parent_id,
            model=acc.model,
            task=acc.task,
            scope=acc.scope,
            tags=all_tags,
            status=Status.ERROR if acc.has_error else Status.COMPLETED,
            decision=acc.decision,
            correction=acc.correction,
            tools_used=acc.tools,
            searches=acc.searches,
            sources_read=acc.sources,
            context=acc.context,
            token_usage=acc.token_usage,
            turn_count=len(acc.tools) + len(acc.searches),
            duration_ms=duration_ms,
            metadata=acc.metadata,
        )


class BedrockCloudWatchIngester:
    """Polls CloudWatch for /aws/bedrock/agents/{agent_id} traces."""

    def __init__(
        self,
        adapter: BedrockAdapter,
        agent_id: str,
        region: str | None = None,
        boto3_session: Any | None = None,
    ) -> None:
        if not _HAS_BOTO3 and boto3_session is None:
            msg = "boto3 required. Install with: pip install openflux[bedrock]"
            raise ImportError(msg)

        self._adapter = adapter
        self._agent_id = agent_id
        self._log_group = f"/aws/bedrock/agents/{agent_id}"
        self._next_token: str | None = None

        if boto3_session is not None:
            self._logs_client = boto3_session.client("logs", region_name=region)
        elif _HAS_BOTO3:
            import boto3

            session = boto3.Session(region_name=region)
            self._logs_client = session.client("logs")
        else:
            self._logs_client = None

    def poll(
        self,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> list[Trace]:
        import time

        now_ms = int(time.time() * 1000)
        if start_time is None:
            start_time = now_ms - 3_600_000
        if end_time is None:
            end_time = now_ms

        kwargs: dict[str, Any] = {
            "logGroupName": self._log_group,
            "startTime": start_time,
            "endTime": end_time,
            "limit": limit,
            "startFromHead": True,
        }
        if self._next_token:
            kwargs["nextToken"] = self._next_token

        try:
            resp = self._logs_client.filter_log_events(**kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to read CloudWatch log group {self._log_group}: {exc}"
            ) from exc

        self._next_token = resp.get("nextToken")

        traces: list[Trace] = []
        for event in resp.get("events", []):
            if trace := self._parse_log_event(event.get("message", "")):
                traces.append(trace)

        return traces

    def _parse_log_event(self, message: str) -> Trace | None:
        try:
            data = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return None

        trace_data = data.get("trace", data)
        if not isinstance(trace_data, dict):
            return None

        known_keys = {
            "preProcessingTrace",
            "orchestrationTrace",
            "postProcessingTrace",
            "failureTrace",
            "guardrailTrace",
        }
        if not known_keys & trace_data.keys():
            return None

        session_id = data.get("sessionId", generate_session_id())
        return self._adapter.parse_trace_dict(trace_data, session_id=session_id)
