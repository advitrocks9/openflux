# Changelog

## 0.2.0 (2026-03-30)

### Features
- Web dashboard (`openflux serve`) with dark-first UI, trace explorer, detail panel, stats charts
- `openflux cost` command for token usage and cost breakdown by model/agent/day
- `openflux forget` and `openflux prune` commands for trace management
- Tabbed trace detail panel (overview, tools, sources, raw JSON)
- Command palette (Cmd+K) for quick navigation
- Dark/light mode toggle

### Improvements
- Frontend built with React 19, Tailwind CSS 4, Recharts, motion
- Code-split recharts + motion into separate chunks for faster loads
- Stacked bar charts for token usage, emerald bars for daily trace counts
- Dynamic version via hatchling (single source of truth in `__init__.py`)
- GitHub Actions release pipeline for automated PyPI publish on tag push

## 0.1.1 (2026-03-28)

### Bug fixes
- Fix LangChain adapter crash on any tool use (missing slots on `_RunAccumulator`)
- Fix LangChain `on_chat_model_start` and `on_llm_end` UnboundLocalError when exception occurs
- Fix Claude Agent SDK `record_usage()` silently failing (trace index never populated)
- Fix Google ADK always reporting `turn_count=0`
- Fix AutoGen always reporting `duration_ms=0`
- Fix OpenAI Agents SDK always reporting `duration_ms=0`

### Improvements
- Add pre-commit config (ruff check + format)
- Fix CI to run unit tests only (acceptance tests need API keys)
- Remove ~15 dead functions across LangChain, Google ADK, CrewAI adapters
- Fix all SQL queries in cost analysis docs
- Fix stale adapter coverage claims in docs
- Add logo

## 0.1.0 (2026-03-27)

Initial release.

### Features
- 22-field Trace schema for normalized AI agent telemetry
- 9 framework adapters: Claude Code, OpenAI Agents SDK, LangChain, Claude Agent SDK, AutoGen, CrewAI, Google ADK, MCP, Amazon Bedrock
- 3 sinks: SQLite with FTS5 (default), OTLP/HTTP, NDJSON stdout
- CLI: `openflux recent`, `search`, `trace`, `export`, `status`, `install`
- Zero runtime dependencies for core (stdlib only)
- Content hashing with SHA-256 and fidelity modes (full/redacted)
- Thread-safe collector with per-session event buffering
- Path exclusion for sensitive files (*.env, *credentials*, etc.)
- `openflux install claude-code` auto-configures lifecycle hooks

### Adapters tested E2E
- MCP (22/22 fields, 100%)
- Bedrock (21/22, simulated events)
- Claude Code (hooks + transcript parsing)
- LangChain (real Gemini API)
- Google ADK (real Gemini API)
- Claude Agent SDK (local, Docker needs CLI auth)

### Known limitations
- OpenAI Agents, AutoGen, CrewAI adapters built but not yet E2E tested (API quota)
- SQLite storage only for local use; OTLP for export to external systems
