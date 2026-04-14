"""Alpha engine — deterministic signal fusion and portfolio construction.

Replaces the LLM boss agent with math:
  1. Convert agent signals to numeric alpha scores
  2. Build target portfolio with vol scaling and sector caps
  3. Generate BUY/SELL/HOLD decisions by comparing targets to current positions
"""

import logging
import math
from collections import defaultdict

from config.settings import settings

logger = logging.getLogger(__name__)

DIRECTION_MAP = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}

TICKER_SECTORS = {
    "NVDA": "tech", "MSFT": "tech", "AAPL": "tech", "GOOGL": "tech", "META": "tech",
    "NVO": "pharma", "LLY": "pharma", "MRNA": "pharma", "PFE": "pharma", "ABBV": "pharma",
    "XOM": "energy", "CVX": "energy", "COP": "energy", "SLB": "energy",
    "SPY": "macro", "XLE": "energy",
}

# Regime/thematic agents signal non-tradeable tickers. Map them to sector tilts.
SECTOR_TILT_AGENTS = {
    "political": None,  # tilts ALL tickers (regime-level risk)
    "science": None,    # tilts ALL tickers (broad thematic)
    "macro": None,      # tilts ALL tickers (macro regime)
}

# Non-tradeable tickers that indicate sector/regime signals
NON_TRADEABLE = {"REGIME", "RESEARCH", "PORTFOLIO", "NONE"}

APPROVED_TICKERS = set(TICKER_SECTORS.keys())

TRADING_DAYS = 252
RISK_FREE = 0.05


def compute_alpha_scores(signals: dict) -> dict[str, float]:
    """Convert agent signals into per-ticker numeric alpha scores.

    Each signal contributes: direction × confidence × agent_weight × horizon_discount.
    Scores are aggregated per ticker across all agents.

    Args:
        signals: dict keyed by agent name, values are signal dicts or lists of signal dicts.

    Returns:
        dict of {ticker: aggregate_score}
    """
    agent_weights = settings.agent_weights
    horizon_discounts = settings.horizon_discounts
    scores = defaultdict(float)
    contributors = defaultdict(list)  # track which agents contributed to each ticker

    # First pass: collect regime/thematic tilts (non-tradeable signals)
    regime_tilts = []  # list of (direction * confidence * weight * discount)

    for agent_name, signal_data in signals.items():
        if ":" in agent_name:
            continue

        weight = agent_weights.get(agent_name, 0.10)
        signal_list = signal_data if isinstance(signal_data, list) else [signal_data]

        for sig in signal_list:
            if not isinstance(sig, dict):
                continue

            ticker = sig.get("ticker", "")
            direction = DIRECTION_MAP.get(sig.get("signal", "NEUTRAL"), 0.0)
            confidence = sig.get("confidence", 0.0)
            horizon = sig.get("time_horizon", "30d")
            h_discount = horizon_discounts.get(horizon, 0.5)

            if ticker in NON_TRADEABLE:
                # Regime/thematic signal — applies as tilt to all tradeable tickers
                if direction != 0:
                    tilt = direction * confidence * weight * h_discount
                    regime_tilts.append({"agent": agent_name, "tilt": tilt,
                                        "signal": sig.get("signal"), "confidence": confidence})
                continue

            if ticker not in APPROVED_TICKERS:
                continue

            # Direct ticker signal
            score = direction * confidence * weight * h_discount
            scores[ticker] += score
            if direction != 0:
                contributors[ticker].append({
                    "agent": agent_name,
                    "signal": sig.get("signal"),
                    "confidence": confidence,
                })

    # Apply regime tilts to tickers that already have direct signals.
    # Regime amplifies existing conviction — bullish regime boosts bullish tickers,
    # bearish regime makes bearish tickers more bearish. Tickers with no direct
    # signal don't get regime tilt (no signal = nothing to amplify).
    if regime_tilts:
        total_tilt = sum(t["tilt"] for t in regime_tilts)
        scored_tickers = [t for t in scores if scores[t] != 0]
        for ticker in scored_tickers:
            # Regime tilt amplifies in the direction of the existing score
            # If regime is bearish (-) and ticker is bearish (-), product is positive → more bearish
            if scores[ticker] > 0:
                scores[ticker] += max(total_tilt, 0) * 0.5  # bullish regime boosts bullish tickers
            else:
                scores[ticker] += min(total_tilt, 0) * 0.5  # bearish regime deepens bearish tickers
            for rt in regime_tilts:
                contributors[ticker].append({
                    "agent": rt["agent"],
                    "signal": rt["signal"],
                    "confidence": rt["confidence"],
                })

    # Remove tickers with zero score (no signal at all)
    scores = {t: s for t, s in scores.items() if s != 0}

    logger.info("Alpha scores: %s", {t: round(s, 4) for t, s in sorted(scores.items(), key=lambda x: x[1], reverse=True)})
    return dict(scores), dict(contributors)


