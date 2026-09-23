"""Crude relative-value: the Brent - WTI spread.

The one genuinely data-backed arbitrage here — both legs come straight from the
FRED prices already in the store (DCOILBRENTEU, DCOILWTICO). We measure how far
today's spread sits from its own recent history (a rolling z-score) and flag
mean-reversion entries when it stretches past a band.

Invariant discipline: a day missing either leg produces a NaN spread and is
never forward-filled or interpolated (Invariant: a gap stays a gap). The
z-score is computed only on real observations.
"""
import numpy as np
import pandas as pd

from ..db import connect

WTI = "DCOILWTICO"
BRENT = "DCOILBRENTEU"


def load_spread() -> pd.DataFrame:
    """Trading-day spread series from the store: columns date, wti, brent, spread.

    Only session dates appear (calendar-gated by the join). Where either leg is
    missing, spread is NaN — not filled.
    """
    sql = """
        SELECT c.obs_date AS date,
               w.close     AS wti,
               b.close     AS brent
        FROM market_calendar c
        LEFT JOIN prices w ON w.series_id = ? AND w.obs_date = c.obs_date
        LEFT JOIN prices b ON b.series_id = ? AND b.obs_date = c.obs_date
        WHERE c.is_trading = 1
        ORDER BY c.obs_date
    """
    with connect() as conn:
        df = pd.read_sql_query(sql, conn, params=(WTI, BRENT))
    df["date"] = pd.to_datetime(df["date"])
    df["spread"] = df["brent"] - df["wti"]   # NaN wherever a leg is missing
    return df


def add_zscore(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Rolling mean/σ z-score of the spread, plus a POINT-IN-TIME percentile.

    min_periods == window: no z-score is emitted until a full window of real
    observations exists, so a thin early window is never mistaken for signal.
    NaN spreads are excluded from the rolling stats rather than filled.
    (z-score semantics are unchanged: a trailing window is already point-in-time.)

    pctile (changed): previously `s.rank(pct=True)` ranked each day against the
    WHOLE sample, so the value at t depended on spreads after t (lookahead). It is
    now the expanding percentile: share of real spreads observed on/before t
    that are <= the spread at t. It uses no future data, so appending later
    observations can never change a past value.
    """
    df = df.copy()
    s = df["spread"]
    roll = s.rolling(window, min_periods=window)
    df["spread_mean"] = roll.mean()
    df["spread_std"] = roll.std()
    df["zscore"] = (s - df["spread_mean"]) / df["spread_std"]
    df["pctile"] = expanding_pctile(s)
    return df


def expanding_pctile(s: pd.Series) -> pd.Series:
    """Percentile of s[t] among the non-NaN values of s[0..t] (inclusive).
    NaN where s[t] is NaN. Depends only on data up to t."""
    vals = s.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    seen: list[float] = []
    for i, v in enumerate(vals):
        if np.isnan(v):
            continue
        seen.append(v)
        out[i] = np.mean(np.asarray(seen) <= v)
    return pd.Series(out, index=s.index)


def entry_signal(df: pd.DataFrame, band: float = 2.0) -> pd.DataFrame:
    """Mean-reversion flag from the z-score.

    z < -band  -> LONG_SPREAD  (spread unusually tight; expect it to widen)
    z > +band  -> SHORT_SPREAD (spread unusually wide; expect it to narrow)
    otherwise  -> FLAT ; NaN z-score -> NO_DATA
    """
    df = df.copy()

    def flag(z):
        if pd.isna(z):
            return "NO_DATA"
        if z <= -band:
            return "LONG_SPREAD"
        if z >= band:
            return "SHORT_SPREAD"
        return "FLAT"

    df["signal"] = df["zscore"].map(flag)
    return df


def run(window: int = 20, band: float = 2.0) -> pd.DataFrame:
    """Full crude-spread view: spread, z-score, percentile, entry signal."""
    return entry_signal(add_zscore(load_spread(), window=window), band=band)


def latest(window: int = 20, band: float = 2.0) -> dict:
    """The most recent day that has a computable spread, as a summary dict."""
    df = run(window=window, band=band).dropna(subset=["spread"])
    if df.empty:
        return {"status": "no_data", "note": "no day has both WTI and Brent yet"}
    row = df.iloc[-1]
    return {
        "date": row["date"].strftime("%Y-%m-%d"),
        "wti": float(row["wti"]),
        "brent": float(row["brent"]),
        "spread": round(float(row["spread"]), 2),
        "zscore": None if pd.isna(row["zscore"]) else round(float(row["zscore"]), 2),
        "pctile": None if pd.isna(row["pctile"]) else round(float(row["pctile"]), 3),
        "signal": row["signal"],
    }
