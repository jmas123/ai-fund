"""Political agent — analyzes legislative activity for regime/risk signals (no tickers)."""

import json
import logging

from config.settings import settings
from memory.working_memory import get_portfolio_state, get_regime, set_signal
from data.congress_scraper import get_recent_activity
from data.news_scraper import search_headlines
from data.quiver_feeds import get_congress_trades, get_lobbying_batch
from memory.semantic import get_rules
from memory.episodic import query_similar_setups
from agents.base import call_claude, neutral_signal, slim_similar, SIGNAL_SCHEMA

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""You are a political/regulatory risk specialist for an autonomous hedge fund.
Analyze legislative activity, political news, congressional stock trades (STOCK Act disclosures),
and corporate lobbying spend. Congressional buys/sells are high-signal — if multiple members
are buying the same ticker, that is a strong bullish indicator. Large lobbying spend changes
suggest regulatory attention. Use agent="political", ticker="REGIME".
No individual stocks. Also include "regime_risks":{{"regulation_risk":0-1,
"trade_war_risk":0-1,"fiscal_policy_risk":0-1,
"sector_impacts":{{"tech":-1 to 1,"energy":-1 to 1,"pharma":-1 to 1}}}}.
{SIGNAL_SCHEMA}"""


def run() -> dict:
    """Execute political agent cycle. Returns a single regime signal dict."""
    portfolio = get_portfolio_state()
    regime = get_regime()

    bills = get_recent_activity()
    news = search_headlines("congress legislation regulation trade policy tariff")
    congress_trades = get_congress_trades(limit=50)
    lobbying_data = get_lobbying_batch([
        "NVDA", "MSFT", "AAPL", "GOOGL", "META",
        "NVO", "LLY", "MRNA", "PFE", "ABBV",
        "XOM", "CVX", "COP", "SLB",
    ])
    rules = get_rules("political")
    similar = query_similar_setups({"agent": "political", "ticker": "REGIME"})

    user_content = json.dumps({
        "legislative_activity": bills,
        "congress_stock_trades": congress_trades,
        "lobbying_spend_by_ticker": lobbying_data,
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
