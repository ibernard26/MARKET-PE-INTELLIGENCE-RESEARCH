"""Rule-based NYSE session calendar (2010–2030) for spread_stress_v2.

The v2 snapshot grid is defined on exchange sessions, not on the dates a price
provider happens to return, so a missing print never shifts the grid. Rules are
the NYSE full-day closure rules plus documented special closures. Half-days are
sessions.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

FIRST_YEAR, LAST_YEAR = 2010, 2030

# Unscheduled full-day closures (not derivable from the holiday rules).
SPECIAL_CLOSURES = frozenset({
    date(2012, 10, 29), date(2012, 10, 30),   # Hurricane Sandy
    date(2018, 12, 5),                        # President G.H.W. Bush funeral
    date(2025, 1, 9),                         # President Carter funeral
})


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(d: date, saturday_to_friday: bool = True) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1) if saturday_to_friday else None
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def nyse_holidays(year: int) -> frozenset[date]:
    if not FIRST_YEAR <= year <= LAST_YEAR:
        raise ValueError(f"calendar covers {FIRST_YEAR}-{LAST_YEAR}, got {year}")
    days = {
        # NYSE does not close the preceding Friday when Jan 1 is a Saturday.
        _observed(date(year, 1, 1), saturday_to_friday=False),
        _nth_weekday(year, 1, 0, 3),            # MLK Day
        _nth_weekday(year, 2, 0, 3),            # Washington's Birthday
        _easter(year) - timedelta(days=2),      # Good Friday
        _last_weekday(year, 5, 0),              # Memorial Day
        _observed(date(year, 7, 4)),            # Independence Day
        _nth_weekday(year, 9, 0, 1),            # Labor Day
        _nth_weekday(year, 11, 3, 4),           # Thanksgiving
        _observed(date(year, 12, 25)),          # Christmas
    }
    if year >= 2022:
        days.add(_observed(date(year, 6, 19)))  # Juneteenth
    days.discard(None)
    return frozenset(days) | {d for d in SPECIAL_CLOSURES if d.year == year}


def is_session(d: date) -> bool:
    return d.weekday() < 5 and d not in nyse_holidays(d.year)


def next_session_after(d: date) -> date:
    """First session strictly after calendar date d."""
    x = d + timedelta(days=1)
    while not is_session(x):
        x += timedelta(days=1)
    return x


def session_on_or_after(d: date) -> date:
    return d if is_session(d) else next_session_after(d)


def previous_session(d: date) -> date:
    x = d - timedelta(days=1)
    while not is_session(x):
        x -= timedelta(days=1)
    return x


def add_sessions(start: date, n: int) -> date:
    """The session n sessions after `start` (a session). n=0 returns start."""
    if not is_session(start):
        raise ValueError(f"{start} is not a session")
    x = start
    for _ in range(n):
        x = next_session_after(x)
    return x
