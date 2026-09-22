"""Derived metrics and the trading signal.

Nothing here is persisted except the signal itself, and the signal is tagged
with the ruleset that produced it -- so changing a threshold creates a new
version rather than silently rewriting history.
"""
import pandas as pd

from ..config import BUY_THRESHOLD, MA_WINDOW, RULESET, SELL_THRESHOLD
from ..db import connect


def load_series(series_id: str) -> pd.DataFrame:
    """Trading days only, ascending, with NULL closes preserved as NaN."""
    sql = """
        SELECT c.obs_date, p.close, p.provenance
        FROM market_calendar c
        LEFT JOIN prices p
               ON p.series_id = ? AND p.obs_date = c.obs_date
        WHERE c.is_trading = 1
        ORDER BY c.obs_date
    """
    with connect() as conn:
        df = pd.read_sql_query(sql, conn, params=(series_id,))
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    return df


def add_metrics(df: pd.DataFrame, ma_window: int = MA_WINDOW) -> pd.DataFrame:
    """Δ%, moving average, window completeness, and month-to-date return.

    min_periods=1 means an MA is emitted even across a gap; obs_in_window
    reports how many real observations backed it so a thin MA is never
    mistaken for a full one.
    """
    df = df.copy()
    df["daily_pct"] = df["close"].pct_change()
    df["ma"] = df["close"].rolling(ma_window, min_periods=1).mean()
    df["obs_in_window"] = df["close"].rolling(ma_window, min_periods=1).count()
    df["window_complete"] = df["obs_in_window"] >= ma_window

    month = df["obs_date"].dt.to_period("M")
    baseline = df.groupby(month)["close"].transform(lambda s: s.dropna().iloc[0]
                                                    if s.notna().any() else pd.NA)
    df["mtd_pct"] = df["close"] / pd.to_numeric(baseline, errors="coerce") - 1
    return df


def classify(df: pd.DataFrame, buy=BUY_THRESHOLD, sell=SELL_THRESHOLD) -> pd.DataFrame:
    """BUY / SELL / HOLD / NO_DATA. Same rule as the Phase 0 workbook."""
    df = df.copy()
    have = df["close"].notna() & df["ma"].notna() & df["daily_pct"].notna()
    is_buy = have & (df["close"] > df["ma"]) & (df["daily_pct"] > buy)
    is_sell = have & (df["close"] < df["ma"]) & (df["daily_pct"] < sell)

    df["signal"] = "NO_DATA"
    df.loc[have, "signal"] = "HOLD"
    df.loc[is_buy, "signal"] = "BUY"
    df.loc[is_sell, "signal"] = "SELL"
    return df


def persist(df: pd.DataFrame, series_id: str, ruleset: str = RULESET) -> int:
    rows = [(series_id, d.strftime("%Y-%m-%d"), ruleset, s)
            for d, s in zip(df["obs_date"], df["signal"])]
    with connect() as conn:
        conn.executemany(
            """INSERT INTO signals (series_id, obs_date, ruleset, signal)
               VALUES (?,?,?,?)
               ON CONFLICT(series_id, obs_date, ruleset) DO UPDATE SET
                   signal = excluded.signal, computed_at = datetime('now')""",
            rows,
        )
    return len(rows)


def run(series_id: str = "SP500", persist_result: bool = True) -> pd.DataFrame:
    df = classify(add_metrics(load_series(series_id)))
    if persist_result:
        persist(df, series_id)
    return df


def backtest(df: pd.DataFrame) -> dict:
    """Forward one-day return following each signal.

    This is the whole reason the rule had to be written down. A signal that
    does not beat HOLD is not a signal -- it is a habit.
    """
    df = df.copy()
    df["fwd_1d"] = df["close"].pct_change().shift(-1)
    out = {}
    for label, grp in df.groupby("signal"):
        r = grp["fwd_1d"].dropna()
        out[label] = {
            "n": int(len(r)),
            "mean_fwd_1d": float(r.mean()) if len(r) else None,
            "hit_rate": float((r > 0).mean()) if len(r) else None,
        }
    base = df["fwd_1d"].dropna()
    out["_ALL_DAYS"] = {
        "n": int(len(base)),
        "mean_fwd_1d": float(base.mean()) if len(base) else None,
        "hit_rate": float((base > 0).mean()) if len(base) else None,
    }
    return out
