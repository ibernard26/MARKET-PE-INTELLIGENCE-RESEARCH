"""spread_stress_v2 frozen methodology: XNYS timing, PIT censoring, no execute."""
from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path

import pytest

from src.config import MIN_SAMPLE_N
from src.ingest.providers.sec_edgar import EVENT_RULES
from src.ingest.equity_prices.reconciliation import RECONCILE_RULES
from src.model.dataset import FEATURE_SCHEMA_VERSION as FS_V1
from src.model.logistic import MIN_CLASS_N, MODEL_VERSION as BREAK_LOGIT_V1
from src.model.spread_stress.features import FEATURE_SCHEMA_VERSION as FS_SS_V1
from src.model.spread_stress.model import MODEL_VERSION as SS_V1
from src.model.spread_stress.v2_spec import (
    ACTIVE,
    DATE_ONLY_PRECISION_BUCKET,
    EXECUTION_AUTHORIZED,
    FROZEN_POLICY_ID,
    FROZEN_TRAIN_FRACTION,
    INTRADAY_PRECISION_BUCKET,
    ORDERING_AMBIGUOUS,
    RESOLVED_KNOWN,
    SESSION_CALENDAR,
    SPEC_STATUS,
    VOL_MIN_DELTAS,
    announcement_market_date,
    announcement_order_key,
    authorize_execution,
    calendar_offset_session,
    chronological_group_split_by_fraction,
    execution_blockers,
    feature_session_date,
    feature_session_time,
    fit,
    freeze_blockers,
    nyse_session,
    nyse_session_close,
    partition_snapshots_by_known_at,
    pit_policy_document,
    snapshot_activity_state,
    snapshot_rows_for_policy,
)


def test_spec_is_frozen_but_execution_stays_disabled():
    assert SPEC_STATUS == "frozen"
    assert EXECUTION_AUTHORIZED is False
    assert freeze_blockers() == []
    assert execution_blockers() == [
        "V2_PANEL_COHORT_FREEZE_REQUIRED",
        "V2_MODEL_IMPLEMENTATION_REQUIRED",
        "EXPLICIT_EXECUTION_AUTHORIZATION_REQUIRED",
    ]
    gate = authorize_execution()
    assert gate["authorized"] is False
    assert gate["MODEL_FIT_EXECUTED"] == "NO"
    assert gate["WALK_FORWARD_EXECUTED"] == "NO"
    assert gate["CALIBRATION_EXECUTED"] == "NO"
    assert gate["BACKTEST_EXECUTED"] == "NO"
    with pytest.raises(RuntimeError, match="methodology frozen"):
        fit([])


def test_locked_v1_invariants_and_gates_unchanged():
    assert MIN_SAMPLE_N == 20
    assert MIN_CLASS_N == 2
    assert FS_V1 == "fs_v1"
    assert BREAK_LOGIT_V1 == "break_logit_v1"
    assert FS_SS_V1 == "fs_spread_stress_v1"
    assert SS_V1 == "spread_stress_v1"
    assert "announcement" in EVENT_RULES
    assert RECONCILE_RULES["price_reconcile_v2"] == (0.01, 1e-4)


def test_xnys_calendar_replaces_weekday_placeholder_and_knows_early_close():
    assert SESSION_CALENDAR == "XNYS_exchange_calendars"
    assert nyse_session(date(2024, 7, 3)) is True
    assert nyse_session(date(2024, 7, 4)) is False
    close = nyse_session_close(date(2024, 7, 3))
    assert (close.hour, close.minute) == (13, 0)  # Independence Day early close
    assert close.utcoffset() is not None


def test_date_only_tplus_counts_real_sessions_not_weekdays():
    # Jul 4 is closed. DATE_ONLY Jul 1 skips Jul 1 itself: Jul2=1, Jul3=2, Jul5=3.
    assert feature_session_date("2024-07-01", 3) == date(2024, 7, 5)
    assert calendar_offset_session("2024-07-01", 3) == date(2024, 7, 5)


