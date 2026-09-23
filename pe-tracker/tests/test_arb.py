"""Tests for the three arbitrage engines.

Merger math is checked against a hand-worked example; crude-spread and index-RV
are checked for correct z-scores AND for the no-fabrication rule (a NaN gap must
never be filled). The merger ranker is exercised against an in-memory deals
table so it never touches the real DB.
"""
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.arb import crude_spread, index_rv, merger

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()


# ------------------------------------------------------------- merger math
def test_gross_spread_and_annualization():
    assert merger.gross_spread(100.0, 95.0) == pytest.approx(5 / 95)
    # a 90-day horizon annualizes by 365/90
    assert merger.annualize(0.05, 90) == pytest.approx(0.05 * 365 / 90)


def test_days_to_close_floored_at_one():
    assert merger.days_to_close("2026-01-10", "2026-01-01") == 9
    assert merger.days_to_close("2026-01-01", "2026-01-10") == 1  # never <= 0


def test_break_adjusted_ev_hand_worked():
    # offer 100, current 95, unaffected 80, p_break 0.10
    # upside = 5, downside = 15; EV = 0.9*5 - 0.1*15 = 4.5 - 1.5 = 3.0
    ev = merger.break_adjusted_ev(100.0, 95.0, 0.10, 80.0)
    assert ev["upside"] == 5.0
    assert ev["downside"] == 15.0
    assert ev["ev_per_share"] == pytest.approx(3.0)
    assert ev["ev_pct"] == pytest.approx(3.0 / 95.0)


def test_high_break_prob_turns_ev_negative():
    # same trade but a coin-flip break: 0.5*5 - 0.5*15 = -5 -> avoid
    ev = merger.break_adjusted_ev(100.0, 95.0, 0.50, 80.0)
    assert ev["ev_per_share"] < 0


# ------------------------------------------------------- merger DB ranker
def _deals_db(rows):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany(
        """INSERT INTO deals (deal_id, announce_date, target, acquirer, sector,
               status, p_break, offer_price, current_price, unaffected_price,
               expected_close_date)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""", rows)
    return conn


def test_ranker_scores_quoted_and_defers_unquoted():
    conn = _deals_db([
        # fully quoted, pending -> ranked
        ("A", "2026-01-01", "Tgt A", "Acq", "Tech", "pending", 0.10,
         100.0, 95.0, 80.0, "2026-04-01"),
        # pending but no quote -> awaiting_quote
        ("B", "2026-01-01", "Tgt B", "Acq", "Energy", "pending", 0.15,
         None, None, None, None),
        # closed -> excluded from a live-deal ranking entirely
        ("C", "2026-01-01", "Tgt C", "Acq", "Health", "closed", 0.20,
         50.0, 49.0, 40.0, "2026-02-01"),
    ])
    out = merger.rank_live_deals(as_of="2026-01-15", conn=conn)
    assert [d["deal_id"] for d in out["ranked"]] == ["A"]
    assert [d["deal_id"] for d in out["awaiting_quote"]] == ["B"]


def test_ranker_orders_by_break_adjusted_ev():
    conn = _deals_db([
        ("LOW", "2026-01-01", "L", "Acq", "X", "pending", 0.45,
         100.0, 96.0, 70.0, "2026-06-01"),   # high break prob, thin cushion
        ("HIGH", "2026-01-01", "H", "Acq", "X", "pending", 0.05,
         100.0, 96.0, 90.0, "2026-06-01"),   # low break prob, small downside
    ])
    out = merger.rank_live_deals(as_of="2026-01-15", conn=conn)
    assert [d["deal_id"] for d in out["ranked"]] == ["HIGH", "LOW"]


# ------------------------------------------------------------- crude spread
def _frame(dates, wti, brent):
    df = pd.DataFrame({"date": pd.to_datetime(dates), "wti": wti, "brent": brent})
    df["spread"] = df["brent"] - df["wti"]
    return df


def test_crude_gap_is_not_filled():
    df = _frame(["2026-04-20", "2026-04-21", "2026-04-22"],
                [80.0, None, 82.0], [83.0, 84.0, None])
    # a missing leg -> NaN spread, never forward-filled
    assert pd.isna(df["spread"].iloc[1])   # WTI missing
    assert pd.isna(df["spread"].iloc[2])   # Brent missing
    assert df["spread"].iloc[0] == pytest.approx(3.0)


def test_crude_zscore_and_entry_flags():
    # 21 flat spreads then one spike; z-score on window 20 flags the spike
    dates = pd.bdate_range("2026-01-01", periods=22)
    wti = [80.0] * 22
    brent = [83.0] * 21 + [95.0]            # last day: spread jumps 3 -> 15
    df = _frame(dates, wti, brent)
    out = crude_spread.entry_signal(crude_spread.add_zscore(df, window=20), band=2.0)
    assert out["signal"].iloc[-1] == "SHORT_SPREAD"   # spread unusually wide
    assert out["zscore"].iloc[-1] > 2.0
    # early rows without a full window emit no signal
    assert out["signal"].iloc[0] == "NO_DATA"


# ------------------------------------------------------------- index RV
def test_index_ratio_zscore_is_baseline_labeled():
    dates = pd.bdate_range("2026-01-01", periods=22)
    df = pd.DataFrame({"date": pd.to_datetime(dates),
                       "sp500": [7000.0] * 22,
                       "nasdaq": [26000.0] * 21 + [24000.0]})
    df["ratio"] = df["sp500"] / df["nasdaq"]
    out = index_rv.add_zscore(df, window=20)
    assert out["zscore"].iloc[-1] > 2.0      # ratio jumps when nasdaq drops
    assert pd.isna(out["zscore"].iloc[0])    # no full window yet
