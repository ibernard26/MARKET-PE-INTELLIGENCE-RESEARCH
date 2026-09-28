"""spread_stress_v2: frozen session-grid policy, PIT rules, grouping, gates.

Offline only. No model is fit anywhere in these tests.
"""
from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path

import pytest

import src.config as config
from src.model.spread_stress_v2 import (
    SplitLeakError, annual_cutoffs, authorize_execution, build_panel, label_for,
    resolution_eligible, snapshot_schedule, walk_forward)
from src.model.spread_stress_v2 import gates as G
from src.model.spread_stress_v2.calendar import (
    add_sessions, is_session, next_session_after, nyse_holidays)
from src.model.spread_stress_v2.schedule import first_eligible_session
from src.model.spread_stress_v2.spec import (
    POLICY_PATH, SPEC_PATH, SpecNotFrozenError, assert_frozen, load_policy)
from src.model.spread_stress_v2.splits import assert_disjoint

ROOT = Path(__file__).resolve().parents[1]
POLICY = load_policy()


# ------------------------------------------------------------------ calendar
def test_calendar_matches_repo_2026_holidays():
    assert {d.isoformat() for d in nyse_holidays(2026)} == set(config.MARKET_HOLIDAYS)


@pytest.mark.parametrize("d,session", [
    ("2018-12-05", False),   # Bush funeral
    ("2021-12-24", False),   # Christmas observed (Fri)
    ("2021-12-31", True),    # Jan 1 2022 is Saturday: no Friday closure
    ("2022-06-20", False),   # Juneteenth observed
    ("2021-06-18", True),    # before Juneteenth existed
    ("2022-04-15", False),   # Good Friday
    ("2022-01-17", False),   # MLK
])
def test_calendar_known_days(d, session):
    assert is_session(date.fromisoformat(d)) is session


# ------------------------------------------------------------------ schedule
def test_date_only_announcement_skips_announcement_day_close():
    # Fri 2022-01-14 announcement; Mon 01-17 is MLK -> S0 = Tue 01-18
    assert first_eligible_session("2022-01-14") == date(2022, 1, 18)
    assert first_eligible_session("2022-01-18") == date(2022, 1, 19)


@pytest.mark.parametrize("ts,s0", [
    ("2022-01-18T14:00:00-05:00", date(2022, 1, 18)),   # before the close: same session
    ("2022-01-18T16:30:00-05:00", date(2022, 1, 19)),   # after the close: next
    ("2022-01-17T10:00:00-05:00", date(2022, 1, 18)),   # holiday: next session
])
def test_intraday_announcement_policy(ts, s0):
    assert first_eligible_session(ts) == s0


def test_intraday_without_offset_is_rejected():
    with pytest.raises(ValueError):
        first_eligible_session("2022-01-18T14:00:00")


def test_schedule_is_deterministic_and_has_no_resolution_input():
    params = set(inspect.signature(snapshot_schedule).parameters)
    assert params == {"announcement_ts", "first_offset", "step", "max_snapshots"}
    g = POLICY["snapshot_grid"]
    a = snapshot_schedule("2022-01-14", g["first_offset"], g["step"], g["max_snapshots"])
    b = snapshot_schedule("2022-01-14", g["first_offset"], g["step"], g["max_snapshots"])
    assert a == b and len(a) == 12
    assert a[0] == add_sessions(date(2022, 1, 18), 10)
    assert all(is_session(d) for d in a)


# ---------------------------------------------------------------- fixtures
def _deal(**kw):
    d = {"deal_id": "DEAL-ACME-BIG-2022", "announcement_timestamp": "2022-01-14",
         "resolution_timestamp": "2022-12-30", "resolution_type": "closed",
         "consideration_type": "cash", "offer_price": 50.0}
    d.update(kw)
    return d


def _prints(deal, start="2022-01-14", n=260, price=48.0, skip=()):
    out, d = [], date.fromisoformat(start)
    for i in range(n):
        d = next_session_after(d)
        if d.isoformat() in skip:
            continue
        out.append({"deal_id": deal["deal_id"], "session_date": d.isoformat(),
                    "target_price": price + 0.01 * (i % 7), "close_field_used": "close"})
    return out


def _panel(deals, prints):
    return build_panel(deals, prints, {d["deal_id"] for d in deals}, POLICY)