def test_intraday_requires_offset_and_uses_actual_early_close():
    assert feature_session_date("2024-07-03T12:59:00-04:00", 1) == date(2024, 7, 3)
    assert feature_session_date("2024-07-03T13:00:00-04:00", 1) == date(2024, 7, 5)
    # Same pre-close instant expressed in UTC.
    assert feature_session_date("2024-07-03T16:59:00+00:00", 1) == date(2024, 7, 3)
    with pytest.raises(ValueError, match="explicit timezone offset"):
        feature_session_date("2024-07-03T12:00:00", 1)


def test_intraday_market_date_uses_timezone_not_string_prefix():
    # 00:30 +02 on Jul 3 is 18:30 ET on Jul 2 (after Jul 2 close), so Jul 3 is session 1.
    ts = "2024-07-03T00:30:00+02:00"
    assert announcement_market_date(ts) == date(2024, 7, 2)
    assert feature_session_date(ts, 1) == date(2024, 7, 3)


def test_feature_time_functions_cannot_take_resolution_parameters():
    for fn in (feature_session_date, feature_session_time, calendar_offset_session):
        params = inspect.signature(fn).parameters
        assert not {"resolution", "resolution_ts", "resolution_timestamp", "resolution_known_at"} & set(params)


def test_frozen_snapshot_builder_ignores_resolution_and_rejects_alternate_policy():
    deals = [
        {"deal_id": "A", "announcement_timestamp": "2024-07-01", "resolution_timestamp": "2024-07-02"},
        {"deal_id": "B", "announcement_timestamp": "2024-07-01", "resolution_timestamp": "2030-01-01"},
    ]
    rows = snapshot_rows_for_policy(deals)
    assert {r["policy_id"] for r in rows} == {FROZEN_POLICY_ID}
    assert rows[0]["feature_date"] == rows[1]["feature_date"]
    assert rows[0]["feature_time"] == rows[1]["feature_time"]
    assert all("resolution" not in k for r in rows for k in r)
    with pytest.raises(ValueError, match="frozen to"):
        snapshot_rows_for_policy(deals, "ann_tplus_5_session")


def test_activity_uses_known_at_and_censors_same_day_unknown_order():
    ft = "2024-07-03T13:00:00-04:00"
    assert snapshot_activity_state(ft, None) == ACTIVE
    assert snapshot_activity_state(ft, "2024-07-02") == RESOLVED_KNOWN
    assert snapshot_activity_state(ft, "2024-07-04") == ACTIVE
    assert snapshot_activity_state(ft, "2024-07-03") == ORDERING_AMBIGUOUS
    assert snapshot_activity_state(ft, "2024-07-03T12:59:00-04:00") == RESOLVED_KNOWN
    assert snapshot_activity_state(ft, "2024-07-03T13:01:00-04:00") == ACTIVE
    assert snapshot_activity_state(ft, "2024-07-03T12:00:00") == ORDERING_AMBIGUOUS


def test_activity_censoring_does_not_substitute_feature_dates():
    rows = [
        {"deal_id": "A", "feature_time": "2024-07-03T13:00:00-04:00", "feature_date": "2024-07-03"},
        {"deal_id": "B", "feature_time": "2024-07-03T13:00:00-04:00", "feature_date": "2024-07-03"},
    ]
    out = partition_snapshots_by_known_at(rows, {"A": "2024-07-03", "B": "2024-07-04"})
    assert [r["deal_id"] for r in out["active"]] == ["B"]
    assert [r["deal_id"] for r in out["censored"]] == ["A"]
    assert out["censored"][0]["feature_date"] == "2024-07-03"


