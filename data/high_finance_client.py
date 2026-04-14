"""Client for high_finance internal API — replaces Quiver/congress scrapers."""

import logging

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

TIMEOUT = 5


def _base() -> str:
    return settings.high_finance_url.rstrip("/")


def _get(path: str, params: dict | None = None) -> dict | list:
    """GET with 5s timeout, returns empty dict on any failure."""
    url = f"{_base()}{path}"
    if not settings.high_finance_url:
        return {}
    try:
        resp = httpx.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("high_finance %s failed: %s", path, e)
        return {}


# ── Politician trades ────────────────────────────────────────

def get_politician_trades(days: int = 7, min_relevance: str = "low") -> list[dict]:
    """Recent politician trades with committee relevance scoring."""
    data = _get("/internal/politician-trades", {"days": days, "min_relevance": min_relevance})
    return data.get("trades", [])


# ── Insider trades ───────────────────────────────────────────

def get_insider_trades(ticker: str, days: int = 30) -> dict:
    """Insider trades (Form 4) for a single ticker."""
    return _get("/internal/insider-trades", {"ticker": ticker, "days": days})


def get_insider_trades_batch(tickers: list[str], days: int = 30) -> dict[str, dict]:
    """Insider trades for multiple tickers."""
    return {t: get_insider_trades(t, days) for t in tickers}


def get_insider_summary_batch(tickers: list[str], days: int = 30) -> dict[str, dict]:
    """Compact insider summary per ticker — safe for LLM context."""
    result = {}
    for t in tickers:
        raw = get_insider_trades(t, days)
        if not raw or not raw.get("summary"):
            result[t] = None
            continue
        s = raw["summary"]
        recent = raw.get("trades", [])[:3]
        result[t] = {
            "buys": s.get("buys", 0),
            "sells": s.get("sells", 0),
            "net_shares": s.get("net_shares", 0),
            "buy_value": s.get("buy_value", 0),
            "sell_value": s.get("sell_value", 0),
            "recent": [
                {"insider": tr.get("insider"), "type": tr["transaction_type"],
                 "shares": tr["shares"], "date": tr.get("date")}
                for tr in recent
            ],
        }
    return result


# ── Institutional flow ───────────────────────────────────────

def get_institutional_flow(ticker: str) -> dict:
    """Institutional ownership flow for a ticker."""
    return _get("/internal/institutional-flow", {"ticker": ticker})


# ── Options flow ─────────────────────────────────────────────

def get_options_flow(ticker: str) -> dict:
    """Options overview with unusual activity detection."""
    return _get("/internal/options-flow", {"ticker": ticker})


def get_options_flow_batch(tickers: list[str]) -> dict[str, dict]:
    """Options flow for multiple tickers."""
    return {t: get_options_flow(t) for t in tickers}


def get_options_summary_batch(tickers: list[str]) -> dict[str, dict]:
    """Compact options summary per ticker — safe for LLM context."""
    result = {}
    for t in tickers:
        raw = get_options_flow(t)
        if not raw:
            result[t] = None
            continue
        unusual = raw.get("unusual_activity", [])
        bullish = [u for u in unusual if u.get("signal") in ("BULLISH", "ITM CALL")]
        bearish = [u for u in unusual if u.get("signal") in ("BEARISH", "ITM PUT")]
        result[t] = {
            "put_call_ratio": raw.get("put_call_ratio"),
            "iv_percentile": raw.get("iv_percentile"),
            "max_pain": raw.get("max_pain"),
            "unusual_bullish": len(bullish),
            "unusual_bearish": len(bearish),
            "top_unusual": [
                {"type": u["type"], "strike": u["strike"], "volume": u["volume"],
                 "signal": u["signal"], "premium_value": u.get("premium_value", 0)}
                for u in unusual[:3]
            ],
        }
    return result


# ── Macro snapshot ───────────────────────────────────────────

def get_macro_snapshot() -> dict:
    """Current macro indicators from high_finance."""
    return _get("/internal/macro-snapshot")