# ----------------------------------------------------------------- PIT rules
def test_resolution_only_excludes_never_selects():
    a = _deal()
    grid_closed = [s["snapshot"] for s in _panel([a], _prints(a))["deals"][0]["snapshots"]]
    b = _deal(resolution_type="terminated", resolution_timestamp="2022-03-01")
    grid_broken = [s["snapshot"] for s in _panel([b], _prints(b))["deals"][0]["snapshots"]]
    assert grid_closed == grid_broken                  # same grid whatever the outcome
    snaps = _panel([b], _prints(b))["deals"][0]["snapshots"]
    assert all(s["status"] == "NOT_PROVABLY_BEFORE_RESOLUTION"
               for s in snaps if s["snapshot"] >= "2022-03-01")


def test_resolution_day_close_is_not_eligible():
    first = snapshot_schedule("2022-01-14", 10, 10, 12)[0]
    assert resolution_eligible(first, first.isoformat()) is False
    assert resolution_eligible(first, next_session_after(first).isoformat()) is True
    inst = f"{first.isoformat()}T15:00:00-05:00"
    assert resolution_eligible(first, inst) is False   # before the 16:00 close


def test_missing_print_is_missing_not_filled():
    a = _deal()
    first = snapshot_schedule("2022-01-14", 10, 10, 12)[0].isoformat()
    snaps = _panel([a], _prints(a, skip={first}))["deals"][0]["snapshots"]
    s = next(x for x in snaps if x["snapshot"] == first)
    assert s["status"] == "NO_PRINT_ON_SNAPSHOT_SESSION" and s["pct_spread"] is None


def test_delta_never_bridges_a_gap_and_vol_needs_three_deltas():
    a = _deal()
    grid = snapshot_schedule("2022-01-14", 10, 10, 12)
    prev = add_sessions(grid[0], 0)
    from src.model.spread_stress_v2.calendar import previous_session
    gap = previous_session(prev).isoformat()
    snaps = _panel([a], _prints(a, skip={gap}))["deals"][0]["snapshots"]
    assert snaps[0]["delta_spread"] is None            # previous session missing
    assert snaps[0]["status"] == "INCOMPLETE_FEATURES"
    only_two = _prints(a, n=3)                           # S0..S0+2 only
    from src.model.spread_stress_v2.panel import features_at
    s0 = first_eligible_session("2022-01-14")
    closes = {date.fromisoformat(p["session_date"]): p["target_price"] for p in only_two}
    f = features_at(add_sessions(s0, 2), s0, closes, 50.0, 10, 3)
    assert f["n_delta_obs"] == 2.0 and f["spread_vol"] is None


def test_pre_announcement_prints_never_enter_features():
    a = _deal()
    early = [{"deal_id": a["deal_id"], "session_date": "2022-01-13",
              "target_price": 1.0, "close_field_used": "close"}]
    base = _panel([a], _prints(a))["deals"][0]["snapshots"]
    with_early = _panel([a], early + _prints(a))["deals"][0]["snapshots"]
    assert base == with_early


def test_adjusted_closes_rejected():
    a = _deal()
    bad = [{**p, "close_field_used": "adjusted_close"} for p in _prints(a)]
    with pytest.raises(ValueError, match="raw closes"):
        _panel([a], bad)


def test_weights_sum_to_one_per_deal():
    a = _deal()
    d = _panel([a], _prints(a))["deals"][0]
    assert d["n_eligible"] > 1
    assert sum(s["weight"] for s in d["snapshots"]) == pytest.approx(1.0)


def test_non_cash_consideration_excluded():
    a = _deal(consideration_type="stock")
    d = _panel([a], _prints(a))["deals"][0]
    assert d["excluded"] == "UNSUPPORTED_CONSIDERATION" and d["snapshots"] == []


# -------------------------------------------------------------------- labels
@pytest.mark.parametrize("rt,ts,y", [
    ("closed", "2022-12-30", 0), ("terminated", "2022-12-30", 1),
    ("withdrawn", "2022-12-30", 1), (None, None, None), ("pending", None, None),
    ("closed", None, None), ("unknown", "2022-12-30", None)])
def test_censored_never_negative(rt, ts, y):
    assert label_for(_deal(resolution_type=rt, resolution_timestamp=ts)) == y


# -------------------------------------------------------------------- splits
def test_same_deal_never_crosses_split():
    deals = [
        {"deal_id": "A", "announcement_timestamp": "2020-03-01",
         "resolution_timestamp": "2020-09-01", "label": 0},
        {"deal_id": "B", "announcement_timestamp": "2020-11-01",
         "resolution_timestamp": "2021-06-01", "label": 1},   # open at 2021-01-01
        {"deal_id": "C", "announcement_timestamp": "2021-02-01",
         "resolution_timestamp": "2021-05-01", "label": 0},
        {"deal_id": "P", "announcement_timestamp": "2021-03-01",
         "resolution_timestamp": None, "label": None},        # pending
    ]
    folds = walk_forward(deals, annual_cutoffs(2021, 2022))
    f = folds[0]
    assert f["train"] == ["A"] and f["test"] == ["C", "P"]
    assert "B" not in f["train"] + f["test"]                  # censored at cutoff
    with pytest.raises(SplitLeakError):
        assert_disjoint({"cutoff": "x", "train": ["A"], "test": ["A"]})


