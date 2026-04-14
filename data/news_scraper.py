"""News scraper — financial headlines via RSS feeds (more reliable than browser)."""

import logging
import re
import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 10

# RSS feeds — no browser needed, no bot blocking
RSS_FEEDS = {
    "reuters": "https://news.google.com/rss/search?q=site:reuters.com+markets&hl=en-US&gl=US&ceid=US:en",
    "ft": "https://news.google.com/rss/search?q=site:ft.com+markets&hl=en-US&gl=US&ceid=US:en",
    "wsj": "https://news.google.com/rss/search?q=site:wsj.com+markets&hl=en-US&gl=US&ceid=US:en",
    "bloomberg": "https://news.google.com/rss/search?q=site:bloomberg.com+markets&hl=en-US&gl=US&ceid=US:en",
}


def _parse_rss_items(xml: str, source: str) -> list[dict]:
    """Simple regex-based RSS parser — no extra dependencies."""
    items = []
    for match in re.finditer(r'<item>(.*?)</item>', xml, re.DOTALL):
        block = match.group(1)
        title_match = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', block)
        pub_match = re.search(r'<pubDate>(.*?)</pubDate>', block)
        if title_match:
            title = title_match.group(1).strip()
            # Skip very short or generic titles
            if len(title) > 10:
                items.append({
                    "source": source,
                    "headline": title,
                    "published": pub_match.group(1).strip() if pub_match else None,
                })
    return items


def scrape_feed(name: str, url: str) -> list[dict]:
    """Fetch a single RSS feed."""
    try:
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        items = _parse_rss_items(resp.text, name)
        logger.info("%s: fetched %d headlines", name, len(items))
        return items[:15]
    except Exception as e:
        logger.error("%s RSS fetch failed: %s", name, e)
        return []


def get_all_headlines() -> list[dict]:
    """Fetch headlines from all RSS sources."""
    headlines = []
    for name, url in RSS_FEEDS.items():
        headlines.extend(scrape_feed(name, url))
    return headlines


def search_headlines(query: str) -> list[dict]:
    """Search Google News RSS for a specific topic."""
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    return scrape_feed(f"search:{query}", url)
