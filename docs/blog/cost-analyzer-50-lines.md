# Build a Cost Analyzer for AI Agents in 50 Lines of Python

I run Claude Code for daily development and a LangChain RAG pipeline for internal docs search. Last month I got an API bill that was 3x what I expected. I had no idea which agent was responsible, which model was burning through tokens, or even how to compare across the two -- Claude Code reports usage through lifecycle hooks, LangChain through callback handlers, and neither gives you a unified view.

The frustrating part is that every framework _does_ track tokens. They just all do it differently. OpenAI puts it in `GenerationSpanData.usage`. LangChain buries it in `llm_output.token_usage`. Google ADK calls it `usage_metadata`. If you want a single cost report, you're writing three parsers and a bunch of glue code, or you're eyeballing dashboards and doing mental math.

## The fix

[OpenFlux](https://github.com/advitrocks9/openflux) normalizes agent telemetry from 9 frameworks into a single schema called a Trace. Every trace has a `token_usage` field with `input_tokens` and `output_tokens`, regardless of which framework produced it. Everything lands in a local SQLite database. No vendor lock-in, no SaaS dashboard -- just SQL.

```bash
pip install openflux[langchain]
```

## Set up

For Claude Code, install the hooks:

```bash
openflux install claude-code
```

For LangChain, add the callback handler:

```python
import openflux

handler = openflux.langchain_handler(agent="docs-rag")
result = chain.invoke({"input": query}, config={"callbacks": [handler]})
```

Both adapters write to `~/.openflux/traces.db`. That's it. Run your agents for a while, then come back.

## The cost analyzer

Here's a standalone script. It connects to the OpenFlux SQLite database, groups token usage by model and agent, applies per-token pricing, and prints a formatted report. No OpenFlux imports needed -- it's just `sqlite3`.

```python
#!/usr/bin/env python3
"""Cost analyzer for OpenFlux traces."""
import sqlite3
from pathlib import Path

DB = Path.home() / ".openflux" / "traces.db"
RATES = {  # USD per million tokens: (input, output)
    "gpt-4o":       (2.50, 10.00),
    "gpt-4o-mini":  (0.15,  0.60),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-haiku-4-5-20250514": (0.80,  4.00),
    "gemini-2.5-flash": (0.075, 0.30),
}
FALLBACK = (1.00, 3.00)

def get_rate(model: str) -> tuple[float, float]:
    for key, rate in RATES.items():
        if key in model:
            return rate
    return FALLBACK

def cost(model: str, inp: int, out: int) -> float:
    r_in, r_out = get_rate(model)
    return (inp * r_in + out * r_out) / 1_000_000

conn = sqlite3.connect(str(DB))
rows = conn.execute(
    "SELECT model, COUNT(*), SUM(token_input), SUM(token_output) "
    "FROM traces WHERE model != '' "
    "GROUP BY model ORDER BY SUM(token_input) + SUM(token_output) DESC"
).fetchall()

print(f"{'MODEL':<40} {'TRACES':>6} {'INPUT':>10} {'OUTPUT':>10} {'COST':>10}")
print("-" * 80)
total_cost = 0.0
for model, count, inp, out in rows:
    c = cost(model, inp or 0, out or 0)
    total_cost += c
    print(f"{model:<40} {count:>6} {inp or 0:>10,} {out or 0:>10,} ${c:>8.4f}")

agent_rows = conn.execute(
    "SELECT agent, COUNT(*), SUM(token_input), SUM(token_output) "
    "FROM traces GROUP BY agent ORDER BY SUM(token_input) + SUM(token_output) DESC"
).fetchall()
print(f"\n{'AGENT':<40} {'TRACES':>6} {'INPUT':>10} {'OUTPUT':>10}")
print("-" * 70)
for agent, count, inp, out in agent_rows:
    print(f"{agent:<40} {count:>6} {inp or 0:>10,} {out or 0:>10,}")

print(f"\nTotal estimated cost: ${total_cost:,.4f}")
conn.close()
```

50 lines, no dependencies beyond stdlib. The key insight: OpenFlux stores `token_input` and `token_output` as plain integer columns, so you just `SUM()` them. No JSON parsing, no framework-specific deserialization.

## Sample output

```
MODEL                                    TRACES      INPUT     OUTPUT       COST
--------------------------------------------------------------------------------
claude-sonnet-4-20250514                     47    892,340    156,200   $5.0200
gpt-4o-mini                                 23     45,120     12,800   $0.0144
gemini-2.5-flash                             12     31,000      8,400   $0.0049

AGENT                                    TRACES      INPUT     OUTPUT
----------------------------------------------------------------------
claude-code                                  47    892,340    156,200
docs-rag                                     23     45,120     12,800
adk-search                                   12     31,000      8,400

Total estimated cost: $5.0393
```

Immediately obvious: Claude Code is 99% of the spend. The RAG pipeline is basically free.

## Going further

If you don't want to maintain a script, OpenFlux ships with a built-in cost command:

```bash
openflux cost              # last 7 days
openflux cost --days 30    # last 30 days
openflux cost --agent claude-code
```

It does the same model-rate math plus a daily breakdown with sparkline bars. See the [cost analysis docs](../cost.md) for the full SQL query reference.

## The bigger picture

Cost is one question you can answer with normalized telemetry. The same `traces` table supports compliance auditing (which files did agents read?), fleet analytics (how many traces per agent per day?), and regression detection (did average token usage spike after a prompt change?). These are all just SQL queries against the same schema.

That's the whole point of OpenFlux. It doesn't build the dashboards. It builds the substrate that makes dashboards trivial. One `pip install`, a few lines of adapter config, and every agent you run feeds the same database. What you build on top is up to you.
