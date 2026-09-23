"""Crude-spread percentile must be point-in-time (no lookahead)."""
import numpy as np
import pandas as pd

from src.arb import crude_spread


def _df(spreads):
    return pd.DataFrame({"date": pd.date_range("2026-01-01", periods=len(spreads)),
                         "spread": spreads})


def test_appending_future_data_does_not_change_past_signal():
    base = [4.0, 5.0, np.nan, 3.0, 6.0, 4.5] * 5
    before = crude_spread.add_zscore(_df(base), window=5)
    after = crude_spread.add_zscore(_df(base + [100.0, -50.0, 7.0]), window=5)
    for col in ("pctile", "zscore", "spread_mean", "spread_std"):
        pd.testing.assert_series_equal(before[col], after[col].iloc[:len(base)],
                                       check_names=False)


def test_expanding_pctile_hand_values_and_nan_gap():
    p = crude_spread.expanding_pctile(pd.Series([2.0, 1.0, np.nan, 3.0, 2.0]))
    assert p[0] == 1.0 and p[1] == 0.5 and np.isnan(p[2])
    assert p[3] == 1.0 and p[4] == 0.75          # 2.0 among {2,1,3,2}: 3/4 <= 2
