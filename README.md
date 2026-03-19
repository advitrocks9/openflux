# OpenFlux

[![PyPI version](https://img.shields.io/pypi/v/openflux.svg)](https://pypi.org/project/openflux/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://github.com/advitrocks9/openflux/actions/workflows/ci.yml/badge.svg)](https://github.com/advitrocks9/openflux/actions)

Open standard for AI agent telemetry. One schema across every framework.

## Why

Every agent framework emits telemetry in its own format. Claude Code uses lifecycle hooks. OpenAI Agents SDK has TracingProcessor. LangChain has callbacks. If you want to build analytics or compliance tooling on top, you need N integrations from scratch. Most people don't bother.

OpenFlux sits between the frameworks and your tools. It normalizes everything into a single schema called a **Trace** - one traced unit of agent work, end to end. Context in, searches run, sources read, tools called, decision made.

Same idea as OpenTelemetry for observability. OTel didn't build dashboards - it built the standard that let Datadog, Grafana, and Honeycomb exist. OpenFlux does that for agent telemetry.

## How it works

```
Adapter (framework-specific) -> Normalizer -> Trace -> Sink(s)
```

- **Adapters** hook into framework callbacks and emit raw events
- **Normalizer** classifies events, hashes content, applies fidelity truncation
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

**Claude Code** (auto-configures hooks):

```bash
openflux install claude-code
```

**OpenAI Agents SDK:**

```python
import openflux
openflux.init(agent="my-agent")  # auto-detects frameworks
```

Or explicitly:

```python
from agents.tracing import add_trace_processor
from openflux.adapters.openai_agents import OpenFluxProcessor
add_trace_processor(OpenFluxProcessor(agent="my-agent"))
```

**LangChain:**

```python
import openflux
handler = openflux.langchain_handler(agent="my-rag-app")
result = chain.invoke({"input": "..."}, config={"callbacks": [handler]})
```

**Any framework:**

```python
import openflux

collector = openflux.collector(agent="my-agent")
collector.record_event(session_id, {"type": "tool_call", "name": "search", ...})
trace = collector.flush(session_id)
```

## CLI

```bash
openflux recent                          # last 10 traces
openflux recent --agent=claude-code      # filter by agent
openflux search "staging deploy"         # full-text search
openflux trace trc-a1b2c3d4e5f6          # full provenance for one trace
openflux export > traces.json            # dump everything
openflux status                          # db path, counts, adapter status
openflux install claude-code             # auto-configure hooks
openflux install --list                  # show available adapters
```

## Adapter support

| Framework | Mechanism | Status |
|---|---|---|
| Claude Code | Lifecycle hooks (subprocess) | Available |
| OpenAI Agents SDK | TracingProcessor | Available |
| LangChain / LangGraph | BaseCallbackHandler | Available |
| Claude Agent SDK | HookMatcher/HookCallback | Planned |
| AutoGen v0.4 | Stream consumer | Planned |
| CrewAI | EventBus listener | Planned |
| Google ADK | Callbacks | Planned |
| MCP | Tools + Resources | Planned |
| Amazon Bedrock | CloudWatch/X-Ray | Planned |

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

## The Trace schema

A Trace captures one complete unit of agent work:

- **Identity**: id, timestamp, agent, session_id, parent_id
- **What happened**: task, decision, status, correction
- **Provenance**: context given, searches run, sources read, tools called
- **Metrics**: token usage, duration, turn count, files modified
- **Extensibility**: tags, scope, metadata dict

Full schema definition in [docs/PRD.md](docs/PRD.md).

## Layer 1 / Layer 2

OpenFlux is strictly Layer 1: capture, normalize, store, export.

Dashboards, compliance engines, cost analyzers, fleet analytics - those are Layer 2 products that consume Traces. They don't need to know about LangChain callbacks or OpenAI tracing. They just query Traces.

Add one adapter, and every Layer 2 product gets coverage for free.

## Development

```bash
uv run pytest tests/ -v          # tests
uv run ruff check src/ tests/    # lint
uv run ruff format src/ tests/   # format
uv run pyright src/               # type check
```

## License

[MIT](LICENSE)
