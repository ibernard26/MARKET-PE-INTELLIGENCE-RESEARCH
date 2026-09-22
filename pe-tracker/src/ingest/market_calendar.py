"""NYSE trading calendar.

The calendar GATES ingestion: a non-session date can never receive a price.
Weekends and the holidays in config.MARKET_HOLIDAYS are marked is_trading = 0
with a reason; every other weekday is a session. Half-days are still sessions
and are intentionally not listed as holidays.
"""
from datetime import date, timedelta

from ..config import MARKET_HOLIDAYS
from ..db import connect


def _iter_days(start: str, end: str):
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    d = d0
    while d <= d1:
        yield d
        d += timedelta(days=1)


def build_calendar(start: str, end: str) -> int:
    """Populate market_calendar for [start, end]. Idempotent. Returns the
    number of trading days written in the range."""
    rows = []
    trading = 0
    for d in _iter_days(start, end):
        iso = d.isoformat()
        if d.weekday() >= 5:
            rows.append((iso, 0, "weekend"))
        elif iso in MARKET_HOLIDAYS:
            rows.append((iso, 0, MARKET_HOLIDAYS[iso]))
        else:
            rows.append((iso, 1, None))
            trading += 1
    with connect() as conn:
        conn.executemany(
            """INSERT INTO market_calendar (obs_date, is_trading, reason)
               VALUES (?,?,?)
               ON CONFLICT(obs_date) DO UPDATE SET
                   is_trading = excluded.is_trading,
                   reason     = excluded.reason""",
            rows,
        )
    return trading


def is_trading_day(obs_date: str) -> bool:
    with connect() as conn:
        r = conn.execute(
            "SELECT is_trading FROM market_calendar WHERE obs_date = ?",
            (obs_date,)).fetchone()
    return bool(r and r["is_trading"])
