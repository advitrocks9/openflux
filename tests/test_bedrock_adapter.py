from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from openflux.adapters.bedrock import (
    BedrockAdapter,
    BedrockCloudWatchIngester,
    _handle_failure,
    _handle_guardrail,
    _handle_orchestration,
    _handle_postprocessing,
    _handle_preprocessing,
    _process_trace_event,
    _TraceAccumulator,
)
from openflux.schema import ContextType, SourceType, Status


@pytest.fixture()
def adapter() -> BedrockAdapter:
    traces: list[Any] = []
    a = BedrockAdapter(agent="test-bedrock", on_trace=traces.append)
    a._test_traces = traces
    return a


def _make_acc(session_id: str = "ses-test") -> _TraceAccumulator:
    return _TraceAccumulator(session_id=session_id, started_at="2026-01-01T00:00:00Z")


class TestPreprocessing:
    def test_extracts_system_prompt(self) -> None:
        acc = _make_acc()
        trace = {
            "modelInvocationInput": {
                "text": "You are a helpful assistant.",
                "foundationModel": "anthropic.claude-3-sonnet",
                "type": "PRE_PROCESSING",
            },
            "modelInvocationOutput": {
                "metadata": {
                    "usage": {"inputTokens": 50, "outputTokens": 10},
                },
                "parsedResponse": {"isValid": True, "rationale": "ok"},
            },
        }
        _handle_preprocessing(trace, acc)

        assert acc.model == "anthropic.claude-3-sonnet"
        assert len(acc.context) == 1
        assert acc.context[0].type == ContextType.SYSTEM_PROMPT
        assert acc.context[0].source == "bedrock:preprocessing"
        assert acc.token_usage.input_tokens == 50
        assert acc.token_usage.output_tokens == 10

    def test_no_prompt_text(self) -> None:
        acc = _make_acc()
        _handle_preprocessing(
            {"modelInvocationInput": {}, "modelInvocationOutput": {}}, acc
        )
        assert len(acc.context) == 0

    def test_missing_usage(self) -> None:
        acc = _make_acc()
        _handle_preprocessing(
            {
                "modelInvocationInput": {"text": "hi"},
                "modelInvocationOutput": {},
            },
            acc,
        )
        assert acc.token_usage.input_tokens == 0


