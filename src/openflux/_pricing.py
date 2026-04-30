"""Model-aware token pricing with cache token support."""

from __future__ import annotations

# (input, output, cache_read, cache_creation) per million tokens
_RATES: list[tuple[str, float, float, float, float]] = [
    # Anthropic — match most specific first
    ("opus", 15.00, 75.00, 1.50, 18.75),
    ("sonnet", 3.00, 15.00, 0.30, 3.75),
    ("haiku", 0.25, 1.25, 0.025, 0.30),
    ("claude-", 3.00, 15.00, 0.30, 3.75),  # fallback for unknown claude models
    # OpenAI
    ("gpt-4o-mini", 0.15, 0.60, 0.0, 0.0),
    ("gpt-4o", 2.50, 10.00, 0.0, 0.0),
    ("o3", 10.00, 40.00, 0.0, 0.0),
    ("o1", 15.00, 60.00, 0.0, 0.0),
    # Google
    ("gemini", 0.075, 0.30, 0.0, 0.0),
]
_DEFAULT_RATE = (1.00, 3.00, 0.10, 1.00)


def estimate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Estimate USD cost from model name and token counts."""
    model_lower = model.lower()
    for prefix, in_r, out_r, cr_r, cc_r in _RATES:
        if prefix in model_lower:
            return (
                input_tokens * in_r
                + output_tokens * out_r
                + cache_read_tokens * cr_r
                + cache_creation_tokens * cc_r
            ) / 1_000_000
    in_r, out_r, cr_r, cc_r = _DEFAULT_RATE
    return (
        input_tokens * in_r
        + output_tokens * out_r
        + cache_read_tokens * cr_r
        + cache_creation_tokens * cc_r
    ) / 1_000_000
