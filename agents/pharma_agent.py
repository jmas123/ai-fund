"""Pharma agent — analyzes clinical trials and FDA data for pharma tickers."""

import json
import logging

from config.settings import settings
from memory.working_memory import get_portfolio_state, get_regime, set_signal
from data.fda_scraper import search_trials, get_fda_approvals
from data.news_scraper import search_headlines
from data.high_finance_client import get_insider_trades_batch, get_politician_trades
from memory.semantic import get_rules
from memory.episodic import query_similar_setups
from agents.base import call_claude, neutral_signal, slim_similar, SIGNAL_SCHEMA

logger = logging.getLogger(__name__)

TICKERS = ["NVO", "LLY", "MRNA", "PFE", "ABBV"]

COMPANY_MAP = {
    "NVO": "Novo Nordisk",
    "LLY": "Eli Lilly",
    "MRNA": "Moderna",
    "PFE": "Pfizer",
    "ABBV": "AbbVie",
}

SYSTEM_PROMPT = f"""You are a pharmaceutical sector specialist for an autonomous hedge fund.
Analyze clinical trials, FDA events, news, congressional stock trades, and insider trading.
Congressional buys in pharma tickers ahead of FDA decisions are highly informative.
Insider buys from executives are bullish; cluster sells at highs are bearish. Use agent="pharma".
Return a JSON array — one signal per ticker.
Keep rationale under 50 words per ticker. Be terse.
{SIGNAL_SCHEMA}"""


def run() -> list[dict]:
    """Execute pharma agent cycle. Returns list of signal dicts."""
    portfolio = get_portfolio_state()
    regime = get_regime()

    trials_data = {}
    for ticker, company in COMPANY_MAP.items():
        trials = search_trials(company)
        trials_data[ticker] = [
            {**t, "summary": t.get("summary", "")[:300]}
            for t in (trials[:3] if trials else [])
        ]

    fda_events = get_fda_approvals(5)
    news = search_headlines("pharma drug FDA approval")
    congress_trades = get_politician_trades(days=14, min_relevance="low")
    pharma_congress = [t for t in congress_trades if t.get("ticker") in TICKERS]
    insider_data = get_insider_trades_batch(TICKERS, days=60)
    rules = get_rules("pharma")
    similar = query_similar_setups({"agent": "pharma", "ticker": "PHARMA"})

    user_content = json.dumps({
        "tickers": TICKERS,
        "clinical_trials": trials_data,
        "fda_events": fda_events,
        "congress_trades": pharma_congress,
        "insider_trades": insider_data,
        "news_headlines": [h["headline"] for h in news[:5]],
        "semantic_rules": [r["rule"] for r in rules[:3]],
        "similar_past_setups": slim_similar(similar[:3]),
    }, indent=2)

    try:
        signals = call_claude(SYSTEM_PROMPT, user_content, max_tokens=settings.pharma_max_tokens)
    except Exception as e:
        logger.error("Pharma agent failed: %s", e)
        signals = [neutral_signal("pharma", t, str(e)) for t in TICKERS]

    if not isinstance(signals, list):
        signals = [signals]

    # Write rolled-up summary for boss, plus per-ticker for debugging
    for sig in signals:
        ticker = sig.get("ticker", "UNKNOWN")
        set_signal(f"pharma:{ticker}", sig)

    set_signal("pharma", _summarize(signals))

    return signals


def _summarize(signals: list[dict]) -> dict:
    """Roll up per-ticker signals into a single pharma summary for the boss."""
    if not signals:
        return neutral_signal("pharma", "PHARMA", "no signals produced")

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
        "agent": "pharma",
        "ticker": "PHARMA",
        "signal": overall,
        "confidence": round(avg_confidence, 2),
        "time_horizon": "30d",
        "catalyst": f"{bullish} bullish, {bearish} bearish across {len(signals)} tickers",
        "risk_flags": risk_flags[:5],
        "suggested_weight": 0.0,
        "rationale": f"Pharma sector summary: {bullish}B/{bearish}S/{len(signals)-bullish-bearish}N",
        "ticker_signals": signals,
    }