class TestOrchestration:
    def test_action_group_invocation(self) -> None:
        acc = _make_acc()
        trace = {
            "modelInvocationInput": {"foundationModel": "anthropic.claude-3-haiku"},
            "modelInvocationOutput": {
                "metadata": {"usage": {"inputTokens": 100, "outputTokens": 50}},
                "rationale": {"traceId": "t1", "text": "I need to look up the order"},
                "invocationInput": {
                    "traceId": "t1",
                    "invocationType": "ACTION_GROUP",
                    "actionGroupInvocationInput": {
                        "actionGroupName": "OrderLookup",
                        "apiPath": "/orders/{id}",
                        "verb": "GET",
                        "parameters": [
                            {"name": "id", "type": "string", "value": "123"}
                        ],
                    },
                },
                "observation": {
                    "traceId": "t1",
                    "type": "ACTION_GROUP",
                    "actionGroupInvocationOutput": {
                        "text": '{"orderId": "123", "status": "shipped"}',
                    },
                },
            },
        }
        _handle_orchestration(trace, acc)

        assert acc.model == "anthropic.claude-3-haiku"
        assert acc.token_usage.input_tokens == 100
        assert len(acc.tools) == 1
        assert acc.tools[0].name == "OrderLookup"
        assert "orders" in acc.tools[0].tool_input
        assert "shipped" in acc.tools[0].tool_output
        assert acc.tools[0].error is False
        assert "I need to look up the order" in acc.metadata["rationales"]

    def test_knowledge_base_lookup(self) -> None:
        acc = _make_acc()
        trace = {
            "modelInvocationInput": {},
            "modelInvocationOutput": {
                "metadata": {"usage": {"inputTokens": 30, "outputTokens": 20}},
                "invocationInput": {
                    "invocationType": "KNOWLEDGE_BASE",
                    "knowledgeBaseLookupInput": {
                        "knowledgeBaseId": "kb-abc123",
                        "text": "What is the return policy?",
                    },
                },
                "observation": {
                    "type": "KNOWLEDGE_BASE",
                    "knowledgeBaseLookupOutput": {
                        "retrievedReferences": [
                            {
                                "content": {"text": "Returns accepted within 30 days."},
                                "location": {
                                    "type": "S3",
                                    "s3Location": {"uri": "s3://docs/returns.pdf"},
                                },
                            },
                            {
                                "content": {
                                    "text": "Refunds processed in 5 business days."
                                },
                                "location": {
                                    "type": "S3",
                                    "s3Location": {"uri": "s3://docs/refunds.pdf"},
                                },
                            },
                        ],
                    },
                },
            },
        }
        _handle_orchestration(trace, acc)

        assert len(acc.searches) == 1
        assert acc.searches[0].query == "What is the return policy?"
        assert acc.searches[0].engine == "bedrock-kb:kb-abc123"
        assert acc.searches[0].results_count == 2

        assert len(acc.sources) == 2
        assert acc.sources[0].type == SourceType.DOCUMENT
        assert acc.sources[0].path == "s3://docs/returns.pdf"
        assert "30 days" in acc.sources[0].content

    def test_agent_collaborator(self) -> None:
        acc = _make_acc()
        trace = {
            "modelInvocationInput": {},
            "modelInvocationOutput": {
                "invocationInput": {
                    "invocationType": "AGENT_COLLABORATOR",
                    "agentCollaboratorInvocationInput": {
                        "agentCollaboratorName": "math-agent",
                        "agentCollaboratorAliasArn": (
                            "arn:aws:bedrock:us-east-1:123:agent-alias/abc"
                        ),
                        "input": {"text": "calculate 2+2"},
                    },
                },
                "observation": {
                    "type": "AGENT_COLLABORATOR",
                    "agentCollaboratorInvocationOutput": {
                        "agentCollaboratorName": "math-agent",
                        "output": {"text": "4"},
                    },
                },
            },
        }
        _handle_orchestration(trace, acc)

        assert len(acc.tools) == 1
        assert acc.tools[0].name == "collaborator:math-agent"
        assert acc.tools[0].tool_input == "calculate 2+2"
        assert acc.tools[0].tool_output == "4"

    def test_final_response(self) -> None:
        acc = _make_acc()
        trace = {
            "modelInvocationInput": {},
            "modelInvocationOutput": {
                "observation": {
                    "type": "FINISH",
                    "finalResponse": {"text": "Your order has been shipped."},
                },
            },
        }
        _handle_orchestration(trace, acc)
        assert acc.decision == "Your order has been shipped."

    def test_reprompt_marks_error(self) -> None:
        acc = _make_acc()
        trace = {
            "modelInvocationInput": {},
            "modelInvocationOutput": {
                "invocationInput": {
                    "invocationType": "ACTION_GROUP",
                    "actionGroupInvocationInput": {
                        "actionGroupName": "BadTool",
                        "apiPath": "/fail",
                        "verb": "POST",
                    },
                },
                "observation": {
                    "type": "REPROMPT",
                    "repromptResponse": {"source": "ACTION_GROUP", "text": "Try again"},
                },
            },
        }
        _handle_orchestration(trace, acc)
        assert acc.tools[0].error is True


class TestPostprocessing:
    def test_extracts_decision(self) -> None:
        acc = _make_acc()
        acc.decision = "old decision"
        trace = {
            "modelInvocationInput": {"foundationModel": "anthropic.claude-3-sonnet"},
            "modelInvocationOutput": {
                "metadata": {"usage": {"inputTokens": 20, "outputTokens": 30}},
                "parsedResponse": {"text": "Here is your final answer."},
            },
        }
        _handle_postprocessing(trace, acc)

        assert acc.decision == "Here is your final answer."
        assert acc.token_usage.input_tokens == 20


class TestFailureAndGuardrail:
    def test_failure_trace(self) -> None:
        acc = _make_acc()
        _handle_failure({"failureReason": "Lambda timeout", "traceId": "t1"}, acc)
        assert acc.has_error is True
        assert acc.failure_reason == "Lambda timeout"

    def test_guardrail_intervened(self) -> None:
        acc = _make_acc()
        _handle_guardrail({"action": "GUARDRAIL_INTERVENED"}, acc)
        assert acc.has_error is True
        assert acc.metadata["guardrail_action"] == "GUARDRAIL_INTERVENED"

    def test_guardrail_none(self) -> None:
        acc = _make_acc()
        _handle_guardrail({"action": "NONE"}, acc)
        assert acc.has_error is False


