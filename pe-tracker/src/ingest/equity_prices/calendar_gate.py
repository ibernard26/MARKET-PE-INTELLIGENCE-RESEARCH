"""Session-date gate for equity closes.

Reject weekends always. When market_calendar is populated, also reject
non-trading holidays. Never invent a price on a non-session date.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def is_valid_session(session_date: str,
                     conn: Optional[sqlite3.Connection] = None) -> bool:
    """True iff `session_date` (YYYY-MM-DD) is an admissible trading session."""
    d = date.fromisoformat(session_date[:10])
    if is_weekend(d):
        return False
    if conn is None:
        return True  # weekend-only gate when calendar not available
    row = conn.execute(
        "SELECT is_trading FROM market_calendar WHERE obs_date = ?",
        (d.isoformat(),),
    ).fetchone()
    if row is None:
        # Calendar not built for this date — fall back to weekend-only.
        return True
    return bool(row[0] if not hasattr(row, "keys") else row["is_trading"])


def filter_session_observations(observations: list, conn=None) -> tuple[list, list]:
    """Split into (accepted, rejected_non_session)."""
    ok, bad = [], []
    for o in observations:
        sd = o.session_date if hasattr(o, "session_date") else o["session_date"]
        if is_valid_session(sd, conn=conn):
            ok.append(o)
        else:
            bad.append(o)
    return ok, bad