def test_frozen_split_is_outcome_blind_grouped_60_40():
    rows = [
        {"deal_id": "A", "announcement_ts": "2020-01-01", "label": 1},
        {"deal_id": "A", "announcement_ts": "2020-01-01", "label": 1},
        {"deal_id": "B", "announcement_ts": "2021-01-01", "label": 0},
        {"deal_id": "C", "announcement_ts": "2022-01-01", "label": 1},
        {"deal_id": "D", "announcement_ts": "2023-01-01", "label": 0},
        {"deal_id": "E", "announcement_ts": "2024-01-01", "label": 0},
    ]
    assert FROZEN_TRAIN_FRACTION == 0.60
    out = chronological_group_split_by_fraction(rows)
    assert out["n_train_deals"] == 3
    assert out["n_test_deals"] == 2
    train_ids = {r["deal_id"] for r in out["train"]}
    test_ids = {r["deal_id"] for r in out["test"]}
    assert train_ids == {"A", "B", "C"}
    assert test_ids == {"D", "E"}
    assert not train_ids & test_ids


def test_intraday_split_order_is_utc_not_raw_string():
    early_utc = "2024-01-02T00:00:00+00:00"
    later_et = "2024-01-01T23:30:00-05:00"  # 04:30 UTC; later absolutely, earlier lexicographically
    assert later_et < early_utc  # raw-string trap
    ka = announcement_order_key(early_utc, "A")
    kb = announcement_order_key(later_et, "B")
    assert ka[0] == kb[0] == date(2024, 1, 1)
    assert ka[1] == kb[1] == INTRADAY_PRECISION_BUCKET
    assert ka[2] < kb[2]
    rows = [
        {"deal_id": "LATE", "announcement_ts": later_et, "label": 1,
         "resolution_timestamp": "2024-02-01", "resolution_known_at": "2024-02-01",
         "resolution_type": "terminated"},
        {"deal_id": "EARLY", "announcement_ts": early_utc, "label": 0,
         "resolution_timestamp": "2023-01-01", "resolution_known_at": "2023-01-01",
         "resolution_type": "closed"},
        {"deal_id": "C", "announcement_ts": "2024-01-03T12:00:00+00:00", "label": 1},
        {"deal_id": "D", "announcement_ts": "2024-01-04T12:00:00+00:00", "label": 0},
        {"deal_id": "E", "announcement_ts": "2024-01-05T12:00:00+00:00", "label": 1},
    ]
    out = chronological_group_split_by_fraction(rows)
    assert out["ordered_deal_ids"][:2] == ["EARLY", "LATE"]
    assert out["ordered_deal_ids"][0] == "EARLY"


def test_equivalent_offset_instants_sort_identically_then_deal_id():
    et = "2024-01-01T23:30:00-05:00"
    utc = "2024-01-02T04:30:00+00:00"
    assert announcement_order_key(et, "X")[2] == announcement_order_key(utc, "X")[2]
    assert announcement_order_key(et, "X")[0] == date(2024, 1, 1)
    rows_et = [
        {"deal_id": "B", "announcement_ts": et},
        {"deal_id": "A", "announcement_ts": utc},
        {"deal_id": "C", "announcement_ts": "2024-06-01T12:00:00+00:00"},
        {"deal_id": "D", "announcement_ts": "2024-07-01T12:00:00+00:00"},
        {"deal_id": "E", "announcement_ts": "2024-08-01T12:00:00+00:00"},
    ]
    rows_swapped = [
        {"deal_id": "B", "announcement_ts": utc},
        {"deal_id": "A", "announcement_ts": et},
        {"deal_id": "C", "announcement_ts": "2024-06-01T12:00:00+00:00"},
        {"deal_id": "D", "announcement_ts": "2024-07-01T12:00:00+00:00"},
        {"deal_id": "E", "announcement_ts": "2024-08-01T12:00:00+00:00"},
    ]
    a = chronological_group_split_by_fraction(rows_et)
    b = chronological_group_split_by_fraction(rows_swapped)
    assert a["ordered_deal_ids"][:2] == ["A", "B"] == b["ordered_deal_ids"][:2]


