"""spread_stress_v2 draft: PIT feature time, grouped splits, frozen gates, no execute."""
from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path

import pytest

from src.config import MIN_SAMPLE_N
from src.ingest.equity_prices.pit_flags import DATE_ONLY, time_precision
from src.ingest.providers.sec_edgar import EVENT_RULES
from src.model.dataset import FEATURE_SCHEMA_VERSION as FS_V1
from src.model.logistic import MIN_CLASS_N, MODEL_VERSION as BREAK_LOGIT_V1
from src.model.spread_stress.features import FEATURE_SCHEMA_VERSION as FS_SS_V1
from src.model.spread_stress.model import MODEL_VERSION as SS_V1
from src.model.spread_stress.v2_spec import (
    FREEZE_SESSION_CALENDAR,
    POLICY_CANDIDATES,
    RECOMMENDED_POLICY_ID,
    SESSION_CALENDAR,
    SPEC_STATUS,
    authorize_execution,
    calendar_offset_session,
    deal_equal_snapshot_weight,
    feature_session_date,
    fit,
    freeze_blockers,
    grouped_chronological_split,
    snapshot_is_active_at_feature_time,
    snapshot_rows_for_policy,
    weekday_session,
)
from src.ingest.equity_prices.reconciliation import RECONCILE_RULES


def test_spec_is_draft_and_cannot_execute():
    assert SPEC_STATUS == "draft"
    gate = authorize_execution()
    assert gate["authorized"] is False
    assert gate["MODEL_FIT_EXECUTED"] == "NO"
    assert gate["BACKTEST_EXECUTED"] == "NO"
    assert "draft" in gate["reason"]
    with pytest.raises(RuntimeError, match="draft"):
        fit([])


def test_class_and_sample_gates_unchanged():
    assert MIN_SAMPLE_N == 20
    assert MIN_CLASS_N == 2
    gate = authorize_execution()
    assert gate["MIN_SAMPLE_N"] == 20
    assert gate["MIN_CLASS_N"] == 2


def test_locked_invariants_not_redefined_by_v2():
    assert FS_V1 == "fs_v1"
    assert BREAK_LOGIT_V1 == "break_logit_v1"
    assert FS_SS_V1 == "fs_spread_stress_v1"
    assert SS_V1 == "spread_stress_v1"
    assert "announcement" in EVENT_RULES
    assert RECONCILE_RULES["price_reconcile_v2"] == (0.01, 1e-4)


def test_feature_session_signature_has_no_resolution_parameter():
    params = inspect.signature(feature_session_date).parameters
    assert "resolution" not in params
    assert "resolution_ts" not in params
    assert "resolution_timestamp" not in params
    params = inspect.signature(calendar_offset_session).parameters
    assert "resolution" not in params


def test_date_only_announcement_skips_same_day_close():
    ann = "2015-05-29"  # Friday
    assert time_precision(ann) == DATE_ONLY
    d1 = feature_session_date(ann, 1)
    assert d1 == date(2015, 6, 1)  # next weekday after Friday
    assert d1.isoformat() != ann
    d10 = feature_session_date(ann, 10)
    assert d10 > d1
    # two deals with the same announcement and different resolutions must
    # still share the feature date — resolution is not an input.
    other = feature_session_date(ann, 10)
    assert other == d10


def test_intraday_before_close_may_use_announcement_session_as_first():
    # Monday 10:00 is before 16:00 close → session 1 can be that Monday.
    d1 = feature_session_date("2015-06-01T10:00:00", 1)
    assert d1 == date(2015, 6, 1)


def test_intraday_after_close_skips_that_session():
    d1 = feature_session_date("2015-06-01T17:00:00", 1)
    assert d1 == date(2015, 6, 2)


def test_recommended_policy_is_ex_ante_single_snapshot():
    assert RECOMMENDED_POLICY_ID == "ann_tplus_10_session"
    ids = [p["policy_id"] for p in POLICY_CANDIDATES]
    assert "ann_tplus_5_session" in ids
    assert "weekly_grid_5_60" in ids
    assert "calendar_7_14_30" in ids
    assert "active_deal_weekly_panel" in ids
    rec = next(p for p in POLICY_CANDIDATES if p["policy_id"] == RECOMMENDED_POLICY_ID)
    assert rec["uses_resolution_to_choose_feature_date"] is False
    assert rec["snapshots_per_deal"] == 1


