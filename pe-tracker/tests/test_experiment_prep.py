"""Preparation freeze for first_walkforward_v1 — never fits the real cohort."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import MIN_SAMPLE_N, STRATEGY_VERSION
from src.ingest.historical import SourceRef, ingest
from src.model.cohort import ModelCohort
from src.model.dataset import FEATURE_SCHEMA_VERSION
from src.model.experiment_prep import (
    ExperimentPrepError,
    assert_locked_contract,
    cohort_from_file,
    prepare_walkforward_plan,
    refuse_execution,
)
from src.model.logistic import MODEL_VERSION
from tests.test_historical_ingest import ListProvider, mem, rec

EXP = Path(__file__).resolve().parents[1] / "data" / "experiments" / "first_walkforward_v1"


def _ref(ts: str) -> SourceRef:
    return SourceRef("TEST SOURCE", "https://example.test/doc",
                     source_timestamp=ts, known_at=ts)


def _deal(deal_id: str, ann: str, resolution: str, res: str):
    return rec(
        deal_id,
        announcement_timestamp=ann,
        announcement_source=_ref(ann),
        terms_source=_ref(ann),
        resolution=resolution,
        resolution_timestamp=res,
        resolution_source=_ref(res),
    )


def test_frozen_cohort_file_matches_modelcohort_contract():
    c = cohort_from_file(EXP / "cohort.json")
    assert c.cohort_id == "sec_reviewed_corpus_batch8"
    assert c.cohort_version == "v1"
    assert c.outcome_blind is False
    assert c.probability_calibration_eligible is False
    assert len(c.deal_ids) == 62
    assert c.deal_ids == tuple(sorted(c.deal_ids))
    raw = json.loads((EXP / "cohort.json").read_text())
    assert "DEAL-KLAC-LRCX-2015" not in raw["deal_ids"]
    assert "DEAL-AKRX-FRESENIUS-2017" not in raw["deal_ids"]
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "sec_deal_manifest.json").read_text()
    )
    # Frozen walk-forward cohort is a subset of the growing canonical corpus.
    assert set(raw["deal_ids"]).issubset({d["deal_id"] for d in manifest["deals"]})
    assert len(manifest["deals"]) >= len(raw["deal_ids"])


def test_protocol_locked_contract_matches_code():
    protocol = json.loads((EXP / "protocol.json").read_text())
    assert protocol["execution_authorized"] is False
    assert protocol["status"] == "PREPARED_NOT_EXECUTED"
    assert_locked_contract(protocol)
    assert protocol["locked_model_contract"]["STRATEGY_VERSION"] == STRATEGY_VERSION
    assert protocol["locked_model_contract"]["MODEL_VERSION"] == MODEL_VERSION
    assert protocol["locked_model_contract"]["FEATURE_SCHEMA_VERSION"] == FEATURE_SCHEMA_VERSION
    assert protocol["locked_model_contract"]["calibration"] == "none"
    assert protocol["walk_forward"]["cutoffs"] == [
        "2021-06-30", "2023-06-30", "2025-06-30"]


def test_refuse_execution_without_authorization():
    protocol = json.loads((EXP / "protocol.json").read_text())
    with pytest.raises(ExperimentPrepError, match="NOT AUTHORIZED"):
        refuse_execution(protocol)


def test_prepare_plan_fingerprints_without_fitting():
    """Synthetic expanding windows: fingerprints stable; fit_executed always false."""
    c = mem()
    deals = [
        _deal("D01", "2020-01-10T08:00:00", "closed", "2020-06-01T16:00:00"),
        _deal("D02", "2020-03-10T08:00:00", "terminated", "2020-09-01T16:00:00"),
        _deal("D03", "2021-02-10T08:00:00", "closed", "2021-08-01T16:00:00"),
        _deal("D04", "2021-05-10T08:00:00", "terminated", "2021-11-01T16:00:00"),
        _deal("D05", "2022-01-10T08:00:00", "closed", "2022-07-01T16:00:00"),
    ]
    ingest(ListProvider(deals), c)
    cohort = ModelCohort.from_ids(
        "syn", "v1", "synthetic", "unit_test", False, False,
        [f"D0{i}" for i in range(1, 6)], "deadbeef")
    protocol = {
        "experiment_id": "synthetic_prep",
        "execution_authorized": False,
        "dataset_freeze": {"manifest_freeze_commit": "deadbeef"},
        "locked_model_contract": {
            "STRATEGY_VERSION": STRATEGY_VERSION,
            "MODEL_VERSION": MODEL_VERSION,
            "FEATURE_SCHEMA_VERSION": FEATURE_SCHEMA_VERSION,
            "penalty": "l2", "C": 1.0, "solver": "lbfgs", "max_iter": 1000,
            "class_weight": None, "standardize": True,
            "impute": "train_median+missing_indicator",
            "calibration": "none",
            "MIN_SAMPLE_N": MIN_SAMPLE_N, "MIN_CLASS_N": 2,
            "COST_FN": 15, "COST_FP": 1, "COST_RATIO_GRID": [5, 10, 15, 20],
        },
        "walk_forward": {
            "cutoffs": ["2020-12-31", "2021-12-31"],
            "horizon": "2022-12-31",
        },
    }
    plan = prepare_walkforward_plan(
        c, cohort=cohort, protocol=protocol, code_commit="deadbeef")
    assert plan["status"] == "PREPARED_NOT_EXECUTED"
    assert plan["execution_authorized"] is False
    assert all(w["fit_executed"] is False for w in plan["windows"])
    assert all(w["status"] == "PREPARED_NOT_FITTED" for w in plan["windows"])
    again = prepare_walkforward_plan(
        c, cohort=cohort, protocol=protocol, code_commit="deadbeef")
    for a, b in zip(plan["windows"], again["windows"]):
        assert a["dataset_fingerprint"] == b["dataset_fingerprint"]
    assert c.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 0


def test_prepare_rejects_authorized_flag_in_prep_mode():
    c = mem()
    ingest(ListProvider([rec("A1")]), c)
    cohort = ModelCohort.from_ids(
        "syn", "v1", "", "unit_test", False, False, ["A1"], "x")
    protocol = {
        "experiment_id": "x",
        "execution_authorized": True,
        "dataset_freeze": {"manifest_freeze_commit": "x"},
        "locked_model_contract": {
            "STRATEGY_VERSION": STRATEGY_VERSION,
            "MODEL_VERSION": MODEL_VERSION,
            "FEATURE_SCHEMA_VERSION": FEATURE_SCHEMA_VERSION,
            "penalty": "l2", "C": 1.0, "solver": "lbfgs", "max_iter": 1000,
            "class_weight": None, "standardize": True,
            "impute": "train_median+missing_indicator",
            "calibration": "none",
            "MIN_SAMPLE_N": MIN_SAMPLE_N, "MIN_CLASS_N": 2,
            "COST_FN": 15, "COST_FP": 1, "COST_RATIO_GRID": [5, 10, 15, 20],
        },
        "walk_forward": {"cutoffs": ["2025-01-01"], "horizon": "2026-01-01"},
    }
    with pytest.raises(ExperimentPrepError, match="only prepares"):
        prepare_walkforward_plan(c, cohort=cohort, protocol=protocol, code_commit="x")


def test_prepare_rejects_store_outside_cohort():
    c = mem()
    ingest(ListProvider([rec("IN"), rec("OUT")]), c)
    cohort = ModelCohort.from_ids(
        "syn", "v1", "", "unit_test", False, False, ["IN"], "x")
    protocol = json.loads((EXP / "protocol.json").read_text())
    protocol = dict(protocol)
    protocol["execution_authorized"] = False
    protocol["walk_forward"] = {"cutoffs": ["2025-01-01"], "horizon": "2026-01-01"}
    with pytest.raises(ExperimentPrepError, match="outside frozen cohort"):
        prepare_walkforward_plan(c, cohort=cohort, protocol=protocol, code_commit="x")