class TestProcessTraceEvent:
    def test_dispatches_preprocessing(self) -> None:
        acc = _make_acc()
        _process_trace_event(
            {
                "preProcessingTrace": {
                    "modelInvocationInput": {"text": "prompt", "foundationModel": "m1"},
                    "modelInvocationOutput": {},
                },
            },
            acc,
        )
        assert acc.model == "m1"

    def test_dispatches_orchestration(self) -> None:
        acc = _make_acc()
        _process_trace_event(
            {
                "orchestrationTrace": {
                    "modelInvocationInput": {},
                    "modelInvocationOutput": {
                        "observation": {
                            "type": "FINISH",
                            "finalResponse": {"text": "done"},
                        },
                    },
                },
            },
            acc,
        )
        assert acc.decision == "done"

    def test_dispatches_failure(self) -> None:
        acc = _make_acc()
        _process_trace_event(
            {
                "failureTrace": {"failureReason": "boom"},
            },
            acc,
        )
        assert acc.has_error is True

    def test_ignores_unknown(self) -> None:
        acc = _make_acc()
        _process_trace_event({"unknownTrace": {}}, acc)
        assert not acc.has_error


def _make_event_stream(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "trace": {
                "agentId": "agent-xyz",
                "agentAliasId": "alias-1",
                "sessionId": "ses-1",
                "trace": event,
            },
        }
        for event in events
    ]


class TestParseInvokeAgentResponse:
    def test_full_invocation(self, adapter: BedrockAdapter) -> None:
        events = _make_event_stream(
            [
                {
                    "preProcessingTrace": {
                        "modelInvocationInput": {
                            "text": "System prompt here",
                            "foundationModel": "anthropic.claude-3-sonnet",
                        },
                        "modelInvocationOutput": {
                            "metadata": {
                                "usage": {"inputTokens": 100, "outputTokens": 10}
                            },
                        },
                    },
                },
                {
                    "orchestrationTrace": {
                        "modelInvocationInput": {},
                        "modelInvocationOutput": {
                            "metadata": {
                                "usage": {"inputTokens": 200, "outputTokens": 80}
                            },
                            "invocationInput": {
                                "invocationType": "ACTION_GROUP",
                                "actionGroupInvocationInput": {
                                    "actionGroupName": "SearchAPI",
                                    "apiPath": "/search",
                                    "verb": "GET",
                                },
                            },
                            "observation": {
                                "type": "ACTION_GROUP",
                                "actionGroupInvocationOutput": {"text": "results"},
                            },
                        },
                    },
                },
                {
                    "orchestrationTrace": {
                        "modelInvocationInput": {},
                        "modelInvocationOutput": {
                            "observation": {
                                "type": "FINISH",
                                "finalResponse": {"text": "Here are the results."},
                            },
                        },
                    },
                },
            ]
        )

        trace = adapter.parse_invoke_agent_response(events, session_id="ses-custom")

        assert trace.agent == "test-bedrock"
        assert trace.session_id == "ses-custom"
        assert trace.model == "anthropic.claude-3-sonnet"
        assert trace.status == Status.COMPLETED
        assert trace.decision == "Here are the results."
        assert len(trace.context) == 1
        assert trace.context[0].type == ContextType.SYSTEM_PROMPT
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "SearchAPI"
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 300
        assert trace.token_usage.output_tokens == 90
        assert trace.metadata["agent_id"] == "agent-xyz"

    def test_failure_sets_error_status(self, adapter: BedrockAdapter) -> None:
        events = _make_event_stream(
            [
                {"failureTrace": {"failureReason": "Internal error"}},
            ]
        )
        trace = adapter.parse_invoke_agent_response(events)
        assert trace.status == Status.ERROR
        assert trace.metadata["failure_reason"] == "Internal error"

    def test_empty_stream(self, adapter: BedrockAdapter) -> None:
        trace = adapter.parse_invoke_agent_response([])
        assert trace.status == Status.COMPLETED
        assert len(trace.tools_used) == 0

    def test_on_trace_callback(self) -> None:
        collected: list[Any] = []
        adapter = BedrockAdapter(on_trace=collected.append)
        adapter.parse_invoke_agent_response([])
        assert len(collected) == 1

    def test_completed_traces_property(self, adapter: BedrockAdapter) -> None:
        adapter.parse_invoke_agent_response([])
        adapter.parse_invoke_agent_response([])
        assert len(adapter.completed_traces) == 2


