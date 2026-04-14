"""Semantic memory — SQLite store for distilled trading rules by domain."""

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / "semantic_memory.db"

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("""
            CREATE TABLE IF NOT EXISTS rules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                domain      TEXT    NOT NULL,
                rule        TEXT    NOT NULL,
                confidence  REAL    NOT NULL,
                n_trades    INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL
            )
        """)
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_rules_domain ON rules(domain)")
        _conn.commit()
    return _conn


def get_rules(domain: str) -> list[dict]:
    """Fetch all rules for a domain, ordered by confidence descending."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, domain, rule, confidence, n_trades, created_at "
        "FROM rules WHERE domain = ? ORDER BY confidence DESC",
        (domain,),
    ).fetchall()
    return [
        {
            "id": r[0], "domain": r[1], "rule": r[2],
            "confidence": r[3], "n_trades": r[4], "created_at": r[5],
        }
        for r in rows
    ]


def write_rules(domain: str, rules: list[dict]) -> int:
    """Replace all rules for a domain with new ones.

    Args:
        domain: e.g. "pharma", "tech", "energy", "macro"
        rules: list of dicts with keys: rule, confidence, n_trades

    Returns:
        Number of rules written.
    """
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()

    # Delete old rules for this domain
    conn.execute("DELETE FROM rules WHERE domain = ?", (domain,))

    # Insert new rules
    for r in rules:
        conn.execute(
            "INSERT INTO rules (domain, rule, confidence, n_trades, created_at) VALUES (?, ?, ?, ?, ?)",
            (domain, r["rule"], r.get("confidence", 0.5), r.get("n_trades", 0), now),
        )

    conn.commit()
    logger.info("Semantic: wrote %d rules for domain '%s'", len(rules), domain)
    return len(rules)


def get_all_rules() -> list[dict]:
    """Fetch all rules across all domains."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, domain, rule, confidence, n_trades, created_at "
        "FROM rules ORDER BY domain, confidence DESC",
    ).fetchall()
    return [
        {
            "id": r[0], "domain": r[1], "rule": r[2],
            "confidence": r[3], "n_trades": r[4], "created_at": r[5],
        }
        for r in rows
    ]


def get_domains() -> list[str]:
    """List all domains that have rules."""
    conn = _get_conn()
    rows = conn.execute("SELECT DISTINCT domain FROM rules").fetchall()
    return [r[0] for r in rows]
