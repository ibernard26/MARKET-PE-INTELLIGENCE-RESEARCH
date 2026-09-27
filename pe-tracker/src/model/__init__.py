"""Break-probability model v1 (regularized logistic regression).

Layers, kept separate on purpose:
  dataset     point-in-time training rows (features as-of, labels known by cutoff)
  logistic    preprocessing + L2 logistic fit / predict / serialize
  evaluate    probability metrics (π, ROC AUC, AP, Brier, log loss, calibration)
              + pre-test threshold selection + frozen-threshold evaluation
  validation  chronological split + walk-forward, baselines
  registry    model metadata + immutable predictions (SQLite, append-only)
  experiment_prep  freeze cohort/fingerprints for a walk-forward (no fit)
  decision    EV = (1-p)·U − p·D, separate from the probability model
  spread_stress  challenger (spread_stress_v1 / fs_spread_stress_v1); gated
                 real-data walk-forward/backtest — does not mutate fs_v1 /
                 break_logit_v1 / first_walkforward_v1
"""
