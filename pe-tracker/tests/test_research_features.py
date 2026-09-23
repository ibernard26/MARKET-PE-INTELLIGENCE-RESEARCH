"""Stage 2 tests: point-in-time feature layer.

The load-bearing test is no-lookahead: a feature vector built as-of D must not
change when an event dated after D is added.
"""
import sqlite3
from pathlib import Path

import pytest

from src.research import events as ev
from src.research import features as ft
from src.research.observations import Observation, record_observation

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()


def mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _seed(c):
    record_observation(Observation(
        "D1", "2026-02-01T00:00:00", "sec_filing",
        offer_price=100.0, target_price=95.0, unaffected_price=80.0,
        expected_close_date="2026-08-01", deal_type="take_private",
        consideration_type="cash", deal_value_usd_mm=5000.0,
        shareholder_vote_state="required_pending",
        regulatory_attrs={"cfius": True, "antitrust": False}), conn=c)
    ev.record_event("D1", "2026-02-01", "announcement", "s", conn=c)


def test_economics_match_hand_work():
    c = mem(); _seed(c)
    f = ft.build_features_for_deal("D1", "2026-02-01", conn=c)
    assert f["raw_spread"] == pytest.approx(5.0)          # 100 - 95
    assert f["pct_spread"] == pytest.approx(5 / 95)
    assert f["downside_to_unaffected"] == pytest.approx(15.0)   # 95 - 80
    assert f["days_to_expected_close"] == 181             # Feb 1 -> Aug 1 2026
    assert f["annualized_spread"] == pytest.approx((5 / 95) * 365 / 181)
    assert f["premium_to_unaffected"] == pytest.approx((100 - 80) / 80)
    assert f["is_sponsor"] is True
    assert f["is_all_cash"] is True
    assert f["cfius_exposure"] is True
    assert f["antitrust_exposure"] is False
    assert f["shareholder_approval_required"] is True


def test_no_lookahead_future_event_does_not_change_past_features():
    c = mem(); _seed(c)
    before = ft.build_features_for_deal("D1", "2026-05-01", conn=c)
    # a DOJ challenge occurs AFTER the as-of date
    ev.record_event("D1", "2026-06-15", "doj_challenge", "s", conn=c)
    after = ft.build_features_for_deal("D1", "2026-05-01", conn=c)
    assert before == after                                  # as-of view is immutable
    # but as-of a later date the challenge is visible
    later = ft.build_features_for_deal("D1", "2026-07-01", conn=c)
    assert later["under_regulatory_challenge"] is True


def test_missing_inputs_yield_none_not_zero():
    c = mem()
    record_observation(Observation("D2", "2026-03-01T00:00:00", "s",
                                   offer_price=50.0), conn=c)   # no current/unaffected
    f = ft.build_features_for_deal("D2", "2026-03-02", conn=c)
    assert f["raw_spread"] is None
    assert f["downside_to_unaffected"] is None
    assert f["annualized_spread"] is None


def test_market_context_passes_through_only_when_supplied():
    c = mem(); _seed(c)
    f0 = ft.build_features_for_deal("D1", "2026-03-01", conn=c)
    assert f0["sp_return"] is None
    f1 = ft.build_features_for_deal("D1", "2026-03-01",
                                    market_ctx={"sp_return": 0.012, "ust10y": 4.5}, conn=c)
    assert f1["sp_return"] == 0.012 and f1["ust10y"] == 4.5
