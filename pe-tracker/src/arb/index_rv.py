"""Index relative value: the S&P 500 / NASDAQ Composite ratio.

A deliberately weak baseline, not a live trade signal. It tracks how the ratio
of the two equity indices sits versus its own recent history (rolling z-score).
Its job is to be the thing a real signal must beat — the same role ma5_v1 plays
for the deal-break model. Both legs are real FRED series from the store; a day
missing either leg yields a NaN ratio and is never filled.
"""
import pandas as pd

from ..db import connect

SP500 = "SP500"
NASDAQ = "NASDAQCOM"


def load_ratio() -> pd.DataFrame:
    """Trading-day ratio series: columns date, sp500, nasdaq, ratio (NaN on gaps)."""
    sql = """
        SELECT c.obs_date AS date,
               s.close     AS sp500,
               n.close     AS nasdaq
        FROM market_calendar c
        LEFT JOIN prices s ON s.series_id = ? AND s.obs_date = c.obs_date
        LEFT JOIN prices n ON n.series_id = ? AND n.obs_date = c.obs_date
        WHERE c.is_trading = 1
        ORDER BY c.obs_date
    """
    with connect() as conn:
        df = pd.read_sql_query(sql, conn, params=(SP500, NASDAQ))
    df["date"] = pd.to_datetime(df["date"])
    df["ratio"] = df["sp500"] / df["nasdaq"]   # NaN where either leg missing
    return df


def add_zscore(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Rolling z-score of the ratio; no output until a full real window exists."""
    df = df.copy()
    roll = df["ratio"].rolling(window, min_periods=window)
    df["ratio_mean"] = roll.mean()
    df["ratio_std"] = roll.std()
    df["zscore"] = (df["ratio"] - df["ratio_mean"]) / df["ratio_std"]
    return df


def run(window: int = 20) -> pd.DataFrame:
    """Full ratio view. Labeled a baseline — read the note before trusting it."""
    out = add_zscore(load_ratio(), window=window)
    out.attrs["note"] = ("BASELINE ONLY — index relative value has no established "
                         "edge; it exists to be beaten, not traded.")
    return out
