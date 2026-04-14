"""Portfolio performance — equity curve, Sharpe, drawdown, benchmark comparison."""

import json
import logging
import math
from datetime import datetime, timedelta, timezone

import httpx
from config.settings import settings

logger = logging.getLogger(__name__)

TIMEOUT = 10
RISK_FREE_RATE = 0.05  # annualized, ~current T-bill rate
TRADING_DAYS_PER_YEAR = 252


def _alpaca_headers() -> dict:
    return {
        "APCA-API-KEY-ID": settings.alpaca_key,
        "APCA-API-SECRET-KEY": settings.alpaca_secret,
    }


def get_portfolio_history(days: int = 30, timeframe: str = "1D") -> dict | None:
    """Fetch portfolio equity history from Alpaca."""
    try:
        resp = httpx.get(
            f"{settings.alpaca_base_url}/v2/account/portfolio/history",
            headers=_alpaca_headers(),
            params={
                "period": f"{days}D",
                "timeframe": timeframe,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Failed to fetch portfolio history: %s", e)
        return None


def get_positions() -> list[dict]:
    """Fetch current open positions from Alpaca."""
    try:
        resp = httpx.get(
            f"{settings.alpaca_base_url}/v2/positions",
            headers=_alpaca_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Failed to fetch positions: %s", e)
        return []


def get_account() -> dict | None:
    """Fetch account details from Alpaca."""
    try:
        resp = httpx.get(
            f"{settings.alpaca_base_url}/v2/account",
            headers=_alpaca_headers(),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("Failed to fetch account: %s", e)
        return None


def get_spy_history(days: int = 30) -> list[dict]:
    """Fetch SPY daily bars for benchmark comparison."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days + 5)  # buffer for weekends
    try:
        resp = httpx.get(
            "https://data.alpaca.markets/v2/stocks/SPY/bars",
            headers=_alpaca_headers(),
            params={
                "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "timeframe": "1Day",
                "limit": days + 5,
                "feed": "iex",
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("bars", []) or []
    except Exception as e:
        logger.error("Failed to fetch SPY bars: %s", e)
        return []


def compute_metrics(equity_series: list[float]) -> dict:
    """Compute performance metrics from an equity time series.

    Returns dict with: total_return, annualized_return, sharpe, sortino,
    max_drawdown, max_drawdown_duration, volatility, best_day, worst_day.
    """
    # Strip leading zeros (Alpaca returns 0 for days before first deposit)
    equity_series = [e for e in equity_series if e > 0]

    if len(equity_series) < 2:
        return {"error": "Not enough data points"}

    # Daily returns
    returns = []
    for i in range(1, len(equity_series)):
        if equity_series[i - 1] > 0:
            returns.append(equity_series[i] / equity_series[i - 1] - 1)

    if not returns:
        return {"error": "No valid returns"}

    n = len(returns)
    total_return = equity_series[-1] / equity_series[0] - 1

    # Annualized return
    days_held = n
    if days_held > 0 and total_return > -1:
        annualized = (1 + total_return) ** (TRADING_DAYS_PER_YEAR / days_held) - 1
    else:
        annualized = 0.0

    # Volatility
    mean_ret = sum(returns) / n
    variance = sum((r - mean_ret) ** 2 for r in returns) / max(n - 1, 1)
    daily_vol = math.sqrt(variance)
    annual_vol = daily_vol * math.sqrt(TRADING_DAYS_PER_YEAR)

    # Sharpe ratio
    daily_rf = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
    excess_returns = [r - daily_rf for r in returns]
    excess_mean = sum(excess_returns) / n
    sharpe = (excess_mean / daily_vol * math.sqrt(TRADING_DAYS_PER_YEAR)) if daily_vol > 0 else 0.0

    # Sortino ratio (downside deviation only)
    downside = [r for r in excess_returns if r < 0]
    if downside:
        downside_var = sum(r ** 2 for r in downside) / len(downside)
        downside_dev = math.sqrt(downside_var)
        sortino = (excess_mean / downside_dev * math.sqrt(TRADING_DAYS_PER_YEAR)) if downside_dev > 0 else 0.0
    else:
        sortino = float("inf")  # no down days

    # Max drawdown
    peak = equity_series[0]
    max_dd = 0.0
    dd_start = 0
    max_dd_duration = 0
    current_dd_start = 0
    for i, eq in enumerate(equity_series):
        if eq > peak:
            peak = eq
            current_dd_start = i
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd
            dd_start = current_dd_start
            max_dd_duration = i - current_dd_start

    return {
        "total_return_pct": round(total_return * 100, 2),
        "annualized_return_pct": round(annualized * 100, 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "max_drawdown_duration_days": max_dd_duration,
        "annual_volatility_pct": round(annual_vol * 100, 2),
        "best_day_pct": round(max(returns) * 100, 2),
        "worst_day_pct": round(min(returns) * 100, 2),
        "trading_days": n,
    }


def compute_benchmark_returns(spy_bars: list[dict]) -> list[float]:
    """Extract close prices from SPY bars into an equity-like series."""
    return [bar["c"] for bar in spy_bars if "c" in bar]


def run_report(days: int = 30) -> str:
    """Generate a full performance report. Returns formatted string."""
    lines = []
    lines.append("=" * 60)
    lines.append("  APEX FUND — PERFORMANCE REPORT")
    lines.append("=" * 60)

    # Account snapshot
    account = get_account()
    if account:
        equity = float(account.get("equity", 0))
        cash = float(account.get("cash", 0))
        buying_power = float(account.get("buying_power", 0))
        pnl = float(account.get("equity", 0)) - float(account.get("last_equity", 0))
        lines.append(f"\n  Account Snapshot")
        lines.append(f"  {'Equity:':<25} ${equity:>12,.2f}")
        lines.append(f"  {'Cash:':<25} ${cash:>12,.2f}")
        lines.append(f"  {'Buying Power:':<25} ${buying_power:>12,.2f}")
        lines.append(f"  {'Day P&L:':<25} ${pnl:>12,.2f}")
    else:
        lines.append("\n  [Could not fetch account data]")

    # Portfolio history + metrics
    history = get_portfolio_history(days=days)
    if history and history.get("equity"):
        equity_series = [float(e) for e in history["equity"] if e is not None]
        timestamps = history.get("timestamp", [])

        if len(equity_series) >= 2:
            metrics = compute_metrics(equity_series)
            lines.append(f"\n  Portfolio Metrics ({days}d)")
            lines.append(f"  {'-' * 40}")
            lines.append(f"  {'Total Return:':<25} {metrics['total_return_pct']:>10.2f}%")
            lines.append(f"  {'Annualized Return:':<25} {metrics['annualized_return_pct']:>10.2f}%")
            lines.append(f"  {'Sharpe Ratio:':<25} {metrics['sharpe_ratio']:>10.3f}")
            lines.append(f"  {'Sortino Ratio:':<25} {metrics['sortino_ratio']:>10.3f}")
            lines.append(f"  {'Max Drawdown:':<25} {metrics['max_drawdown_pct']:>10.2f}%")
            lines.append(f"  {'Drawdown Duration:':<25} {metrics['max_drawdown_duration_days']:>8d}  days")
            lines.append(f"  {'Annual Volatility:':<25} {metrics['annual_volatility_pct']:>10.2f}%")
            lines.append(f"  {'Best Day:':<25} {metrics['best_day_pct']:>10.2f}%")
            lines.append(f"  {'Worst Day:':<25} {metrics['worst_day_pct']:>10.2f}%")
            lines.append(f"  {'Trading Days:':<25} {metrics['trading_days']:>10d}")

            # Benchmark comparison
            spy_bars = get_spy_history(days=days)
            if spy_bars:
                spy_closes = compute_benchmark_returns(spy_bars)
                spy_metrics = compute_metrics(spy_closes)
                alpha = metrics["total_return_pct"] - spy_metrics["total_return_pct"]

                lines.append(f"\n  Benchmark Comparison (vs SPY)")
                lines.append(f"  {'-' * 40}")
                lines.append(f"  {'APEX Return:':<25} {metrics['total_return_pct']:>10.2f}%")
                lines.append(f"  {'SPY Return:':<25} {spy_metrics['total_return_pct']:>10.2f}%")
                lines.append(f"  {'Alpha:':<25} {alpha:>10.2f}%")
                lines.append(f"  {'APEX Sharpe:':<25} {metrics['sharpe_ratio']:>10.3f}")
                lines.append(f"  {'SPY Sharpe:':<25} {spy_metrics['sharpe_ratio']:>10.3f}")
                lines.append(f"  {'APEX Max DD:':<25} {metrics['max_drawdown_pct']:>10.2f}%")
                lines.append(f"  {'SPY Max DD:':<25} {spy_metrics['max_drawdown_pct']:>10.2f}%")
        else:
            lines.append(f"\n  [Not enough data points ({len(equity_series)}) for metrics]")
    else:
        lines.append(f"\n  [No portfolio history available yet — run some cycles first]")

    # Current positions
    positions = get_positions()
    if positions:
        lines.append(f"\n  Open Positions ({len(positions)})")
        lines.append(f"  {'-' * 55}")
        lines.append(f"  {'Ticker':<8} {'Qty':>6} {'Entry':>10} {'Current':>10} {'P&L %':>8} {'P&L $':>10}")
        for pos in positions:
            ticker = pos.get("symbol", "?")
            qty = pos.get("qty", "0")
            entry = float(pos.get("avg_entry_price", 0))
            current = float(pos.get("current_price", 0))
            pnl_pct = float(pos.get("unrealized_plpc", 0)) * 100
            pnl_usd = float(pos.get("unrealized_pl", 0))
            lines.append(f"  {ticker:<8} {qty:>6} ${entry:>9.2f} ${current:>9.2f} {pnl_pct:>7.2f}% ${pnl_usd:>9.2f}")
    else:
        lines.append(f"\n  No open positions")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)
