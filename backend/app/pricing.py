"""Per-model $-per-1K-token pricing, used to estimate cost for both the chat
UI's `estimated_cost_usd` field and the token_usage_events tracking table.

Previously `rag.estimate_cost_usd` unconditionally used OpenAI's rates
(config.OPENAI_COST_PER_1K_INPUT/OUTPUT) regardless of which provider/model
actually served the request — so Claude usage was silently priced as if it
were OpenAI. This module fixes that: look up the actual model, fall back to
the OpenAI constants only for an unrecognized one.

Rates are approximate list prices (USD per 1K tokens) as of writing — update
here if a provider changes pricing; nothing else in the app needs to change.
"""
from app.config import OPENAI_COST_PER_1K_INPUT, OPENAI_COST_PER_1K_OUTPUT

MODEL_PRICING = {
    # OpenAI chat
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4.1": {"input": 0.002, "output": 0.008},
    "gpt-4.1-mini": {"input": 0.0004, "output": 0.0016},
    # OpenAI embeddings (output tokens don't apply)
    "text-embedding-3-small": {"input": 0.00002, "output": 0.0},
    "text-embedding-3-large": {"input": 0.00013, "output": 0.0},
    # Anthropic Claude
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
    "claude-opus-4-6": {"input": 0.015, "output": 0.075},
    "claude-haiku-4-5-20251001": {"input": 0.0008, "output": 0.004},
    # Local embeddings — no API cost
    "all-MiniLM-L6-v2": {"input": 0.0, "output": 0.0},
}

_FALLBACK_PRICING = {"input": OPENAI_COST_PER_1K_INPUT, "output": OPENAI_COST_PER_1K_OUTPUT}


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, _FALLBACK_PRICING)
    return round(
        (prompt_tokens / 1000) * pricing["input"] + (completion_tokens / 1000) * pricing["output"],
        6,
    )
