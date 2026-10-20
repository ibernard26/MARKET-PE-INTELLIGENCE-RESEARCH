"""Execute the frozen first_walkforward_v1 protocol (authorized fits only).

Requires protocol.json → execution_authorized = true. Reconstructs the same
PIT windows as experiment_prep, asserts fingerprints against the frozen
plan.json, fits break_logit_v1 / fs_v1 with calibration=none, freezes t* from
training only, grades untouched test windows, and registers each artifact by
model_run_id.

Does not calibrate, tune hyperparameters, alter EVENT_RULES / fs_v1, or make
population-probability / alpha / P&L claims.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from ..config import MIN_SAMPLE_N, STRATEGY_VERSION
from ..research.bitemporal import normalize_as_of
from .cohort import ModelCohort
from .dataset import FEATURE_SCHEMA_VERSION, FEATURES, build_training_set
from .experiment_prep import (
    DEFAULT_EXP_DIR,
    ExperimentPrepError,
    assert_locked_contract,
    cohort_from_file,
    load_json,
    refuse_execution,
)
from .fingerprint import dataset_fingerprint
from .logistic import MODEL_VERSION, BreakModel, InsufficientDataError
from .registry import code_commit, register_model
from .validation import _in_window, fit_and_score

ROOT = Path(__file__).resolve().parents[2]


class ExperimentExecuteError(RuntimeError):
    pass


def _jsonable(obj: Any) -> Any:
    """Convert numpy / nested structures to plain JSON types."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, (int,)):
        return int(obj)
    if isinstance(obj, float):
        return float(obj)
    if hasattr(obj, "item"):  # numpy scalar
        try:
            return obj.item()
        except Exception:
            pass
    return obj


def _open_ephemeral_store() -> sqlite3.Connection:
    from ..config import ROOT as PKG_ROOT
    from ..db import _migrate_model_run_identity, _upgrade_model_registry_columns
    from ..ingest.historical import ingest
    from ..ingest.providers.sec_edgar import SECEdgarProvider

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((PKG_ROOT / "schema.sql").read_text())
    _upgrade_model_registry_columns(conn)
    _migrate_model_run_identity(conn)

    manifest = ROOT / "data" / "sec_deal_manifest.json"
    out = ingest(SECEdgarProvider(manifest), conn)
    if out.get("n_quarantined"):
        raise ExperimentExecuteError(f"quarantined deals during execute ingest: {out}")
    return conn


def _assert_cohort_store_identity(conn: sqlite3.Connection, cohort: ModelCohort) -> None:
    store_ids = {r[0] for r in conn.execute("SELECT deal_id FROM deals")}
    missing = [d for d in cohort.deal_ids if d not in store_ids]
    if missing:
        raise ExperimentExecuteError(f"cohort deal_ids missing from store: {missing}")
    extra = sorted(store_ids - set(cohort.deal_ids))
    if extra:
        raise ExperimentExecuteError(
            f"store contains deals outside frozen cohort (fail closed): {extra}")


def _assert_fingerprints_match_plan(live: dict, frozen_plan: dict) -> None:
    if live["cohort_n"] != frozen_plan["cohort_n"]:
        raise ExperimentExecuteError(
            f"cohort_n drift: live={live['cohort_n']} plan={frozen_plan['cohort_n']}")
    if live["cutoffs"] != frozen_plan["cutoffs"]:
        raise ExperimentExecuteError(
            f"cutoffs drift: live={live['cutoffs']} plan={frozen_plan['cutoffs']}")
    if len(live["windows"]) != len(frozen_plan["windows"]):
        raise ExperimentExecuteError("window count drift vs frozen plan")
    for a, b in zip(live["windows"], frozen_plan["windows"]):
        for key in ("window", "train_cutoff", "test_end", "n_train", "n_test",
                    "dataset_fingerprint", "test_dataset_fingerprint"):
            if a.get(key) != b.get(key):
                raise ExperimentExecuteError(
                    f"window {a.get('window')} {key} drift: "
                    f"live={a.get(key)!r} plan={b.get(key)!r}")


