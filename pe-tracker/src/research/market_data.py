"""Point-in-time reads of the canonical FRED store, and derived market features.

    FRED -> market_observations (valid time, known_at, provenance)
         -> series_as_of(T)            the series exactly as knowable at T
         -> derived features            returns, levels, changes, spreads
         -> PointInTimeMarketContext    what build_features consumes

Every value returned carries series_id, obs_date (valid time), source,
known_at and ingestion_timestamp. Missing observations stay missing: a return
needs two real prints and is None otherwise — nothing is forward-filled.

These features are RESEARCH functions. They are not part of the active break
model (feature schema fs_v1); adding any of them requires a new
feature_schema_version.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from .bitemporal import normalize_as_of
from .market_context import (MARKET_FIELDS, MarketDataOverwriteError,
                             PointInTimeMarketContext)

SP500, NASDAQ, WTI, BRENT, UST10Y = "SP500", "NASDAQCOM", "DCOILWTICO", "DCOILBRENTEU", "DGS10"


def valid_ts(obs_date: str) -> str:
    """A daily close is only complete at the end of its day (conservative)."""
    return normalize_as_of(obs_date[:10])


def series_as_of(conn: sqlite3.Connection, series_id: str, as_of: str) -> list[dict]:
    """Series as knowable at `as_of`: for each obs_date <= T, the latest vintage
    with known_at <= T. Rows whose value is NULL are kept (value None)."""
    t = normalize_as_of(as_of)
    rows = conn.execute(
        """SELECT m.* FROM market_observations m
           WHERE m.series_id = ? AND m.obs_date <= ? AND m.known_at <= ?
             AND m.known_at = (SELECT MAX(k.known_at) FROM market_observations k
                               WHERE k.series_id = m.series_id AND k.obs_date = m.obs_date
                                 AND k.known_at <= ?)
           ORDER BY m.obs_date""", (series_id, t[:10], t, t)).fetchall()
    return [dict(r) for r in rows]


def _last_two(points: list[dict]) -> tuple[Optional[dict], Optional[dict]]:
    """The two most recent NON-NULL prints (a NULL is a gap, not a zero)."""
    real = [p for p in points if p["value"] is not None]
    if len(real) < 2:
        return (real[-1] if real else None), None
    return real[-1], real[-2]


def _meta(*pts) -> dict:
    return {"series_id": pts[0]["series_id"],
            "obs_dates": [p["obs_date"] for p in pts],
            "source": pts[0]["source"],
            "known_at": max(p["known_at"] for p in pts),
            "ingestion_timestamp": max(p["ingestion_timestamp"] for p in pts)}


def level(conn, series_id: str, as_of: str) -> Optional[dict]:
    last, _ = _last_two(series_as_of(conn, series_id, as_of))
    return {"value": last["value"], **_meta(last)} if last else None


def simple_return(conn, series_id: str, as_of: str) -> Optional[dict]:
    """(P_t / P_{t-1}) - 1 between the two latest real prints knowable at T."""
    last, prev = _last_two(series_as_of(conn, series_id, as_of))
    if last is None or prev is None or not prev["value"]:
        return None
    return {"value": last["value"] / prev["value"] - 1.0, **_meta(last, prev)}


def change(conn, series_id: str, as_of: str) -> Optional[dict]:
    """Level change between the two latest real prints (e.g. 10Y in pct points)."""
    last, prev = _last_two(series_as_of(conn, series_id, as_of))
    if last is None or prev is None:
        return None
    return {"value": last["value"] - prev["value"], **_meta(last, prev)}


def brent_wti_spread(conn, as_of: str) -> Optional[dict]:
    """Brent − WTI on the latest date where BOTH legs have a real print."""
    b = {p["obs_date"]: p for p in series_as_of(conn, BRENT, as_of) if p["value"] is not None}
    w = {p["obs_date"]: p for p in series_as_of(conn, WTI, as_of) if p["value"] is not None}
    common = sorted(set(b) & set(w))
    if not common:
        return None
    d = common[-1]
    m = _meta(b[d], w[d])
    m["series_id"] = f"{BRENT}-{WTI}"
    return {"value": b[d]["value"] - w[d]["value"], **m}


# Research feature catalogue (NOT in fs_v1).
RESEARCH_FEATURES = {
    "sp_return": lambda c, t: simple_return(c, SP500, t),
    "nasdaq_return": lambda c, t: simple_return(c, NASDAQ, t),
    "wti_return": lambda c, t: simple_return(c, WTI, t),
    "brent_return": lambda c, t: simple_return(c, BRENT, t),
    "brent_wti_spread": lambda c, t: brent_wti_spread(c, t),
    "ust10y": lambda c, t: level(c, UST10Y, t),
    "ust10y_change": lambda c, t: change(c, UST10Y, t),
}


def research_features(conn, as_of: str) -> dict:
    """All research market features knowable at `as_of`, each with provenance."""
    return {k: fn(conn, as_of) for k, fn in RESEARCH_FEATURES.items()}


def market_context_from_store(conn, as_of_dates: list[str],
                              max_age_days: float = 3.0) -> PointInTimeMarketContext:
    """Populate a PointInTimeMarketContext from the canonical store.

    For each requested as-of, the derived value is recorded with
    timestamp = end of its latest obs_date (valid time) and known_at = the max
    known_at of the prints it uses. Values are never pulled from raw API
    responses — only from market_observations.
    """
    ctx = PointInTimeMarketContext(max_age_days=max_age_days)
    for t in sorted(as_of_dates, key=normalize_as_of):
        for field in MARKET_FIELDS:
            v = RESEARCH_FEATURES[field](conn, t)
            if v is None:
                continue
            try:
                ctx.add(field, valid_ts(v["obs_dates"][0]), v["value"],
                        f"{v['source']}:{v['series_id']}", known_at=v["known_at"])
            except MarketDataOverwriteError:
                # same field/valid time already recorded from an earlier as-of:
                # the first-knowable value is kept (a later revision is never
                # back-dated into an earlier view)
                pass
    return ctx
