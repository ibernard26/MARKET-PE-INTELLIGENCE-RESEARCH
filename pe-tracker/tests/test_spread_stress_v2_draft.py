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
    EXECUTION_AUTHORIZED,
    FROZEN_POLICY_ID,
    FROZEN_TRAIN_FRACTION,
    ORDERING_AMBIGUOUS,
    RESOLVED_KNOWN,
    SESSION_CALENDAR,
    SPEC_STATUS,
    VOL_MIN_DELTAS,
    announcement_market_date,
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
         "resolution_timestamp": "2020-02-01", "resolution_type": "terminated"},
        {"deal_id": "B", "announcement_ts": "2021-01-01", "label": 0,
         "resolution_timestamp": "2021-02-01", "resolution_type": "closed"},
        {"deal_id": "C", "announcement_ts": "2022-01-01", "label": 1,
         "resolution_timestamp": "2022-02-01", "resolution_type": "withdrawn"},
        {"deal_id": "D", "announcement_ts": "2023-01-01", "label": 0,
         "resolution_timestamp": "2023-02-01", "resolution_type": "closed"},
        {"deal_id": "E", "announcement_ts": "2024-01-01", "label": 1,
         "resolution_timestamp": "2024-02-01", "resolution_type": "terminated"},
    ]
    out = chronological_group_split_by_fraction(rows)
    flipped = [{**r, "label": 1 - r["label"], "resolution_type": "closed"} for r in rows]
    again = chronological_group_split_by_fraction(flipped)
    assert {r["deal_id"] for r in out["train"]} == {r["deal_id"] for r in again["train"]}
    assert {r["deal_id"] for r in out["test"]} == {r["deal_id"] for r in again["test"]}
    params = inspect.signature(chronological_group_split_by_fraction).parameters
    assert "resolution" not in params and "label" not in params


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
