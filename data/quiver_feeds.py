"""Quiver Quantitative data feeds — congressional trades, lobbying, contracts, dark pool, insiders."""

import logging
import time

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

QUIVER_BASE = "https://api.quiverquant.com/beta"
TIMEOUT = 10


def _headers() -> dict[str, str]:
    return {"x-api-key": settings.quiver_api_key, "accept": "application/json"}


# ---------------------------------------------------------------------------
# Public endpoint wrappers
# ---------------------------------------------------------------------------

def get_congress_trades(limit: int = 50) -> list[dict]:
    """Fetch recent congressional stock trades (STOCK Act disclosures)."""
    try:
        resp = httpx.get(
            f"{QUIVER_BASE}/live/congresstrading",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()[:limit]
    except Exception as e:
        logger.error("Quiver congress trades fetch failed: %s", e)
        return []


def get_lobbying(ticker: str, limit: int = 20) -> list[dict]:
    """Fetch lobbying spend history for a single ticker."""
    try:
        resp = httpx.get(
            f"{QUIVER_BASE}/historical/lobbying/{ticker}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()[:limit]
    except Exception as e:
        logger.debug("Quiver lobbying unavailable for %s: %s", ticker, e)
        return []


def get_gov_contracts(ticker: str, limit: int = 20) -> list[dict]:
    """Fetch government contract history for a single ticker."""
    try:
        resp = httpx.get(
            f"{QUIVER_BASE}/historical/govcontractsall/{ticker}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()[:limit]
    except Exception as e:
        logger.debug("Quiver gov contracts unavailable for %s: %s", ticker, e)
        return []


def get_dark_pool(ticker: str, limit: int = 30) -> list[dict]:
    """Fetch off-exchange / dark pool volume data for a single ticker."""
    try:
        resp = httpx.get(
            f"{QUIVER_BASE}/historical/offexchange/{ticker}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()[:limit]
    except Exception as e:
        logger.debug("Quiver dark pool unavailable for %s: %s", ticker, e)
        return []


def get_insider_trades(limit: int = 50) -> list[dict]:
    """Fetch recent SEC Form 4 insider trading filings."""
    try:
        resp = httpx.get(
            f"{QUIVER_BASE}/live/insiders",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()[:limit]
    except Exception as e:
        logger.debug("Quiver insider trades unavailable: %s", e)
        return []


def get_congress_trades_for_tickers(tickers: list[str], limit: int = 100) -> list[dict]:
    """Fetch congress trades and filter to only the given tickers."""
    all_trades = get_congress_trades(limit=limit)
    ticker_set = set(tickers)
    return [t for t in all_trades if t.get("Ticker") in ticker_set]


# ---------------------------------------------------------------------------
# Batch helpers — iterate tickers with rate-limit delay
# ---------------------------------------------------------------------------

def _batch_fetch(fn, tickers: list[str], delay: float = 0.25) -> dict[str, list[dict]]:
    """Call a per-ticker Quiver function across multiple tickers."""
    results = {}
    for i, ticker in enumerate(tickers):
        results[ticker] = fn(ticker)
        if i < len(tickers) - 1:
            time.sleep(delay)
    return results


def get_lobbying_batch(tickers: list[str]) -> dict[str, list[dict]]:
    """Fetch lobbying data for multiple tickers."""
    return _batch_fetch(get_lobbying, tickers)


def get_gov_contracts_batch(tickers: list[str]) -> dict[str, list[dict]]:
    """Fetch government contract data for multiple tickers."""
    return _batch_fetch(get_gov_contracts, tickers)


def get_dark_pool_batch(tickers: list[str]) -> dict[str, list[dict]]:
    """Fetch dark pool data for multiple tickers."""
    return _batch_fetch(get_dark_pool, tickers)
