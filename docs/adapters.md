# Adapter Guides

Each adapter hooks into a specific framework's telemetry system and normalizes events into OpenFlux Traces. The core library has zero dependencies; each adapter adds one optional dependency via pip extras.

---

## Claude Code

**Install:** No pip extra required (stdlib only).

```bash
openflux install claude-code
```

This writes lifecycle hooks into `~/.claude/settings.json`. From that point, every Claude Code session automatically records traces to SQLite.

**How it works:** Claude Code fires subprocess hooks at `SessionStart`, `PostToolUse`, `PostToolUseFailure`, `SubagentStart`, and `Stop`/`SessionEnd`. The adapter classifies each tool call (Read, Write, Edit, Bash, WebSearch, WebFetch, Grep, Glob) into the appropriate record types, buffers events in an NDJSON file, and builds a Trace when the session ends.

**Fields populated:**

| Field | Source |
|---|---|
| id, timestamp, agent, session_id | Auto-generated / session metadata |
| model | Session start metadata |
| status | Error detection from tool failures |
| task | (Derived from transcript if available) |
| decision | (Derived from transcript if available) |
| correction | Regex pattern matching on transcript for user corrections |
| context | (System prompts from transcript parsing) |
| searches | WebSearch queries, Grep/Glob pattern searches |
| sources_read | File reads (Read), URL fetches (WebFetch), search result files |
| tools_used | Bash commands and unclassified tool calls |
| files_modified | Paths from Write and Edit tool calls |
| turn_count | Number of tool calls |
| duration_ms | Calculated from session start to end |
| metadata | `environment.cwd`, `environment.permission_mode` |
| schema_version | Always set |

**N/A fields:** `parent_id` (no parent trace concept), `scope` (no grouping signal), `tags` (no tagging mechanism), `token_usage` (not exposed by Claude Code hooks).

---

## OpenAI Agents SDK

**Install:**

```bash
pip install openflux[openai]
```

**Integration:**

```python
from agents import Agent, Runner
from agents.tracing import add_trace_processor
from openflux.adapters.openai_agents import OpenFluxProcessor

processor = OpenFluxProcessor(agent="my-agent")
add_trace_processor(processor)

agent = Agent(name="assistant", instructions="You are helpful.")
result = Runner.run_sync(agent, "Summarize this document.")

# Access completed traces
traces = processor.completed_traces
```

**Custom search tool detection:** By default, tools named `web_search`, `search`, or `retrieve` are classified as searches. Override with:

```python
processor = OpenFluxProcessor(agent="my-agent", search_tools={"my_search", "rag_lookup"})
```

**Callback for custom sinks:**

```python
def on_trace(trace):
    print(f"Trace recorded: {trace.id}")

processor = OpenFluxProcessor(agent="my-agent", on_trace=on_trace)
```

**Fields populated:**

| Field | Source |
|---|---|
| id, timestamp, agent, session_id | Auto-generated / SDK trace ID |
| model | GenerationSpanData |
| status | Error spans set `Status.ERROR` |
| context | Agent instructions (system prompt) from AgentSpanData |
| searches | Function calls matching `search_tools` set |
| tools_used | FunctionSpanData (name, input, output, duration, error) |
| turn_count | Number of tool calls |
| token_usage | GenerationSpanData usage (input + output tokens) |
| metadata | Handoff data, guardrail triggers |
| schema_version | Always set |

**N/A fields:** `parent_id`, `correction`, `scope`, `tags`, `sources_read`, `files_modified`, `duration_ms` (span-level only), `task`, `decision`.

---

## LangChain / LangGraph

**Install:**

```bash
pip install openflux[langchain]
```

**Integration:**

```python
import openflux

handler = openflux.langchain_handler(agent="my-rag-app")

# Use with any LangChain chain or agent
result = chain.invoke({"input": "..."}, config={"callbacks": [handler]})

# Or with a retrieval chain
result = rag_chain.invoke(
    {"input": "What does X do?"},
    config={"callbacks": [handler]},
)

# Access completed traces
traces = handler.completed_traces
```

**Fields populated:**

| Field | Source |
|---|---|
| id, timestamp, agent, session_id | Auto-generated / LangChain run ID |
| parent_id | Parent run ID from callback hierarchy |
| model | LLM serialized kwargs or llm_output |
| task | Chain input (`input` or `question` key) |
| decision | Agent finish output or chain end output |
| status | Chain/tool errors set `Status.ERROR` |
| scope | Chain name from serialized data |
| context | RAG chunks from retriever results |
| searches | Retriever queries with result counts |
| sources_read | Retrieved documents with content hashes |
| tools_used | Tool start/end with input/output |
| turn_count | Number of tool calls |
| token_usage | LLM output token usage (prompt + completion tokens) |
| metadata | Agent reasoning logs |
| schema_version | Always set |

