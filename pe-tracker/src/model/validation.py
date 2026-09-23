"""Chronological split and walk-forward validation, with baselines.

Every training set is rebuilt point-in-time at its own cutoff (labels known by
the cutoff, features as of each deal's feature date). The test window holds
deals whose FEATURE DATE falls after the cutoff, graded on labels known by the
evaluation horizon. No random splits — time only moves forward.

Baselines, graded on the same out-of-time rows:
  * constant   — training-set prevalence for everyone (no-skill reference);
  * spread     — the same L2 logistic on pct_spread alone.
"""
from __future__ import annotations

import sqlite3

from ..config import MIN_SAMPLE_N
from ..research.bitemporal import normalize_as_of
from .dataset import FEATURE_SCHEMA_VERSION, build_training_set
from .evaluate import score
from .logistic import MODEL_VERSION, BreakModel, InsufficientDataError


def _in_window(row, start, end):
    fa = normalize_as_of(row["feature_as_of"])
    return normalize_as_of(start) < fa <= normalize_as_of(end)


def fit_and_score(train_rows, test_rows, min_n: int = MIN_SAMPLE_N) -> dict:
    ys = [r["label"] for r in train_rows]
    out = {"n_train": len(ys), "train_pos": sum(ys), "train_neg": len(ys) - sum(ys),
           "n_test": len(test_rows), "model_version": MODEL_VERSION,
           "feature_schema_version": FEATURE_SCHEMA_VERSION}
    ty = [r["label"] for r in test_rows]
    ids = [r["deal_id"] for r in test_rows]
    txs = [r["x"] for r in test_rows]
    if not test_rows:
        out["status"] = "no_test_rows"
        return out
    # constant base-rate baseline needs only a prevalence
    if ys:
        pi = sum(ys) / len(ys)
        out["baseline_constant"] = score([pi] * len(ty), ty, ids, min_n=min_n)
    try:
        m = BreakModel().fit([r["x"] for r in train_rows], ys, min_n=min_n)
        out["model"] = score(list(m.predict_proba(txs)), ty, ids, min_n=min_n)
        out["coefficients"] = m.coefficients()
        s = BreakModel(features=["pct_spread"]).fit([r["x"] for r in train_rows], ys, min_n=min_n)
        out["baseline_spread"] = score(list(s.predict_proba(txs)), ty, ids, min_n=min_n)
        out["status"] = "fitted"
    except InsufficientDataError as exc:
        out["status"] = "insufficient_data"
        out["reason"] = str(exc)
    return out


def chronological_split(conn: sqlite3.Connection, cutoff: str, horizon: str,
                        min_n: int = MIN_SAMPLE_N) -> dict:
    train = build_training_set(cutoff, conn)
    evalset = build_training_set(horizon, conn)
    test = [r for r in evalset["rows"] if _in_window(r, cutoff, horizon)]
    return {"train_cutoff": cutoff, "test_start": cutoff, "test_end": horizon,
            "n_censored_at_cutoff": train["n_censored"],
            **fit_and_score(train["rows"], test, min_n=min_n)}


def walk_forward(conn: sqlite3.Connection, cutoffs: list[str], horizon: str,
                 min_n: int = MIN_SAMPLE_N) -> dict:
    """Expanding-window walk-forward. Window k trains at cutoffs[k] and tests on
    deals with feature dates in (cutoffs[k], cutoffs[k+1]] (last: horizon)."""
    cutoffs = sorted(cutoffs)
    evalset = build_training_set(horizon, conn)
    windows = []
    for k, c in enumerate(cutoffs):
        end = cutoffs[k + 1] if k + 1 < len(cutoffs) else horizon
        train = build_training_set(c, conn)
        test = [r for r in evalset["rows"] if _in_window(r, c, end)]
        w = {"window": k, "train_cutoff": c, "test_start": c, "test_end": end,
             "n_censored_at_cutoff": train["n_censored"],
             **fit_and_score(train["rows"], test, min_n=min_n)}
        windows.append(w)
    return {"horizon": horizon, "model_version": MODEL_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "n_labeled_at_horizon": evalset["n"], "n_pos_at_horizon": evalset["n_pos"],
            "n_censored_at_horizon": evalset["n_censored"], "windows": windows}
