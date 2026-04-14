"""Order router — translates boss decisions into Alpaca paper/live orders."""

import logging
import math

import httpx
from config.settings import settings
from data.price_feeds import get_latest_price, get_account_equity

logger = logging.getLogger(__name__)

TIMEOUT = 10

APPROVED_TICKERS = {
    "NVO", "LLY", "MRNA", "PFE", "ABBV",
    "NVDA", "MSFT", "AAPL", "GOOGL", "META",
    "XOM", "CVX", "COP", "SLB", "SPY", "XLE",
}


def _has_open_order(ticker: str) -> bool:
    """Check if there's an existing open order for this ticker."""
    try:
        resp = httpx.get(
            f"{settings.alpaca_base_url}/v2/orders",
            headers={
                "APCA-API-KEY-ID": settings.alpaca_key,
                "APCA-API-SECRET-KEY": settings.alpaca_secret,
            },
            params={"status": "open", "symbols": ticker},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return len(resp.json()) > 0
    except Exception as e:
        logger.error("Failed to check open orders for %s: %s", ticker, e)
        return True  # fail safe — assume open order exists


def route(decision: dict) -> dict:
    """Submit an order to Alpaca. Returns order result dict with status."""
    ticker = decision.get("ticker", "UNKNOWN")
    action = decision.get("action", "HOLD")
    weight_pct = decision.get("weight_pct", 0.0)

    if ticker not in APPROVED_TICKERS:
        logger.warning("BLOCKED: %s not in approved ticker list", ticker)
        return {"status": "BLOCKED", "reason": f"{ticker} not in approved list"}

    if action == "HOLD":
        return {"status": "SKIPPED", "reason": "HOLD action"}

    # Check for existing open orders on this ticker to avoid wash trades
    if _has_open_order(ticker):
        logger.warning("SKIPPED %s %s: open order already exists", action, ticker)
        return {"status": "SKIPPED", "reason": f"Open order exists for {ticker}"}

    # Get equity and price to calculate share quantity
    equity = get_account_equity()
    if equity is None:
        return {"status": "ERROR", "reason": "Could not fetch account equity"}

    price = get_latest_price(ticker)
    if price is None or price <= 0:
        return {"status": "ERROR", "reason": f"Could not fetch price for {ticker}"}

    dollar_amount = equity * (weight_pct / 100.0)
    qty = math.floor(dollar_amount / price)

    if qty == 0:
        logger.info("SKIPPED %s %s: qty rounds to 0 ($%.2f / $%.2f)", action, ticker, dollar_amount, price)
        return {"status": "SKIPPED", "reason": f"qty=0 (${dollar_amount:.2f} / ${price:.2f})"}

    # Map action to Alpaca side
    if action == "BUY":
        side = "buy"
    elif action in ("SELL", "REDUCE"):
        side = "sell"
        if action == "REDUCE":
            qty = math.floor(qty * 0.5)
    else:
        return {"status": "SKIPPED", "reason": f"Unknown action {action}"}

    try:
        resp = httpx.post(
            f"{settings.alpaca_base_url}/v2/orders",
            headers={
                "APCA-API-KEY-ID": settings.alpaca_key,
                "APCA-API-SECRET-KEY": settings.alpaca_secret,
            },
            json={
                "symbol": ticker,
                "qty": str(qty),
                "side": side,
                "type": "market",
                "time_in_force": "day",
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        order = resp.json()
        order_id = order.get("id", "unknown")
        logger.info(
            "SUBMITTED %s %s x%d @ market — order_id=%s",
            side.upper(), ticker, qty, order_id,
        )
        return {"status": "SUBMITTED", "order_id": order_id, "qty": qty, "side": side}

    except httpx.HTTPStatusError as e:
        error_body = e.response.text
        logger.error("Alpaca order rejected: %s — %s", e, error_body)
        return {"status": "REJECTED", "reason": error_body}
    except Exception as e:
        logger.error("Order routing failed: %s", e)
        return {"status": "ERROR", "reason": str(e)}