**N/A fields:** `correction` (no correction signal), `tags` (no tagging mechanism), `files_modified` (not tracked), `duration_ms` (not calculated at trace level).

---

## Claude Agent SDK

**Install:**

```bash
pip install openflux[claude-agent-sdk]
```

**Integration:**

```python
from openflux.adapters.claude_agent_sdk import create_openflux_hooks

hooks = create_openflux_hooks(agent="my-claude-agent")

# Pass hooks to ClaudeAgentOptions
# options = ClaudeAgentOptions(hooks=hooks)
```

Or use the adapter directly for more control:

```python
from openflux.adapters.claude_agent_sdk import ClaudeAgentSDKAdapter

adapter = ClaudeAgentSDKAdapter(agent="my-agent", on_trace=lambda t: print(t.id))
hooks = adapter.create_hooks()

# After the agent runs:
traces = adapter.completed_traces
```

**How it works:** Hooks fire on `PostToolUse`, `PostToolUseFailure`, `SubagentStart`, and `Stop`. The adapter accumulates tool events per session and builds a Trace when the agent stops.

**Fields populated:**

| Field | Source |
|---|---|
| id, timestamp, agent, session_id | Auto-generated / session data |
| model | Via `record_usage()` call |
| status | Tool errors set `Status.ERROR` |
| sources_read | Read/WebFetch tool calls produce SourceRecords |
| tools_used | All tool calls with input/output |
| files_modified | Write/Edit tool paths |
| turn_count | Number of tool calls |
| token_usage | Via `adapter.record_usage(session_id, usage_dict, model="...")` |
| metadata | `environment.cwd`, subagent info |
| schema_version | Always set |

**N/A fields:** `parent_id`, `task`, `decision`, `correction`, `scope`, `tags`, `context`, `searches`, `duration_ms`.

---

## AutoGen

**Install:**

```bash
pip install openflux[autogen]
```

**Integration:**

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from openflux.adapters.autogen import AutoGenStreamConsumer

consumer = AutoGenStreamConsumer(agent="my-autogen-team")

team = RoundRobinGroupChat(
    [agent],
    termination_condition=TextMentionTermination("TERMINATE"),
)

# Process the stream
async for message in team.run_stream(task="Do something"):
    consumer.process(message)

# Or flush manually
trace = consumer.flush()
traces = consumer.completed_traces
```

**How it works:** The consumer processes AutoGen v0.4 message types (`TextMessage`, `ToolCallRequestEvent`, `ToolCallExecutionEvent`, `HandoffMessage`, `StopMessage`, `TaskResult`) and accumulates them into a Trace. Pending tool call IDs are matched to their results.

**Fields populated:**

| Field | Source |
|---|---|
| id, timestamp, agent, session_id | Auto-generated |
| model | (Set if accessible from agent config) |
| status | Tool execution errors |
| searches | Tool calls matching `search_tools` set |
| tools_used | ToolCallRequest/Execution events with input/output |
| turn_count | Number of tool calls |
| token_usage | `models_usage` from messages (prompt + completion tokens) |
| metadata | Handoffs, stop reason, agents seen |
| schema_version | Always set |

**N/A fields:** `parent_id`, `task`, `decision`, `correction`, `scope`, `tags`, `context`, `sources_read`, `files_modified`, `duration_ms`.

---

## CrewAI

**Install:**

```bash
pip install openflux[crewai]
```

**Integration:**

```python
from crewai import Crew, Agent, Task
from crewai.events import crewai_event_bus
from openflux.adapters.crewai import OpenFluxCrewListener

listener = OpenFluxCrewListener(agent="my-crew")
listener.setup_listeners(crewai_event_bus)

crew = Crew(agents=[agent], tasks=[task])
result = crew.kickoff()

traces = listener.completed_traces  # One trace per task
```

**How it works:** One Trace is emitted per CrewAI task. The listener subscribes to the `crewai_event_bus` for task lifecycle, agent execution, LLM calls, and tool usage events. Parallel tasks get independent accumulators.

**Fields populated:**

| Field | Source |
|---|---|
| id, timestamp, agent, session_id | Auto-generated (session shared per crew kickoff) |
| model | LLMCallCompletedEvent |
| task | Task description |
| decision | Task or agent completion output |
| status | Tool errors set `Status.ERROR` |
| scope | Agent role |
| sources_read | LLM response content as API source records |
| tools_used | Tool start/finish/error events with duration |
| turn_count | LLM call count (not tool count) |
| token_usage | LLMCallCompletedEvent usage |
| duration_ms | Calculated from task start to flush |
| metadata | `crew_name` |
| schema_version | Always set |

**N/A fields:** `parent_id`, `correction`, `tags`, `context`, `searches`, `files_modified`.

---

## Google ADK

**Install:**

```bash
pip install openflux[google-adk]
```

**Integration:**

```python
from google.adk.agents import Agent
from openflux.adapters.google_adk import create_adk_callbacks

