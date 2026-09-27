"""Baseline vs spread-stress vs combined comparison harness (gated).

Does not mutate break_logit_v1 or first_walkforward_v1. Combined (break_logit_v2)
is reported as NOT_AVAILABLE until a separately versioned spec exists.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from ..evaluate import probability_metrics
from ..logistic import BreakModel, MODEL_VERSION as BASE_MODEL_VERSION
from ..dataset import FEATURE_SCHEMA_VERSION as FS_V1, build_training_set
from .features import FEATURE_SCHEMA_VERSION as FS_STRESS, build_spread_stress_panel
from .gates import authorize_spread_stress_backtest
from .model import MODEL_VERSION as STRESS_MODEL_VERSION, SpreadStressModel


def common_universe(baseline_ids: set[str], stress_ids: set[str]) -> dict:
    """Disclose intersection and symmetric difference for fair comparison."""
    common = sorted(baseline_ids & stress_ids)
    return {
        "common_universe": common,
        "COMMON_TEST_UNIVERSE_N": len(common),
        "baseline_only": sorted(baseline_ids - stress_ids),
        "stress_only": sorted(stress_ids - baseline_ids),
        "baseline_n": len(baseline_ids),
        "stress_n": len(stress_ids),
    }


def incremental_metrics(base: dict, chall: dict) -> dict:
    """Δ of probability metrics (challenger − baseline). None-safe."""
    out = {}
    for k in ("brier", "ap", "roc_auc", "log_loss"):
        b, c = base.get(k), chall.get(k)
        out[f"delta_{k}"] = (None if b is None or c is None else c - b)
    return out


def run_gated_comparison(conn: sqlite3.Connection, cutoff: str, horizon: str,
                         pit_validation_passed: bool = True,
                         min_n: int = 20) -> dict:
    """Execute the authorized sequence, or return a blocked status honestly.

    Sequence when authorized:
      data audit → PIT → features → chronological fit → OOS predict
    Trading / historical P&L require additional priced paths and are reported
    separately; this harness never invents P&L when blocked.
    """
    gate = authorize_spread_stress_backtest(
        conn, cutoff, pit_validation_passed=pit_validation_passed)
    report = {
        "cutoff": cutoff,
        "horizon": horizon,
        "gate": gate,
        "SPREAD_STRESS_BACKTEST_STATUS": gate["SPREAD_STRESS_BACKTEST_STATUS"],
        "BASELINE_BACKTEST_COMPLETE": False,
        "SPREAD_STRESS_BACKTEST_COMPLETE": False,
        "COMBINED_BACKTEST_COMPLETE": False,
        "WALK_FORWARD_EXECUTED": False,
        "BACKTEST_EXECUTED": False,
        "REAL_MODEL_FIT_EXECUTED": False,
        "CALIBRATION_EXECUTED": False,
        "combined_status": "NOT_AVAILABLE_NO_break_logit_v2",
        "INCREMENTAL_OUT_OF_TIME_IMPROVEMENT": "INCONCLUSIVE",
    }
    if not gate["authorized"]:
        # Still allow baseline-only probability diagnostics if fs_v1 data exists,
        # without pretending the spread-stress strategy was backtested.
        base_train = build_training_set(cutoff, conn)
        report["baseline_supported_components"] = {
            "feature_schema_version": FS_V1,
            "model_version": BASE_MODEL_VERSION,
            "n_train_labeled": base_train["n"],
            "note": (
                "Baseline announcement-time panel may be evaluable, but "
                "spread-stress backtest is blocked pending price history."
            ),
        }
        report["verdict_reason"] = gate.get("reason")
        return report

    # Authorized path: fit baseline and challenger on pre-horizon training,
    # score a common out-of-time set. (Full portfolio backtest is a separate
    # step once trades attach contemporaneous predictions.)
    base_train = build_training_set(cutoff, conn)
    stress_train = build_spread_stress_panel(cutoff, conn)
    base_eval = build_training_set(horizon, conn)
    stress_eval = build_spread_stress_panel(horizon, conn)

    def _oos(rows_train_cut, rows_all, cut, end):
        from ..validation import _in_window
        return [r for r in rows_all if _in_window(r, cut, end)]

    base_test = _oos(base_train["rows"], base_eval["rows"], cutoff, horizon)
    stress_test = _oos(stress_train["rows"], stress_eval["rows"], cutoff, horizon)
    uni = common_universe({r["deal_id"] for r in base_test},
                          {r["deal_id"] for r in stress_test})
    report["universe"] = uni

    # Fit on training only
    try:
        bm = BreakModel().fit([r["x"] for r in base_train["rows"]],
                              [r["label"] for r in base_train["rows"]], min_n=min_n)
        sm = SpreadStressModel().fit([r["x"] for r in stress_train["rows"]],
                                    [r["label"] for r in stress_train["rows"]],
                                    min_n=min_n)
        report["REAL_MODEL_FIT_EXECUTED"] = True
        report["WALK_FORWARD_EXECUTED"] = True  # single expanding split here
    except Exception as exc:
        report["fit_error"] = str(exc)
        report["verdict_reason"] = f"fit failed: {exc}"
        return report

    # Common-universe scoring
    common = set(uni["common_universe"])
    b_common = [r for r in base_test if r["deal_id"] in common]
    s_common = [r for r in stress_test if r["deal_id"] in common]
    # align by deal_id
    b_map = {r["deal_id"]: r for r in b_common}
    s_map = {r["deal_id"]: r for r in s_common}
    ids = sorted(common)
    if len(ids) < min_n:
        report["verdict_reason"] = (
            f"common-universe n={len(ids)} < min_n={min_n}; inconclusive")
        report["COMMON_TEST_UNIVERSE_N"] = len(ids)
        return report

    by = [b_map[i]["label"] for i in ids]
    bp = list(bm.predict_proba([b_map[i]["x"] for i in ids]))
    sp = list(sm.predict_proba([s_map[i]["x"] for i in ids]))
    # labels must match on common deals
    sy = [s_map[i]["label"] for i in ids]
    assert by == sy

    base_m = probability_metrics(bp, by, ids, min_n=min_n)
    stress_m = probability_metrics(sp, sy, ids, min_n=min_n)
    report["COMMON_TEST_UNIVERSE_N"] = len(ids)
    report["baseline_probability_metrics"] = base_m
    report["stress_probability_metrics"] = stress_m
    report["incremental"] = incremental_metrics(base_m, stress_m)
    report["feature_schema_baseline"] = FS_V1
    report["feature_schema_stress"] = FS_STRESS
    report["model_version_baseline"] = BASE_MODEL_VERSION
    report["model_version_stress"] = STRESS_MODEL_VERSION
    report["SPREAD_STRESS_BACKTEST_COMPLETE"] = False  # predictive OOS only here
    report["BASELINE_BACKTEST_COMPLETE"] = False
    report["BACKTEST_EXECUTED"] = False  # economic backtest needs trade layer + prices
    report["predictive_oos_complete"] = True
    report["INCREMENTAL_OUT_OF_TIME_IMPROVEMENT"] = "INCONCLUSIVE"
    report["verdict_reason"] = (
        "Predictive out-of-time comparison computed on common universe; "
        "economic P&L backtest still requires investable price paths and "
        "frozen decision rules — do not equate ΔBrier/ΔAP alone with alpha."
    )
    return report