def test_grouped_split_keeps_deal_snapshots_together():
    rows = [
        {"deal_id": "DEAL-A", "announcement_ts": "2015-01-15", "feature_date": "2015-01-22"},
        {"deal_id": "DEAL-A", "announcement_ts": "2015-01-15", "feature_date": "2015-01-29"},
        {"deal_id": "DEAL-B", "announcement_ts": "2016-06-01", "feature_date": "2016-06-08"},
    ]
    split = grouped_chronological_split(rows, train_announcement_before="2016-01-01")
    assert {r["deal_id"] for r in split["train"]} == {"DEAL-A"}
    assert {r["deal_id"] for r in split["test"]} == {"DEAL-B"}
    assert split["n_train_deals"] == 1
    assert split["n_test_deals"] == 1


def test_deal_equal_weight_prevents_duration_dominance():
    long_w = deal_equal_snapshot_weight(20, 2)
    short_w = deal_equal_snapshot_weight(2, 2)
    assert pytest.approx(20 * long_w) == pytest.approx(2 * short_w) == pytest.approx(0.5)


def test_committed_draft_policy_json_matches_module():
    from src.model.spread_stress.v2_spec import pit_policy_document
    path = Path(__file__).resolve().parents[1] / "data" / "spread_stress_v2_pit_policy_draft.json"
    doc = json.loads(path.read_text())
    live = pit_policy_document()
    assert doc["V2_SPEC_STATUS"] == live["V2_SPEC_STATUS"] == "draft"
    assert doc["PIT_POLICY_STATUS"] == "draft"
    assert doc["recommended_policy_id"] == live["recommended_policy_id"] == "ann_tplus_10_session"
    assert doc["MIN_SAMPLE_N"] == 20
    assert doc["MIN_CLASS_N"] == 2
    assert doc["execution"]["authorized"] is False
    assert all(not p["uses_resolution_to_choose_feature_date"]
               for p in doc["feature_time_policy_candidates"])


def test_snapshot_builder_does_not_read_resolution_fields():
    deals = [
        {"deal_id": "DEAL-A", "announcement_ts": "2015-06-01"},
        {"deal_id": "DEAL-B", "announcement_ts": "2015-06-01",
         "resolution_timestamp": "2015-06-03", "resolution_type": "terminated"},
    ]
    rows = snapshot_rows_for_policy(deals, "ann_tplus_10_session")
    assert len(rows) == 2
    assert rows[0]["feature_date"] == rows[1]["feature_date"]
    assert all("resolution" not in r for r in rows)


def test_timezone_aware_intraday_announcement_uses_ny_close():
    # 2015-06-01 is EDT (UTC-4). 16:00 ET == 20:00 UTC.
    assert feature_session_date("2015-06-01T15:59:00-04:00", 1) == date(2015, 6, 1)
    assert feature_session_date("2015-06-01T16:00:00-04:00", 1) == date(2015, 6, 2)
    assert feature_session_date("2015-06-01T19:59:00+00:00", 1) == date(2015, 6, 1)
    assert feature_session_date("2015-06-01T20:00:00+00:00", 1) == date(2015, 6, 2)
    # Same instant in two zones: resolution already known_at feature_time.
    assert snapshot_is_active_at_feature_time(
        "2015-06-15T16:00:00-04:00", "2015-06-15T20:00:00+00:00") is False
    assert snapshot_is_active_at_feature_time(
        "2015-06-15T16:00:00-04:00", "2015-06-15T20:00:01+00:00") is True


def test_freeze_requires_nyse_calendar_and_does_not_execute():
    assert SPEC_STATUS == "draft"
    assert SESSION_CALENDAR == "weekday_placeholder"
    assert FREEZE_SESSION_CALENDAR == "nyse_market_calendar"
    blockers = freeze_blockers()
    assert "NYSE_SESSION_CALENDAR_REQUIRED" in blockers
    assert "TIMEZONE_AWARE_INTRADAY_REQUIRED" in blockers
    assert "ACTIVE_AT_FEATURE_TIME_MUST_USE_PIT_KNOWN_AT" in blockers
    assert "RESOLUTION_MUST_NOT_CHOOSE_FEATURE_DATES" in blockers
    gate = authorize_execution()
    assert gate["authorized"] is False
    assert weekday_session is not None  # placeholder exists
    # known_at censors labels; it does not pick a different feature date
    assert snapshot_is_active_at_feature_time("2015-06-15T16:00:00", None) is True
    assert snapshot_is_active_at_feature_time(
        "2015-06-15T16:00:00", "2015-06-10T12:00:00") is False
    deals = [{"deal_id": "DEAL-A", "announcement_ts": "2015-06-01",
              "resolution_timestamp": "2015-06-03"}]
    rows = snapshot_rows_for_policy(deals, "ann_tplus_10_session")
    assert rows[0]["feature_date"] == feature_session_date("2015-06-01", 10).isoformat()
