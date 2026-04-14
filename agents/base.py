"""Shared utilities for all agents — Claude client, JSON parsing, error signals."""

import hashlib
import json
import logging

import anthropic
from config.settings import settings
from memory.working_memory import _get_redis

logger = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

SIGNAL_SCHEMA = """Return ONLY a JSON object. No prose, no markdown.
Schema: {"agent":str, "ticker":str, "signal":"BULLISH|BEARISH|NEUTRAL",
"confidence":0.0-1.0, "time_horizon":"30d|90d|180d", "catalyst":str,
"risk_flags":[], "suggested_weight":0.0-0.10, "rationale":str}"""

CACHE_TTL = 5400  # 90 minutes — matches scheduler interval


def _content_hash(system: str, user_content: str, model: str) -> str:
    """Hash the full prompt to detect unchanged inputs."""
    raw = f"{model}:{system}:{user_content}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def call_claude(
    system: str,
    user_content: str,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    retry: bool = True,
    use_cache: bool = True,
) -> dict | list:
    """Call Claude and return parsed JSON. Retries once on parse failure.

    If use_cache=True, checks Redis for a cached response from an identical
    prompt. Skips the API call entirely if found (saves ~100% of that call).
    """
    model = model or settings.agent_model
    max_tokens = max_tokens or settings.agent_max_tokens
    temperature = temperature if temperature is not None else settings.agent_temperature

    # Check content-hash cache
    if use_cache:
        h = _content_hash(system, user_content, model)
        cache_key = f"llm_cache:{h}"
        try:
            cached = _get_redis().get(cache_key)
            if cached:
                logger.info("CACHE HIT [%s] — skipping API call", cache_key)
                return json.loads(cached)
        except Exception:
            pass  # Redis down — just call the API

    resp = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    text = strip_markdown(resp.content[0].text)
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        if retry:
            logger.warning("JSON parse failed, retrying")
            return call_claude(
                system,
                user_content + "\n\nReturn only raw JSON, no markdown.",
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                retry=False,
                use_cache=False,
            )
        raise

    # Store in cache
    if use_cache:
        try:
            _get_redis().set(cache_key, json.dumps(result), ex=CACHE_TTL)
        except Exception:
            pass

    return result


def strip_markdown(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return text


def slim_similar(setups: list[dict]) -> list[dict]:
    """Strip bulky fields from episodic similar setups before sending to Claude."""
    keep = ("ticker", "signal", "confidence", "outcome", "pnl_pct", "domain")
    return [{k: s[k] for k in keep if k in s} for s in setups]


def neutral_signal(agent: str, ticker: str, error_msg: str) -> dict:
    """Return a safe NEUTRAL signal when an agent fails."""
    return {
        "agent": agent,
        "ticker": ticker,
        "signal": "NEUTRAL",
        "confidence": 0.0,
        "time_horizon": "30d",
        "catalyst": "agent_error",
        "risk_flags": [f"{agent}_agent_failure: {error_msg}"],
        "suggested_weight": 0.0,
        "rationale": f"Agent failed: {error_msg}",
    }
