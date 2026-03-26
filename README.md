# OpenFlux

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
collector.record_event(session_id, {"type": "tool_call", "name": "search", ...})
trace = collector.flush(session_id)
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

## Adapter Status

Verified end-to-end on 2026-03-25 against real SDKs. Full validation report: [docs/test-results/OVERALL-REPORT.md](docs/test-results/OVERALL-REPORT.md).

| Adapter | Status | Coverage | Known Limitations | Install |
|---------|--------|----------|-------------------|---------|
| Claude Code | Working | 85% | No token_usage from hooks; task/decision require transcript parsing | `(stdlib)` |
| OpenAI Agents SDK | Working | 73% | No system prompt capture; no source/file tracking | `openflux[openai]` |
| LangChain | Working | 82% | Scope requires constructor arg; needs LangGraph for modern usage | `openflux[langchain]` |
| Claude Agent SDK | Working | 85% | Needs manual `record_usage()` with ResultMessage data | `openflux[claude-agent-sdk]` |
| AutoGen v0.4 | Working | 86% | Model name not in stream (pass to constructor); no file tracking | `openflux[autogen]` |
| CrewAI | Working | 100% | Token usage estimated (chars/4); duplicate ToolRecord for native calls | `openflux[crewai]` |
| Google ADK | Working | 86% | No correction tracking; cache_creation_tokens always 0 | `openflux[google-adk]` |
| MCP | Working | 95% | No parent_id param; manual recording only | `openflux[mcp]` |
| Amazon Bedrock | Working | 90% | Caller must provide task/scope via params | `openflux[bedrock]` |

## Configuration

All env vars, no config files.

| Variable | Default | Purpose |
|---|---|---|
| `OPENFLUX_DB_PATH` | `~/.openflux/traces.db` | SQLite database location |
| `OPENFLUX_OTLP_ENDPOINT` | (none) | OTLP/HTTP endpoint for export |
| `OPENFLUX_AGENT` | `"unknown"` | Default agent name |
| `OPENFLUX_DISABLED` | `false` | Kill switch |
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