callbacks = create_adk_callbacks(agent="my-adk-agent")

agent = Agent(
    name="assistant",
    model="gemini-2.5-flash",
    instruction="You are helpful.",
    before_model_callback=callbacks.before_model,
    after_model_callback=callbacks.after_model,
    before_tool_callback=callbacks.before_tool,
    after_tool_callback=callbacks.after_tool,
)

# After the agent runs, flush to get traces
traces = callbacks._adapter.flush()
```

**How it works:** Four callbacks (`before_model`, `after_model`, `before_tool`, `after_tool`) capture model requests/responses and tool calls. System instructions are extracted from the LLM request. Agent handoffs via `transfer_to_agent` function calls are detected automatically.

**Fields populated:**

| Field | Source |
|---|---|
| id, timestamp, agent, session_id | Auto-generated / ADK session ID |
| model | LLM response metadata |
| status | Error detection |
| context | System instructions from LLM requests |
| searches | Tool calls matching `search_tools` set (includes `google_search`) |
| tools_used | Before/after tool callbacks with duration |
| turn_count | Number of tool calls |
| token_usage | `usage_metadata` (prompt + candidate tokens) |
| metadata | Handoff data from `transfer_to_agent` calls |
| schema_version | Always set |

**N/A fields:** `parent_id`, `task`, `decision`, `correction`, `scope`, `tags`, `sources_read`, `files_modified`, `duration_ms` (trace-level).

---

## MCP (Model Context Protocol)

**Install:**

```bash
pip install openflux[mcp]
```

**Integration:**

The MCP adapter exposes OpenFlux as an MCP server with tools and resources that any MCP client (Claude, etc.) can call.

```python
from openflux.adapters.mcp import MCPServerAdapter

server = MCPServerAdapter(agent="my-mcp-agent", db_path="/path/to/traces.db")
server.run()  # Starts stdio transport
```

**Exposed MCP tools:**

- `trace_record` -- Record what the agent just did. Accepts `task`, `decision`, `agent`, `model`, `status`, `scope`, `tags`, `files_modified`, `correction`, `duration_ms`, `metadata`, `session_id`.
- `trace_search` -- Full-text search across past traces. Accepts `query`, `limit`, `agent`, `scope`.

**Exposed MCP resources:**

- `trace://recent` -- Recent traces for session context injection.
- `trace://context/{topic}` -- Past traces relevant to a topic (FTS5 search).

**Fields populated:** Determined by what the MCP client passes to `trace_record`. All fields accepted by the tool are stored directly on the Trace.

**N/A fields:** `parent_id`, `turn_count`, `token_usage`, `context`, `searches`, `sources_read`, `tools_used` (the MCP tool creates traces from explicit parameters, not from observed events).

---

## Amazon Bedrock

**Install:**

```bash
pip install openflux[bedrock]
```

**Integration (invoke_agent response):**

```python
import boto3
from openflux.adapters.bedrock import BedrockAdapter

adapter = BedrockAdapter(agent="my-bedrock-agent")

client = boto3.client("bedrock-agent-runtime")
response = client.invoke_agent(
    agentId="AGENT_ID",
    agentAliasId="ALIAS_ID",
    sessionId="session-123",
    inputText="What are my options?",
    enableTrace=True,
)

trace = adapter.parse_invoke_agent_response(
    response["completion"],
    session_id="session-123",
)
```

**Integration (CloudWatch polling):**

```python
adapter = BedrockAdapter(agent="bedrock-fleet")
ingester = adapter.cloudwatch_ingester(agent_id="AGENT_ID", region="us-east-1")

# Poll for new traces
traces = ingester.poll(start_time=1700000000000)
```

**Integration (single trace dict):**

```python
# Parse a single trace event from logs
trace = adapter.parse_trace_dict(trace_data, session_id="session-456")
```

**Fields populated:**

| Field | Source |
|---|---|
| id, timestamp, agent, session_id | Auto-generated / provided |
| model | `foundationModel` from model invocation input |
| decision | Final response or parsed postprocessing response |
| status | Failure traces set `Status.ERROR` |
| context | Preprocessing prompt text as system prompt |
| searches | Knowledge base lookups with query, KB ID, result count |
| sources_read | Knowledge base retrieved references (S3 URIs, content hashes) |
| tools_used | Action group invocations, agent collaborator calls |
| turn_count | Tool calls + search count |
| token_usage | `inputTokens` + `outputTokens` from usage metadata |
| metadata | `agent_id`, `agent_alias_id`, rationales, guardrail actions, failure reasons |
| schema_version | Always set |

**N/A fields:** `parent_id`, `task` (input text not in trace events), `correction`, `scope`, `tags`, `files_modified`, `duration_ms`.