def test_date_only_same_day_ties_break_on_deal_id():
    rows = [
        {"deal_id": "B", "announcement_ts": "2024-01-02"},
        {"deal_id": "A", "announcement_ts": "2024-01-02"},
        {"deal_id": "C", "announcement_ts": "2024-01-02"},
        {"deal_id": "D", "announcement_ts": "2024-01-02"},
        {"deal_id": "E", "announcement_ts": "2024-01-02"},
    ]
    out = chronological_group_split_by_fraction(rows)
    assert out["ordered_deal_ids"] == ["A", "B", "C", "D", "E"]
    assert {r["deal_id"] for r in out["train"]} == {"A", "B", "C"}
    assert {r["deal_id"] for r in out["test"]} == {"D", "E"}
    ka = announcement_order_key("2024-01-02", "A")
    kb = announcement_order_key("2024-01-02", "B")
    assert ka[0] == kb[0] == date(2024, 1, 2)
    assert ka[1] == kb[1] == DATE_ONLY_PRECISION_BUCKET
    assert ka[3] < kb[3]


def test_mixed_precision_same_market_date_is_a_total_order():
    # 01:00 UTC and 02:00 UTC on 2024-01-02 are 20:00/21:00 ET on 2024-01-01.
    rows = [
        {"deal_id": "M", "announcement_ts": "2024-01-01"},
        {"deal_id": "Z", "announcement_ts": "2024-01-02T01:00:00+00:00"},
        {"deal_id": "A", "announcement_ts": "2024-01-02T02:00:00+00:00"},
        {"deal_id": "C", "announcement_ts": "2024-06-01"},
        {"deal_id": "D", "announcement_ts": "2024-07-01"},
    ]
    out = chronological_group_split_by_fraction(rows)
    assert out["ordered_deal_ids"][:3] == ["Z", "A", "M"]
    kz, ka, km = (announcement_order_key(ts, did) for did, ts in (
        ("Z", "2024-01-02T01:00:00+00:00"),
        ("A", "2024-01-02T02:00:00+00:00"),
        ("M", "2024-01-01"),
    ))
    assert [kz, ka, km] == sorted([km, ka, kz])
    assert kz < ka < km


def test_mixed_precision_bucket_then_utc_or_deal_id():
    rows = [
        {"deal_id": "D2", "announcement_ts": "2024-01-01"},
        {"deal_id": "D1", "announcement_ts": "2024-01-01"},
        {"deal_id": "I2", "announcement_ts": "2024-01-01T23:00:00-05:00"},
        {"deal_id": "I1", "announcement_ts": "2024-01-01T12:00:00-05:00"},
        {"deal_id": "X", "announcement_ts": "2024-06-01"},
    ]
    out = chronological_group_split_by_fraction(rows)
    assert out["ordered_deal_ids"][:4] == ["I1", "I2", "D1", "D2"]
    assert announcement_order_key("2024-01-01T12:00:00-05:00", "I1")[1] == INTRADAY_PRECISION_BUCKET
    assert announcement_order_key("2024-01-01", "D1")[1] == DATE_ONLY_PRECISION_BUCKET


def test_intraday_market_date_is_new_york_not_utc_calendar_date():
    ts = "2024-01-01T23:30:00-05:00"
    assert announcement_market_date(ts) == date(2024, 1, 1)
    key = announcement_order_key(ts, "X")
    assert key[0] == date(2024, 1, 1)
    assert key[2].date() == date(2024, 1, 2)  # UTC date is the next calendar day


def test_model_and_threshold_specs_are_frozen_not_executed():
    doc = pit_policy_document()
    assert doc["MODEL_HYPERPARAMETERS"] == {
        "penalty": "l2",
        "C": 1.0,
        "solver": "lbfgs",
        "max_iter": 1000,
        "class_weight": None,
        "standardize": True,
        "impute": "train_median+missing_indicator",
    }
    assert doc["CALIBRATION_METHOD"] == "none"
    ts = doc["threshold_selection"]
    assert ts["rule"] == "train_only_cost_min"
    assert ts["COST_FP"] == 1.0
    assert ts["COST_FN"] == 15.0
    assert list(ts["COST_RATIO_GRID"]) == [5, 10, 15, 20]


