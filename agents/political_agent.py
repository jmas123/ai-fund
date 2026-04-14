"""Political agent — analyzes legislative activity for regime/risk signals (no tickers)."""

import json
import logging

from config.settings import settings
from memory.working_memory import get_portfolio_state, get_regime, set_signal
from data.high_finance_client import get_politician_trades
from data.news_scraper import search_headlines
from data.quiver_feeds import get_congress_trades
from memory.semantic import get_rules
from memory.episodic import query_similar_setups
from agents.base import call_claude, neutral_signal, slim_similar, SIGNAL_SCHEMA

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""You are a political/regulatory risk specialist for an autonomous hedge fund.
Analyze legislative activity, political news, and congressional stock trades (STOCK Act disclosures).
Congressional buys/sells are high-signal — if multiple members are buying the same ticker,
that is a strong bullish indicator.

Politician trades include a "relevance_label" (Low/Medium/High) and "relevance_score" (0-1)
based on committee oversight relevance — weight High-relevance trades much more heavily.
A committee chair buying a stock their committee oversees is extremely informative.

Use agent="political", ticker="REGIME".
No individual stocks. Also include "regime_risks":{{"regulation_risk":0-1,
"trade_war_risk":0-1,"fiscal_policy_risk":0-1,
"sector_impacts":{{"tech":-1 to 1,"energy":-1 to 1,"pharma":-1 to 1}}}}.
{SIGNAL_SCHEMA}"""


def run() -> dict:
    """Execute political agent cycle. Returns a single regime signal dict."""
    portfolio = get_portfolio_state()
    regime = get_regime()

    # Primary source: high_finance (DB-backed, committee-scored politician trades)
    hf_trades = get_politician_trades(days=14, min_relevance="low")

    # Fallback: Quiver live feed (if high_finance is down, hf_trades will be [])
    quiver_trades = get_congress_trades(limit=50) if not hf_trades else []

    news = search_headlines("congress legislation regulation trade policy tariff")
    rules = get_rules("political")
    similar = query_similar_setups({"agent": "political", "ticker": "REGIME"})

    user_content = json.dumps({
        "politician_trades_scored": hf_trades[:50],
        "congress_stock_trades_fallback": quiver_trades,
        "news_headlines": [h["headline"] for h in news[:15]],
        "current_regime": regime,
        "portfolio": portfolio,
        "semantic_rules": rules,
        "similar_past_setups": slim_similar(similar),
    }, indent=2)

    try:
        signal = call_claude(SYSTEM_PROMPT, user_content)
    except Exception as e:
        logger.error("Political agent failed: %s", e)
        signal = neutral_signal("political", "REGIME", str(e))

    set_signal("political", signal)
    return signal
