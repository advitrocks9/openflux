# OpenFlux vs ccusage and CodeBurn

The Claude Code observability space has a few good tools. Each answers a different question. This doc is here so you can pick the right one without trying all three.

_Star counts and last-pushed dates as of 2026-04-29. Pull current numbers from each repo if you're reading this later._

| | [ccusage](https://github.com/ryoppippi/ccusage) | [CodeBurn](https://github.com/getagentseal/codeburn) | OpenFlux |
|---|---|---|---|
| **Stars** | 13,580 | 4,610 | (this repo) |
| **Last push** | 2026-04-29 | 2026-04-29 | 2026-04-29 |
| **Question it answers** | What did I spend? | Why was that session inefficient? | Did this session ship working code? |
| **Cost reporting** | Yes (CLI table) | Yes (TUI dashboard) | Yes (Sessions tab) |
| **Per-tool waste** | No | Yes (A-F grade, Read:Edit ratio, wasted bash) | No |
| **Git diff per session** | No | No | **Yes** |
| **Test result per session** | No | No | **Yes** |
| **PR-merged correlation** | No | No | Planned (roadmap) |
| **UI** | CLI | TUI | Web dashboard + CLI |
| **Storage** | reads `~/.claude/projects/*.jsonl` | reads `~/.claude/projects/*.jsonl` | SQLite at `~/.openflux/traces.db` |
| **Multi-framework** | No (Claude Code only) | No (Claude Code only) | Yes (9 adapters: LangChain, OpenAI Agents, AutoGen, CrewAI, Bedrock, Google ADK, MCP, Claude Agent SDK) |
| **Local-only** | Yes | Yes | Yes |
| **License** | MIT | MIT | MIT |

## When to pick which

- **You want a quick number for last week's spend.** Pick `ccusage`. Mature, fast, no setup.
- **You want to know why a session was wasteful** (re-reads, ignored MCP servers, low Read:Edit ratio). Pick CodeBurn.
- **You want to know if a session shipped working code.** Pick OpenFlux. Sessions tab links cost to git diff and test pass/fail.
- **You run agents in more than one framework** (Claude Code today, LangGraph or AutoGen tomorrow). OpenFlux's 9 adapters give you one schema across all of them; the others are Claude-Code-only.

## When NOT to pick OpenFlux

- You only run Claude Code and only care about cost. ccusage is shorter and battle-tested.
- You want anomaly detection or cache-hit-ratio dashboards today. The user's parallel `feature/waste-detection` branch on this repo is closer to that, but it's not the headline.
- You expect a hosted SaaS. OpenFlux is local-only by design.

## How OpenFlux relates to OpenTelemetry, LangSmith, Langfuse, Phoenix

Those are general LLM-observability platforms. OpenFlux is narrower: AI **coding** sessions specifically, with the outcome question (did code ship? did tests pass?) as the wedge. The 9-adapter Trace schema overlaps with what those platforms expose, but OpenFlux's pitch is local-first and outcome-linked, not "OTel for LLMs."

## Honest limitations

- Outcome capture (git diff + tests) only works when Claude Code is run inside a git repo with `OPENFLUX_TEST_CMD` set.
- Cost is computed from per-model rates, not your actual provider invoice. Override with `OPENFLUX_RATES_JSON`.
- "Tests passed" is whatever exit code your test command produces. If your tests are flaky, the column is flaky. Buy yourself good tests, then this column tells the truth.
- Cursor and aider adapters are roadmap, not shipped.

## Source

These are all real tools. Pull current star counts before quoting:

```bash
gh api repos/ryoppippi/ccusage --jq .stargazers_count
gh api repos/getagentseal/codeburn --jq .stargazers_count
```
