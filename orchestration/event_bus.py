"""Event bus — Redis pub/sub for agent coordination and system events."""

import json
import logging
import redis
from config.settings import settings

logger = logging.getLogger(__name__)

_redis: redis.Redis | None = None

CHANNEL_SIGNALS = "agent:signals"
CHANNEL_SYSTEM = "system:events"


def _get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
        )
    return _redis


def publish_signal(agent_name: str, signal: dict) -> None:
    """Publish that an agent has completed its signal."""
    _get_redis().publish(CHANNEL_SIGNALS, json.dumps({
        "agent": agent_name,
        "signal": signal.get("signal", "NEUTRAL") if isinstance(signal, dict) else "NEUTRAL",
    }))


def publish_event(event_type: str, data: dict | None = None) -> None:
    """Publish a system event (cycle_start, cycle_end, halt, etc.)."""
    msg = {"event": event_type}
    if data:
        msg["data"] = data
    _get_redis().publish(CHANNEL_SYSTEM, json.dumps(msg))
    logger.info("Event: %s", event_type)
