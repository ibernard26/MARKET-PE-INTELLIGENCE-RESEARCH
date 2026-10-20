"""Authorized execute path for first_walkforward_v1 — synthetic fits only here.

The real N=62 cohort is exercised by `python -m src.model.experiment_execute`
after protocol.execution_authorized is true; unit tests use a tiny synthetic
store so CI never depends on network or the SEC manifest ingest path alone.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import MIN_SAMPLE_N, STRATEGY_VERSION
from src.ingest.historical import SourceRef, ingest
from src.model.cohort import ModelCohort
from src.model.dataset import FEATURE_SCHEMA_VERSION
from src.model.experiment_execute import (
    ExperimentExecuteError,
    execute_walkforward,
    reconstruct_windows,
)
from src.model.experiment_prep import ExperimentPrepError, refuse_execution
from src.model.fingerprint import dataset_fingerprint
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


def _locked_contract() -> dict:
    return {
        "STRATEGY_VERSION": STRATEGY_VERSION,
        "MODEL_VERSION": MODEL_VERSION,
        "FEATURE_SCHEMA_VERSION": FEATURE_SCHEMA_VERSION,
        "penalty": "l2", "C": 1.0, "solver": "lbfgs", "max_iter": 1000,
        "class_weight": None, "standardize": True,
        "impute": "train_median+missing_indicator",
        "calibration": "none",
        "MIN_SAMPLE_N": MIN_SAMPLE_N, "MIN_CLASS_N": 2,
        "COST_FN": 15, "COST_FP": 1, "COST_RATIO_GRID": [5, 10, 15, 20],
    }


def _synthetic_corpus(n_train_closed: int = 12, n_train_term: int = 12,
                      n_test_closed: int = 4, n_test_term: int = 4):
    """Enough labeled rows for MIN_SAMPLE_N with both classes + a thin OOS window."""
    c = mem()
    deals = []
    # Train window (labels known by 2021-06-30): >= MIN_SAMPLE_N, both classes
    for i in range(n_train_closed):
        month = (i % 9) + 1
        deals.append(_deal(
            f"C{i:02d}", f"2019-{month:02d}-10T08:00:00",
            "closed", f"2020-{month:02d}-15T16:00:00"))
    for i in range(n_train_term):
        month = (i % 9) + 1
        deals.append(_deal(
            f"T{i:02d}", f"2019-{month:02d}-12T08:00:00",
            "terminated", f"2020-{month:02d}-20T16:00:00"))
    # OOS test window: feature_as_of in (2021-06-30, 2022-12-31]
    for i in range(n_test_closed):
        deals.append(_deal(
            f"XC{i:02d}", "2021-09-10T08:00:00",
            "closed", "2022-03-01T16:00:00"))
    for i in range(n_test_term):
        deals.append(_deal(
            f"XT{i:02d}", "2021-10-10T08:00:00",
            "terminated", "2022-04-01T16:00:00"))
    ingest(ListProvider(deals), c)
    ids = [d.deal_id for d in deals]
    cohort = ModelCohort.from_ids(
        "syn_exec", "v1", "synthetic execute", "unit_test", False, False,
        ids, "deadbeef")
    protocol = {
        "experiment_id": "synthetic_execute",
        "execution_authorized": True,
        "authorization_command_required": "AUTHORIZE FIRST REAL WALKFORWARD",
        "dataset_freeze": {"manifest_freeze_commit": "deadbeef"},
        "locked_model_contract": _locked_contract(),
        "walk_forward": {
            "cutoffs": ["2021-06-30"],
            "horizon": "2022-12-31",
            "calibration": False,
            "hyperparameter_tuning": False,
        },
        "reporting_contract": {
            "population_calibrated_probability_claim": False,
            "alpha_or_pnl_claim": False,
        },
    }
    return c, cohort, protocol


def test_refuse_still_blocks_unauthorized_execute():
    protocol = {"execution_authorized": False,
                "authorization_command_required": "AUTHORIZE FIRST REAL WALKFORWARD"}
    with pytest.raises(ExperimentPrepError, match="NOT AUTHORIZED"):
        refuse_execution(protocol)


def test_execute_registers_model_run_ids_and_scores_oos():
    c, cohort, protocol = _synthetic_corpus()
    live = reconstruct_windows(c, cohort=cohort, protocol=protocol)
    assert live["windows"][0]["n_train"] >= MIN_SAMPLE_N
    frozen_plan = {
        "cohort_n": live["cohort_n"],
        "cutoffs": live["cutoffs"],
        "windows": [
            {
                "window": w["window"],
                "train_cutoff": w["train_cutoff"],
                "test_end": w["test_end"],
                "n_train": w["n_train"],
                "n_test": w["n_test"],
                "dataset_fingerprint": w["dataset_fingerprint"],
                "test_dataset_fingerprint": w["test_dataset_fingerprint"],
            }
            for w in live["windows"]
        ],
    }
    results = execute_walkforward(
        c, cohort=cohort, protocol=protocol, frozen_plan=frozen_plan)
    assert results["status"] == "EXECUTED"
    assert results["calibration"] == "none"
    assert len(results["windows"]) == 1
    w0 = results["windows"][0]
    assert w0["fit_executed"] is True
    assert w0["model_version"] == MODEL_VERSION
    assert w0["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert len(w0["model_run_id"]) == 64
    assert w0["claims"]["calibration_applied"] is False
    assert w0["claims"]["alpha_or_pnl"] is False
    assert "probability_metrics" in w0
    n_reg = c.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0]
    assert n_reg == 1
    row = dict(c.execute(
        "SELECT model_run_id, cohort_id, dataset_fingerprint FROM model_registry"
    ).fetchone())
    assert row["model_run_id"] == w0["model_run_id"]
    assert row["cohort_id"] == "syn_exec"
    assert row["dataset_fingerprint"] == w0["dataset_fingerprint"]


def test_execute_fails_closed_on_fingerprint_drift():
    c, cohort, protocol = _synthetic_corpus()
    live = reconstruct_windows(c, cohort=cohort, protocol=protocol)
    bad_plan = {
        "cohort_n": live["cohort_n"],
        "cutoffs": live["cutoffs"],
        "windows": [
            {
                "window": w["window"],
                "train_cutoff": w["train_cutoff"],
                "test_end": w["test_end"],
                "n_train": w["n_train"],
                "n_test": w["n_test"],
                "dataset_fingerprint": "0" * 64,
                "test_dataset_fingerprint": w["test_dataset_fingerprint"],
            }
            for w in live["windows"]
        ],
    }
    with pytest.raises(ExperimentExecuteError, match="dataset_fingerprint"):
        execute_walkforward(
            c, cohort=cohort, protocol=protocol, frozen_plan=bad_plan)


def test_frozen_protocol_is_authorized_for_first_walkforward():
    protocol = json.loads((EXP / "protocol.json").read_text())
    assert protocol["execution_authorized"] is True
    assert protocol["experiment_id"] == "first_walkforward_v1"
    assert protocol["locked_model_contract"]["MODEL_VERSION"] == MODEL_VERSION
    assert protocol["locked_model_contract"]["calibration"] == "none"
    assert protocol["walk_forward"]["hyperparameter_tuning"] is False
    assert protocol["walk_forward"]["calibration"] is False
    plan = json.loads((EXP / "plan.json").read_text())
    assert plan["cohort_n"] == 62
    assert len(plan["windows"]) == 3
    # Fingerprints remain the frozen prep values (authoritative).
    assert plan["windows"][0]["dataset_fingerprint"].startswith("8d0e153c")
    assert plan["windows"][1]["dataset_fingerprint"].startswith("369cf517")
    assert plan["windows"][2]["dataset_fingerprint"].startswith("a15992b4")


def test_fingerprint_helper_stable_on_synthetic_rows():
    c, cohort, protocol = _synthetic_corpus()
    live = reconstruct_windows(c, cohort=cohort, protocol=protocol)
    rows = live["windows"][0]["train_rows"]
    assert dataset_fingerprint(rows) == dataset_fingerprint(list(rows))
