"""Bedrock acceptance test - simulated event streams, exactly how a real user feeds boto3 data."""

import pytest
from helpers import check_trace

from openflux._util import utc_now
from openflux.adapters.bedrock import BedrockAdapter
from openflux.sinks.sqlite import SQLiteSink


@pytest.fixture()
def db_path(tmp_path):
    return tmp_path / "traces.db"


def _make_full_event_stream():
    """Build a realistic Bedrock InvokeAgent event stream with all trace types."""
    return [
        # 1. Preprocessing - system prompt + model invocation
        {
            "trace": {
                "agentId": "AGENT123",
                "agentAliasId": "ALIAS456",
                "trace": {
                    "preProcessingTrace": {
                        "modelInvocationInput": {
                            "foundationModel": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                            "text": "You are a helpful research assistant. Answer questions using the knowledge base.",
                        },
                        "modelInvocationOutput": {
                            "metadata": {
                                "usage": {
                                    "inputTokens": 350,
                                    "outputTokens": 50,
                                }
                            },
                            "parsedResponse": {
                                "isValid": True,
                            },
                        },
                    }
                },
            }
        },
        # 2. Orchestration - KB lookup (search + source)
        {
            "trace": {
                "agentId": "AGENT123",
                "trace": {
                    "orchestrationTrace": {
                        "modelInvocationInput": {
                            "foundationModel": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                            "text": "Use the knowledge base to find information.",
                        },
                        "modelInvocationOutput": {
                            "metadata": {
                                "usage": {
                                    "inputTokens": 2000,
                                    "outputTokens": 300,
                                }
                            },
                            "rationale": {
                                "text": "I need to search the knowledge base for relevant documents.",
                            },
                        },
                        "invocationInput": {
                            "knowledgeBaseLookupInput": {
                                "text": "authentication best practices 2024",
                                "knowledgeBaseId": "KB-SEC-001",
                            }
                        },
                        "observation": {
                            "knowledgeBaseLookupOutput": {
                                "retrievedReferences": [
                                    {
                                        "content": {
                                            "text": "OAuth 2.0 PKCE flow is recommended for public clients."
                                        },
                                        "location": {
                                            "s3Location": {
                                                "uri": "s3://docs-bucket/auth-guide.pdf"
                                            }
                                        },
                                    },
                                    {
                                        "content": {
                                            "text": "Session tokens should be rotated every 15 minutes."
                                        },
                                        "location": {
                                            "s3Location": {
                                                "uri": "s3://docs-bucket/security-policy.pdf"
                                            }
                                        },
                                    },
                                ]
                            }
                        },
                    }
                },
            }
        },
        # 3. Orchestration - action group invocation (tool)
        {
            "trace": {
                "agentId": "AGENT123",
                "trace": {
                    "orchestrationTrace": {
                        "modelInvocationInput": {
                            "foundationModel": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                        },
                        "modelInvocationOutput": {
                            "metadata": {
                                "usage": {
                                    "inputTokens": 1500,
                                    "outputTokens": 200,
                                }
                            },
                        },
                        "invocationInput": {
                            "actionGroupInvocationInput": {
                                "actionGroupName": "SecurityScanner",
                                "apiPath": "/scan",
                                "verb": "POST",
                                "parameters": [
                                    {"name": "target", "value": "auth-module"}
                                ],
                            }
                        },
                        "observation": {
                            "type": "ACTION_GROUP",
                            "actionGroupInvocationOutput": {
                                "text": "Scan complete: 2 issues found (medium severity)"
                            },
                        },
                    }
                },
            }
        },
        # 4. Orchestration - collaborator (sub-agent)
        {
            "trace": {
                "agentId": "AGENT123",
                "trace": {
                    "orchestrationTrace": {
                        "modelInvocationInput": {
                            "foundationModel": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                        },
                        "modelInvocationOutput": {
                            "metadata": {
                                "usage": {
                                    "inputTokens": 800,
                                    "outputTokens": 150,
                                }
                            },
                        },
                        "invocationInput": {
                            "agentCollaboratorInvocationInput": {
                                "agentCollaboratorName": "ComplianceChecker",
                                "input": {
                                    "text": "Check if auth module meets SOC2 requirements"
                                },
                            }
                        },
                        "observation": {
                            "agentCollaboratorInvocationOutput": {
                                "output": {
                                    "text": "SOC2 compliance: 3/5 controls satisfied. Missing: MFA enforcement, audit logging."
                                }
                            },
                        },
                    }
                },
            }
        },
        # 5. Orchestration - REPROMPT (correction)
        {
            "trace": {
                "agentId": "AGENT123",
                "trace": {
                    "orchestrationTrace": {
                        "modelInvocationInput": {
                            "foundationModel": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                        },
                        "modelInvocationOutput": {
                            "metadata": {
                                "usage": {
                                    "inputTokens": 500,
                                    "outputTokens": 100,
                                }
                            },
                        },
                        "invocationInput": {
                            "actionGroupInvocationInput": {
                                "actionGroupName": "SecurityScanner",
                                "apiPath": "/deep-scan",
                                "verb": "POST",
                                "parameters": [],
                            }
                        },
                        "observation": {
                            "type": "REPROMPT",
                            "actionGroupInvocationOutput": {
                                "text": "Rate limited, retry with backoff"
                            },
                        },
                    }
                },
            }
        },
        # 6. Postprocessing - final answer (decision)
        {
            "trace": {
                "agentId": "AGENT123",
                "trace": {
                    "postProcessingTrace": {
                        "modelInvocationInput": {
                            "foundationModel": "anthropic.claude-3-5-sonnet-20241022-v2:0",
                        },
                        "modelInvocationOutput": {
                            "metadata": {
                                "usage": {
                                    "inputTokens": 600,
                                    "outputTokens": 400,
                                }
                            },
                            "parsedResponse": {
                                "text": "Security audit complete. Found 2 medium-severity issues in auth module. SOC2 compliance at 60%. Recommendations: enable MFA, add audit logging."
                            },
                        },
                    }
                },
            }
        },
        # 7. Guardrail trace
        {
            "trace": {
                "agentId": "AGENT123",
                "trace": {
                    "guardrailTrace": {
                        "action": "GUARDRAIL_NONE",
                    }
                },
            }
        },
    ]


