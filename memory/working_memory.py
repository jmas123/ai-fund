"""Working memory layer — Redis-backed shared state for all agents."""

import json
import redis
from config.settings import settings

_redis: redis.Redis | None = None

SIGNAL_TTL = 86400  # 24 hours


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
        )
    return _redis


# ── Portfolio state ──────────────────────────────────────────────

def get_portfolio_state() -> dict:
    raw = _get_redis().get("portfolio:state")
    if raw is None:
        return {}
    return json.loads(raw)


def set_portfolio_state(state: dict) -> None:
    _get_redis().set("portfolio:state", json.dumps(state))


# ── Signals ──────────────────────────────────────────────────────

def set_signal(agent_name: str, signal: dict) -> None:
    r = _get_redis()
    key = f"signals:today:{agent_name}"
    r.set(key, json.dumps(signal), ex=SIGNAL_TTL)


def get_signal(agent_name: str) -> dict | None:
    raw = _get_redis().get(f"signals:today:{agent_name}")
    if raw is None:
        return None
    return json.loads(raw)


def get_all_signals() -> dict[str, dict]:
    r = _get_redis()
    keys = r.keys("signals:today:*")
    signals = {}
    for key in keys:
        agent_name = key.split("signals:today:")[-1]
        raw = r.get(key)
        if raw is not None:
            signals[agent_name] = json.loads(raw)
    return signals


def clear_stale_signals() -> int:
    r = _get_redis()
    keys = r.keys("signals:today:*")
    if keys:
        return r.delete(*keys)
    return 0


# ── Macro regime ─────────────────────────────────────────────────

def get_regime() -> dict:
    raw = _get_redis().get("macro:regime")
    if raw is None:
        return {}
    return json.loads(raw)


def set_regime(regime: dict) -> None:
    _get_redis().set("macro:regime", json.dumps(regime))


# ── System halt ──────────────────────────────────────────────────

def is_system_halted() -> bool:
    return _get_redis().get("system:halted") == "1"


def set_system_halted(halted: bool = True) -> None:
    r = _get_redis()
    if halted:
        r.set("system:halted", "1")
    else:
        r.delete("system:halted")
