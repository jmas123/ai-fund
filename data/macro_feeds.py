"""FRED data fetcher — cached macro series for the macro agent."""

import logging
from functools import lru_cache

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Key macro series
SERIES = {
    "fed_funds": "FEDFUNDS",
    "cpi": "CPIAUCSL",
    "yield_curve": "T10Y2Y",
    "high_yield_spread": "BAMLH0A0HYM2",
    "unemployment": "UNRATE",
    "treasury_10y": "DGS10",
}

TIMEOUT = 10


@lru_cache(maxsize=32)
def _fetch_series(series_id: str, limit: int = 12) -> list[dict]:
    """Fetch recent observations for a FRED series. Cached for the process lifetime."""
    try:
        resp = httpx.get(
            FRED_BASE,
            params={
                "series_id": series_id,
                "api_key": settings.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        observations = resp.json().get("observations", [])
        return [{"date": o["date"], "value": o["value"]} for o in observations]
    except Exception as e:
        logger.error("FRED fetch failed for %s: %s", series_id, e)
        return []


def get_macro_data() -> dict[str, list[dict]]:
    """Return all key macro series as a dict of name → observations."""
    data = {}
    for name, series_id in SERIES.items():
        data[name] = _fetch_series(series_id)
    return data


def get_series(name: str, limit: int = 12) -> list[dict]:
    """Fetch a single named series."""
    series_id = SERIES.get(name)
    if series_id is None:
        logger.warning("Unknown series name: %s", name)
        return []
    return _fetch_series(series_id, limit)
