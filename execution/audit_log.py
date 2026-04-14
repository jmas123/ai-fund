"""Audit log — SQLite record of every decision and order. Log everything."""

import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "audit_log.db"

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH))
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT    NOT NULL,
                ticker      TEXT    NOT NULL,
                action      TEXT    NOT NULL,
                weight_pct  REAL    NOT NULL,
                decision    TEXT    NOT NULL,
                status      TEXT    NOT NULL,
                error       TEXT,
                order_id    TEXT
            )
        """)
        _conn.commit()
    return _conn


def write(decision: dict, status: str, error: str | None = None, order_id: str | None = None) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """
        INSERT INTO audit_log (timestamp, ticker, action, weight_pct, decision, status, error, order_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            decision.get("ticker", "UNKNOWN"),
            decision.get("action", "UNKNOWN"),
            decision.get("weight_pct", 0.0),
            json.dumps(decision),
            status,
            error,
            order_id,
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    logger.info(
        "AUDIT [%s] %s %s @ %.1f%% — status=%s order_id=%s",
        row_id, decision.get("action"), decision.get("ticker"),
        decision.get("weight_pct", 0.0), status, order_id,
    )
    return row_id


def get_recent(limit: int = 20) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, timestamp, ticker, action, weight_pct, status, error, order_id "
        "FROM audit_log ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {
            "id": r[0], "timestamp": r[1], "ticker": r[2], "action": r[3],
            "weight_pct": r[4], "status": r[5], "error": r[6], "order_id": r[7],
        }
        for r in rows
    ]