def reconstruct_windows(
    conn: sqlite3.Connection,
    *,
    cohort: ModelCohort,
    protocol: dict,
) -> dict:
    """Rebuild PIT train/test windows (no fit). Same geometry as experiment_prep."""
    assert_locked_contract(protocol)
    cohort.validate(conn)
    _assert_cohort_store_identity(conn, cohort)

    wf = protocol["walk_forward"]
    cutoffs = sorted(wf["cutoffs"], key=normalize_as_of)
    horizon = wf["horizon"]
    cohort_ids = set(cohort.deal_ids)
    evalset = build_training_set(horizon, conn)
    eval_rows = [r for r in evalset["rows"] if r["deal_id"] in cohort_ids]

    windows = []
    for k, cutoff in enumerate(cutoffs):
        end = cutoffs[k + 1] if k + 1 < len(cutoffs) else horizon
        train = build_training_set(cutoff, conn)
        train_rows = [r for r in train["rows"] if r["deal_id"] in cohort_ids]
        outside = sorted({r["deal_id"] for r in train_rows} - cohort_ids)
        if outside:
            raise ExperimentExecuteError(f"training deals outside cohort: {outside}")
        test_rows = [r for r in eval_rows if _in_window(r, cutoff, end)]
        n = len(train_rows)
        n_pos = sum(int(r["label"]) for r in train_rows)
        n_neg = n - n_pos
        if n < MIN_SAMPLE_N:
            raise ExperimentExecuteError(
                f"window {k} n_train={n} < MIN_SAMPLE_N={MIN_SAMPLE_N}")
        if n_pos < 2 or n_neg < 2:
            raise ExperimentExecuteError(
                f"window {k} class counts insufficient: pos={n_pos} neg={n_neg}")
        windows.append({
            "window": k,
            "train_cutoff": cutoff,
            "test_start": cutoff,
            "test_end": end,
            "n_train": n,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "sample_prevalence": n_pos / n,
            "n_censored_at_cutoff": train["n_censored"],
            "dataset_fingerprint": dataset_fingerprint(train_rows),
            "n_test": len(test_rows),
            "test_pos": sum(int(r["label"]) for r in test_rows),
            "test_neg": len(test_rows) - sum(int(r["label"]) for r in test_rows),
            "test_dataset_fingerprint": (
                dataset_fingerprint(test_rows) if test_rows else None),
            "train_rows": train_rows,
            "test_rows": test_rows,
            "training_set": {
                "cutoff": cutoff,
                "rows": train_rows,
                "n": n,
                "n_pos": n_pos,
                "n_neg": n_neg,
            },
        })
    return {
        "cohort_n": len(cohort.deal_ids),
        "cutoffs": cutoffs,
        "horizon": horizon,
        "n_labeled_at_horizon": len(eval_rows),
        "n_pos_at_horizon": sum(int(r["label"]) for r in eval_rows),
        "n_censored_at_horizon": evalset["n_censored"],
        "windows": windows,
    }


def execute_window(
    conn: sqlite3.Connection,
    *,
    window: dict,
    cohort: ModelCohort,
) -> dict:
    """Fit break_logit_v1, register by model_run_id, grade OOS (no calibration)."""
    train_rows = window["train_rows"]
    test_rows = window["test_rows"]
    training_set = window["training_set"]
    fp = window["dataset_fingerprint"]

    scored = fit_and_score(train_rows, test_rows, min_n=MIN_SAMPLE_N)
    if scored.get("status") != "fitted":
        raise ExperimentExecuteError(
            f"window {window['window']} fit failed: {scored.get('status')} "
            f"{scored.get('reason')}")

    # Re-fit once for registration; break_logit_v1 is deterministic for fixed data.
    xs = [r["x"] for r in train_rows]
    ys = [int(r["label"]) for r in train_rows]
    try:
        model = BreakModel().fit(xs, ys, min_n=MIN_SAMPLE_N)
    except InsufficientDataError as exc:
        raise ExperimentExecuteError(
            f"window {window['window']} register fit failed: {exc}") from exc

    if model.coefficients() != scored.get("coefficients"):
        raise ExperimentExecuteError(
            f"window {window['window']}: register fit coefficients != scored fit "
            "(non-deterministic fit; refuse)")

    meta = register_model(
        model, training_set, conn, cohort=cohort, fingerprint=fp)

    model_block = scored.get("model") or {}
    pm = model_block.get("probability_metrics") or {}
    return {
        "window": window["window"],
        "train_cutoff": window["train_cutoff"],
        "test_start": window["test_start"],
        "test_end": window["test_end"],
        "n_train": window["n_train"],
        "n_pos": window["n_pos"],
        "n_neg": window["n_neg"],
        "sample_prevalence": window["sample_prevalence"],
        "n_test": window["n_test"],
        "test_pos": window["test_pos"],
        "test_neg": window["test_neg"],
        "test_prevalence": scored.get("test_prevalence"),
        "dataset_fingerprint": fp,
        "test_dataset_fingerprint": window["test_dataset_fingerprint"],
        "model_run_id": meta["model_run_id"],
        "model_version": MODEL_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "calibration": "none",
        "code_commit": meta["code_commit"],
        "cohort_id": meta["cohort_id"],
        "cohort_version": meta["cohort_version"],
        "t_star_frozen": scored.get("t_star_frozen"),
        "threshold_selection": model_block.get("threshold_selection"),
        "frozen_policy": model_block.get("frozen_policy"),
        "probability_metrics": pm,
        "baseline_constant": scored.get("baseline_constant"),
        "baseline_spread": scored.get("baseline_spread"),
        "coefficients": scored.get("coefficients"),
        "fit_executed": True,
        "status": "FITTED_AND_REGISTERED",
        "sufficient_oos_sample": bool(pm.get("sufficient_sample")),
        "claims": {
            "population_calibrated_probability": False,
            "alpha_or_pnl": False,
            "hyperparameter_tuning": False,
            "calibration_applied": False,
        },
    }


