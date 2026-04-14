"""Risk check — hard limits enforced between every boss decision and every order."""

import logging
from config.settings import settings
from memory.working_memory import get_portfolio_state, set_system_halted

logger = logging.getLogger(__name__)


def risk_check(decision: dict, portfolio: dict | None = None) -> bool:
    """Return True if the trade is allowed, False if blocked.

    On drawdown kill, sets system:halted in Redis.
    """
    if portfolio is None:
        portfolio = get_portfolio_state()

    ticker = decision.get("ticker", "UNKNOWN")
    weight_pct = decision.get("weight_pct", 0.0)
    action = decision.get("action", "HOLD")

    # HOLD needs no risk check
    if action == "HOLD":
        return True

    # ── 1. Drawdown kill switch ──────────────────────────────────
    current_drawdown = portfolio.get("drawdown", 0.0)
    if current_drawdown >= settings.max_drawdown_kill:
        logger.critical(
            "SYSTEM HALT: drawdown %.1f%% >= kill threshold %.1f%%. "
            "Setting system:halted. Manual reset required.",
            current_drawdown * 100, settings.max_drawdown_kill * 100,
        )
        set_system_halted(True)
        return False

    # ── 2. Single position limit ─────────────────────────────────
    weight = weight_pct / 100.0
    if weight > settings.max_single_position:
        logger.warning(
            "BLOCKED %s %s: weight %.1f%% exceeds max single position %.1f%%",
            action, ticker, weight_pct, settings.max_single_position * 100,
        )
        return False

    # ── 3. Portfolio VaR ─────────────────────────────────────────
    portfolio_var = portfolio.get("daily_var", 0.0)
    if portfolio_var >= settings.max_portfolio_var:
        logger.warning(
            "BLOCKED %s %s: portfolio VaR %.2f%% >= limit %.2f%%",
            action, ticker, portfolio_var * 100, settings.max_portfolio_var * 100,
        )
        return False

    # ── 4. Sector exposure ───────────────────────────────────────
    sector = decision.get("sector")
    if sector and action == "BUY":
        sector_exposures = portfolio.get("sector_exposures", {})
        current_sector = sector_exposures.get(sector, 0.0)
        new_sector = current_sector + weight
        if new_sector > settings.max_sector_exposure:
            logger.warning(
                "BLOCKED %s %s: sector '%s' exposure would be %.1f%% > limit %.1f%%",
                action, ticker, sector, new_sector * 100,
                settings.max_sector_exposure * 100,
            )
            return False

    logger.info("APPROVED %s %s @ %.1f%%", action, ticker, weight_pct)
    return True
