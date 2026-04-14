"""Energy agent — analyzes EIA data, oil prices, and news for energy tickers."""

import json
import logging

import httpx
from config.settings import settings
from memory.working_memory import get_portfolio_state, get_regime, set_signal
from data.news_scraper import search_headlines
from data.quiver_feeds import get_congress_trades_for_tickers, get_insider_trades, get_gov_contracts_batch
from memory.semantic import get_rules
from memory.episodic import query_similar_setups
from agents.base import call_claude, neutral_signal, slim_similar, SIGNAL_SCHEMA

logger = logging.getLogger(__name__)

TICKERS = ["XOM", "CVX", "COP", "SLB"]

EIA_BASE = "https://api.eia.gov/v2/petroleum/pri/spt/data/"

SYSTEM_PROMPT = f"""You are an energy sector specialist for an autonomous hedge fund.
Analyze oil/gas prices, EIA data, news, congressional stock trades, insider trading, and government contracts.
Congressional trades in energy tickers signal policy expectations. DOE/DOD contracts are large and
affect revenue. Use agent="energy".
Return a JSON array — one signal per ticker.
{SIGNAL_SCHEMA}"""


def run() -> list[dict]:
    """Execute energy agent cycle."""
    portfolio = get_portfolio_state()
    regime = get_regime()

    oil_prices = _fetch_oil_prices()
    news = search_headlines("oil gas energy prices OPEC crude")
    congress_trades = get_congress_trades_for_tickers(TICKERS)
    all_insider_trades = get_insider_trades(limit=50)
    energy_insider_trades = [t for t in all_insider_trades if t.get("Ticker") in TICKERS]
    gov_contracts = get_gov_contracts_batch(TICKERS)
    rules = get_rules("energy")
    similar = query_similar_setups({"agent": "energy", "ticker": "ENERGY"})

    user_content = json.dumps({
        "tickers": TICKERS,
        "oil_prices": oil_prices,
        "congress_trades": congress_trades,
        "insider_trades": energy_insider_trades,
        "government_contracts": gov_contracts,
        "news_headlines": [h["headline"] for h in news[:10]],
        "portfolio": portfolio,
        "regime": regime,
        "semantic_rules": rules,
        "similar_past_setups": slim_similar(similar),
    }, indent=2)

    try:
        signals = call_claude(SYSTEM_PROMPT, user_content, max_tokens=2048)
    except Exception as e:
        logger.error("Energy agent failed: %s", e)
        signals = [neutral_signal("energy", t, str(e)) for t in TICKERS]

    if not isinstance(signals, list):
        signals = [signals]

    for sig in signals:
        ticker = sig.get("ticker", "UNKNOWN")
        set_signal(f"energy:{ticker}", sig)

    set_signal("energy", _summarize(signals))

    return signals


def _fetch_oil_prices() -> list[dict]:
    """Fetch recent crude oil spot prices from EIA."""
    try:
        resp = httpx.get(
            EIA_BASE,
            params={
                "api_key": settings.eia_api_key,
                "frequency": "weekly",
                "data[0]": "value",
                "facets[product][]": "EPCBRENT",
                "sort[0][column]": "period",
                "sort[0][direction]": "desc",
                "length": 12,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("response", {}).get("data", [])
        return [{"date": d.get("period"), "price": d.get("value")} for d in data]
    except Exception as e:
        logger.error("EIA fetch failed: %s", e)
        return []


def _summarize(signals: list[dict]) -> dict:
    """Roll up per-ticker signals into a single energy summary for the boss."""
    if not signals:
        return neutral_signal("energy", "ENERGY", "no signals produced")

    confidences = [s.get("confidence", 0.0) for s in signals]
    avg_confidence = sum(confidences) / len(confidences)

    bullish = sum(1 for s in signals if s.get("signal") == "BULLISH")
    bearish = sum(1 for s in signals if s.get("signal") == "BEARISH")

    if bullish > bearish:
        overall = "BULLISH"
    elif bearish > bullish:
        overall = "BEARISH"
    else:
        overall = "NEUTRAL"

    risk_flags = []
    for s in signals:
        risk_flags.extend(s.get("risk_flags", []))

    return {
        "agent": "energy",
        "ticker": "ENERGY",
        "signal": overall,
        "confidence": round(avg_confidence, 2),
        "time_horizon": "30d",
        "catalyst": f"{bullish} bullish, {bearish} bearish across {len(signals)} tickers",
        "risk_flags": risk_flags[:5],
        "suggested_weight": 0.0,
        "rationale": f"Energy sector summary: {bullish}B/{bearish}S/{len(signals)-bullish-bearish}N",
        "ticker_signals": signals,
    }