def build_portfolio(
    scores: dict[str, float],
    portfolio: dict,
    price_data: dict,
    scenarios: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """Build target portfolio weights from alpha scores + optional scenario data.

    Applies:
      - Threshold filter (|score| >= alpha_threshold)
      - Volatility scaling (using scenario expected_vol when available)
      - Scenario penalties (high downside probability, high dispersion)
      - Position cap (max_single_position)
      - Sector cap (max_sector_exposure)
      - Normalization

    Args:
        scores: {ticker: alpha_score} from compute_alpha_scores
        portfolio: current portfolio state from working memory
        price_data: price summaries with daily_vol from quant agent
        scenarios: optional {ticker: scenario_dict} from scenario engine

    Returns:
        {ticker: {"weight_pct": float, "side": "buy"|"sell", "score": float}}
    """
    threshold = settings.alpha_threshold
    max_pos = settings.max_single_position
    max_sector = settings.max_sector_exposure

    # Filter by threshold
    actionable = {t: s for t, s in scores.items() if abs(s) >= threshold}

    if not actionable:
        logger.info("No scores above threshold (%.2f) — HOLD all", threshold)
        return {}

    # Volatility scaling: inverse vol weighting
    vol_adjusted = {}
    for ticker, score in actionable.items():
        daily_vol = 0.0

        # Prefer scenario expected_vol when available
        if scenarios and ticker in scenarios:
            sc = scenarios[ticker]
            # expected_vol is period vol (30d), convert to daily equivalent
            period_vol = sc.get("expected_vol", 0.0)
            if period_vol > 0:
                daily_vol = period_vol / math.sqrt(settings.scenario_horizon)

        # Fallback to raw price data vol
        if daily_vol <= 0 and price_data and price_data.get(ticker):
            daily_vol = price_data[ticker].get("daily_vol", 0.0) or 0.0

        if daily_vol > 0:
            vol_scale = min(settings.vol_target / (daily_vol * math.sqrt(TRADING_DAYS)), 3.0)
        else:
            vol_scale = 1.0

        vol_adjusted[ticker] = abs(score) * vol_scale

    # Apply scenario-based penalties
    if scenarios:
        for ticker in list(vol_adjusted.keys()):
            sc = scenarios.get(ticker)
            if sc is None:
                continue

            # Penalize high downside tail risk
            if sc.get("p_down_10pct", 0) > settings.scenario_downside_penalty_threshold:
                penalty = 0.5
                logger.info("Scenario penalty %s: p_down_10pct=%.0f%% → weight × %.1f",
                            ticker, sc["p_down_10pct"] * 100, penalty)
                vol_adjusted[ticker] *= penalty

            # Penalize high uncertainty / dispersion
            if sc.get("scenario_dispersion", 0) > settings.scenario_dispersion_penalty_threshold:
                penalty = 0.7
                logger.info("Scenario penalty %s: dispersion=%.2f → weight × %.1f",
                            ticker, sc["scenario_dispersion"], penalty)
                vol_adjusted[ticker] *= penalty

    # Normalize to sum to ~50% (leave room for cash)
    total_raw = sum(vol_adjusted.values())
    if total_raw == 0:
        return {}

    target_allocation = 0.50
    targets = {}

    for ticker in vol_adjusted:
        raw_weight = (vol_adjusted[ticker] / total_raw) * target_allocation
        capped_weight = min(raw_weight, max_pos)
        side = "buy" if actionable[ticker] > 0 else "sell"

        targets[ticker] = {
            "weight_pct": round(capped_weight * 100, 2),
            "side": side,
            "score": round(actionable[ticker], 4),
        }

    # Enforce sector caps
    sector_weights = defaultdict(float)
    for ticker, target in targets.items():
        sector = TICKER_SECTORS.get(ticker, "other")
        sector_weights[sector] += target["weight_pct"] / 100.0

    for sector, total_weight in sector_weights.items():
        if total_weight > max_sector:
            scale = max_sector / total_weight
            for ticker, target in targets.items():
                if TICKER_SECTORS.get(ticker) == sector:
                    target["weight_pct"] = round(target["weight_pct"] * scale, 2)
            logger.info("Sector %s capped: %.1f%% → %.1f%%", sector, total_weight * 100, max_sector * 100)

    logger.info("Target portfolio: %s", {t: f"{v['side']} {v['weight_pct']}%" for t, v in targets.items()})
    return targets


def generate_decisions(
    target_weights: dict[str, dict],
    current_positions: dict,
    contributors: dict[str, list] | None = None,
) -> list[dict]:
    """Generate trade decisions by comparing target weights to current positions.

    Args:
        target_weights: from build_portfolio
        current_positions: current position weights from portfolio state
        contributors: which agents contributed to each ticker's score

    Returns:
        list of decision dicts matching the boss agent schema
    """
    if not target_weights:
        return [_hold_decision("No signals above threshold — staying in cash")]

    decisions = []
    current = current_positions or {}

    for ticker, target in target_weights.items():
        weight_pct = target["weight_pct"]
        side = target["side"]
        score = target["score"]
        sector = TICKER_SECTORS.get(ticker, "other")

        # Determine action
        current_weight = current.get(ticker, {}).get("weight_pct", 0.0) if isinstance(current.get(ticker), dict) else 0.0

        if side == "sell":
            action = "SELL"
        elif current_weight == 0:
            action = "BUY"
        elif weight_pct > current_weight:
            action = "BUY"
        elif weight_pct < current_weight * 0.5:
            action = "REDUCE"
        else:
            action = "HOLD"
            weight_pct = 0.0

        # Build rationale from contributors
        rationale = _build_rationale(ticker, score, contributors)

        decisions.append({
            "action": action,
            "ticker": ticker,
            "weight_pct": weight_pct,
            "conviction": min(abs(score) * 2, 1.0),  # scale score to 0-1 conviction
            "rationale": rationale,
            "stop_loss_pct": 0.05 if action in ("BUY", "SELL") else 0.0,
            "sector": sector,
        })

    # Sort by conviction (highest first)
    decisions.sort(key=lambda d: d["conviction"], reverse=True)

    logger.info("Generated %d decisions", len(decisions))
    return decisions


def _build_rationale(ticker: str, score: float, contributors: dict | None) -> str:
    """Build a deterministic rationale string."""
    parts = []
    if contributors and ticker in contributors:
        c = contributors[ticker]
        n_bull = sum(1 for x in c if x["signal"] == "BULLISH")
        n_bear = sum(1 for x in c if x["signal"] == "BEARISH")
        avg_conf = sum(x["confidence"] for x in c) / len(c) if c else 0
        parts.append(f"{n_bull}B/{n_bear}S of {len(c)} agents")
        parts.append(f"avg_conf={avg_conf:.2f}")
    parts.append(f"score={score:.3f}")
    return ", ".join(parts)


def _hold_decision(rationale: str) -> dict:
    return {
        "action": "HOLD",
        "ticker": "PORTFOLIO",
        "weight_pct": 0.0,
        "conviction": 0.0,
        "rationale": rationale,
        "stop_loss_pct": 0.0,
        "sector": "macro",
    }


def run_engine(
    signals: dict,
    portfolio: dict,
    price_data: dict,
    scenarios: dict[str, dict] | None = None,
) -> list[dict]:
    """Full alpha engine pipeline. Convenience function for orchestration layer.

    Args:
        signals: all agent signals from working memory
        portfolio: current portfolio state
        price_data: price summaries with vol metrics from quant agent
        scenarios: optional scenario engine outputs for risk-adjusted sizing

    Returns:
        list of decision dicts ready for risk_check → order_router
    """
    scores, contributors = compute_alpha_scores(signals)
    targets = build_portfolio(scores, portfolio, price_data, scenarios=scenarios)
    decisions = generate_decisions(targets, portfolio.get("positions", {}), contributors)
    return decisions
