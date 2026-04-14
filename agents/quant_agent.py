"""Quant agent — analyzes portfolio state and price data for sizing recommendations."""

import json
import logging
import math

from config.settings import settings
from memory.working_memory import get_portfolio_state, get_regime, get_all_signals, set_signal
from data.price_feeds import get_bars
from data.quiver_feeds import get_dark_pool_batch
from memory.semantic import get_rules
from memory.episodic import query_similar_setups
from agents.base import call_claude, neutral_signal, slim_similar, SIGNAL_SCHEMA

logger = logging.getLogger(__name__)

ALL_TICKERS = [
    "NVO", "LLY", "MRNA", "PFE", "ABBV",
    "NVDA", "MSFT", "AAPL", "GOOGL", "META",
    "XOM", "CVX", "COP", "SLB",
    "SPY",  # needed for beta calculation
]

TRADING_DAYS = 252
RISK_FREE = 0.05

SYSTEM_PROMPT = f"""You are a quantitative analyst for an autonomous hedge fund.
Analyze portfolio, momentum, volatility, existing signals, and dark pool activity.
Unusual spikes in dark pool short volume relative to total volume indicate institutional selling pressure.
Sustained dark pool activity with stable prices suggests accumulation.
Use agent="quant", ticker="PORTFOLIO".
Sizing only — no new trade ideas. Also include "sizing_recommendations":{{"TICKER":{{"current_weight":0,
"recommended_weight":0,"reason":"..."}}}}, "portfolio_metrics":{{"concentration_risk":0-1,
"momentum_score":-1 to 1,"suggested_cash_pct":0-1}}.
Keep all reason fields under 30 words. Be terse.
{SIGNAL_SCHEMA}"""


def run() -> dict:
    """Execute quant agent cycle."""
    portfolio = get_portfolio_state()
    regime = get_regime()
    existing_signals = get_all_signals()

    # Quant only needs signal + confidence, not full objects
    signal_summary = {
        k: {"signal": v.get("signal"), "confidence": v.get("confidence"),
            "ticker": v.get("ticker")}
        for k, v in existing_signals.items()
        if not k.startswith(("pharma:", "tech:", "energy:"))  # use rollups, skip per-ticker
    }

    price_data = _get_price_summaries()
    dark_pool_data = get_dark_pool_batch(ALL_TICKERS)
    rules = get_rules("quant")
    similar = query_similar_setups({"agent": "quant", "ticker": "PORTFOLIO"})

    user_content = json.dumps({
        "portfolio": portfolio,
        "regime": regime,
        "signal_summary": signal_summary,
        "price_summaries": price_data,
        "dark_pool_activity": dark_pool_data,
        "semantic_rules": [r["rule"] for r in rules[:3]],
        "risk_limits": {
            "max_single_position": settings.max_single_position,
            "max_sector_exposure": settings.max_sector_exposure,
            "max_portfolio_var": settings.max_portfolio_var,
        },
    }, indent=2)

    try:
        signal = call_claude(SYSTEM_PROMPT, user_content, max_tokens=settings.quant_max_tokens)
    except Exception as e:
        logger.error("Quant agent failed: %s", e)
        signal = neutral_signal("quant", "PORTFOLIO", str(e))

    set_signal("quant", signal)
    return signal


def _daily_returns(closes: list[float]) -> list[float]:
    """Compute daily returns from close prices."""
    return [(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1] > 0]


def _get_price_summaries() -> dict:
    """Get 30-day price bars and compute stats including vol, beta, sharpe."""
    # Fetch all bars first, need SPY for beta calc
    all_bars = {}
    for ticker in ALL_TICKERS:
        bars = get_bars(ticker, days=30)
        closes = [b.get("c", 0) for b in bars if "c" in b] if bars else []
        all_bars[ticker] = closes

    spy_returns = _daily_returns(all_bars.get("SPY", []))

    summaries = {}
    for ticker in ALL_TICKERS:
        closes = all_bars[ticker]
        if len(closes) < 5:
            summaries[ticker] = None
            continue

        current = closes[-1]
        start = closes[0]
        high = max(closes)
        low = min(closes)
        avg = sum(closes) / len(closes)
        ret_30d = (current - start) / start if start else 0

        # Daily returns and volatility
        returns = _daily_returns(closes)
        n = len(returns)

        if n < 2:
            summaries[ticker] = {
                "current": current, "high_30d": high, "low_30d": low,
                "avg_30d": round(avg, 2), "return_30d": round(ret_30d, 4),
                "daily_vol": None, "beta_spy": None, "sharpe_30d": None,
            }
            continue

        mean_ret = sum(returns) / n
        variance = sum((r - mean_ret) ** 2 for r in returns) / max(n - 1, 1)
        daily_vol = math.sqrt(variance)
        annual_vol = daily_vol * math.sqrt(TRADING_DAYS)

        # Sharpe ratio (annualized)
        annual_ret = (1 + ret_30d) ** (TRADING_DAYS / max(n, 1)) - 1
        sharpe = (annual_ret - RISK_FREE) / annual_vol if annual_vol > 0 else 0.0

        # Beta vs SPY
        beta = None
        if spy_returns and len(spy_returns) >= len(returns):
            spy_sub = spy_returns[:n]
            if len(spy_sub) == n:
                spy_mean = sum(spy_sub) / n
                spy_var = sum((r - spy_mean) ** 2 for r in spy_sub) / max(n - 1, 1)
                if spy_var > 0:
                    covariance = sum(
                        (returns[i] - mean_ret) * (spy_sub[i] - spy_mean)
                        for i in range(n)
                    ) / max(n - 1, 1)
                    beta = round(covariance / spy_var, 3)

        summaries[ticker] = {
            "current": current,
            "high_30d": high,
            "low_30d": low,
            "avg_30d": round(avg, 2),
            "return_30d": round(ret_30d, 4),
            "daily_vol": round(daily_vol, 6),
            "annual_vol": round(annual_vol, 4),
            "beta_spy": beta,
            "sharpe_30d": round(sharpe, 3),
        }

    return summaries
