"""Sweep tests: grid shape, the thin-sample flag, and reuse of the
production classifier (a sweep cell at the default thresholds must agree
with the ma5_v1 backtest)."""
import pandas as pd
import pytest

from src.compute.signals import add_metrics, backtest, classify
from src.compute.sweep import sweep


def frame(closes, start="2026-04-20"):
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"obs_date": dates, "close": closes})


def rising(n=30):
    return frame([100 + i + (3 if i % 5 == 0 else 0) for i in range(n)])


def test_grid_has_one_row_per_combo_and_signal():
    df = sweep(base_df=rising(), buy_grid=(0.0, 0.005), sell_grid=(0.0,),
               window_grid=(3, 5))
    assert len(df) == 2 * 1 * 2 * 2   # buy x sell x window x {BUY,SELL}


def test_thin_flag_marks_small_samples():
    df = sweep(base_df=rising(10), window_grid=(5,), min_n=20)
    assert df["thin"].all()           # 10 days can never reach n=20


def test_default_cell_matches_production_backtest():
    data = rising(40)
    cell = sweep(base_df=data, buy_grid=(0.0025,), sell_grid=(-0.0025,),
                 window_grid=(5,))
    prod = backtest(classify(add_metrics(data)))
    buy_row = cell[cell["signal"] == "BUY"].iloc[0]
    assert buy_row["n"] == prod["BUY"]["n"]
    assert buy_row["mean_fwd_1d"] == pytest.approx(prod["BUY"]["mean_fwd_1d"])
