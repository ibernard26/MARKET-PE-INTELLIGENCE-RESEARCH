"""Out-of-sample metrics for break probabilities.

ROC AUC is prevalence-invariant; PR AUC is always reported BESIDE π (its
no-skill baseline). Brier and log loss grade the probabilities themselves;
calibration bins show reliability. The operating point t* is cost-based
(FN:FP from config), never 0.5, and is only reported when n >= MIN_SAMPLE_N.
"""
from __future__ import annotations

import math

import numpy as np

from ..compute.metrics import aucs, optimal_threshold
from ..config import COST_FN, COST_FP, MIN_SAMPLE_N


def calibration_bins(p, y, n_bins: int = 5) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, int)
    edges = np.linspace(0, 1, n_bins + 1)
    out = []
    for i in range(n_bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < n_bins - 1 else (p <= 1))
        if m.any():
            out.append({"bin": f"[{edges[i]:.1f},{edges[i+1]:.1f}]", "n": int(m.sum()),
                        "mean_p": float(p[m].mean()), "observed_rate": float(y[m].mean())})
    return out


def score(p, y, ids=None, min_n: int = MIN_SAMPLE_N) -> dict:
    p = [float(v) for v in p]
    y = [int(v) for v in y]
    n = len(y)
    out = {"n": n, "n_pos": sum(y), "n_neg": n - sum(y),
           "pi": (sum(y) / n) if n else None, "sufficient_sample": n >= min_n}
    if not n:
        return out
    pairs = list(zip(ids or range(n), p, y))
    a = aucs(pairs)
    out.update(roc_auc=a["roc_auc"], pr_auc=a["pr_auc"], pr_baseline_pi=a["pi"])
    out["brier"] = float(np.mean([(pi - yi) ** 2 for pi, yi in zip(p, y)]))
    eps = 1e-12
    out["log_loss"] = float(-np.mean([yi * math.log(max(pi, eps)) +
                                      (1 - yi) * math.log(max(1 - pi, eps))
                                      for pi, yi in zip(p, y)]))
    out["calibration"] = calibration_bins(p, y)
    if n >= min_n:
        t = optimal_threshold(pairs, cost_fp=COST_FP, cost_fn=COST_FN)
        c = t["confusion"]
        out["t_star"] = t["t_star"]
        out["expected_cost_at_t_star"] = t["expected_cost"]
        out["confusion_at_t_star"] = {"tp": c.tp, "fp": c.fp, "fn": c.fn, "tn": c.tn}
    else:
        out["t_star"] = None
        out["t_star_note"] = f"n={n} < MIN_SAMPLE_N={min_n}; threshold not reported"
    return out
