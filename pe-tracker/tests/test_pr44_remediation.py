"""PR #44 remediation: reconciliation auditability, identity evidence, cohort fingerprint."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.freeze_thesis_price_cohort import (
    cohort_fingerprint_v2,
    fingerprint_payload,
)
from scripts import freeze_thesis_price_cohort as freeze
from scripts.run_free_price_coverage import (
    MAX_HOURLY_429_WAITS,
    CacheMigrationError,
    canonical_status,
    migrate_cached_row,
    plan_tiingo_retry,
    reconcile_totals_from_rows,
    row_cache_reusable,
    tiingo_hourly_limited,
    unresolved_infrastructure,
)
from src.ingest.equity_prices.pit_flags import (
    ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS,
    RESOLUTION_DAY_ORDERING_AMBIGUOUS,
    pit_flags_for_print,
)
from src.ingest.equity_prices.reconciliation import (
    RECONCILE_RULES,
    THESIS_RECONCILE_RULE,
    reconcile_session_evidence,
    summarize_session_evidence,
)
from src.ingest.equity_prices.schema import NormalizedEquityObservation
from src.model.spread_stress.features import build_spread_stress_panel
from src.model.spread_stress.panel_diagnostic import diagnose_v1_panel
from src.research.observations import Observation, record_observation
from tests.model_fixtures import add_deal, mem

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
MANIFEST = ROOT / "data" / "target_price_manifest.json"
COHORT = ROOT / "data" / "spread_stress_thesis_v1_cohort.json"
EVIDENCE = ROOT / "data" / "price_reconcile_v2_evidence.json"
IDENTITY = ROOT / "data" / "tiingo_identity_evidence.json"
PIT = ROOT / "data" / "pit_ordering_diagnostics.json"
DIAG = ROOT / "data" / "spread_stress_v1_panel_diagnostic.json"
HISTORICAL_FINGERPRINT = (
    "2bf7e403a6e37cb5ce31dcd7ff388ae21ac8ff006afd11966a7e61abfdae3037"
)
ALLOWED_PROVIDERS = {"tiingo", "yahoo_finance_chart"}

COMPLETE_ROW = {
    "row_schema_version": 2,
    "deal_id": "D1",
    "overlap_sessions": 2,
    "exact_matches": 1,
    "tolerable_matches": 1,
    "material_conflicts": 0,
    "canonical_status": "DEFERRED_IDENTITY",
    "identity_proofs": ["B_TIINGO_NAME_AND_LISTING_WINDOW"],
    "reconcile_rule": "price_reconcile_v2",
    "tiingo_identity_verified": True,
    "tiingo_status": "ok",
    "yahoo_status": "ok",
    "tiingo_n": 2,
    "yahoo_n": 2,
}


def _obs(provider, day, close):
    return NormalizedEquityObservation(
        deal_id="D", session_date=day, close=close, provider=provider,
        provider_symbol="X", retrieval_timestamp="t", close_field_used="close")


def test_session_evidence_partitions_overlap_and_matches_counts():
    tiingo = [_obs("tiingo", "2015-03-02", 10.0), _obs("tiingo", "2015-03-03", 10.0),
              _obs("tiingo", "2015-03-04", 50.0)]
    yahoo = [_obs("yahoo_finance_chart", "2015-03-02", 10.0),
             _obs("yahoo_finance_chart", "2015-03-03", 10.01),
             _obs("yahoo_finance_chart", "2015-03-04", 60.0)]
    sessions = reconcile_session_evidence(
        tiingo, yahoo, deal_id="D1", rule=THESIS_RECONCILE_RULE)
    per_deal, totals = summarize_session_evidence(sessions)
    assert [s["classification"] for s in sessions] == ["EXACT", "TOLERABLE", "MATERIAL_CONFLICT"]
    assert totals == {"overlap_sessions": 3, "exact": 1, "tolerable": 1, "conflict": 1}
    assert per_deal[0]["exact_matches"] + per_deal[0]["tolerable_matches"] + per_deal[0]["material_conflicts"] == 3
    assert sessions[0]["rule_version"] == "price_reconcile_v2"
    assert "adjusted" not in json.dumps(sessions)


def test_stale_cached_row_missing_schema_is_not_reused():
    stale = dict(COMPLETE_ROW)
    del stale["row_schema_version"]
    assert row_cache_reusable(stale) is False
    missing = dict(COMPLETE_ROW)
    del missing["exact_matches"]
    del missing["tolerable_matches"]
    missing["overlap_sessions"] = 4
    assert row_cache_reusable(missing) is False
    with pytest.raises(CacheMigrationError, match="positive overlap"):
        migrate_cached_row(missing)
    zero = dict(missing)
    zero["overlap_sessions"] = 0
    zero["material_conflicts"] = 0
    migrated = migrate_cached_row(zero)
    assert migrated["exact_matches"] == 0 and migrated["tolerable_matches"] == 0
    assert migrated["row_schema_version"] == 2
    assert row_cache_reusable(migrated) is True
    transient = dict(COMPLETE_ROW)
    transient["tiingo_status"] = "TRANSIENT_FAILURE"
    assert row_cache_reusable(transient) is False


def test_non_429_transient_is_not_no_price_history_or_hourly_cap():
    empty = {"status": "TRANSIENT_FAILURE", "provider_trace": []}
    assert tiingo_hourly_limited(empty) is False
    assert plan_tiingo_retry(empty, 0) == "bounded_retry"
    network = {"status": "TRANSIENT_FAILURE",
               "provider_trace": [{"error": "Tiingo meta HTTP 599", "http_status": 599}]}
    assert tiingo_hourly_limited(network) is False
    assert plan_tiingo_retry(network, 0) == "bounded_retry"
    row = {
        "tiingo_status": "TRANSIENT_FAILURE", "tiingo_n": 0,
        "yahoo_status": "TRANSIENT_FAILURE", "yahoo_n": 0,
        "material_conflicts": 0, "openfigi_status": "NO_MATCH",
        "tiingo_identity_verified": False, "combined_n": 0,
    }
    assert unresolved_infrastructure(row) is True
    status, reason = canonical_status(row)
    assert status != "NO_PRICE_HISTORY"
    assert status is None
    assert reason == "UNRESOLVED_INFRASTRUCTURE"


def test_explicit_429_is_bounded_hourly_not_a_price_outcome():
    res = {"status": "TRANSIENT_FAILURE",
           "provider_trace": [{"error": "Tiingo meta HTTP 429", "http_status": 429}]}
    assert tiingo_hourly_limited(res) is True
    assert plan_tiingo_retry(res, 0) == "hourly_wait"
    assert plan_tiingo_retry(res, MAX_HOURLY_429_WAITS - 1) == "hourly_wait"
    assert plan_tiingo_retry(res, MAX_HOURLY_429_WAITS) == "unresolved"
    row = {
        "tiingo_status": "TRANSIENT_FAILURE", "tiingo_n": 0,
        "yahoo_status": "NO_HISTORY", "yahoo_n": 0,
        "material_conflicts": 0, "openfigi_status": "NO_MATCH",
        "tiingo_identity_verified": False, "combined_n": 0,
    }
    assert canonical_status(row)[0] != "NO_PRICE_HISTORY"


def test_date_only_same_day_closes_are_pit_ambiguous():
    ann_close = {
        "session_date": "2016-06-11",
        "observation_timestamp": "2016-06-11T16:00:00",
    }
    flags = pit_flags_for_print(ann_close, "2016-06-11", "2016-12-08")
    assert flags["announcement_time_precision"] == "DATE_ONLY"
    assert ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS in flags["pit_ordering_flags"]
    res_close = {
        "session_date": "2016-12-08",
        "observation_timestamp": "2016-12-08T16:00:00",
    }
    flags = pit_flags_for_print(res_close, "2016-06-11", "2016-12-08")
    assert RESOLUTION_DAY_ORDERING_AMBIGUOUS in flags["pit_ordering_flags"]
    assert ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS not in flags["pit_ordering_flags"]
    intraday = pit_flags_for_print(res_close, "2016-06-11T09:30:00", "2016-12-08T16:00:00")
    assert intraday["pit_ordering_flags"] == []
    assert intraday["announcement_time_precision"] == "INTRADAY"


def test_v1_panel_collision_is_not_missing_price_history():
    conn = mem()
    add_deal(conn, "D1", "2024-01-02", 0.05, 0, resolve_days=5)
    for day in ("2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06", "2024-01-07"):
        record_observation(Observation(
            "D1", day + "T16:00:00", "tiingo",
            target_price=10.0, known_at=day + "T16:00:00"), conn=conn)
    panel = build_spread_stress_panel("2030-01-01", conn, min_prints=3)
    reasons = [row["reason"] for row in panel["excluded"]]
    assert "feature_not_before_resolution" in reasons
    assert "insufficient_price_history" not in reasons
    assert panel["n"] == 0
    diag = diagnose_v1_panel(
        panel, price_coverage_ready=True,
        pre_resolution_prints=4, deals_with_3plus_pre_resolution_prints=1)
    assert diag["PRICE_COVERAGE_READY"] == "YES"
    assert diag["SPREAD_STRESS_V1_PANEL_VALID"] == "NO"
    assert diag["SPREAD_STRESS_V1_EXECUTED"] == "NO"
    assert diag["SPREAD_STRESS_V1_MODEL_FIT"] == "NO"
    assert diag["SPREAD_STRESS_V1_BLOCK_REASON"] == "FEATURE_TIME_RESOLUTION_TIMESTAMP_COLLISION"
    assert "insufficient historical price" not in json.dumps(diag).lower()


def test_fingerprint_stable_when_code_sha_and_created_at_change(tmp_path, monkeypatch):
    matrix = tmp_path / "matrix.json"
    manifest = tmp_path / "manifest.json"
    deals_path = tmp_path / "deals.json"
    out = tmp_path / "cohort.json"
    eligible = sorted(f"DEAL-T{i}-X-2020" for i in range(20))
    matrix.write_text(json.dumps({
        "meta": {
            "canonical_n": 20,
            "deals_with_3plus_prints": 20,
            "historical_price_data_ready": True,
            "total_real_price_prints": 100,
            "tiingo_deals_covered": 20,
            "yahoo_deals_covered": 0,
            "multi_provider_confirmed": 0,
            "reconcile_rule": "price_reconcile_v2",
        },
        "deals": [{
            "deal_id": deal_id, "tiingo_n": 5, "yahoo_n": 0,
            "final_coverage_status": "TIINGO_COVERED",
        } for deal_id in eligible],
    }))
    prints = []
    for deal_id in eligible:
        for day in range(2, 7):
            prints.append({
                "deal_id": deal_id,
                "session_date": f"2020-01-{day:02d}",
                "observation_timestamp": f"2020-01-{day:02d}T16:00:00",
                "target_price": 10.0 + day,
                "provider": "tiingo",
                "source_name": "tiingo",
                "source_identifier": f"tiingo:T@{deal_id}-{day}",
                "close_field_used": "close",
                "retrieval_timestamp": "2026-09-27T00:00:00+00:00",
            })
    manifest.write_text(json.dumps({"prints": prints}))
    deals_path.write_text(json.dumps({"deals": [{
        "deal_id": deal_id, "target": "T", "announcement_timestamp": "2020-01-02",
        "resolution_timestamp": "2020-02-02", "resolution_type": "closed",
    } for deal_id in eligible]}))
    monkeypatch.setattr(freeze, "MATRIX", matrix)
    monkeypatch.setattr(freeze, "MANIFEST", manifest)
    monkeypatch.setattr(freeze, "DEAL_MANIFEST", deals_path)
    monkeypatch.setattr(freeze, "OUT", out)
    shas = iter(["a" * 40, "b" * 40])
    moments = iter([
        __import__("datetime").datetime(2026, 1, 1, tzinfo=__import__("datetime").timezone.utc),
        __import__("datetime").datetime(2026, 6, 1, tzinfo=__import__("datetime").timezone.utc),
    ])

    def _git(*args, **kwargs):
        return next(shas) + "\n"

    class _Clock:
        @staticmethod
        def now(tz=None):
            return next(moments)

    monkeypatch.setattr(freeze.subprocess, "check_output", _git)
    monkeypatch.setattr(freeze, "datetime", _Clock)
    assert freeze.main() == 0
    first = json.loads(out.read_text())
    assert freeze.main() == 0
    second = json.loads(out.read_text())
    assert first["dataset_fingerprint"] == second["dataset_fingerprint"]
    assert first["code_sha"] != second["code_sha"]
    assert first["created_at"] != second["created_at"]
    assert first["fingerprint_version"] == "cohort_fingerprint_v2"
    assert "commit_sha" not in first["fingerprinted_inputs"]
    assert "retrieved_at" not in json.dumps(first["fingerprinted_inputs"])
    assert first["inclusion_rules"]["reconcile_rule"] == THESIS_RECONCILE_RULE
    changed = json.loads(manifest.read_text())
    changed["prints"][0]["target_price"] = 99.0
    payload = fingerprint_payload(
        eligible, changed["prints"], json.loads(deals_path.read_text())["deals"])
    assert cohort_fingerprint_v2(payload) != first["dataset_fingerprint"]


def _load(path: Path) -> dict:
    assert path.exists(), path
    return json.loads(path.read_text())


def test_committed_reconcile_totals_match_and_partition():
    doc = _load(MATRIX)
    evidence = _load(EVIDENCE)
    meta = doc["meta"]
    rows = doc["deals"]
    assert "reconcile_pre_retry" not in meta
    assert meta["historical_debug"]["label"] == "NOT_INCLUDED_IN_SCIENTIFIC_RECONCILE_TOTALS"
    totals = reconcile_totals_from_rows(rows)
    assert totals == meta["reconcile"]
    assert totals["exact"] + totals["tolerable"] + totals["conflict"] == totals["overlap_sessions"]
    per = {r["deal_id"]: r for r in evidence["per_deal"]}
    for row in rows:
        overlap = int(row.get("overlap_sessions") or 0)
        parts = int(row["exact_matches"]) + int(row["tolerable_matches"]) + int(row["material_conflicts"])
        assert overlap == parts
        if overlap:
            ev = per[row["deal_id"]]
            assert ev["overlap_sessions"] == overlap
            assert ev["exact_matches"] == row["exact_matches"]
            assert ev["tolerable_matches"] == row["tolerable_matches"]
            assert ev["material_conflicts"] == row["material_conflicts"]
    assert len(evidence["sessions"]) == totals["overlap_sessions"]
    for session in evidence["sessions"]:
        assert session["rule_version"] == "price_reconcile_v2"
        assert session["classification"] in {"EXACT", "TOLERABLE", "MATERIAL_CONFLICT"}
        assert "tiingo_raw_close" in session and "yahoo_raw_close" in session
    assert evidence["adjusted_close_used"] is False
    assert evidence["averaged"] is False
    assert RECONCILE_RULES["price_reconcile_v2"] == (0.01, 1e-4)


def test_committed_manifest_is_admitted_real_closes_without_duplicate_sessions():
    matrix = _load(MATRIX)
    manifest = _load(MANIFEST)
    prints = manifest["prints"]
    admitted = {r["deal_id"] for r in matrix["deals"] if r.get("prints_admitted") is True}
    assert {p["deal_id"] for p in prints} == admitted
    seen = set()
    for row in prints:
        assert row["source_name"] in ALLOWED_PROVIDERS
        assert row["provider"] in ALLOWED_PROVIDERS
        assert row["close_field_used"] == "close"
        blob = json.dumps(row).lower()
        assert "synthetic" not in blob
        key = (row["deal_id"], row.get("session_date") or row["observation_timestamp"])
        assert key not in seen
        seen.add(key)


def test_committed_proof_b_evidence_is_reconstructable():
    matrix = _load(MATRIX)
    identity = _load(IDENTITY)
    by_id = {r["deal_id"]: r for r in identity["deals"]}
    assert identity["credential_stored"] is False
    assert "api_token" not in json.dumps(identity).lower()
    b_only = 0
    for row in matrix["deals"]:
        proofs = row.get("identity_proofs") or []
        if row.get("canonical_status") != "CANONICALLY_ADMITTED":
            continue
        if "B_TIINGO_NAME_AND_LISTING_WINDOW" not in proofs:
            continue
        ev = by_id[row["deal_id"]]
        assert ev["proof_B_earned"] is True
        assert ev["names_agree"] is True
        assert ev["listing_window_covers_announcement"] is True
        assert ev["tiingo_provider_name"]
        assert ev["tiingo_listing_start"]
        assert ev["normalized_target_tokens"]
        assert ev["normalized_provider_tokens"]
        assert ev["provider_endpoint"].startswith("https://api.tiingo.com/tiingo/daily/")
        assert "token=" not in ev["provider_endpoint"]
        if proofs == ["B_TIINGO_NAME_AND_LISTING_WINDOW"]:
            b_only += 1
        if "A_OPENFIGI_MATCHED" in proofs:
            assert ev["openfigi"]["status"] == "MATCHED"
            assert ev["openfigi"]["figi"]
            assert ev["openfigi"]["proof_A"] is True
    assert b_only >= 1


def test_committed_cohort_rule_matches_matrix_and_keeps_historical_fingerprint():
    cohort = _load(COHORT)
    matrix = _load(MATRIX)
    assert cohort["inclusion_rules"]["reconcile_rule"] == "price_reconcile_v2"
    assert cohort["inclusion_rules"]["reconcile_rule"] == matrix["meta"]["reconcile_rule"]
    assert cohort["fingerprint_version"] == "cohort_fingerprint_v2"
    historical = cohort["historical_dataset_fingerprint"]
    assert historical["dataset_fingerprint"] == HISTORICAL_FINGERPRINT
    assert historical["fingerprint_version"] == "v1_includes_commit_sha"
    assert "commit_sha" not in cohort["fingerprinted_inputs"]
    assert cohort["code_sha"]
    assert cohort["dataset_fingerprint"] != historical["dataset_fingerprint"]
    assert RECONCILE_RULES["price_reconcile_v2"] == (0.01, 1e-4)


def test_committed_pit_flags_and_v1_diagnostic():
    pit = _load(PIT)
    manifest = _load(MANIFEST)
    diag = _load(DIAG)
    assert pit["DATE_ONLY_ANNOUNCEMENTS"] >= 1
    assert pit["ANNOUNCEMENT_DAY_AMBIGUOUS_PRINTS"] == sum(
        1 for row in manifest["prints"]
        if ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS in (row.get("pit_ordering_flags") or []))
    assert pit["RESOLUTION_DAY_AMBIGUOUS_PRINTS"] == sum(
        1 for row in manifest["prints"]
        if RESOLUTION_DAY_ORDERING_AMBIGUOUS in (row.get("pit_ordering_flags") or []))
    for row in manifest["prints"]:
        flags = row.get("pit_ordering_flags") or []
        if ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS in flags:
            assert row["announcement_time_precision"] == "DATE_ONLY"
        if RESOLUTION_DAY_ORDERING_AMBIGUOUS in flags:
            assert row["resolution_time_precision"] == "DATE_ONLY"
    assert diag["PRICE_COVERAGE_READY"] == "YES"
    assert diag["SPREAD_STRESS_V1_PANEL_VALID"] == "NO"
    assert diag["SPREAD_STRESS_V1_BLOCK_REASON"] == "FEATURE_TIME_RESOLUTION_TIMESTAMP_COLLISION"
    assert diag["SPREAD_STRESS_V1_MODEL_FIT"] == "NO"
    assert diag["PRE_RESOLUTION_PRINTS_AVAILABLE"] > 0
    assert diag["PANEL_ROWS_EXCLUDED_FEATURE_NOT_BEFORE_RESOLUTION"] > 0
    assert "insufficient historical price" not in json.dumps(diag).lower()
