"""Chronological split and walk-forward validation, with baselines.

Per window the sequence is fixed:

    training rows (labels known by the cutoff)
      -> fit probability model
      -> in-sample TRAINING predictions
      -> select cost-optimal t*  (select_threshold)       <- pre-test data only
      -> freeze t*
      -> predict the untouched future test window
      -> probability_metrics + evaluate_frozen_threshold(t* frozen)

Test labels are never used to choose t*. Calibration is NOT part of v1
validation: predictions are raw logistic probabilities (see logistic.py).

Baselines, graded identically on the same out-of-time rows:
  * constant — training prevalence for everyone;
  * spread   — the same L2 logistic on pct_spread alone.
"""
from __future__ import annotations

import sqlite3

from ..config import MIN_SAMPLE_N
from ..research.bitemporal import normalize_as_of
from .dataset import FEATURE_SCHEMA_VERSION, build_training_set
from .evaluate import (evaluate_frozen_threshold, probability_metrics,
                       select_threshold)
from .logistic import MODEL_VERSION, BreakModel, InsufficientDataError

CALIBRATION = "none (raw logistic probabilities)"


def _in_window(row, start, end) -> bool:
    """Feature time strictly after `start` and on/before `end` (full timestamps;
    a bare date bound means end of that day)."""
    fa = normalize_as_of(row["feature_as_of"])
    return normalize_as_of(start) < fa <= normalize_as_of(end)


def _policy(train_p, train_y, test_p, test_y, ids, min_n) -> dict:
    """Probability metrics + threshold chosen on TRAIN, frozen, applied to TEST."""
    sel = select_threshold(train_p, train_y, min_n=min_n)
    return {"probability_metrics": probability_metrics(test_p, test_y, ids, min_n=min_n),
            "threshold_selection": sel,
            "frozen_policy": evaluate_frozen_threshold(test_p, test_y, sel["t_star"])}


def fit_and_score(train_rows, test_rows, min_n: int = MIN_SAMPLE_N) -> dict:
    ys = [r["label"] for r in train_rows]
    ty = [r["label"] for r in test_rows]
    out = {"n_train": len(ys), "train_pos": sum(ys), "train_neg": len(ys) - sum(ys),
           "train_prevalence": (sum(ys) / len(ys)) if ys else None,
           "n_test": len(ty), "test_prevalence": (sum(ty) / len(ty)) if ty else None,
           "model_version": MODEL_VERSION,
           "feature_schema_version": FEATURE_SCHEMA_VERSION,
           "calibration": CALIBRATION, "calibration_source_period": None}
    if not test_rows:
        out["status"] = "no_test_rows"
        return out
    ids = [r["deal_id"] for r in test_rows]
    xs, txs = [r["x"] for r in train_rows], [r["x"] for r in test_rows]
    if ys:
        pi = sum(ys) / len(ys)
        out["baseline_constant"] = _policy([pi] * len(ys), ys, [pi] * len(ty), ty, ids, min_n)
    try:
        m = BreakModel().fit(xs, ys, min_n=min_n)
        out["model"] = _policy(list(m.predict_proba(xs)), ys,
                               list(m.predict_proba(txs)), ty, ids, min_n)
        out["coefficients"] = m.coefficients()
        s = BreakModel(features=["pct_spread"]).fit(xs, ys, min_n=min_n)
        out["baseline_spread"] = _policy(list(s.predict_proba(xs)), ys,
                                         list(s.predict_proba(txs)), ty, ids, min_n)
        out["t_star_frozen"] = out["model"]["threshold_selection"]["t_star"]
        out["status"] = "fitted"
    except InsufficientDataError as exc:
        out["t_star_frozen"] = None
        out["status"] = "insufficient_data"
        out["reason"] = str(exc)
    return out


def _window(train, test, cutoff, end, min_n) -> dict:
    rows = train["rows"]
    train_start = min((r["feature_as_of"] for r in rows), default=None)
    return {"train_start": train_start, "train_end": cutoff, "train_cutoff": cutoff,
            "threshold_source_period": (
                f"training rows, feature time [{train_start}, {cutoff}], "
                f"labels known by {cutoff} (in-sample predictions)") if rows else None,
            "test_start": cutoff, "test_end": end,
            "test_rule": "feature time in (test_start, test_end]; labels known by horizon",
            "n_censored_at_cutoff": train["n_censored"],
            **fit_and_score(rows, test, min_n=min_n)}


def chronological_split(conn: sqlite3.Connection, cutoff: str, horizon: str,
                        min_n: int = MIN_SAMPLE_N) -> dict:
    train = build_training_set(cutoff, conn)
    evalset = build_training_set(horizon, conn)
    test = [r for r in evalset["rows"] if _in_window(r, cutoff, horizon)]
    return _window(train, test, cutoff, horizon, min_n)


def walk_forward(conn: sqlite3.Connection, cutoffs: list[str], horizon: str,
                 min_n: int = MIN_SAMPLE_N) -> dict:
    """Expanding-window walk-forward. Window k trains at cutoffs[k] and tests on
    deals with feature time in (cutoffs[k], cutoffs[k+1]] (last: horizon)."""
    cutoffs = sorted(cutoffs, key=normalize_as_of)
    evalset = build_training_set(horizon, conn)
    windows = []
    for k, c in enumerate(cutoffs):
        end = cutoffs[k + 1] if k + 1 < len(cutoffs) else horizon
        test = [r for r in evalset["rows"] if _in_window(r, c, end)]
        windows.append({"window": k, **_window(build_training_set(c, conn), test, c, end, min_n)})
    return {"horizon": horizon, "model_version": MODEL_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION, "calibration": CALIBRATION,
            "n_labeled_at_horizon": evalset["n"], "n_pos_at_horizon": evalset["n_pos"],
            "n_censored_at_horizon": evalset["n_censored"], "windows": windows}
