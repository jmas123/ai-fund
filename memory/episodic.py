"""Episodic memory — SQLite store for past trades with context and outcomes.

Uses SQLite with full-text search for now. Can be upgraded to Pinecone
for vector similarity search when PINECONE_API_KEY is configured.
"""

import json
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "episodic_memory.db"

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                domain      TEXT    NOT NULL,
                ticker      TEXT    NOT NULL,
                action      TEXT    NOT NULL,
                signal      TEXT    NOT NULL,
                confidence  REAL    NOT NULL,
                outcome     TEXT,
                pnl_pct     REAL,
                context     TEXT    NOT NULL,
                rationale   TEXT
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_domain ON trades(domain)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(timestamp)")
        _conn.commit()
    return _conn


def write_trade(trade: dict) -> int | None:
    """Write a completed trade to episodic memory.

    Quality gate: only writes if confidence >= episodic_confidence_gate.
    Trade should be written AFTER it closes, not when opened.

    Args:
        trade: dict with keys: domain, ticker, action, signal, confidence,
               outcome, pnl_pct, context (dict), rationale

    Returns:
        Row ID if written, None if gated.
    """
    confidence = trade.get("confidence", 0.0)
    if confidence < settings.episodic_confidence_gate:
        logger.debug(
            "Episodic gate: skipping %s %s (confidence=%.2f < %.2f)",
            trade.get("action"), trade.get("ticker"),
            confidence, settings.episodic_confidence_gate,
        )
        return None

    conn = _get_conn()
    context = trade.get("context", {})
    if isinstance(context, dict):
        context = json.dumps(context)

    cur = conn.execute(
        """
        INSERT INTO trades (timestamp, domain, ticker, action, signal, confidence,
                           outcome, pnl_pct, context, rationale)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            trade.get("domain", "unknown").split(":")[0],
            trade.get("ticker", "UNKNOWN"),
            trade.get("action", "UNKNOWN"),
            trade.get("signal", "NEUTRAL"),
            confidence,
            trade.get("outcome"),
            trade.get("pnl_pct"),
            context,
            trade.get("rationale"),
        ),
    )
    conn.commit()
    logger.info(
        "Episodic: wrote trade %s %s (confidence=%.2f, outcome=%s)",
        trade.get("action"), trade.get("ticker"),
        confidence, trade.get("outcome"),
    )
    return cur.lastrowid


def query_similar_setups(signal: dict, top_k: int = 5) -> list[dict]:
    """Find past trades similar to the current signal.

    Uses ticker + domain matching with confidence ordering.
    For proper semantic similarity, upgrade to Pinecone with embeddings.
    """
    conn = _get_conn()
    ticker = signal.get("ticker", "")
    domain = signal.get("agent", signal.get("domain", ""))

    # First try exact ticker match
    rows = conn.execute(
        "SELECT id, timestamp, domain, ticker, action, signal, confidence, "
        "outcome, pnl_pct, context, rationale "
        "FROM trades WHERE ticker = ? ORDER BY confidence DESC LIMIT ?",
        (ticker, top_k),
    ).fetchall()

    # If not enough, broaden to domain match
    if len(rows) < top_k and domain:
        extra = conn.execute(
            "SELECT id, timestamp, domain, ticker, action, signal, confidence, "
            "outcome, pnl_pct, context, rationale "
            "FROM trades WHERE domain = ? AND ticker != ? "
            "ORDER BY confidence DESC LIMIT ?",
            (domain, ticker, top_k - len(rows)),
        ).fetchall()
        rows.extend(extra)

    return [_row_to_dict(r) for r in rows]


def get_recent_trades(days: int = 30) -> list[dict]:
    """Fetch trades from the last N days for distillation."""
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT id, timestamp, domain, ticker, action, signal, confidence, "
        "outcome, pnl_pct, context, rationale "
        "FROM trades WHERE timestamp >= ? ORDER BY timestamp DESC",
        (cutoff,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_trades_by_domain(domain: str, days: int = 30) -> list[dict]:
    """Fetch trades for a specific domain from the last N days."""
    conn = _get_conn()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT id, timestamp, domain, ticker, action, signal, confidence, "
        "outcome, pnl_pct, context, rationale "
        "FROM trades WHERE domain = ? AND timestamp >= ? ORDER BY timestamp DESC",
        (domain, cutoff),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_trades() -> int:
    """Total number of trades in episodic memory."""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]


def _row_to_dict(r: tuple) -> dict:
    ctx = r[9]
    try:
        ctx = json.loads(ctx) if ctx else {}
    except json.JSONDecodeError:
        ctx = {"raw": ctx}

    return {
        "id": r[0], "timestamp": r[1], "domain": r[2], "ticker": r[3],
        "action": r[4], "signal": r[5], "confidence": r[6],
        "outcome": r[7], "pnl_pct": r[8], "context": ctx, "rationale": r[10],
    }
