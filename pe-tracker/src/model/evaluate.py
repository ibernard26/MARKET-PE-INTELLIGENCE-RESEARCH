"""Out-of-sample evaluation for break probabilities.

Two deliberately separate layers:

1. `probability_metrics(p, y)` — threshold-free grading of the probabilities:
   π, ROC AUC (prevalence-invariant), Average Precision (AP) beside π, Brier,
   log loss, calibration table. It never chooses an operating point.

2. Operating policy:
   `select_threshold(p, y)` chooses the cost-optimal t* (FN:FP from config) and
   must ONLY be called on data available before the test period (training or
   an earlier validation slice). `evaluate_frozen_threshold(p, y, t_star)`
   applies a supplied, already-frozen t* to future test data and reports the
   confusion matrix and realized cost — it cannot re-optimize.

Terminology: "AP" is sklearn.metrics.average_precision_score (step-wise
precision weighted by recall increments), not a trapezoidal area under the PR
curve. Its no-skill reference is π.
"""
from __future__ import annotations

import math

import numpy as np

from ..compute.metrics import aucs, confusion_at, optimal_threshold
from ..config import COST_FN, COST_FP, MIN_SAMPLE_N


def calibration_bins(p, y, n_bins: int = 5) -> list[dict]:
    """Diagnostic reliability table (mean predicted vs observed rate per bin)."""
    p, y = np.asarray(p, float), np.asarray(y, int)
    edges = np.linspace(0, 1, n_bins + 1)
    out = []
    for i in range(n_bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < n_bins - 1 else (p <= 1))
        if m.any():
            out.append({"bin": f"[{edges[i]:.1f},{edges[i+1]:.1f}]", "n": int(m.sum()),
                        "mean_p": float(p[m].mean()), "observed_rate": float(y[m].mean())})
    return out


def probability_metrics(p, y, ids=None, min_n: int = MIN_SAMPLE_N) -> dict:
    """Threshold-free metrics. Contains no t* by construction."""
    p = [float(v) for v in p]
    y = [int(v) for v in y]
    n = len(y)
    out = {"n": n, "n_pos": sum(y), "n_neg": n - sum(y),
           "pi": (sum(y) / n) if n else None, "sufficient_sample": n >= min_n}
    if not n:
        return out
    a = aucs(list(zip(ids or range(n), p, y)))
    out.update(roc_auc=a["roc_auc"], average_precision=a["pr_auc"],
               average_precision_baseline_pi=a["pi"])
    out["brier"] = float(np.mean([(pi - yi) ** 2 for pi, yi in zip(p, y)]))
    eps = 1e-12
    out["log_loss"] = float(-np.mean([yi * math.log(max(pi, eps)) +
                                      (1 - yi) * math.log(max(1 - pi, eps))
                                      for pi, yi in zip(p, y)]))
    out["calibration"] = calibration_bins(p, y)
    return out


def select_threshold(p, y, min_n: int = MIN_SAMPLE_N,
                     cost_fp: float = COST_FP, cost_fn: float = COST_FN) -> dict:
    """Cost-optimal t* from PRE-TEST data only. Withheld (None) below min_n."""
    y = [int(v) for v in y]
    if len(y) < min_n:
        return {"t_star": None, "n_selection": len(y),
                "note": f"n={len(y)} < MIN_SAMPLE_N={min_n}; no threshold selected"}
    t = optimal_threshold(list(zip(range(len(y)), [float(v) for v in p], y)),
                          cost_fp=cost_fp, cost_fn=cost_fn)
    return {"t_star": t["t_star"], "n_selection": len(y),
            "selection_cost": t["expected_cost"], "cost_fp": cost_fp, "cost_fn": cost_fn}


def evaluate_frozen_threshold(p, y, t_star, cost_fp: float = COST_FP,
                              cost_fn: float = COST_FN) -> dict:
    """Apply a FROZEN t* to test data. Never selects or adjusts the threshold."""
    if t_star is None:
        return {"t_star_frozen": None, "note": "no frozen threshold; policy not evaluated"}
    c = confusion_at(list(zip(range(len(y)), [float(v) for v in p], [int(v) for v in y])),
                     t_star)
    return {"t_star_frozen": t_star, "tp": c.tp, "fp": c.fp, "fn": c.fn, "tn": c.tn,
            "realized_cost": c.fp * cost_fp + c.fn * cost_fn,
            "cost_fp": cost_fp, "cost_fn": cost_fn}
