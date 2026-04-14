"""Signal & decision analysis — audit log stats, agent accuracy, risk block rates."""

import json
import sqlite3
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

AUDIT_DB = Path(__file__).resolve().parent.parent / "audit_log.db"
EPISODIC_DB = Path(__file__).resolve().parent.parent / "episodic_memory.db"


def _query_audit(query: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(str(AUDIT_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(query, params).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def _query_episodic(query: str, params: tuple = ()) -> list[dict]:
    if not EPISODIC_DB.exists():
        return []
    conn = sqlite3.connect(str(EPISODIC_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(query, params).fetchall()
    result = [dict(r) for r in rows]
    conn.close()
    return result


def decision_summary() -> dict:
    """Breakdown of all decisions by action and status."""
    rows = _query_audit(
        "SELECT action, status, COUNT(*) as cnt FROM audit_log GROUP BY action, status ORDER BY cnt DESC"
    )
    total = sum(r["cnt"] for r in rows)
    return {"total_decisions": total, "breakdown": rows}


def block_rate() -> dict:
    """How often risk_check blocks trades."""
    rows = _query_audit(
        "SELECT status, COUNT(*) as cnt FROM audit_log WHERE status IN ('BLOCKED', 'SUBMITTED', 'PRE_SUBMIT', 'HOLD', 'SKIPPED', 'REJECTED', 'ERROR') GROUP BY status"
    )
    counts = {r["status"]: r["cnt"] for r in rows}
    total_actionable = sum(counts.values())
    blocked = counts.get("BLOCKED", 0)
    return {
        "total_actionable": total_actionable,
        "blocked": blocked,
        "block_rate_pct": round(blocked / total_actionable * 100, 1) if total_actionable > 0 else 0,
        "by_status": counts,
    }


def ticker_activity() -> list[dict]:
    """Most traded tickers with action counts."""
    rows = _query_audit(
        "SELECT ticker, action, COUNT(*) as cnt FROM audit_log "
        "GROUP BY ticker, action ORDER BY cnt DESC LIMIT 30"
    )
    return rows


def agent_accuracy() -> list[dict]:
    """Per-agent win/loss rate from episodic memory (trades with outcomes)."""
    rows = _query_episodic(
        "SELECT domain, signal, outcome, pnl_pct FROM trades WHERE outcome IS NOT NULL"
    )
    if not rows:
        return []

    by_agent = defaultdict(lambda: {"wins": 0, "losses": 0, "total_pnl": 0.0, "trades": 0})
    for r in rows:
        agent = r["domain"]
        pnl = r["pnl_pct"] or 0.0
        by_agent[agent]["trades"] += 1
        by_agent[agent]["total_pnl"] += pnl
        if pnl > 0:
            by_agent[agent]["wins"] += 1
        else:
            by_agent[agent]["losses"] += 1

    results = []
    for agent, stats in sorted(by_agent.items()):
        win_rate = stats["wins"] / stats["trades"] * 100 if stats["trades"] > 0 else 0
        avg_pnl = stats["total_pnl"] / stats["trades"] if stats["trades"] > 0 else 0
        results.append({
            "agent": agent,
            "trades": stats["trades"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate_pct": round(win_rate, 1),
            "avg_pnl_pct": round(avg_pnl, 2),
            "total_pnl_pct": round(stats["total_pnl"], 2),
        })
    return results


def signal_confidence_distribution() -> dict:
    """Distribution of signal confidence levels from episodic memory."""
    rows = _query_episodic("SELECT confidence, outcome, pnl_pct FROM trades")
    if not rows:
        return {"buckets": []}

    buckets = {"0.5-0.6": [], "0.6-0.7": [], "0.7-0.8": [], "0.8-0.9": [], "0.9-1.0": []}
    for r in rows:
        conf = r["confidence"] or 0
        pnl = r["pnl_pct"] or 0
        if conf < 0.6:
            buckets["0.5-0.6"].append(pnl)
        elif conf < 0.7:
            buckets["0.6-0.7"].append(pnl)
        elif conf < 0.8:
            buckets["0.7-0.8"].append(pnl)
        elif conf < 0.9:
            buckets["0.8-0.9"].append(pnl)
        else:
            buckets["0.9-1.0"].append(pnl)

    result = []
    for bucket, pnls in buckets.items():
        n = len(pnls)
        avg = sum(pnls) / n if n > 0 else 0
        wins = sum(1 for p in pnls if p > 0)
        result.append({
            "confidence_range": bucket,
            "count": n,
            "avg_pnl_pct": round(avg, 2),
            "win_rate_pct": round(wins / n * 100, 1) if n > 0 else 0,
        })
    return {"buckets": result}


def recent_decisions(limit: int = 20) -> list[dict]:
    """Most recent decisions from audit log with parsed decision JSON."""
    rows = _query_audit(
        "SELECT id, timestamp, ticker, action, weight_pct, status, error, order_id, decision "
        "FROM audit_log ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    for r in rows:
        try:
            r["decision"] = json.loads(r["decision"]) if r.get("decision") else {}
        except (json.JSONDecodeError, TypeError):
            r["decision"] = {}
    return rows


def run_report() -> str:
    """Generate a full signal analysis report. Returns formatted string."""
    lines = []
    lines.append("=" * 60)
    lines.append("  APEX FUND — SIGNAL & DECISION ANALYSIS")
    lines.append("=" * 60)

    # Decision summary
    summary = decision_summary()
    lines.append(f"\n  Total Decisions Logged: {summary['total_decisions']}")
    if summary["breakdown"]:
        lines.append(f"\n  Decision Breakdown")
        lines.append(f"  {'-' * 40}")
        lines.append(f"  {'Action':<10} {'Status':<15} {'Count':>6}")
        for row in summary["breakdown"]:
            lines.append(f"  {row['action']:<10} {row['status']:<15} {row['cnt']:>6}")

    # Block rate
    blocks = block_rate()
    if blocks["total_actionable"] > 0:
        lines.append(f"\n  Risk Check Stats")
        lines.append(f"  {'-' * 40}")
        lines.append(f"  {'Total Actionable:':<25} {blocks['total_actionable']:>6}")
        lines.append(f"  {'Blocked:':<25} {blocks['blocked']:>6}")
        lines.append(f"  {'Block Rate:':<25} {blocks['block_rate_pct']:>5.1f}%")
        for status, cnt in sorted(blocks["by_status"].items()):
            lines.append(f"    {status:<23} {cnt:>6}")

    # Ticker activity
    tickers = ticker_activity()
    if tickers:
        lines.append(f"\n  Ticker Activity (top trades)")
        lines.append(f"  {'-' * 40}")
        lines.append(f"  {'Ticker':<10} {'Action':<10} {'Count':>6}")
        for row in tickers[:15]:
            lines.append(f"  {row['ticker']:<10} {row['action']:<10} {row['cnt']:>6}")

    # Agent accuracy (from episodic memory)
    accuracy = agent_accuracy()
    if accuracy:
        lines.append(f"\n  Agent Accuracy (from closed trades)")
        lines.append(f"  {'-' * 55}")
        lines.append(f"  {'Agent':<12} {'Trades':>6} {'Wins':>5} {'Loss':>5} {'Win%':>6} {'AvgPnL':>8} {'TotalPnL':>9}")
        for a in accuracy:
            lines.append(
                f"  {a['agent']:<12} {a['trades']:>6} {a['wins']:>5} {a['losses']:>5} "
                f"{a['win_rate_pct']:>5.1f}% {a['avg_pnl_pct']:>7.2f}% {a['total_pnl_pct']:>8.2f}%"
            )
    else:
        lines.append(f"\n  [No closed trades in episodic memory yet]")

    # Confidence distribution
    conf = signal_confidence_distribution()
    if conf["buckets"] and any(b["count"] > 0 for b in conf["buckets"]):
        lines.append(f"\n  Confidence vs Outcome")
        lines.append(f"  {'-' * 45}")
        lines.append(f"  {'Range':<12} {'Count':>6} {'AvgPnL':>8} {'WinRate':>8}")
        for b in conf["buckets"]:
            if b["count"] > 0:
                lines.append(
                    f"  {b['confidence_range']:<12} {b['count']:>6} "
                    f"{b['avg_pnl_pct']:>7.2f}% {b['win_rate_pct']:>6.1f}%"
                )

    # Recent decisions
    recent = recent_decisions(10)
    if recent:
        lines.append(f"\n  Last 10 Decisions")
        lines.append(f"  {'-' * 55}")
        for r in recent:
            ts = r["timestamp"][:16] if r["timestamp"] else "?"
            lines.append(
                f"  {ts}  {r['action']:<6} {r['ticker']:<6} "
                f"{r['weight_pct']:>5.1f}%  → {r['status']}"
            )

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)
