# Changelog

## 0.5.1 (2026-04-30)

### Added
- Backfill from JSONL transcripts now reconstructs per-tool detail (`tools_used`, `searches`, `sources_read`, `files_modified`) by walking `tool_use` and `tool_result` content blocks and running them through the same classifier the live `PostToolUse` hook uses. As a result, the `loop` and `error_storm` anomaly classes now fire on backfilled databases instead of silently no-op-ing. On a real 2,939-trace database, refresh imported 55,948 tool records / 60,670 sources / 5,452 searches and surfaced 4 error storms and 252 agent loops that v0.5.0 missed.
- `SessionCost.uncached_input_cost`: dollars paid at the full input rate per session. The actionable "cache pain" metric; doesn't saturate the way `cache_hit_ratio` does. Surfaced in `openflux sessions` (alongside total cost) and `--sort cache` now means "highest uncached input cost first".
- `has_tool_coverage(conn, days, agent)` helper. `openflux anomalies` prints an explanation banner when the window's traces have no tool coverage instead of silently returning empty.

### Bug fixes
- `session_costs` no longer crashes when `trace_tools` is empty for a trace. SQLite's `SUM` over zero rows returns NULL; both `tool_count` and `error_count` are now guarded with `or 0` so `SessionCost` always carries valid `int` fields.
- Transcript task extraction stopped corrupting prompts that contain angle brackets. The tag stripper is now whitelisted to known Claude Code wrapper tags (`local-command-caveat`, `system-reminder`, `command-name`, etc); legitimate prompts like `"Fix <select> handling"` survive unchanged.
- Slash-command transcripts now resolve to the user's intent rather than the transport. A session opening `<command-name>/build</command-name>` followed by a substantive prompt sets `task` to the prompt; the slash command name is captured only as a last-resort fallback when no later user message has substantive content.

### Changed
- `openflux cost` leads with cache savings dollars instead of the saturated cache hit ratio. The ratio is kept as a softer line with a value-dependent note (`>=95%` healthy, `70-95%` below typical, `<70%` discipline broken).
- README's Cost forensics section rewritten to match shipped behavior (cache savings as the headline; uncached input cost as the actionable cache-pain metric; all four anomaly classes now backed by real data on backfill).

## 0.5.0 (2026-04-30)

### Added
- Cost forensics module (`openflux.insights`) covering cache hit ratio, cost-without-cache, daily burn rate, monthly projection, and per-model + per-day breakdowns.
- `openflux cost` CLI: total spend, cache discipline, savings vs no-cache, burn rate, model and day breakdowns.
- `openflux sessions` CLI: per-session cost, sortable by cost / cache / time.
- `openflux anomalies` CLI: detects cost spikes, cache misses, error storms, and agent loops; sorted by cost impact.
- `openflux budget set <amount>` / `openflux budget check`: daily budget cap with end-of-day spend projection.
- `openflux backfill`: import historical Claude Code transcripts from `~/.claude/projects/` into the local database. Idempotent; `--refresh` flag to re-parse already-imported sessions.
- Three new dashboard endpoints: `/api/insights`, `/api/insights/sessions`, `/api/insights/anomalies`.
- Waste tab in the dashboard: visual breakdown of the same metrics surfaced in the CLI.
- `billable_messages` table (schema v4): per-Anthropic-message-id billing record so the same API call across resumed or forked transcripts is counted once.
- `openflux._pricing`: centralized per-model token pricing helper, used by both the cost CLI and the insights module.

### Changed
- README rebranded around the cost-forensics question ("Find out where your Claude Code budget actually went this week"); Sessions tab demoted to a secondary feature; placeholder example data removed.
- For Claude Code, cost is computed from `billable_messages` when available (deduplicated by message.id) and falls back to per-trace token aggregates for adapters that do not expose message ids. Mutually exclusive, so no double-counting.
- `_SCHEMA_VERSION` bumped to 5; three new migrations (`v3` dedup_sessions, `v4` billable_messages, `v5` outcomes) all idempotent.

### Bug fixes
- `tests/unit/test_sqlite_sink.py::test_most_accessed_first`: anchored to `datetime.now(UTC)` so the days-window filter does not drop test rows as the calendar advances past a hardcoded date.

## 0.4.0 (2026-04-30)

### Added
- Outcome capture: every Claude Code session is linked to its git diff (start_sha → end_sha, lines added/removed, files changed) and test result (exit code from `OPENFLUX_TEST_CMD`).
- Sessions tab in the dashboard (the new headline view): cost, lines, files, tests passed, diff range, original task.
- `openflux outcomes` CLI: terminal view of session outcomes.
- `/api/outcomes` endpoints: list and detail.
- Per-model cost rates for Sonnet, Opus, Haiku, GPT-4o, Gemini, computed server-side and exposed in the Sessions tab.
- `scripts/seed_demo_data.py`: deterministic demo database for screenshots and screencasts (no private `~/.openflux/traces.db` required).

### Changed
- README rebranded around outcome-linked observability ("did this session ship working code?"), Sessions tab as the hero screenshot.
- `outcomes` table added to SQLite schema (joined to traces by `session_id`); existing databases auto-migrate on first read.

## 0.3.0 (2026-04-11)

### Breaking
- Google ADK adapter callbacks now use keyword arguments (matching ADK API change)

### Bug fixes
- Fix OpenAI Agents adapter: SDK renamed `GenerationSpanData` to `ResponseSpanData`, breaking model/task/decision/context/token capture
- Fix LangChain adapter: `serialized` parameter is now `None` in LangGraph, crashing `on_chain_start` and 4 other callbacks
- Fix LangChain adapter: task/decision not captured from LangGraph's `messages` input format
- Fix LangChain adapter: tool classification (search, source, write) never triggered — tools went to generic list only
- Fix LangChain adapter: token usage not captured from Google providers (`usage_metadata` on message objects)
- Fix LangChain adapter: context records never reached root accumulator due to run traversal ordering
- Fix Google ADK adapter: system instructions moved to `config.system_instruction`, model attribute renamed to `model_version`
- Fix Google ADK adapter: task, decision, source records, and metadata never captured
- Fix CrewAI adapter: system prompts from `event.messages` not captured as context records
- Fix CrewAI test: SQLite cross-thread error when event bus fires `on_trace` from worker thread
- Fix Claude Agent SDK adapter: `record_usage()` stored data on accumulator but never built the trace when Stop hook didn't fire
- Fix Claude Agent SDK adapter: double-write when patching already-emitted traces via `record_usage()`

### Improvements
- All 9 adapters now tested with real API calls (OpenAI, Google Gemini, Anthropic Claude)
- OpenAI Agents adapter: 21/21 fields (100% coverage)
- LangChain adapter: 20/20 fields (100% coverage)
- Google ADK adapter: 18/18 fields (100% coverage, up from 73%)
- CrewAI adapter: 17/18 fields (94% coverage)
- Claude Agent SDK adapter: 19/19 fields (100% coverage)
- AutoGen adapter: 16/16 fields (100% coverage)
- Standardized all acceptance test imports to absolute paths
- Added `finalize()` method to Claude Agent SDK adapter
- Added `_DEFAULT_FILE_READ_TOOLS` and `_DEFAULT_FILE_WRITE_TOOLS` to LangChain adapter

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
