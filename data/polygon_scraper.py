"""Polygon scraper — stock price + news via browser."""

import asyncio
import logging
import re
from data.browser_agent import new_page

logger = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 2


async def scrape_ticker(ticker: str) -> dict | None:
    """Scrape price and news headlines for a ticker from Polygon."""
    page = await new_page()
    try:
        url = f"https://polygon.io/quote/{ticker}"
        await page.goto(url, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(2)

        text = await page.inner_text("body")

        price = _extract_price(text)
        change_pct = _extract_change(text)

        # Get news headlines from the News tab area
        headlines = []
        news_els = await page.query_selector_all("a[href*='/news/'], a[href*='/article/']")
        for el in news_els[:10]:
            t = await el.text_content()
            if t and t.strip() and len(t.strip()) > 15:
                headlines.append(t.strip())

        return {
            "ticker": ticker,
            "price": price,
            "change_pct": change_pct,
            "headlines": headlines,
        }

    except Exception as e:
        logger.error("Polygon scrape failed for %s: %s", ticker, e)
        return None
    finally:
        await page.close()


async def scrape_multiple(tickers: list[str]) -> dict[str, dict | None]:
    """Scrape multiple tickers with rate limiting."""
    results = {}
    for ticker in tickers:
        results[ticker] = await scrape_ticker(ticker)
        if len(tickers) > 1:
            await asyncio.sleep(RATE_LIMIT_DELAY)
    return results


def _extract_price(text: str) -> float | None:
    """Extract price like $260.48 from page text."""
    match = re.search(r'\$(\d{1,5}\.\d{2})', text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _extract_change(text: str) -> float | None:
    """Extract change percentage like +0.19% from page text."""
    match = re.search(r'([+-]\d+\.?\d*%)', text)
    if match:
        try:
            return float(match.group(1).rstrip('%'))
        except ValueError:
            pass
    return None
