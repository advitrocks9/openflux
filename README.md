<p align="center">
  <picture>
    <img src="assets/logo.png" width="80" alt="OpenFlux">
  </picture>
</p>
<h1 align="center">OpenFlux</h1>
<p align="center">
  <em>See what your AI coding sessions actually cost <strong>and</strong> what they actually shipped.</em>
</p>
<p align="center">
  <a href="https://pypi.org/project/openflux/"><img src="https://img.shields.io/pypi/v/openflux?style=flat-square&color=6366f1" alt="PyPI"></a>
  <a href="https://pypi.org/project/openflux/"><img src="https://img.shields.io/pypi/dm/openflux?style=flat-square&color=818cf8" alt="Downloads"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-4f46e5?style=flat-square" alt="Python 3.12+"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-a5b4fc?style=flat-square" alt="MIT"></a>
</p>

## The question

You ran a 45-minute Claude Code session. It cost $32 in tokens. **Did any of that ship working code?**

Existing tools tell you what you spent. None tell you whether the spend produced anything that survived `pytest`. OpenFlux does.

```
$ openflux serve
```

The **Sessions** tab links every session to its git diff and test result:

| When | Outcome | Cost | Lines | Files | Tests | Diff | Task |
|---|---|---|---|---|---|---|---|
| 2026-04-29 14:22 | shipped | $4.18 | +127 / -34 | 6 | ✓ pass | a3f2c1e → 8b4d9f0 | refactor auth middleware |
| 2026-04-29 12:08 | broke tests | $11.40 | +89 / -12 | 4 | ✗ fail | 8b4d9f0 → c1e2a3f | add user roles |
| 2026-04-29 10:55 | no diff | $2.06 | 0 / 0 | 0 | — | 71d5fa8 → 71d5fa8 | debug login flow |

The **Insights** tab gives you the cost side: cache hit ratio, daily burn rate, projected monthly, anomaly detection per session.

Together they answer the only question that matters: *was that session worth it?*

## How it works

OpenFlux hooks into your AI coding tool (Claude Code today; Cursor and aider planned), records the session, captures `git rev-parse HEAD` at start and end, runs your test command if you set `OPENFLUX_TEST_CMD`, and stores everything locally in SQLite. No data leaves your machine.

```
Adapter (framework-specific) -> Normalizer -> Trace -> Sink(s)
                                                |
                                                +-> outcome (git diff + tests) per session
```

- **Adapters** hook into framework callbacks and emit raw events
- **Normalizer** classifies events, hashes content, applies fidelity controls
- **Trace** is the universal schema (22 fields + 4 nested record types)
- **Outcome** is the per-session diff + test result, joined to the trace by session_id
- **Sinks** write the data somewhere: SQLite (default), OTLP, or JSON stdout

Zero dependencies beyond Python stdlib for the core. Each framework adapter adds one optional dep.

## Dashboard

OpenFlux ships with a built-in web dashboard. Run `openflux serve` and open your browser.

The dashboard has four tabs:

- **Sessions** — outcomes view (the headline). Cost, lines added, lines removed, files, tests passed, diff range, original task. Built for the question *"did this session ship working code?"*
- **Insights** — cost intelligence. Daily burn, projected monthly, cache hit ratio, anomaly detection per session.
- **Traces** — the raw trace explorer with sortable columns, full-text search, agent filtering.
- **Stats** — token usage over time, traces per day, aggregate metrics.

<p align="center">
  <img src="assets/screenshots/traces-dark.png" width="100%" alt="Trace Explorer">
</p>

**Trace Explorer** with sortable columns, status filters, full-text search, and agent filtering. Click any row to open the detail panel.

<p align="center">
  <img src="assets/screenshots/detail-dark.png" width="100%" alt="Trace Detail">
</p>

**Trace Detail** panel with tabs for overview, tools, sources, and raw JSON. Collapsible sections, metadata grid, and cost estimation.

<p align="center">
  <img src="assets/screenshots/stats-dark.png" width="100%" alt="Stats Dashboard">
</p>

**Stats Dashboard** with token usage over time, traces per day, and aggregate metrics. Light mode also supported:

<p align="center">
  <img src="assets/screenshots/traces-light.png" width="100%" alt="Light Mode">
</p>

## Install

```bash
pip install openflux

# With a specific adapter
pip install openflux[openai]
pip install openflux[langchain]
pip install openflux[bedrock]

# Everything
pip install openflux[all]
```

## Quick start

### Claude Code (the wedge)

```bash
pip install openflux
openflux install claude-code
export OPENFLUX_TEST_CMD="pytest -q"   # optional, enables tests_passed column
```

Every Claude Code session is now traced. Every session in a git repo gets a recorded outcome (start sha, end sha, lines added/removed, files changed, optional test result). Visit `openflux serve` and click **Sessions** to see them.

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

collector.record_event("session-1", {"type": "meta", "task": "fix auth bug", "model": "gpt-4o"})
collector.record_event("session-1", {"type": "tool", "tool_name": "Bash", "tool_input": "pytest", "tool_output": "3 passed"})
collector.record_event("session-1", {"type": "search", "query": "oauth best practices", "engine": "web"})

