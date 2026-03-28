# Schema Reference

OpenFlux normalizes all agent telemetry into a single data model: the **Trace**. A Trace captures one complete unit of agent work -- context given, searches run, sources read, tools called, and the decision made.

Current schema version: `0.2.0`

## Trace

The core telemetry primitive. Every adapter produces Traces with the same 22 fields.

| Field | Type | Description |
|---|---|---|
| `id` | `str` | Unique identifier. Format: `trc-{12 hex chars}`, auto-generated via `secrets.token_hex(6)`. |
| `timestamp` | `str` | ISO 8601 UTC timestamp of when the trace started. |
| `agent` | `str` | Agent identifier (e.g., `"claude-code"`, `"my-rag-app"`). |
| `session_id` | `str` | Groups related traces within a session. Format varies by adapter. |
| `parent_id` | `str \| None` | Links to a parent trace for hierarchical agent workflows. `None` for top-level traces. |
| `model` | `str` | Model used (e.g., `"gpt-4o-mini"`, `"claude-sonnet-4-20250514"`, `"gemini-2.5-flash"`). Empty string if unknown. |
| `task` | `str` | What the agent was asked to do. Extracted from user input or task description. |
| `decision` | `str` | What the agent decided or produced. The final output or conclusion. |
| `status` | `str` | Execution outcome. One of the `Status` enum values. Default: `"completed"`. |
| `correction` | `str \| None` | If the agent was corrected mid-session, what changed. `None` if no correction detected. |
| `scope` | `str \| None` | Logical grouping (e.g., `"refactor"`, `"debug"`, chain name). `None` if not applicable. |
| `tags` | `list[str]` | Freeform tags for categorization, A/B experiments, filtering. |
| `context` | `list[ContextRecord]` | Context injected into the agent (system prompts, RAG chunks, memory). |
| `searches` | `list[SearchRecord]` | Searches the agent executed (web, vector DB, grep, etc.). |
| `sources_read` | `list[SourceRecord]` | Sources the agent accessed (files, URLs, API responses, documents). |
| `tools_used` | `list[ToolRecord]` | Tools the agent called, with input/output and timing. |
| `files_modified` | `list[str]` | File paths modified during this trace. |
| `turn_count` | `int` | Number of tool calls or LLM turns in this trace. |
| `token_usage` | `TokenUsage \| None` | Token consumption breakdown. `None` if not available. |
| `duration_ms` | `int` | Wall-clock duration in milliseconds. `0` if not measured. |
| `metadata` | `dict[str, Any]` | Arbitrary key-value pairs for framework-specific data that doesn't fit core fields. |
| `schema_version` | `str` | Schema version string. Currently `"0.2.0"`. |

## Nested Record Types

### ContextRecord

Context injected into the agent before or during execution.

| Field | Type | Description |
|---|---|---|
| `type` | `str` | One of the `ContextType` enum values. |
| `source` | `str` | Where the context came from (e.g., `"agent:assistant"`, a file path). |
| `content_hash` | `str` | SHA-256 hash of the full content. Enables deduplication without storing raw content. |
| `content` | `str` | Raw content, truncated to storage limits. Empty in `redacted` fidelity mode. |
| `bytes` | `int` | Size of the original content in bytes. |
| `timestamp` | `str` | ISO 8601 UTC timestamp. |

### SearchRecord

A search query the agent executed.

| Field | Type | Description |
|---|---|---|
| `query` | `str` | The search query string. |
| `engine` | `str` | Tool or engine used (e.g., `"web_search"`, `"grep"`, `"retriever"`, `"bedrock-kb:KB_ID"`). |
| `results_count` | `int` | Number of results returned. |
| `timestamp` | `str` | ISO 8601 UTC timestamp. |

### SourceRecord

A source the agent read or accessed.

| Field | Type | Description |
|---|---|---|
| `type` | `str` | One of the `SourceType` enum values. |
| `path` | `str` | File path, URL, or resource identifier. |
| `content_hash` | `str` | SHA-256 hash of the full content. |
| `content` | `str` | Raw content, truncated (4KB for files, 16KB for URLs). Empty in `redacted` mode. |
| `tool` | `str` | Tool that produced this source (e.g., `"Read"`, `"WebFetch"`, `"retriever"`). |
| `bytes_read` | `int` | Number of bytes read. |
| `timestamp` | `str` | ISO 8601 UTC timestamp. |

