"""Congress data — uses the free congress.gov API (more reliable than browser)."""

import logging
import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 10
CONGRESS_API = "https://api.congress.gov/v3"
# Congress.gov API is free, no key needed for basic searches
# But we use the public search endpoint instead


def search_bills_api(query: str = "", limit: int = 10) -> list[dict]:
    """Search for bills via the congress.gov website search API."""
    try:
        resp = httpx.get(
            "https://api.congress.gov/v3/bill",
            params={
                "format": "json",
                "limit": limit,
                "sort": "updateDate+desc",
            },
            headers={"accept": "application/json"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        bills_data = resp.json().get("bills", [])

        bills = []
        for b in bills_data:
            bills.append({
                "bill": f"{b.get('type', '')}{b.get('number', '')}",
                "title": b.get("title"),
                "congress": b.get("congress"),
                "latest_action": b.get("latestAction", {}).get("text"),
                "action_date": b.get("latestAction", {}).get("actionDate"),
            })

        logger.info("Congress API: %d bills fetched", len(bills))
        return bills

    except Exception as e:
        logger.error("Congress API failed: %s", e)
        return []


def search_bills_rss(query: str) -> list[dict]:
    """Search congress.gov via RSS (no API key needed)."""
    import re
    try:
        url = f"https://www.congress.gov/rss/legislation.xml"
        resp = httpx.get(url, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()

        bills = []
        for match in re.finditer(r'<item>(.*?)</item>', resp.text, re.DOTALL):
            block = match.group(1)
            title_m = re.search(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', block)
            desc_m = re.search(r'<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>', block)
            if title_m:
                bills.append({
                    "bill": title_m.group(1).strip(),
                    "description": desc_m.group(1).strip() if desc_m else None,
                })

        logger.info("Congress RSS: %d bills for '%s'", len(bills), query)
        return bills[:10]

    except Exception as e:
        logger.error("Congress RSS failed for '%s': %s", query, e)
        return []


def get_recent_activity(topics: list[str] | None = None) -> dict[str, list[dict]]:
    """Get recent legislative activity for market-relevant topics."""
    if topics is None:
        topics = [
            "technology regulation",
            "drug pricing",
            "energy policy",
            "tariff",
            "federal reserve",
        ]
    # Use API instead of RSS (RSS feeds are dead)
    results = {"recent_bills": search_bills_api(limit=20)}
    return results