trace = collector.flush("session-1")
```

## CLI

OpenFlux includes a full CLI for querying, analyzing, and serving your traces.

```bash
openflux recent                          # last 10 traces
openflux recent --agent claude-code      # filter by agent
openflux search "staging deploy"         # full-text search
openflux trace trc-a1b2c3d4e5f6          # full detail for one trace
openflux cost                            # token usage + cost breakdown
openflux cost --days 7 --agent my-agent  # scoped cost report
openflux export > traces.json            # dump as NDJSON
openflux status                          # db path, counts, breakdown
openflux serve                           # launch web dashboard on :5173
openflux serve --port 8080               # custom port
openflux forget --agent old-agent        # delete traces by agent
openflux prune --days 90                 # remove traces older than 90 days
openflux install claude-code             # auto-configure hooks
openflux install --list                  # show available adapters
```

### `openflux cost`

Shows token usage and estimated cost broken down by model, agent, and day:

```
$ openflux cost --days 7
Token Usage (last 7 days)
─────────────────────────────────────────────
  Traces:     42
  Input:       1,234,567 tokens
  Output:        456,789 tokens
  Total:       1,691,356 tokens

By model:
  claude-sonnet-4-20250514           980,000 tokens  $7.35
  gpt-4o-2024-11-20                  711,356 tokens  $4.28

By agent:
  claude-code                          28 traces    1,200,000 tokens
  my-rag-app                           14 traces      491,356 tokens
```

### `openflux serve`

Launches a local web dashboard with:

- **Trace table** with sorting, pagination, status/agent filtering, full-text search
- **Detail panel** with tabbed view (overview, tools, sources, raw JSON)
- **Stats page** with token usage charts, trace counts, cost estimates
- **Command palette** (Cmd+K) for quick navigation
- **Dark/light mode** toggle

The dashboard is built with React, Tailwind CSS, and Recharts, bundled into the Python package. No Node.js required to run it.

## Compared to other Claude Code tools

The space already has [ccusage](https://github.com/ryoppippi/ccusage) (cost reporting) and [CodeBurn](https://github.com/getagentseal/codeburn) (per-tool waste grading). OpenFlux is the only one that links a session to its git diff and test result.

See [docs/comparison.md](docs/comparison.md) for the side-by-side, including when NOT to pick OpenFlux.

## Works with

The outcome view today targets Claude Code (where the wedge is sharpest). The underlying Trace schema is framework-agnostic and ships adapters for the rest of the agent ecosystem so the same dashboard, sinks, and CLI work everywhere.

Tested with real API calls and simulated event streams. Coverage = percentage of the 22 Trace fields populated in a real test.

| Adapter | Coverage | What's N/A | Install |
|---------|----------|------------|---------|
| MCP | 22/22 (100%) | -- | `openflux[mcp]` |
| Amazon Bedrock | 21/22 (100%) | files_modified | `openflux[bedrock]` |
| OpenAI Agents SDK | 21/21 (100%) | correction | `openflux[openai]` |
| Claude Code | 21/22 (95%) | parent_id | `(stdlib)` |
| LangChain | 20/20 (100%) | correction, parent_id | `openflux[langchain]` |
| Claude Agent SDK | 19/19 (100%) | parent_id, correction, files_modified | `openflux[claude-agent-sdk]` |
| Google ADK | 18/18 (100%) | parent_id, correction, files_modified, searches | `openflux[google-adk]` |
| AutoGen v0.4 | 16/16 (100%) | parent_id, correction, searches, sources_read, tools_used, files_modified | `openflux[autogen]` |
| CrewAI | 17/18 (94%) | parent_id, correction, files_modified, token_usage | `openflux[crewai]` |

## Configuration

All env vars, no config files.

| Variable | Default | Purpose |
|---|---|---|
| `OPENFLUX_DB_PATH` | `~/.openflux/traces.db` | SQLite database location |
| `OPENFLUX_TEST_CMD` | unset | Shell command to run at session end. Exit 0 means `tests_passed=true`. Example: `pytest -q` |
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

Full schema definition in [docs/schema.md](docs/schema.md).

## Sinks

| Sink | Description | Config |
|------|-------------|--------|
| **SQLite** | Default. Zero-config, FTS5 search, schema migrations. | `OPENFLUX_DB_PATH` |
| **OTLP** | Raw HTTP POST to any OpenTelemetry collector. No SDK needed. | `OPENFLUX_OTLP_ENDPOINT` |
| **JSON** | NDJSON to stdout. Pipe to files, jq, or other tools. | -- |

## Roadmap

- [ ] PyPI stable release (v1.0)
- [ ] Cursor + aider adapters with the same outcome capture
- [ ] PR-merged correlation (mark sessions whose diff was merged in the public history)
- [ ] Per-model cost rate config (currently Sonnet-class blended estimate)
- [ ] Cost alerting (threshold-based notifications)
- [ ] Trace comparison and diff view
- [ ] OTLP sink integration tests
- [ ] Grafana dashboard template
- [x] ~~OpenAI / AutoGen / CrewAI real API coverage tests~~ (done in v0.3.0)
- [ ] Webhook sink (POST traces to any URL)
- [ ] Trace retention policies (auto-prune by age/size)
- [ ] Multi-user auth for served dashboard

## Development

```bash
git clone https://github.com/advitrocks9/openflux.git
cd openflux
uv sync --all-extras

uv run pytest tests/ -v          # tests
uv run ruff check src/ tests/    # lint
uv run ruff format src/ tests/   # format
uv run pyright src/              # type check
```

Frontend (only needed if modifying the dashboard):

```bash
cd frontend
npm install
npm run dev    # dev server on :5174, proxies API to :5173
npm run build  # builds to src/openflux/static/
```

## License

[MIT](LICENSE)
