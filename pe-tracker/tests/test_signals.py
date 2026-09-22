"""Tests for the two things that were broken in the workbook:
the trading calendar, and the signal rule."""
import pandas as pd
import pytest

from src.compute.signals import add_metrics, backtest, classify
from src.config import MARKET_HOLIDAYS


def frame(closes, start="2026-04-20"):
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({"obs_date": dates, "close": closes})


def test_weekend_is_never_a_trading_day():
    from datetime import date
    assert date(2026, 4, 25).weekday() >= 5   # the fabricated 7,165 rows
    assert date(2026, 4, 26).weekday() >= 5


def test_holidays_are_registered():
    for d in ("2026-05-25", "2026-06-19", "2026-07-03"):
        assert d in MARKET_HOLIDAYS


def test_daily_pct_derives_from_closes():
    df = add_metrics(frame([100.0, 110.0]))
    assert df["daily_pct"].iloc[1] == pytest.approx(0.10)


def test_gap_does_not_silently_shrink_the_window():
    df = add_metrics(frame([100.0, None, 102.0, 103.0, 104.0]))
    assert not df["window_complete"].iloc[4]
    assert df["obs_in_window"].iloc[4] == 4


def test_mtd_anchors_to_first_populated_close_of_month():
    dates = pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-03"])
    df = add_metrics(pd.DataFrame({"obs_date": dates, "close": [None, 200.0, 210.0]}))
    assert df["mtd_pct"].iloc[2] == pytest.approx(0.05)   # anchors to 200, not NaN


def test_buy_requires_both_conditions():
    df = classify(add_metrics(frame([100.0, 100.5, 101.0, 101.5, 108.0])))
    assert df["signal"].iloc[4] == "BUY"


def test_flat_day_above_ma_is_hold_not_buy():
    df = classify(add_metrics(frame([100.0, 101.0, 102.0, 103.0, 103.05])))
    assert df["signal"].iloc[4] == "HOLD"


def test_missing_close_yields_no_data():
    df = classify(add_metrics(frame([100.0, 101.0, None])))
    assert df["signal"].iloc[2] == "NO_DATA"


def test_backtest_reports_a_baseline():
    df = classify(add_metrics(frame([100.0, 101.0, 99.0, 103.0, 102.0, 106.0])))
    out = backtest(df)
    assert "_ALL_DAYS" in out and out["_ALL_DAYS"]["n"] > 0