def execute_walkforward(
    conn: sqlite3.Connection,
    *,
    cohort: ModelCohort,
    protocol: dict,
    frozen_plan: dict,
) -> dict:
    """Full authorized execute: fingerprint gate → fit → register → OOS metrics."""
    refuse_execution(protocol)  # raises if NOT authorized
    if not protocol.get("execution_authorized"):
        raise ExperimentExecuteError("execution_authorized must be true")
    if protocol.get("walk_forward", {}).get("calibration"):
        raise ExperimentExecuteError("protocol forbids calibration=true")
    if protocol.get("walk_forward", {}).get("hyperparameter_tuning"):
        raise ExperimentExecuteError("protocol forbids hyperparameter_tuning=true")

    live = reconstruct_windows(conn, cohort=cohort, protocol=protocol)
    _assert_fingerprints_match_plan(
        {
            "cohort_n": live["cohort_n"],
            "cutoffs": live["cutoffs"],
            "windows": [
                {k: w[k] for k in (
                    "window", "train_cutoff", "test_end", "n_train", "n_test",
                    "dataset_fingerprint", "test_dataset_fingerprint")}
                for w in live["windows"]
            ],
        },
        frozen_plan,
    )

    results_windows = []
    for w in live["windows"]:
        results_windows.append(execute_window(conn, window=w, cohort=cohort))

    registry_rows = [
        dict(r) for r in conn.execute(
            "SELECT model_run_id, model_id, model_version, feature_schema_version, "
            "training_cutoff, n_train, n_pos, n_neg, sample_prevalence, "
            "cohort_id, cohort_version, dataset_fingerprint, code_commit, "
            "calibration, fit_timestamp FROM model_registry ORDER BY training_cutoff"
        )
    ]
    # Parse JSON calibration column if stored as text
    for row in registry_rows:
        cal = row.get("calibration")
        if isinstance(cal, str):
            try:
                row["calibration"] = json.loads(cal)
            except json.JSONDecodeError:
                pass

    return _jsonable({
        "experiment_id": protocol["experiment_id"],
        "status": "EXECUTED",
        "execution_authorized": True,
        "authorization": protocol.get("authorization_command_required"),
        "code_commit_at_execute": code_commit(),
        "manifest_freeze_commit": protocol["dataset_freeze"]["manifest_freeze_commit"],
        "cohort_id": cohort.cohort_id,
        "cohort_version": cohort.cohort_version,
        "cohort_n": live["cohort_n"],
        "feature_names": list(FEATURES),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "calibration": "none",
        "horizon": live["horizon"],
        "cutoffs": live["cutoffs"],
        "n_labeled_at_horizon": live["n_labeled_at_horizon"],
        "n_pos_at_horizon": live["n_pos_at_horizon"],
        "n_censored_at_horizon": live["n_censored_at_horizon"],
        "windows": results_windows,
        "registry": registry_rows,
        "reporting_contract": protocol.get("reporting_contract"),
        "notes": [
            "Out-of-time metrics only; t* frozen from training in-sample predictions.",
            "sample_prevalence / pi are sample class fractions, not population rates.",
            "Thin OOS windows reported honestly; sufficient_oos_sample flags n < MIN_SAMPLE_N.",
            "No calibration, no hyperparameter tuning, no alpha/P&L claim.",
            "Each window artifact is identified by model_run_id in model_registry.",
        ],
    })


def write_results(results: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, sort_keys=False) + "\n")


