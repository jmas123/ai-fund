"""Browser agent — singleton Playwright instance for all scrapers."""

import asyncio
import logging
from playwright.async_api import async_playwright, Browser, Playwright

logger = logging.getLogger(__name__)

_playwright: Playwright | None = None
_browser: Browser | None = None

PAGE_TIMEOUT = 15000  # 15 seconds


async def get_browser() -> Browser:
    """Return the singleton browser instance. Creates one if needed."""
    global _playwright, _browser
    if _browser is None or not _browser.is_connected():
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
        logger.info("Browser launched (headless chromium)")
    return _browser


async def new_page():
    """Create a new page from the singleton browser."""
    browser = await get_browser()
    page = await browser.new_page()
    page.set_default_timeout(PAGE_TIMEOUT)
    return page


async def scrape_page(url: str, selector: str | None = None) -> str | None:
    """Navigate to a URL and return text content. Optionally wait for a selector.

    Returns None on failure — caller handles gracefully.
    """
    page = await new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded")
        if selector:
            try:
                await page.wait_for_selector(selector, timeout=PAGE_TIMEOUT)
            except Exception:
                logger.warning("Selector '%s' not found on %s", selector, url)
                return None
        return await page.content()
    except Exception as e:
        logger.error("Failed to scrape %s: %s", url, e)
        return None
    finally:
        await page.close()


async def shutdown():
    """Close browser and playwright. Call on process exit."""
    global _browser, _playwright
    if _browser:
        await _browser.close()
        _browser = None
    if _playwright:
        await _playwright.stop()
        _playwright = None
    logger.info("Browser shut down")
