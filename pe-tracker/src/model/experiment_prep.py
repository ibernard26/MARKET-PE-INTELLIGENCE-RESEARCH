"""Prepare (not execute) a chronological walk-forward experiment.

This module freezes cohort membership, reconstructs point-in-time training
rows, and computes authoritative dataset fingerprints per expanding window.

It deliberately does **not** call:
  - BreakModel.fit
  - walk_forward / chronological_split / fit_and_score
  - register_model
  - calibrate

Execution of the prepared protocol requires a separate human authorization
(see protocol.json → execution_authorized / AUTHORIZE FIRST REAL WALKFORWARD).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Optional

from ..config import COST_FN, COST_FP, COST_RATIO_GRID, MIN_SAMPLE_N, STRATEGY_VERSION
from ..research.bitemporal import normalize_as_of
from .cohort import ModelCohort
from .dataset import FEATURE_SCHEMA_VERSION, FEATURES, build_training_set
from .fingerprint import dataset_fingerprint
from .logistic import HYPERPARAMETERS, MIN_CLASS_N, MODEL_VERSION
from .validation import _in_window

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXP_DIR = ROOT / "data" / "experiments" / "first_walkforward_v1"


class ExperimentPrepError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def cohort_from_file(path: Path) -> ModelCohort:
    """Build an immutable ModelCohort from a frozen cohort.json."""
    d = load_json(path)
    c = ModelCohort.from_ids(
        cohort_id=d["cohort_id"],
        cohort_version=d["cohort_version"],
        description=d.get("description", ""),
        selection_method=d["selection_method"],
        outcome_blind=bool(d["outcome_blind"]),
        probability_calibration_eligible=bool(d["probability_calibration_eligible"]),
        deal_ids=d["deal_ids"],
        created_from_code_commit=d["created_from_code_commit"],
    )
    c.validate()
    if not d.get("deal_ids"):
        raise ExperimentPrepError("cohort deal_ids empty")
    if tuple(d["deal_ids"]) != c.deal_ids:
        raise ExperimentPrepError(
            "cohort.json deal_ids must be uniquely sorted to match ModelCohort.from_ids")
    if d.get("probability_calibration_eligible"):
        raise ExperimentPrepError(
            "first_walkforward_v1 forbids probability_calibration_eligible=true "
            "(sample ≠ population; see SAMPLING_FRAME.md)")
    return c


def assert_locked_contract(protocol: dict) -> None:
    """Fail closed if the frozen protocol drifts from live locked constants."""
    lc = protocol["locked_model_contract"]
    checks = [
        (lc["STRATEGY_VERSION"], STRATEGY_VERSION, "STRATEGY_VERSION"),
        (lc["MODEL_VERSION"], MODEL_VERSION, "MODEL_VERSION"),
        (lc["FEATURE_SCHEMA_VERSION"], FEATURE_SCHEMA_VERSION, "FEATURE_SCHEMA_VERSION"),
        (lc["C"], HYPERPARAMETERS["C"], "C"),
        (lc["penalty"], HYPERPARAMETERS["penalty"], "penalty"),
        (lc["solver"], HYPERPARAMETERS["solver"], "solver"),
        (lc["max_iter"], HYPERPARAMETERS["max_iter"], "max_iter"),
        (lc["class_weight"], HYPERPARAMETERS["class_weight"], "class_weight"),
        (lc["standardize"], HYPERPARAMETERS["standardize"], "standardize"),
        (lc["impute"], HYPERPARAMETERS["impute"], "impute"),
        (lc["calibration"], "none", "calibration"),
        (lc["MIN_SAMPLE_N"], MIN_SAMPLE_N, "MIN_SAMPLE_N"),
        (lc["MIN_CLASS_N"], MIN_CLASS_N, "MIN_CLASS_N"),
        (float(lc["COST_FN"]), float(COST_FN), "COST_FN"),
        (float(lc["COST_FP"]), float(COST_FP), "COST_FP"),
        (tuple(lc["COST_RATIO_GRID"]), tuple(COST_RATIO_GRID), "COST_RATIO_GRID"),
    ]
    for want, got, name in checks:
        if want != got:
            raise ExperimentPrepError(
                f"locked contract drift on {name}: protocol={want!r} code={got!r}")


def _row_summaries(rows: list[dict]) -> list[dict]:
    """Compact, order-stable row identity list (no feature dump)."""
    out = []
    for r in sorted(rows, key=lambda x: (x["deal_id"], x["feature_as_of"])):
        out.append({
            "deal_id": r["deal_id"],
            "feature_as_of": r["feature_as_of"],
            "label": r["label"],
            "label_known_at": r.get("label_known_at"),
        })
    return out


def prepare_walkforward_plan(
    conn: sqlite3.Connection,
    *,
    cohort: ModelCohort,
    protocol: dict,
    code_commit: str,
) -> dict:
    """Build the no-fit walk-forward preparation plan.

    Reconstructs PIT training sets, enforces training ⊆ cohort, and computes
    authoritative dataset fingerprints. Never fits a model.
    """
    if protocol.get("execution_authorized"):
        raise ExperimentPrepError(
            "protocol.execution_authorized is true, but experiment_prep only prepares; "
            "refuse to proceed in prep mode")
    assert_locked_contract(protocol)
    cohort.validate(conn)

    store_ids = {r[0] for r in conn.execute("SELECT deal_id FROM deals")}
    missing = [d for d in cohort.deal_ids if d not in store_ids]
    if missing:
        raise ExperimentPrepError(f"cohort deal_ids missing from store: {missing}")
    extra = sorted(store_ids - set(cohort.deal_ids))
    if extra:
        raise ExperimentPrepError(
            f"store contains deals outside frozen cohort (fail closed): {extra}")

    wf = protocol["walk_forward"]
    cutoffs = sorted(wf["cutoffs"], key=normalize_as_of)
    horizon = wf["horizon"]
    evalset = build_training_set(horizon, conn)
    # Restrict eval rows to cohort (identity freeze).
    eval_rows = [r for r in evalset["rows"] if r["deal_id"] in set(cohort.deal_ids)]

    windows = []
    for k, cutoff in enumerate(cutoffs):
        end = cutoffs[k + 1] if k + 1 < len(cutoffs) else horizon
        train = build_training_set(cutoff, conn)
        train_rows = [r for r in train["rows"] if r["deal_id"] in set(cohort.deal_ids)]
        outside = sorted({r["deal_id"] for r in train_rows} - set(cohort.deal_ids))
        if outside:
            raise ExperimentPrepError(f"training deals outside cohort: {outside}")
        test_rows = [r for r in eval_rows if _in_window(r, cutoff, end)]
        n = len(train_rows)
        n_pos = sum(int(r["label"]) for r in train_rows)
        n_neg = n - n_pos
        fp = dataset_fingerprint(train_rows) if train_rows else None
        test_fp = dataset_fingerprint(test_rows) if test_rows else None
        windows.append({
            "window": k,
            "train_cutoff": cutoff,
            "test_start": cutoff,
            "test_end": end,
            "n_train": n,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "sample_prevalence": (n_pos / n) if n else None,
            "meets_min_sample_n": n >= MIN_SAMPLE_N,
            "meets_min_class_n": n_pos >= MIN_CLASS_N and n_neg >= MIN_CLASS_N,
            "n_censored_at_cutoff": train["n_censored"],
            "dataset_fingerprint": fp,
            "n_test": len(test_rows),
            "test_pos": sum(int(r["label"]) for r in test_rows),
            "test_neg": len(test_rows) - sum(int(r["label"]) for r in test_rows),
            "test_dataset_fingerprint": test_fp,
            "train_rows": _row_summaries(train_rows),
            "test_deal_ids": sorted({r["deal_id"] for r in test_rows}),
            "fit_executed": False,
            "status": "PREPARED_NOT_FITTED",
        })

    return {
        "experiment_id": protocol["experiment_id"],
        "status": "PREPARED_NOT_EXECUTED",
        "execution_authorized": False,
        "code_commit": code_commit,
        "manifest_freeze_commit": protocol["dataset_freeze"]["manifest_freeze_commit"],
        "cohort_id": cohort.cohort_id,
        "cohort_version": cohort.cohort_version,
        "cohort_n": len(cohort.deal_ids),
        "feature_names": list(FEATURES),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "calibration": "none",
        "horizon": horizon,
        "cutoffs": cutoffs,
        "n_labeled_at_horizon": len(eval_rows),
        "n_pos_at_horizon": sum(int(r["label"]) for r in eval_rows),
        "n_censored_at_horizon": evalset["n_censored"],
        "windows": windows,
        "notes": [
            "Fingerprints are authoritative hashes of reconstructed PIT training rows.",
            "No BreakModel.fit / walk_forward / register_model was invoked.",
            "sample_prevalence is the training-row class fraction, not a population rate.",
            "Thin out-of-sample test windows are reported honestly; they are not padded.",
        ],
    }


def refuse_execution(protocol: dict) -> None:
    """Hard stop if someone attempts to execute without authorization."""
    if not protocol.get("execution_authorized"):
        raise ExperimentPrepError(
            "FIRST REAL WALK-FORWARD NOT AUTHORIZED "
            f"(need {protocol.get('authorization_command_required')!r}; "
            "execution_authorized is false)")


def write_plan(plan: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, sort_keys=False) + "\n")


def _default_commit() -> str:
    freeze = DEFAULT_EXP_DIR / "cohort.json"
    return load_json(freeze)["created_from_code_commit"]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exp-dir", type=Path, default=DEFAULT_EXP_DIR)
    ap.add_argument("--out", type=Path, default=None,
                    help="Write plan JSON (default: <exp-dir>/plan.json)")
    ap.add_argument("--code-commit", default=None,
                    help="Code commit recorded in the plan (default: cohort freeze commit)")
    ap.add_argument("--execute", action="store_true",
                    help="Forbidden until protocol.execution_authorized is true")
    args = ap.parse_args(argv)

    protocol = load_json(args.exp_dir / "protocol.json")
    if args.execute:
        # Delegate to the authorized execute module (fail-closed if not authorized).
        from .experiment_execute import main as execute_main
        return execute_main(["--exp-dir", str(args.exp_dir)])

    if protocol.get("execution_authorized"):
        raise ExperimentPrepError(
            "protocol.execution_authorized is true; refuse prep regeneration "
            "(frozen plan.json must not be rewritten under an authorized protocol)")

    from ..config import ROOT as PKG_ROOT
    from ..db import _migrate_model_run_identity, _upgrade_model_registry_columns
    from ..ingest.historical import ingest
    from ..ingest.providers.sec_edgar import SECEdgarProvider

    # Ephemeral in-memory projection of the frozen reviewed manifest (not a
    # competing on-disk writer). Schema matches the canonical SQLite contract.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((PKG_ROOT / "schema.sql").read_text())
    _upgrade_model_registry_columns(conn)
    _migrate_model_run_identity(conn)

    manifest = ROOT / "data" / "sec_deal_manifest.json"
    out = ingest(SECEdgarProvider(manifest), conn)
    if out.get("n_quarantined"):
        raise ExperimentPrepError(f"quarantined deals during prep ingest: {out}")

    cohort = cohort_from_file(args.exp_dir / "cohort.json")
    commit = args.code_commit or _default_commit()
    plan = prepare_walkforward_plan(
        conn, cohort=cohort, protocol=protocol, code_commit=commit)
    out_path = args.out or (args.exp_dir / "plan.json")
    write_plan(plan, out_path)
    print(json.dumps({
        "wrote": str(out_path),
        "experiment_id": plan["experiment_id"],
        "status": plan["status"],
        "cohort_n": plan["cohort_n"],
        "windows": [
            {"window": w["window"], "train_cutoff": w["train_cutoff"],
             "n_train": w["n_train"], "n_test": w["n_test"],
             "dataset_fingerprint": w["dataset_fingerprint"],
             "fit_executed": w["fit_executed"]}
            for w in plan["windows"]
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
