"""Price feeds — Alpaca bars API for live/recent stock prices."""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

TIMEOUT = 10


def get_latest_price(ticker: str) -> float | None:
    """Get the latest trade price for a ticker via Alpaca."""
    try:
        resp = httpx.get(
            f"https://data.alpaca.markets/v2/stocks/{ticker}/trades/latest",
            headers={
                "APCA-API-KEY-ID": settings.alpaca_key,
                "APCA-API-SECRET-KEY": settings.alpaca_secret,
            },
            params={"feed": "iex"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return float(resp.json()["trade"]["p"])
    except Exception as e:
        logger.error("Failed to get price for %s: %s", ticker, e)
        return None


def get_bars(ticker: str, days: int = 30, timeframe: str = "1Day") -> list[dict]:
    """Get daily bars for a ticker over the last N days."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    try:
        resp = httpx.get(
            f"https://data.alpaca.markets/v2/stocks/{ticker}/bars",
            headers={
                "APCA-API-KEY-ID": settings.alpaca_key,
                "APCA-API-SECRET-KEY": settings.alpaca_secret,
            },
            params={
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timeframe": timeframe,
                "limit": days,
                "feed": "iex",
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("bars", []) or []
    except Exception as e:
        logger.error("Failed to get bars for %s: %s", ticker, e)
        return []


def get_account_equity() -> float | None:
    """Get current account equity from Alpaca."""
    try:
        resp = httpx.get(
            f"{settings.alpaca_base_url}/v2/account",
            headers={
                "APCA-API-KEY-ID": settings.alpaca_key,
                "APCA-API-SECRET-KEY": settings.alpaca_secret,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return float(resp.json()["equity"])
    except Exception as e:
        logger.error("Failed to get account equity: %s", e)
        return None
