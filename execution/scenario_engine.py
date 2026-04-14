"""Scenario engine — Monte Carlo simulation layer between agent signals and portfolio construction.

Translates agent beliefs into probabilistic outcome distributions per ticker.
No LLM calls — pure numpy math.

Pipeline position:
  agents → signals → scenario_engine → alpha_engine → risk_check → execute
"""

import logging
import math
from collections import defaultdict

import numpy as np

from config.settings import settings
from execution.alpha_engine import (
    APPROVED_TICKERS, NON_TRADEABLE, DIRECTION_MAP, TICKER_SECTORS,
    compute_alpha_scores,
)

logger = logging.getLogger(__name__)

REGIME_VOL_MULT = {"expansion": 0.90, "transition": 1.0, "contraction": 1.20}
REGIME_SKEW = {"expansion": 0.0005, "transition": 0.0, "contraction": -0.001}


def simulate_ticker(
    ticker: str,
    mu_daily: float,
    sigma_daily: float,
    composite_score: float,
    disagreement: float,
    regime: str,
    horizon: int | None = None,
    n_paths: int | None = None,
    seed: int | None = None,
) -> dict:
    """Run Monte Carlo simulation for a single ticker.

    Args:
        ticker: stock ticker
        mu_daily: baseline daily drift from recent returns
        sigma_daily: baseline daily vol from recent returns
        composite_score: aggregated alpha score from compute_alpha_scores (-1 to +1)
        disagreement: 0 = full consensus, 0.5 = max disagreement among agents
        regime: "expansion" | "transition" | "contraction"
        horizon: trading days to simulate (default from settings)
        n_paths: number of Monte Carlo paths (default from settings)
        seed: random seed for reproducibility

    Returns:
        dict with expected_return, median_return, expected_vol, tail probabilities, etc.
    """
    horizon = horizon or settings.scenario_horizon
    n_paths = n_paths or settings.scenario_n_paths

    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()

    # Guard against bad inputs
    if sigma_daily <= 0:
        sigma_daily = 0.02  # fallback: ~30% annualized
    if math.isnan(mu_daily):
        mu_daily = 0.0

    # Step 1: Adjust drift based on agent consensus
    drift_adj = composite_score * settings.scenario_drift_scale
    adjusted_mu = mu_daily + drift_adj

    # Step 2: Adjust vol for disagreement + regime
    vol_boost = settings.scenario_disagreement_vol_boost
    regime_mult = REGIME_VOL_MULT.get(regime, 1.0)
    adjusted_sigma = sigma_daily * (1 + disagreement * vol_boost) * regime_mult

    # Step 3: Regime skew
    skew_shift = REGIME_SKEW.get(regime, 0.0)

    # Step 4: Generate paths (vectorized GBM)
    z = rng.standard_normal((n_paths, horizon))
    daily_returns = adjusted_mu + skew_shift + adjusted_sigma * z

    # Cumulative wealth paths
    cumulative = np.cumprod(1 + daily_returns, axis=1)
    final_returns = cumulative[:, -1] - 1.0

    # Step 5: Compute metrics from the distribution
    expected_return = float(np.mean(final_returns))
    median_return = float(np.median(final_returns))
    expected_vol = float(np.std(final_returns))

    p_up_5 = float(np.mean(final_returns > 0.05))
    p_down_5 = float(np.mean(final_returns < -0.05))
    p_down_10 = float(np.mean(final_returns < -0.10))

    pct_10 = float(np.percentile(final_returns, 10))
    pct_90 = float(np.percentile(final_returns, 90))
    dispersion = pct_90 - pct_10

    # Max drawdown estimate from the median path
    median_path = np.median(cumulative, axis=0)
    running_max = np.maximum.accumulate(median_path)
    drawdowns = (running_max - median_path) / running_max
    max_dd = float(np.max(drawdowns))

    return {
        "ticker": ticker,
        "horizon_days": horizon,
        "expected_return": round(expected_return, 5),
        "median_return": round(median_return, 5),
        "expected_vol": round(expected_vol, 5),
        "p_up_5pct": round(p_up_5, 4),
        "p_down_5pct": round(p_down_5, 4),
        "p_down_10pct": round(p_down_10, 4),
        "scenario_dispersion": round(dispersion, 5),
        "max_drawdown_estimate": round(max_dd, 5),
        "pct_10": round(pct_10, 5),
        "pct_90": round(pct_90, 5),
        "composite_score": 0.0,  # filled in by compute_composite
        "regime_sensitivity": 0.0,  # filled in by run_scenarios
        "alpha_score": round(composite_score, 5),
        "disagreement": round(disagreement, 4),
        "regime": regime,
    }


