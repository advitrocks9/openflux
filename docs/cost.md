# Cost Analysis

OpenFlux stores token usage per trace. You can track spend across agents, models, and time periods with the CLI or raw SQL.

## How Token Usage is Captured

Each adapter extracts token counts from its framework's response metadata:

| Adapter | Token Source |
|---|---|
| OpenAI Agents | `GenerationSpanData.usage` (input_tokens, output_tokens) |
| LangChain | `llm_output.token_usage` (prompt_tokens, completion_tokens) |
| Claude Agent SDK | `adapter.record_usage()` call with usage dict |
| AutoGen | `models_usage` on messages (prompt_tokens, completion_tokens) |
| CrewAI | `LLMCallCompletedEvent.usage` |
| Google ADK | `usage_metadata` (prompt_token_count, candidates_token_count) |
| Bedrock | `metadata.usage` (inputTokens, outputTokens) |
| Claude Code | Transcript parsing (usage from assistant messages) |

Token counts are accumulated across all LLM calls within a trace and stored as four integer columns in the `traces` table: `token_input`, `token_output`, `token_cache_read`, and `token_cache_creation`.

## CLI Usage

```bash
# View token usage for recent traces
openflux recent

# Full detail including token breakdown
openflux trace trc-a1b2c3d4e5f6

# Export as JSON for analysis
openflux export --agent my-agent > traces.json
```

The `openflux trace` command displays token usage in a formatted breakdown:

```
Token Usage:
    input:          12,450
    output:         3,200
    cache_read:     8,000
    cache_creation: 2,000
```

## SQL Queries on the SQLite Database

The SQLite database at `~/.openflux/traces.db` stores all traces and can be queried directly. Token usage is stored as four integer columns: `token_input`, `token_output`, `token_cache_read`, `token_cache_creation`.

### Total tokens by agent

```sql
SELECT
    agent,
    COUNT(*) AS traces,
    SUM(token_input) AS total_input,
    SUM(token_output) AS total_output
FROM traces
WHERE token_input > 0 OR token_output > 0
GROUP BY agent
ORDER BY total_input + total_output DESC;
```

### Daily token usage

```sql
SELECT
    DATE(timestamp) AS day,
    agent,
    COUNT(*) AS traces,
    SUM(token_input) AS input_tokens,
    SUM(token_output) AS output_tokens
FROM traces
WHERE token_input > 0 OR token_output > 0
GROUP BY day, agent
ORDER BY day DESC;
```

### Estimated cost per model

This query applies approximate per-token rates. Adjust the rates to match your pricing.

```sql
SELECT
    model,
    COUNT(*) AS traces,
    SUM(token_input) AS total_input,
    SUM(token_output) AS total_output,
    ROUND(
        SUM(token_input) *
        CASE model
            WHEN 'gpt-4o-mini' THEN 0.15 / 1000000
            WHEN 'gpt-4o' THEN 2.50 / 1000000
            WHEN 'claude-sonnet-4-20250514' THEN 3.00 / 1000000
            WHEN 'claude-haiku-4-5-20250514' THEN 0.80 / 1000000
            WHEN 'gemini-2.5-flash' THEN 0.15 / 1000000
            ELSE 1.00 / 1000000
        END
        +
        SUM(token_output) *
        CASE model
            WHEN 'gpt-4o-mini' THEN 0.60 / 1000000
            WHEN 'gpt-4o' THEN 10.00 / 1000000
            WHEN 'claude-sonnet-4-20250514' THEN 15.00 / 1000000
            WHEN 'claude-haiku-4-5-20250514' THEN 4.00 / 1000000
            WHEN 'gemini-2.5-flash' THEN 0.60 / 1000000
            ELSE 5.00 / 1000000
        END
    , 4) AS estimated_cost_usd
FROM traces
WHERE (token_input > 0 OR token_output > 0) AND model != ''
GROUP BY model
ORDER BY estimated_cost_usd DESC;
```

### Most expensive traces

```sql
SELECT
    id,
    agent,
    model,
    token_input,
    token_output,
    token_input + token_output AS total_tokens,
    SUBSTR(task, 1, 60) AS task_preview
FROM traces
WHERE token_input > 0 OR token_output > 0
ORDER BY total_tokens DESC
LIMIT 20;
```

### Cache hit rate

For models that support prompt caching (Claude), measure cache effectiveness:

```sql
SELECT
    model,
    COUNT(*) AS traces,
    SUM(token_cache_read) AS cache_hits,
    SUM(token_cache_creation) AS cache_writes,
    SUM(token_input) AS total_input,
    ROUND(
        100.0 * SUM(token_cache_read) /
        NULLIF(SUM(token_input), 0),
    1) AS cache_hit_pct
FROM traces
WHERE token_input > 0 OR token_output > 0
GROUP BY model
HAVING cache_hits > 0;
```

### Token usage over the last 7 days with trend

```sql
SELECT
    DATE(timestamp) AS day,
    SUM(token_input + token_output) AS total_tokens,
    COUNT(*) AS trace_count,
    ROUND(
        1.0 * SUM(token_input + token_output) / COUNT(*),
    0) AS avg_tokens_per_trace
FROM traces
WHERE (token_input > 0 OR token_output > 0)
  AND timestamp >= DATE('now', '-7 days')
GROUP BY day
ORDER BY day;
```

## Building a Cost Analyzer Script

A minimal Python script that reads from the OpenFlux database:

```python
import sqlite3
from pathlib import Path

RATES = {
    "gpt-4o-mini": (0.15e-6, 0.60e-6),
    "gpt-4o": (2.50e-6, 10.00e-6),
    "claude-sonnet-4-20250514": (3.00e-6, 15.00e-6),
    "claude-haiku-4-5-20250514": (0.80e-6, 4.00e-6),
    "gemini-2.5-flash": (0.15e-6, 0.60e-6),
}
DEFAULT_RATE = (1.00e-6, 5.00e-6)

db = sqlite3.connect(str(Path.home() / ".openflux" / "traces.db"))
db.row_factory = sqlite3.Row

rows = db.execute("""
    SELECT model, token_input, token_output
    FROM traces
    WHERE (token_input > 0 OR token_output > 0) AND model != ''
""").fetchall()

totals: dict[str, dict] = {}
for row in rows:
    model = row["model"]
    inp = row["token_input"]
    out = row["token_output"]
    rate_in, rate_out = RATES.get(model, DEFAULT_RATE)
    cost = inp * rate_in + out * rate_out

    if model not in totals:
        totals[model] = {"traces": 0, "input": 0, "output": 0, "cost": 0.0}
    totals[model]["traces"] += 1
    totals[model]["input"] += inp
    totals[model]["output"] += out
    totals[model]["cost"] += cost

print(f"{'Model':<35} {'Traces':>7} {'Input':>10} {'Output':>10} {'Cost':>10}")
print("-" * 75)
for model, t in sorted(totals.items(), key=lambda x: -x[1]["cost"]):
    print(f"{model:<35} {t['traces']:>7} {t['input']:>10,} {t['output']:>10,} ${t['cost']:>8.4f}")

grand = sum(t["cost"] for t in totals.values())
print(f"\nTotal estimated cost: ${grand:.4f}")

db.close()
```

Adjust the `RATES` dictionary to match your actual pricing. The script reads directly from the OpenFlux SQLite database, so it works with traces from any adapter.
