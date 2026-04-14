"""Tech agent — analyzes price action, news, and SEC filings for tech tickers."""

import json
import logging
import asyncio

from config.settings import settings
from memory.working_memory import get_portfolio_state, get_regime, set_signal
from data.polygon_scraper import scrape_multiple
from data.news_scraper import search_headlines
from data.quiver_feeds import get_congress_trades_for_tickers, get_insider_trades, get_gov_contracts_batch
from memory.semantic import get_rules
from memory.episodic import query_similar_setups
from agents.base import call_claude, neutral_signal, slim_similar, SIGNAL_SCHEMA

logger = logging.getLogger(__name__)

TICKERS = ["NVDA", "MSFT", "AAPL", "GOOGL", "META"]

SYSTEM_PROMPT = f"""You are a technology sector specialist for an autonomous hedge fund.
Analyze price data, news, congressional stock trades, insider trading, and government contracts.
Congressional buys are high-signal. Insider buys are bullish; cluster sells at highs are bearish.
MSFT and GOOGL win large government contracts that affect revenue. Use agent="tech".
Return a JSON array — one signal per ticker.
{SIGNAL_SCHEMA}"""


def run() -> list[dict]:
    """Execute tech agent cycle. Returns list of signal dicts."""
    portfolio = get_portfolio_state()
    regime = get_regime()

    price_data = asyncio.run(_get_prices())
    news = search_headlines("technology stocks NVDA MSFT AAPL earnings")
    congress_trades = get_congress_trades_for_tickers(TICKERS)
    all_insider_trades = get_insider_trades(limit=50)
    tech_insider_trades = [t for t in all_insider_trades if t.get("Ticker") in TICKERS]
    gov_contracts = get_gov_contracts_batch(TICKERS)
    rules = get_rules("tech")
    similar = query_similar_setups({"agent": "tech", "ticker": "TECH"})

    user_content = json.dumps({
        "tickers": TICKERS,
        "price_data": price_data,
        "congress_trades": congress_trades,
        "insider_trades": tech_insider_trades,
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
        logger.error("Tech agent failed: %s", e)
        signals = [neutral_signal("tech", t, str(e)) for t in TICKERS]

    if not isinstance(signals, list):
        signals = [signals]

    for sig in signals:
        ticker = sig.get("ticker", "UNKNOWN")
        set_signal(f"tech:{ticker}", sig)

    set_signal("tech", _summarize(signals))

    return signals


async def _get_prices() -> dict:
    results = await scrape_multiple(TICKERS)
    clean = {}
    for ticker, data in results.items():
        if data:
            clean[ticker] = {"price": data["price"], "change_pct": data["change_pct"]}
        else:
            clean[ticker] = None
    return clean


def _summarize(signals: list[dict]) -> dict:
    """Roll up per-ticker signals into a single tech summary for the boss."""
    if not signals:
        return neutral_signal("tech", "TECH", "no signals produced")

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
        "agent": "tech",
        "ticker": "TECH",
        "signal": overall,
        "confidence": round(avg_confidence, 2),
        "time_horizon": "30d",
        "catalyst": f"{bullish} bullish, {bearish} bearish across {len(signals)} tickers",
        "risk_flags": risk_flags[:5],
        "suggested_weight": 0.0,
        "rationale": f"Tech sector summary: {bullish}B/{bearish}S/{len(signals)-bullish-bearish}N",
        "ticker_signals": signals,
    }