### ToolRecord

A tool the agent called.

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Tool name (e.g., `"Bash"`, `"calculator"`, `"collaborator:agent-2"`). |
| `tool_input` | `str` | Serialized input, truncated to 4KB. |
| `tool_output` | `str` | Serialized output, truncated to 16KB. |
| `duration_ms` | `int` | How long the tool call took. |
| `error` | `bool` | Whether the tool call errored. |
| `timestamp` | `str` | ISO 8601 UTC timestamp. |

### TokenUsage

Token consumption for the trace.

| Field | Type | Description |
|---|---|---|
| `input_tokens` | `int` | Tokens consumed by input/prompt. |
| `output_tokens` | `int` | Tokens generated in output/completion. |
| `cache_read_tokens` | `int` | Tokens served from cache. |
| `cache_creation_tokens` | `int` | Tokens written to cache. |

## Enums

### Status

Execution outcome of a trace.

| Value | Meaning |
|---|---|
| `completed` | Agent finished successfully. |
| `error` | Agent encountered an error. |
| `timeout` | Agent timed out. |
| `cancelled` | Agent was cancelled. |

### FidelityMode

Controls how much content is stored.

| Value | Meaning |
|---|---|
| `full` | Store raw content alongside hashes. Default for local storage. |
| `redacted` | Hash-only, no raw content. For export and compliance. |

Set via the `OPENFLUX_FIDELITY` environment variable.

### ContextType

Classification of injected context.

| Value | Meaning |
|---|---|
| `system_prompt` | System-level instructions to the model. |
| `memory` | Retrieved memory from a memory system. |
| `rag_chunk` | Document chunk from a retrieval pipeline. |
| `file_injection` | File content injected as context. |
| `tool_context` | Context from a tool result used as input. |

### SourceType

Classification of accessed sources.

| Value | Meaning |
|---|---|
| `file` | Local file read. |
| `url` | URL fetched. |
| `tool_result` | Output from a tool call used as a source. |
| `api` | External API response. |
| `document` | Document from a retrieval system (e.g., knowledge base). |

## Serialization

### `to_dict()`

Converts a Trace to a dictionary, omitting `None` values:

```python
trace = Trace(
    id="trc-a1b2c3d4e5f6",
    timestamp="2025-06-01T12:00:00Z",
    agent="my-agent",
    session_id="sess-001",
)
d = trace.to_dict()
# {"id": "trc-a1b2c3d4e5f6", "timestamp": "...", "agent": "my-agent",
#  "session_id": "sess-001", "status": "completed", ...}
# parent_id is omitted because it's None
```

### `from_dict()`

Reconstructs a Trace from a dictionary. Nested records and token usage are deserialized automatically:

```python
trace = Trace.from_dict({
    "id": "trc-a1b2c3d4e5f6",
    "timestamp": "2025-06-01T12:00:00Z",
    "agent": "my-agent",
    "session_id": "sess-001",
    "tools_used": [{"name": "Bash", "tool_input": "ls", "tool_output": "file.txt"}],
    "token_usage": {"input_tokens": 100, "output_tokens": 50},
})

assert trace.tools_used[0].name == "Bash"
assert trace.token_usage.input_tokens == 100
```

## ID Format

Trace IDs follow the pattern `trc-{12 hex characters}`, generated via `secrets.token_hex(6)`. This produces 48 bits of entropy, sufficient for avoiding collisions in single-agent workloads. For fleet-scale deployments, the `metadata` dict can carry additional correlation IDs.

## Storage Limits

Default truncation limits for content fields:

| Content Type | Limit |
|---|---|
| File content (SourceRecord, ContextRecord) | 4 KB |
| URL/API content | 16 KB |
| Tool input | 4 KB |
| Tool output | 16 KB |
| Task description | 2 KB |
| Decision | 4 KB |

In `redacted` fidelity mode, raw content is omitted but content hashes and byte counts are preserved.
