# OpenFlux

[![PyPI](https://img.shields.io/pypi/v/openflux)](https://pypi.org/project/openflux/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/openflux)](https://pypi.org/project/openflux/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

Open standard for AI agent telemetry. One schema across every framework.

## Why

Every agent framework emits telemetry differently. Claude Code uses lifecycle hooks. OpenAI Agents SDK has TracingProcessor. LangChain has callbacks. If you want to build analytics, compliance, or cost tooling on top, you need N integrations from scratch.

OpenFlux normalizes everything into a single schema called a **Trace**: one traced unit of agent work, end to end. Context in, searches run, sources read, tools called, decision made.

Same idea as OpenTelemetry for observability. OTel didn't build dashboards. It built the standard that let them exist. OpenFlux does that for agent telemetry.

## How it works

```
Adapter (framework-specific) -> Normalizer -> Trace -> Sink(s)
```

- **Adapters** hook into framework callbacks and emit raw events
- **Normalizer** classifies events, hashes content, applies fidelity controls
- **Trace** is the universal schema (22 fields + 4 nested record types)
- **Sinks** write the Trace somewhere: SQLite (default), OTLP, or JSON stdout

Zero dependencies beyond Python stdlib for the core. Each adapter adds one optional dep.

## Install

```bash
pip install openflux

# With a specific adapter
pip install openflux[openai]
pip install openflux[langchain]

# Everything
pip install openflux[all]
```

## Quick start

### Claude Code

Auto-configures lifecycle hooks:

```bash
openflux install claude-code
```

### OpenAI Agents SDK

```python
from agents.tracing import add_trace_processor
from openflux.adapters.openai_agents import OpenFluxProcessor

add_trace_processor(OpenFluxProcessor(agent="my-agent"))
```

### LangChain

```python
import openflux

handler = openflux.langchain_handler(agent="my-rag-app")
result = chain.invoke({"input": "..."}, config={"callbacks": [handler]})
```

### Any framework

```python
import openflux

collector = openflux.init(agent="my-agent")

# Event types: meta, tool, search, source, context
collector.record_event("session-1", {"type": "meta", "task": "fix auth bug", "model": "gpt-4o"})
collector.record_event("session-1", {"type": "tool", "tool_name": "Bash", "tool_input": "pytest", "tool_output": "3 passed"})
collector.record_event("session-1", {"type": "search", "query": "oauth best practices", "engine": "web"})

trace = collector.flush("session-1")  # persisted to ~/.openflux/traces.db
print(f"Traced: {trace.task} -> {trace.status} ({len(trace.tools_used)} tools)")
# Then query later: openflux recent
```

## CLI

```bash
openflux recent                          # last 10 traces
openflux recent --agent claude-code      # filter by agent
openflux search "staging deploy"         # full-text search
openflux trace trc-a1b2c3d4e5f6          # full detail for one trace
openflux export > traces.json            # dump as NDJSON
openflux status                          # db path, counts, breakdown
openflux install claude-code             # auto-configure hooks
openflux install --list                  # show available adapters
```

## What you see

```
$ openflux recent
ID              WHEN     AGENT        TASK                                      STATUS
trc-a1b2c3d4e5  2m ago   claude-code  Fix authentication bug in auth.py         completed
trc-f6e7d8c9b0  15m ago  my-rag-app   Analyze Q3 revenue data                  completed
trc-1a2b3c4d5e  1h ago   claude-code  Refactor database connection pooling      completed

3 trace(s) shown.
```

## Adapter Status

Tested end-to-end with real API calls (Gemini, Claude) and simulated event streams (Bedrock). Coverage = percentage of the 22 Trace fields that are populated in a real test.

| Adapter | Coverage | What's N/A | Install |
|---------|----------|------------|---------|
| MCP | 22/22 (100%) | — | `openflux[mcp]` |
| Amazon Bedrock | 21/22 (100%) | files_modified (cloud agents) | `openflux[bedrock]` |
| Claude Code | 20/22 (91%) | parent_id, context (not in transcripts) | `(stdlib)` |
| LangChain | 20/22 (100%) | parent_id, correction | `openflux[langchain]` |
| Claude Agent SDK | 19/22 (100%) | parent_id, correction, files_modified | `openflux[claude-agent-sdk]` |
| Google ADK | 18/22 (100%) | parent_id, correction, files_modified, searches | `openflux[google-adk]` |
| OpenAI Agents SDK | Working | Untested (API quota) | `openflux[openai]` |
| AutoGen v0.4 | Working | Untested (API quota) | `openflux[autogen]` |
| CrewAI | Working | Untested (API quota) | `openflux[crewai]` |

Coverage means "of the fields that are structurally possible for this adapter, how many are populated." 100% means every testable field works. See `.claude/findings.md` for details on what's N/A and why.

## Configuration

All env vars, no config files.

| Variable | Default | Purpose |
|---|---|---|
| `OPENFLUX_DB_PATH` | `~/.openflux/traces.db` | SQLite database location |
| `OPENFLUX_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP/HTTP endpoint for export |
| `OPENFLUX_FIDELITY` | `full` | `full` (raw content) or `redacted` (hash-only) |
| `OPENFLUX_EXCLUDE_PATHS` | `*.env,*credentials*,...` | Glob patterns to exclude from content storage |

## Schema

A Trace captures one complete unit of agent work:

- **Identity**: id, timestamp, agent, session_id, parent_id
- **What happened**: task, decision, status, correction
- **Provenance**: context given, searches run, sources read, tools called
- **Metrics**: token usage, duration, turn count, files modified
- **Extensibility**: tags, scope, metadata dict

Full schema definition in [docs/PRD.md](docs/PRD.md).

## Development

```bash
uv run pytest tests/ -v          # tests
uv run ruff check src/ tests/    # lint
uv run ruff format src/ tests/   # format
uv run pyright src/              # type check
```

## License

[MIT](LICENSE)
