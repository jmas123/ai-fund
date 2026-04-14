"""Macro agent — analyzes FRED data to produce regime + sector tilt signals."""

import json
import logging

from config.settings import settings
from memory.working_memory import get_portfolio_state, get_regime, set_signal, set_regime
from data.macro_feeds import get_macro_data
from memory.semantic import get_rules
from memory.episodic import query_similar_setups
from agents.base import call_claude, neutral_signal, slim_similar, SIGNAL_SCHEMA

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""You are a macroeconomic specialist for an autonomous hedge fund.
Analyze FRED data and portfolio context. Use agent="macro", ticker="SPY".
Also include "regime":"expansion|contraction|transition" and
"sector_tilts":{{"tech":0-1,"energy":0-1,"pharma":0-1}}.
{SIGNAL_SCHEMA}"""


def run() -> dict:
    """Execute one macro agent cycle. Returns the signal dict."""
    portfolio = get_portfolio_state()
    current_regime = get_regime()

    macro_data = get_macro_data()
    rules = get_rules("macro")
    similar = query_similar_setups({"agent": "macro", "ticker": "SPY"})

    user_content = json.dumps({
        "macro_data": macro_data,
        "current_portfolio": portfolio,
        "current_regime": current_regime,
        "semantic_rules": rules,
        "similar_past_setups": slim_similar(similar),
    }, indent=2)

    try:
        signal = call_claude(SYSTEM_PROMPT, user_content)
    except Exception as e:
        logger.error("Macro agent failed: %s", e)
        signal = neutral_signal("macro", "SPY", str(e))

    set_signal("macro", signal)
    if "regime" in signal:
        set_regime({
            "regime": signal.get("regime", "transition"),
            "sector_tilts": signal.get("sector_tilts", {}),
        })

    return signal
