"""Boss agent (Capital Allocator) — synthesizes all agent signals into trade decisions."""

import json
import logging

from config.settings import settings
from memory.working_memory import get_portfolio_state, get_all_signals
from agents.base import call_claude

logger = logging.getLogger(__name__)

APPROVED_TICKERS = {
    "NVO", "LLY", "MRNA", "PFE", "ABBV",
    "NVDA", "MSFT", "AAPL", "GOOGL", "META",
    "XOM", "CVX", "COP", "SLB", "SPY", "XLE",
}

SYSTEM_PROMPT = """You are the Capital Allocator for an autonomous hedge fund.
You receive signals from specialist agents and make final trade decisions.
Return ONLY a JSON array of decision objects. No prose, no markdown.
Schema: {"action":"BUY|SELL|HOLD|REDUCE", "ticker":str, "weight_pct":0-10,
"conviction":0.0-1.0, "rationale":str, "stop_loss_pct":0.0-1.0,
"sector":"tech|energy|pharma|macro"}

CRITICAL: You may ONLY trade tickers from this approved list:
NVO, LLY, MRNA, PFE, ABBV, NVDA, MSFT, AAPL, GOOGL, META, XOM, CVX, COP, SLB, SPY, XLE
Any decision with a ticker outside this list must be changed to HOLD.

Rules:
- Max weight_pct per position is 10.
- If no compelling signal, return a single HOLD.
- Only act on high-confidence convergent signals.
- Be terse. Keep each decision rationale under 40 words."""


def run() -> list[dict]:
    """Read all signals, call Claude Opus, return list of decisions."""
    portfolio = get_portfolio_state()
    signals = get_all_signals()

    if not signals:
        logger.warning("Boss agent: no signals available, returning HOLD")
        return [_hold_decision("No agent signals available")]

    # Use rollup signals only, skip per-ticker duplicates
    rollup_signals = {
        k: v for k, v in signals.items()
        if ":" not in k
    }

    slimmed = _slim_signals(rollup_signals)

    user_content = json.dumps({
        "signals": slimmed,
        "portfolio": {
            "cash_pct": portfolio.get("cash_pct"),
            "positions": portfolio.get("positions", {}),
            "drawdown": portfolio.get("drawdown"),
        },
    }, indent=2)

    try:
        decisions = call_claude(
            SYSTEM_PROMPT,
            user_content,
            model=settings.boss_model,
            max_tokens=settings.boss_max_tokens,
            temperature=settings.boss_temperature,
        )
    except Exception as e:
        logger.error("Boss agent failed: %s", e)
        return [_hold_decision(f"Boss agent error: {e}")]

    if not isinstance(decisions, list):
        decisions = [decisions]

    # Hard filter: block any ticker not in approved list
    for d in decisions:
        ticker = d.get("ticker", "")
        if ticker not in APPROVED_TICKERS and d.get("action") != "HOLD":
            logger.warning("BLOCKED unapproved ticker %s — forcing HOLD", ticker)
            d["action"] = "HOLD"
            d["weight_pct"] = 0.0
            d["rationale"] = f"Blocked: {ticker} not in approved ticker list"

    return decisions


def _slim_signals(signals: dict) -> dict:
    """Strip fields the boss doesn't need for decisions."""
    slimmed = {}
    for key, sig in signals.items():
        if not isinstance(sig, dict):
            continue
        slimmed[key] = {
            "agent": sig.get("agent"),
            "ticker": sig.get("ticker"),
            "signal": sig.get("signal"),
            "confidence": sig.get("confidence"),
            "time_horizon": sig.get("time_horizon"),
            "catalyst": sig.get("catalyst"),
            "suggested_weight": sig.get("suggested_weight"),
            "risk_flags": sig.get("risk_flags", [])[:2],
        }
    return slimmed


def _hold_decision(rationale: str) -> dict:
    return {
        "action": "HOLD",
        "ticker": "NONE",
        "weight_pct": 0.0,
        "conviction": 0.0,
        "rationale": rationale,
        "stop_loss_pct": 0.0,
    }