def compute_composite(scenario: dict) -> float:
    """Compute a single composite score from scenario metrics.

    Rewards: expected return, upside probability
    Penalizes: downside probability, high dispersion, max drawdown

    Returns value in roughly [-1, 1] range.
    """
    er = scenario["expected_return"]
    p_up = scenario["p_up_5pct"]
    p_down = scenario["p_down_10pct"]
    dispersion = scenario["scenario_dispersion"]
    max_dd = scenario["max_drawdown_estimate"]

    # Weighted combination
    score = (
        er * 5.0                    # expected return (scaled up since it's small)
        + p_up * 0.3                # reward upside probability
        - p_down * 0.5              # penalize severe downside
        - dispersion * 0.2          # penalize uncertainty
        - max_dd * 0.3              # penalize drawdown risk
    )

    return round(max(min(score, 1.0), -1.0), 4)


def _compute_disagreement(signals: dict, ticker: str) -> float:
    """Compute agent disagreement for a specific ticker.

    Returns 0 (full consensus) to 0.5 (maximum disagreement).
    """
    n_bull = 0
    n_bear = 0

    for agent_name, signal_data in signals.items():
        if ":" in agent_name:
            continue
        signal_list = signal_data if isinstance(signal_data, list) else [signal_data]
        for sig in signal_list:
            if not isinstance(sig, dict):
                continue
            sig_ticker = sig.get("ticker", "")
            if sig_ticker != ticker and sig_ticker not in NON_TRADEABLE:
                continue
            direction = sig.get("signal", "NEUTRAL")
            if direction == "BULLISH":
                n_bull += 1
            elif direction == "BEARISH":
                n_bear += 1

    total = n_bull + n_bear
    if total == 0:
        return 0.0
    return min(n_bull, n_bear) / total


def run_scenarios(
    signals: dict,
    price_data: dict,
    regime: str = "transition",
) -> dict[str, dict]:
    """Run Monte Carlo scenarios for all tickers with agent signals.

    Args:
        signals: all agent signals from working memory
        price_data: price summaries with daily_vol from quant agent
        regime: current macro regime from working memory

    Returns:
        dict of {ticker: scenario_output_dict}
    """
    logger.info("Running scenario engine (%d paths, %dd horizon, regime=%s)...",
                settings.scenario_n_paths, settings.scenario_horizon, regime)

    # Get alpha scores from existing signal fusion (reuse, don't rebuild)
    scores, _ = compute_alpha_scores(signals)

    scenarios = {}

    for ticker in APPROVED_TICKERS:
        # Skip tickers with no price data
        pd = price_data.get(ticker) if price_data else None
        if pd is None:
            continue

        mu = pd.get("return_30d", 0.0)
        if mu is not None:
            # Convert 30d total return to daily
            mu_daily = mu / max(pd.get("trading_days", 20), 1) if "trading_days" in pd else mu / 20
        else:
            mu_daily = 0.0

        sigma_daily = pd.get("daily_vol", 0.02) or 0.02
        alpha = scores.get(ticker, 0.0)
        disagreement = _compute_disagreement(signals, ticker)

        # Use a deterministic seed per ticker for reproducibility within a cycle
        seed = hash(ticker) % (2**31)

        # Main simulation
        scenario = simulate_ticker(
            ticker=ticker,
            mu_daily=mu_daily,
            sigma_daily=sigma_daily,
            composite_score=alpha,
            disagreement=disagreement,
            regime=regime,
            seed=seed,
        )

        # Regime sensitivity: run expansion vs contraction, measure difference
        if regime != "expansion":
            exp_result = simulate_ticker(
                ticker, mu_daily, sigma_daily, alpha, disagreement,
                regime="expansion", seed=seed,
            )
            exp_er = exp_result["expected_return"]
        else:
            exp_er = scenario["expected_return"]

        if regime != "contraction":
            con_result = simulate_ticker(
                ticker, mu_daily, sigma_daily, alpha, disagreement,
                regime="contraction", seed=seed,
            )
            con_er = con_result["expected_return"]
        else:
            con_er = scenario["expected_return"]

        scenario["regime_sensitivity"] = round(abs(exp_er - con_er), 5)

        # Composite score
        scenario["composite_score"] = compute_composite(scenario)

        scenarios[ticker] = scenario

    # Log summary
    if scenarios:
        top = sorted(scenarios.items(), key=lambda x: x[1]["composite_score"], reverse=True)
        for ticker, sc in top[:5]:
            logger.info(
                "  %s: E[r]=%.2f%% med=%.2f%% vol=%.1f%% P(↓10%%)=%.0f%% composite=%.3f",
                ticker, sc["expected_return"] * 100, sc["median_return"] * 100,
                sc["expected_vol"] * 100, sc["p_down_10pct"] * 100, sc["composite_score"],
            )

    logger.info("Scenario engine complete: %d tickers simulated", len(scenarios))
    return scenarios