def write_metrics_report(results: dict, path: Path) -> None:
    """Human-readable OOS metrics report — no alpha / calibration claims."""
    lines = [
        "# first_walkforward_v1 — out-of-time metrics",
        "",
        f"**Status:** `{results['status']}`",
        f"**Cohort:** `{results['cohort_id']}` `{results['cohort_version']}` "
        f"(N={results['cohort_n']})",
        f"**Model:** `{results['model_version']}` / `{results['feature_schema_version']}` "
        f"/ `{results['strategy_version']}`",
        f"**Calibration:** `{results['calibration']}` (not applied)",
        f"**Code commit at execute:** `{results['code_commit_at_execute']}`",
        "",
        "Claims explicitly **not** made: population-calibrated probabilities, "
        "alpha / P&L, hyperparameter tuning, EVENT_RULES or fs_v1 changes.",
        "",
        "## Per-window out-of-time results",
        "",
        "| W | Train cutoff | n_train | π_train | n_test | π_test | "
        "ROC AUC | AP | AP baseline π | Brier | log loss | t* | model_run_id |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for w in results["windows"]:
        pm = w.get("probability_metrics") or {}
        roc = pm.get("roc_auc")
        ap = pm.get("average_precision")
        api = pm.get("average_precision_baseline_pi")
        brier = pm.get("brier")
        ll = pm.get("log_loss")
        tstar = w.get("t_star_frozen")
        flag = "" if w.get("sufficient_oos_sample") else " †"
        lines.append(
            "| {w} | {cut} | {ntr} | {ptr:.4f} | {nte}{flag} | {pte} | "
            "{roc} | {ap} | {api} | {brier} | {ll} | {tstar} | `{rid}` |".format(
                w=w["window"],
                cut=w["train_cutoff"],
                ntr=w["n_train"],
                ptr=w["sample_prevalence"],
                nte=w["n_test"],
                flag=flag,
                pte=("n/d" if w.get("test_prevalence") is None
                     else f"{w['test_prevalence']:.4f}"),
                roc=("n/d" if roc is None else f"{roc:.4f}"),
                ap=("n/d" if ap is None else f"{ap:.4f}"),
                api=("n/d" if api is None else f"{api:.4f}"),
                brier=("n/d" if brier is None else f"{brier:.4f}"),
                ll=("n/d" if ll is None else f"{ll:.4f}"),
                tstar=("n/d" if tstar is None else f"{tstar:.4f}"),
                rid=w["model_run_id"][:16] + "…",
            )
        )
    lines.extend([
        "",
        "† `n_test` < `MIN_SAMPLE_N` — metrics reported, but "
        "`sufficient_oos_sample=false`.",
        "",
        "## Registered artifacts",
        "",
    ])
    for w in results["windows"]:
        lines.append(
            f"- Window {w['window']} (`{w['train_cutoff']}`): "
            f"`model_run_id={w['model_run_id']}` "
            f"fingerprint=`{w['dataset_fingerprint'][:16]}…`"
        )
    lines.extend([
        "",
        "## Baselines (same OOS rows)",
        "",
        "Constant = training prevalence; spread = L2 logit on `pct_spread` alone.",
        "",
    ])
    for w in results["windows"]:
        bc = (w.get("baseline_constant") or {}).get("probability_metrics") or {}
        bs = (w.get("baseline_spread") or {}).get("probability_metrics") or {}
        lines.append(
            f"- W{w['window']}: constant ROC={bc.get('roc_auc')!r} AP={bc.get('average_precision')!r}; "
            f"spread ROC={bs.get('roc_auc')!r} AP={bs.get('average_precision')!r}"
        )
    lines.append("")
    path.write_text("\n".join(lines) + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--exp-dir", type=Path, default=DEFAULT_EXP_DIR)
    ap.add_argument("--out", type=Path, default=None,
                    help="Write results JSON (default: <exp-dir>/results.json)")
    ap.add_argument("--report", type=Path, default=None,
                    help="Write markdown metrics report "
                         "(default: <exp-dir>/RESULTS.md)")
    args = ap.parse_args(argv)

    protocol = load_json(args.exp_dir / "protocol.json")
    refuse_execution(protocol)
    frozen_plan = load_json(args.exp_dir / "plan.json")
    cohort = cohort_from_file(args.exp_dir / "cohort.json")

    conn = _open_ephemeral_store()
    results = execute_walkforward(
        conn, cohort=cohort, protocol=protocol, frozen_plan=frozen_plan)

    out_path = args.out or (args.exp_dir / "results.json")
    report_path = args.report or (args.exp_dir / "RESULTS.md")
    write_results(results, out_path)
    write_metrics_report(results, report_path)

    # Flip protocol status to EXECUTED (authorization remains true).
    protocol_path = args.exp_dir / "protocol.json"
    protocol["status"] = "EXECUTED"
    protocol_path.write_text(json.dumps(protocol, indent=2, sort_keys=False) + "\n")

    print(json.dumps({
        "wrote": str(out_path),
        "report": str(report_path),
        "experiment_id": results["experiment_id"],
        "status": results["status"],
        "cohort_n": results["cohort_n"],
        "windows": [
            {
                "window": w["window"],
                "train_cutoff": w["train_cutoff"],
                "n_train": w["n_train"],
                "n_test": w["n_test"],
                "model_run_id": w["model_run_id"],
                "roc_auc": (w.get("probability_metrics") or {}).get("roc_auc"),
                "average_precision": (
                    (w.get("probability_metrics") or {}).get("average_precision")),
                "sufficient_oos_sample": w.get("sufficient_oos_sample"),
            }
            for w in results["windows"]
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
