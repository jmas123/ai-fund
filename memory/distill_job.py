"""Distillation job — extract trading rules from episodic memory nightly."""

import json
import logging
from collections import defaultdict

from config.settings import settings
from memory.episodic import get_recent_trades
from memory.semantic import write_rules
from agents.base import call_claude

logger = logging.getLogger(__name__)

DOMAINS = ["macro", "pharma", "tech", "energy", "political", "science"]

SYSTEM_PROMPT = """You are a trading strategy analyst reviewing past trade outcomes.
Extract 5-10 actionable rules from the provided trade history.
Each rule should be a specific, testable statement about when to buy, sell, or avoid a position.

Return ONLY a JSON array of rule objects:
[
  {
    "rule": "descriptive rule text",
    "confidence": 0.0-1.0,
    "n_trades": number of trades that support this rule
  }
]

Focus on:
- Patterns that led to profitable trades
- Patterns that led to losses (as warnings)
- Sector-specific insights
- Timing and catalyst patterns

Be specific. "Buy when momentum is positive" is too vague.
"NVO tends to rally 3-5% within 2 weeks of positive Phase 3 trial data" is good."""


def run_distillation(days: int = 30) -> dict:
    """Run the full distillation pipeline.

    Reads recent trades from episodic memory, groups by domain,
    calls Claude to extract rules, writes to semantic memory.

    Returns summary dict with counts per domain.
    """
    logger.info("=== DISTILLATION START ===")

    trades = get_recent_trades(days)
    if not trades:
        logger.warning("No trades in last %d days, nothing to distill", days)
        return {"domains": {}, "total_rules": 0}

    logger.info("Found %d trades in last %d days", len(trades), days)

    # Group trades by domain
    by_domain = defaultdict(list)
    for trade in trades:
        domain = trade.get("domain", "unknown")
        by_domain[domain].append(trade)

    summary = {}
    total_rules = 0

    for domain in DOMAINS:
        domain_trades = by_domain.get(domain, [])
        if len(domain_trades) < settings.min_trades_for_distillation:
            logger.info(
                "Skipping '%s': only %d trades (min %d)",
                domain, len(domain_trades), settings.min_trades_for_distillation,
            )
            continue

        logger.info("Distilling %d trades for domain '%s'", len(domain_trades), domain)

        try:
            rules = _extract_rules(domain, domain_trades)
            n_written = write_rules(domain, rules)
            summary[domain] = n_written
            total_rules += n_written
        except Exception as e:
            logger.error("Distillation failed for domain '%s': %s", domain, e)
            summary[domain] = 0

    logger.info("=== DISTILLATION END === (%d rules across %d domains)", total_rules, len(summary))
    return {"domains": summary, "total_rules": total_rules}


def _extract_rules(domain: str, trades: list[dict]) -> list[dict]:
    """Call Claude to extract rules from a domain's trade history."""
    # Simplify trade data for the prompt
    simplified = []
    for t in trades:
        simplified.append({
            "ticker": t["ticker"],
            "action": t["action"],
            "signal": t["signal"],
            "confidence": t["confidence"],
            "outcome": t.get("outcome", "unknown"),
            "pnl_pct": t.get("pnl_pct"),
            "rationale": t.get("rationale", ""),
            "timestamp": t["timestamp"],
        })

    user_content = json.dumps({
        "domain": domain,
        "trade_count": len(simplified),
        "trades": simplified,
    }, indent=2)

    result = call_claude(
        SYSTEM_PROMPT,
        user_content,
        max_tokens=settings.distill_max_tokens,
    )

    if not isinstance(result, list):
        result = [result]

    # Validate each rule has required fields
    valid_rules = []
    for r in result:
        if isinstance(r, dict) and "rule" in r:
            valid_rules.append({
                "rule": r["rule"],
                "confidence": r.get("confidence", 0.5),
                "n_trades": r.get("n_trades", len(trades)),
            })

    logger.info("Extracted %d rules for domain '%s'", len(valid_rules), domain)
    return valid_rules