def test_frozen_split_ignores_resolution_and_labels():
    rows = [
        {"deal_id": "A", "announcement_ts": "2020-01-01", "label": 1,
         "resolution_timestamp": "2020-02-01", "resolution_known_at": "2020-02-01T16:00:00-05:00",
         "resolution_type": "terminated"},
        {"deal_id": "B", "announcement_ts": "2021-01-01", "label": 0,
         "resolution_timestamp": "2021-02-01", "resolution_known_at": "2021-02-01T16:00:00-05:00",
         "resolution_type": "closed"},
        {"deal_id": "C", "announcement_ts": "2022-01-01", "label": 1,
         "resolution_timestamp": "2022-02-01", "resolution_known_at": "2022-02-01T16:00:00-05:00",
         "resolution_type": "withdrawn"},
        {"deal_id": "D", "announcement_ts": "2023-01-01", "label": 0,
         "resolution_timestamp": "2023-02-01", "resolution_known_at": "2023-02-01T16:00:00-05:00",
         "resolution_type": "closed"},
        {"deal_id": "E", "announcement_ts": "2024-01-01", "label": 1,
         "resolution_timestamp": "2024-02-01", "resolution_known_at": "2024-02-01T16:00:00-05:00",
         "resolution_type": "terminated"},
    ]
    out = chronological_group_split_by_fraction(rows)
    flipped = [{
        **r,
        "label": 1 - r["label"],
        "resolution_type": "closed",
        "resolution_timestamp": "1999-01-01",
        "resolution_known_at": "1999-01-01T00:00:00+00:00",
    } for r in rows]
    again = chronological_group_split_by_fraction(flipped)
    assert {r["deal_id"] for r in out["train"]} == {r["deal_id"] for r in again["train"]}
    assert {r["deal_id"] for r in out["test"]} == {r["deal_id"] for r in again["test"]}
    assert out["ordered_deal_ids"] == again["ordered_deal_ids"]
    params = inspect.signature(chronological_group_split_by_fraction).parameters
    assert "resolution" not in params and "label" not in params
    assert "resolution_timestamp" not in params and "resolution_known_at" not in params


def test_announcement_order_key_is_directly_sortable_without_cmp():
    import src.model.spread_stress.v2_spec as mod
    src = Path(mod.__file__).read_text()
    assert "cmp_to_key" not in src
    assert "_cmp_announcement_order_keys" not in src
    keys = [
        announcement_order_key("2024-01-01", "M"),
        announcement_order_key("2024-01-02T02:00:00+00:00", "A"),
        announcement_order_key("2024-01-02T01:00:00+00:00", "Z"),
    ]
    assert sorted(keys) == [keys[2], keys[1], keys[0]]


def test_volatility_semantics_resolve_tplus10_delta_count():
    doc = pit_policy_document()
    assert doc["VOL_WINDOW_DEFAULT"] == 10
    assert doc["VOL_MIN_DELTAS"] == VOL_MIN_DELTAS == 3
    vol = next(f for f in doc["base_features"] if f["name"] == "spread_vol")
    assert "up to the last 10" in vol["pit_definition"]
    assert "at least 3" in vol["pit_definition"]


def test_committed_frozen_policy_json_matches_module():
    path = Path(__file__).resolve().parents[1] / "data" / "spread_stress_v2_pit_policy.json"
    committed = json.loads(path.read_text())
    assert committed == pit_policy_document()
    assert committed["V2_SPEC_STATUS"] == "frozen"
    assert committed["PIT_POLICY_STATUS"] == "frozen"
    assert committed["frozen_policy_id"] == FROZEN_POLICY_ID
    assert committed["freeze_blockers"] == []
    assert committed["execution"]["authorized"] is False