# --------------------------------------------------------------------- gates
def _counts(pos, neg):
    return {"n_pos": pos, "n_neg": neg}


def test_min_class_gate_blocks_single_break():
    r = authorize_execution(_counts(1, 30), pit_validation_passed=True,
                            execution_authorization={"approved_by": "x"})
    assert r["status"] == G.BLOCKED_CLASS
    assert authorize_execution(_counts(2, 10))["status"] == G.BLOCKED_SAMPLE


def test_execution_requires_frozen_spec_and_explicit_authorization(tmp_path):
    ok = _counts(5, 30)
    assert authorize_execution(ok, pit_validation_passed=True)["status"] == G.BLOCKED_AUTH
    auth = {"spec_id": POLICY["spec_id"], "spec_sha256": POLICY["spec_sha256"],
            "approved_by": "audit"}
    assert authorize_execution(ok, pit_validation_passed=False,
                               execution_authorization=auth)["status"] == G.BLOCKED_PIT
    assert authorize_execution(ok, pit_validation_passed=True,
                               execution_authorization=auth)["status"] == G.AUTHORIZED
    draft = {**POLICY, "status": "DRAFT"}
    assert authorize_execution(ok, policy=draft, pit_validation_passed=True,
                               execution_authorization=auth)["status"] == G.BLOCKED_SPEC


def test_spec_is_frozen_and_tamper_evident(tmp_path):
    assert assert_frozen()["status"] == "FROZEN"
    tampered = tmp_path / "spec.md"
    tampered.write_text(SPEC_PATH.read_text() + "\nedit after freeze\n")
    with pytest.raises(SpecNotFrozenError, match="changed after freeze"):
        assert_frozen(POLICY, spec_path=tampered)


def test_frozen_policy_pins_protected_gates():
    assert POLICY["gates"] == {"level": "deal", "MIN_SAMPLE_N": 20, "MIN_CLASS_N": 2}
    assert POLICY["model"]["executed"] is False
    assert POLICY["model"]["hyperparameter_search"] is False
    assert POLICY["features"]["fill"] == POLICY["features"]["interpolation"] == "none"


# ------------------------------------------------------------ cohort artifact
def test_cohort_build_is_deterministic(tmp_path):
    import scripts.build_spread_stress_v2_cohort as B
    a, b = _deal(), _deal(deal_id="DEAL-ZED-BIG-2022", resolution_type="terminated")
    (tmp_path / "sec_deal_manifest.json").write_text(json.dumps({"deals": [a, b]}))
    (tmp_path / "free_price_coverage_matrix.json").write_text(json.dumps({"deals": [
        {"deal_id": a["deal_id"], "canonical_status": "CANONICALLY_ADMITTED"},
        {"deal_id": b["deal_id"], "canonical_status": "CANONICALLY_ADMITTED"}]}))
    (tmp_path / "target_price_manifest.json").write_text(
        json.dumps({"prints": _prints(a) + _prints(b)}))
    one, two = B.build(tmp_path), B.build(tmp_path)
    assert one["dataset_fingerprint"] == two["dataset_fingerprint"]
    assert one["status"] == "STOP_CLASS_OR_SAMPLE_GATE" and one["model_fit_executed"] is False


def test_committed_cohort_records_stop_and_no_fit():
    doc = json.loads((ROOT / "data" / "spread_stress_v2_cohort.json").read_text())
    assert doc["spec_sha256"] == POLICY["spec_sha256"]
    assert doc["status"] == "STOP_CLASS_OR_SAMPLE_GATE"
    assert doc["model_fit_executed"] is False
    assert doc["gates"]["MIN_CLASS_N"] == 2 and not doc["gates"]["min_class_pass"]


def test_v2_does_not_import_or_modify_v1_models():
    v2 = ROOT / "src" / "model" / "spread_stress_v2"
    for p in v2.glob("*.py"):
        text = p.read_text()
        for mod in ("spread_stress.", "..spread_stress ", "logistic", "dataset",
                    "first_walkforward"):
            assert f"import {mod}" not in text and f"from ..{mod}" not in text, (p, mod)
        assert "from ..spread_stress" not in text, p
    assert POLICY_PATH.exists()