class TestBedrockUserWorkflow:
    """A user parses Bedrock InvokeAgent response streams into OpenFlux traces."""

    def test_full_event_stream(self, db_path):
        started_at = utc_now()
        adapter = BedrockAdapter(agent="bedrock-security-agent")
        event_stream = _make_full_event_stream()

        trace = adapter.parse_invoke_agent_response(
            event_stream,
            session_id="sess-bedrock-001",
            task="Audit the authentication module for security vulnerabilities and SOC2 compliance",
            scope="security-audit",
            tags=["security", "compliance", "auth"],
            started_at=started_at,
            parent_id="trc-parent-001",
        )

        # Write to SQLite for check_trace
        sink = SQLiteSink(path=str(db_path))
        sink.write(trace)
        sink.close()

        trace_result, coverage = check_trace(
            db_path,
            required=[
                "id",
                "timestamp",
                "agent",
                "session_id",
                "parent_id",
                "model",
                "task",
                "decision",
                "status",
                "correction",
                "scope",
                "tags",
                "context",
                "searches",
                "sources_read",
                "tools_used",
                "token_usage",
                "duration_ms",
                "metadata",
                "schema_version",
                "turn_count",
            ],
            na=["files_modified"],
        )
        assert coverage >= 85

        # Verify specific field contents
        assert trace_result.agent == "bedrock-security-agent"
        assert trace_result.model == "anthropic.claude-3-5-sonnet-20241022-v2:0"
        assert "security" in trace_result.tags
        assert "kb-lookup" in trace_result.tags
        assert "action-group" in trace_result.tags
        assert "collaborator" in trace_result.tags
        assert "guardrail" in trace_result.tags
        assert len(trace_result.searches) >= 1
        assert len(trace_result.sources_read) >= 2
        assert len(trace_result.tools_used) >= 3  # 2 action groups + 1 collaborator
        assert trace_result.token_usage is not None
        assert trace_result.token_usage.input_tokens > 0
        assert trace_result.decision != ""
        assert trace_result.metadata.get("agent_id") == "AGENT123"

    def test_parse_trace_dict_single(self, db_path):
        """User parses a single trace dict (e.g. from CloudWatch logs)."""
        adapter = BedrockAdapter(agent="bedrock-cw")
        trace = adapter.parse_trace_dict(
            {
                "orchestrationTrace": {
                    "modelInvocationInput": {
                        "foundationModel": "anthropic.claude-3-haiku-20240307-v1:0",
                    },
                    "modelInvocationOutput": {
                        "metadata": {"usage": {"inputTokens": 100, "outputTokens": 50}},
                        "rationale": {"text": "Looking up data"},
                    },
                    "invocationInput": {
                        "actionGroupInvocationInput": {
                            "actionGroupName": "DataFetcher",
                            "apiPath": "/fetch",
                            "verb": "GET",
                            "parameters": [],
                        }
                    },
                    "observation": {
                        "type": "ACTION_GROUP",
                        "actionGroupInvocationOutput": {"text": "fetched 42 rows"},
                    },
                }
            },
            task="Fetch user data",
            started_at=utc_now(),
        )

        assert trace.agent == "bedrock-cw"
        assert trace.model == "anthropic.claude-3-haiku-20240307-v1:0"
        assert len(trace.tools_used) == 1
        assert trace.tools_used[0].name == "DataFetcher"
        assert trace.token_usage is not None
        assert trace.token_usage.input_tokens == 100

    def test_failure_trace(self, db_path):
        """User handles a Bedrock failure event."""
        adapter = BedrockAdapter(agent="bedrock-fail")
        trace = adapter.parse_invoke_agent_response(
            [
                {
                    "trace": {
                        "agentId": "FAIL-AGENT",
                        "trace": {
                            "failureTrace": {
                                "failureReason": "Lambda function timed out"
                            }
                        },
                    }
                }
            ],
            task="Process data",
            started_at=utc_now(),
        )

        assert trace.status == "error"
        assert "failure" in trace.tags
        assert trace.metadata.get("failure_reason") == "Lambda function timed out"
