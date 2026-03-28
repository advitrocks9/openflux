# OpenFlux Documentation

The open standard for AI agent telemetry. One schema across every framework.

## Install

```bash
pip install openflux

# With a specific adapter
pip install openflux[openai]
pip install openflux[langchain]

# Everything
pip install openflux[all]
```

## Quick Start (any framework)

The generic collector works with any framework. Record raw events and flush them into a Trace.

```python
import openflux

collector = openflux.init(agent="my-agent")
collector.record_event("session-1", {"type": "tool_call", "name": "search", "input": "query"})
collector.record_event("session-1", {"type": "llm_response", "content": "result"})
trace = collector.flush("session-1")

print(trace.id)          # trc-a1b2c3d4e5f6
print(trace.agent)       # my-agent
print(trace.session_id)  # session-1
```

## Quick Start (Claude Code)

Zero-code integration. The CLI installs lifecycle hooks into `~/.claude/settings.json`:

```bash
openflux install claude-code
# Use Claude Code normally - traces are captured automatically
openflux recent
```

Every tool call, file read, search, and edit is recorded. Traces are written to SQLite at `~/.openflux/traces.db`.

## Quick Start (LangChain)

```python
import openflux
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

handler = openflux.langchain_handler(agent="my-rag-app")

llm = ChatOpenAI(model="gpt-4o-mini")
chain = ChatPromptTemplate.from_template("Answer: {input}") | llm
result = chain.invoke({"input": "What is OpenFlux?"}, config={"callbacks": [handler]})
```

The handler captures LLM calls, tool use, retriever queries, token usage, and agent reasoning into Traces.

## Quick Start (OpenAI Agents SDK)

```python
from agents import Agent, Runner
from agents.tracing import add_trace_processor
from openflux.adapters.openai_agents import OpenFluxProcessor

processor = OpenFluxProcessor(agent="my-agent")
add_trace_processor(processor)

agent = Agent(name="assistant", instructions="You are a helpful assistant.")
result = Runner.run_sync(agent, "What is the capital of France?")

traces = processor.completed_traces
```

## CLI

| Command | Description |
|---|---|
| `openflux recent` | Show the last 10 traces |
| `openflux recent --agent claude-code` | Filter by agent name |
| `openflux recent --limit 50` | Show more results |
| `openflux recent --scope refactor` | Filter by scope |
| `openflux search "staging deploy"` | Full-text search across all traces |
| `openflux trace trc-a1b2c3d4e5f6` | Show full detail for one trace |
| `openflux export` | Dump all traces as NDJSON to stdout |
| `openflux export --agent claude-code` | Export filtered by agent |
| `openflux export --since 2025-01-01T00:00:00Z` | Export traces after a timestamp |
| `openflux status` | Show database path, size, trace count, breakdown by agent/status |
| `openflux install claude-code` | Auto-configure Claude Code lifecycle hooks |
| `openflux install --list` | List available adapters |

## Configuration

All configuration is via environment variables. No config files required.

| Variable | Default | Purpose |
|---|---|---|
| `OPENFLUX_DB_PATH` | `~/.openflux/traces.db` | SQLite database location |
| `OPENFLUX_OTLP_ENDPOINT` | (none) | OTLP/HTTP endpoint for export |
| `OPENFLUX_AGENT` | `"unknown"` | Default agent name |
| `OPENFLUX_DISABLED` | `false` | Kill switch |
| `OPENFLUX_FIDELITY` | `full` | `full` (raw content) or `redacted` (hash-only) |
| `OPENFLUX_EXCLUDE_PATHS` | `*.env,*credentials*,...` | Glob patterns to exclude from content storage |

## What's Next

- [Adapter Guides](adapters.md) -- per-framework setup and field coverage
- [Schema Reference](schema.md) -- the 22-field Trace and nested record types
- [Cost Analysis](cost.md) -- track and analyze token spend
