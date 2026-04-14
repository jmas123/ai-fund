"""Science agent — analyzes ArXiv papers for sector impact signals (no tickers)."""

import json
import logging
import xml.etree.ElementTree as ET

import httpx
from config.settings import settings
from memory.working_memory import get_portfolio_state, get_regime, set_signal
from memory.semantic import get_rules
from memory.episodic import query_similar_setups
from agents.base import call_claude, neutral_signal, slim_similar, SIGNAL_SCHEMA

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"

QUERIES = {
    "ai_ml": "cat:cs.AI OR cat:cs.LG",
    "biotech": "cat:q-bio.BM OR cat:q-bio.GN",
    "energy": "cat:physics.app-ph AND (solar OR battery OR fusion)",
    "quantum": "cat:quant-ph AND computing",
}

SYSTEM_PROMPT = f"""You are a scientific research analyst for an autonomous hedge fund.
Analyze recent papers for market impact. Use agent="science", ticker="RESEARCH".
No individual stocks. Also include "sector_impacts":{{"tech":{{"score":-1 to 1,"catalyst":"..."}},
"pharma":...,"energy":...}}.
{SIGNAL_SCHEMA}"""


def run() -> dict:
    """Execute science agent cycle."""
    portfolio = get_portfolio_state()
    regime = get_regime()

    papers = {}
    for category, query in QUERIES.items():
        papers[category] = _fetch_arxiv(query, max_results=5)

    rules = get_rules("science")
    similar = query_similar_setups({"agent": "science", "ticker": "RESEARCH"})

    user_content = json.dumps({
        "recent_papers": papers,
        "portfolio": portfolio,
        "regime": regime,
        "semantic_rules": rules,
        "similar_past_setups": slim_similar(similar),
    }, indent=2)

    try:
        signal = call_claude(SYSTEM_PROMPT, user_content)
    except Exception as e:
        logger.error("Science agent failed: %s", e)
        signal = neutral_signal("science", "RESEARCH", str(e))

    set_signal("science", signal)
    return signal


def _fetch_arxiv(query: str, max_results: int = 5) -> list[dict]:
    """Fetch recent papers from ArXiv API."""
    try:
        resp = httpx.get(
            ARXIV_API,
            params={
                "search_query": query,
                "start": 0,
                "max_results": max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return _parse_arxiv_xml(resp.text)
    except Exception as e:
        logger.error("ArXiv fetch failed for '%s': %s", query, e)
        return []


def _parse_arxiv_xml(xml_text: str) -> list[dict]:
    """Parse ArXiv Atom feed using stdlib XML parser."""
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_text)
    papers = []
    for entry in root.findall("atom:entry", ns):
        title = entry.find("atom:title", ns)
        summary = entry.find("atom:summary", ns)
        published = entry.find("atom:published", ns)
        if title is not None:
            papers.append({
                "title": " ".join(title.text.strip().split()),
                "summary": " ".join(summary.text.strip().split())[:200] if summary is not None else None,
                "published": published.text.strip() if published is not None else None,
            })
    return papers
