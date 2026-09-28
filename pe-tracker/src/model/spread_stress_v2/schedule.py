"""Ex-ante snapshot schedule for spread_stress_v2.

The schedule is a function of the announcement timestamp and the frozen grid
parameters ONLY. It deliberately takes no resolution date, outcome, or price
data, so feature times cannot depend on when (or how) a deal resolved or on
which days a provider returned prices.
"""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .calendar import add_sessions, is_session, next_session_after

NY = ZoneInfo("America/New_York")
MARKET_CLOSE = time(16, 0)


def time_precision(ts: str | None) -> str:
    text = (ts or "").strip()
    if not text:
        return "MISSING"
    return "DATE_ONLY" if len(text) == 10 else "INTRADAY"


def first_eligible_session(announcement_ts: str) -> date:
    """S0: the first session whose close is provably after the announcement.

    DATE_ONLY: the first session strictly after the announcement calendar date
    (the announcement-date close is never used: it cannot be ordered against a
    date-only event). INTRADAY: the announcement session itself only if the
    announcement instant is before that session's 16:00 America/New_York close;
    otherwise the next session.
    """
    prec = time_precision(announcement_ts)
    if prec == "MISSING":
        raise ValueError("announcement timestamp required")
    d = date.fromisoformat(announcement_ts[:10])
    if prec == "DATE_ONLY":
        return next_session_after(d)
    inst = datetime.fromisoformat(announcement_ts.replace("Z", "+00:00"))
    if inst.tzinfo is None:
        raise ValueError("intraday announcement timestamps must carry a UTC offset")
    local = inst.astimezone(NY)
    if is_session(local.date()) and local.time() < MARKET_CLOSE:
        return local.date()
    return next_session_after(local.date())


def snapshot_schedule(announcement_ts: str, first_offset: int, step: int,
                      max_snapshots: int) -> list[date]:
    """Deterministic grid S0+first_offset, S0+first_offset+step, … (sessions)."""
    s0 = first_eligible_session(announcement_ts)
    return [add_sessions(s0, first_offset + k * step) for k in range(max_snapshots)]
