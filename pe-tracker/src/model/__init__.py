"""Break-probability model v1 (regularized logistic regression).

Layers, kept separate on purpose:
  dataset     point-in-time training rows (features as-of, labels known by cutoff)
  logistic    preprocessing + L2 logistic fit / predict / serialize
  evaluate    probability metrics (π, ROC AUC, AP, Brier, log loss, calibration)
              + pre-test threshold selection + frozen-threshold evaluation
  validation  chronological split + walk-forward, baselines
  registry    model metadata + immutable predictions (SQLite, append-only)
  decision    EV = (1-p)·U − p·D, separate from the probability model
"""