class TestParseTraceDict:
    def test_single_orchestration(self, adapter: BedrockAdapter) -> None:
        trace = {
            "orchestrationTrace": {
                "modelInvocationInput": {"foundationModel": "anthropic.claude-3-haiku"},
                "modelInvocationOutput": {
                    "metadata": {"usage": {"inputTokens": 50, "outputTokens": 25}},
                    "observation": {
                        "type": "FINISH",
                        "finalResponse": {"text": "Answer"},
                    },
                },
            },
        }
        trace = adapter.parse_trace_dict(trace, session_id="ses-dict")
        assert trace.model == "anthropic.claude-3-haiku"
        assert trace.decision == "Answer"
        assert trace.session_id == "ses-dict"


class TestCloudWatchIngester:
    def _make_ingester(
        self,
        adapter: BedrockAdapter,
        log_events: list[dict[str, Any]],
        next_token: str | None = None,
    ) -> BedrockCloudWatchIngester:
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client

        response: dict[str, Any] = {"events": log_events}
        if next_token:
            response["nextToken"] = next_token
        mock_client.filter_log_events.return_value = response

        return BedrockCloudWatchIngester(
            adapter=adapter,
            agent_id="agent-xyz",
            region="us-east-1",
            boto3_session=mock_session,
        )

    def test_parses_log_events(self, adapter: BedrockAdapter) -> None:
        log_events = [
            {
                "message": json.dumps(
                    {
                        "sessionId": "ses-cw-1",
                        "trace": {
                            "orchestrationTrace": {
                                "modelInvocationInput": {
                                    "foundationModel": "anthropic.claude-3-sonnet",
                                },
                                "modelInvocationOutput": {
                                    "metadata": {
                                        "usage": {"inputTokens": 10, "outputTokens": 5}
                                    },
                                    "observation": {
                                        "type": "FINISH",
                                        "finalResponse": {"text": "CW answer"},
                                    },
                                },
                            },
                        },
                    }
                ),
            },
        ]
        ingester = self._make_ingester(adapter, log_events)
        traces = ingester.poll(start_time=0, end_time=9999999999999)

        assert len(traces) == 1
        assert traces[0].decision == "CW answer"
        assert traces[0].session_id == "ses-cw-1"

    def test_skips_invalid_json(self, adapter: BedrockAdapter) -> None:
        log_events = [
            {"message": "not valid json"},
            {"message": json.dumps({"unrelated": "data"})},
        ]
        ingester = self._make_ingester(adapter, log_events)
        traces = ingester.poll(start_time=0, end_time=9999999999999)
        assert len(traces) == 0

    def test_pagination_token(self, adapter: BedrockAdapter) -> None:
        ingester = self._make_ingester(adapter, [], next_token="token-abc")
        ingester.poll(start_time=0, end_time=9999999999999)
        assert ingester._next_token == "token-abc"

    def test_multiple_events(self, adapter: BedrockAdapter) -> None:
        events = [
            {
                "message": json.dumps(
                    {
                        "trace": {
                            "preProcessingTrace": {
                                "modelInvocationInput": {"text": f"prompt-{i}"},
                                "modelInvocationOutput": {},
                            },
                        },
                    }
                ),
            }
            for i in range(3)
        ]
        ingester = self._make_ingester(adapter, events)
        traces = ingester.poll(start_time=0, end_time=9999999999999)
        assert len(traces) == 3

    def test_log_group_name(self, adapter: BedrockAdapter) -> None:
        ingester = self._make_ingester(adapter, [])
        assert ingester._log_group == "/aws/bedrock/agents/agent-xyz"

    def test_api_error_raises(self, adapter: BedrockAdapter) -> None:
        mock_session = MagicMock()
        mock_client = MagicMock()
        mock_session.client.return_value = mock_client
        mock_client.filter_log_events.side_effect = Exception("AccessDenied")

        ingester = BedrockCloudWatchIngester(
            adapter=adapter,
            agent_id="agent-xyz",
            boto3_session=mock_session,
        )

        with pytest.raises(RuntimeError, match="Failed to read CloudWatch"):
            ingester.poll(start_time=0, end_time=9999999999999)
