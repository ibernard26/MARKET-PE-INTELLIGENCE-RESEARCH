# First chronological walk-forward — `first_walkforward_v1`

**Status:** see `data/experiments/first_walkforward_v1/protocol.json`
(`AUTHORIZED_PENDING_EXECUTE` → `EXECUTED` after
`python -m src.model.experiment_execute`).

This experiment freezes the dataset identity and expanding-window protocol,
then (when authorized) fits `break_logit_v1` / `fs_v1` with **calibration =
none**, registers each window artifact by `model_run_id`, and reports
out-of-time metrics. It does **not** calibrate, tune hyperparameters, alter
`EVENT_RULES` / `fs_v1`, or claim population probabilities / alpha / P&L.

Authorization command (already issued for this run):

```text
AUTHORIZE FIRST REAL WALKFORWARD
```

## Frozen artifacts

| Path | Role |
|---|---|
| `data/experiments/first_walkforward_v1/cohort.json` | Exact `ModelCohort` membership (N=62) |
| `data/experiments/first_walkforward_v1/protocol.json` | Locked model contract + cutoff grid + auth gate |
| `data/experiments/first_walkforward_v1/plan.json` | No-fit prep output: per-window counts + fingerprints |
| `data/experiments/first_walkforward_v1/results.json` | Post-execute: OOS metrics + `model_run_id` per window |
| `data/experiments/first_walkforward_v1/RESULTS.md` | Human-readable OOS metrics report |
| `src/model/experiment_prep.py` | Prep machinery (`python -m src.model.experiment_prep`) |
| `src/model/experiment_execute.py` | Authorized execute (`python -m src.model.experiment_execute`) |

## Dataset freeze

- Manifest freeze commit: `f5f634b6290fa078f9018da2ae3da48f316cf655` (Batch 8 merge)
- Canonical N = **62** (Y0 closed = 43, Y1 terminated = 19, censored = 0)
- Batch 8 exclusions remain excluded (no substitutes):  
  `DEAL-KLAC-LRCX-2015`, `DEAL-AKRX-FRESENIUS-2017`

## ModelCohort

| Field | Frozen value |
|---|---|
| `cohort_id` | `sec_reviewed_corpus_batch8` |
| `cohort_version` | `v1` |
| `selection_method` | `reviewer_approved_sec_manifest_batches_1_through_8` |
| `outcome_blind` | `false` |
| `probability_calibration_eligible` | `false` |
| `sampling_design` | convenience / reviewer-curated resolved deals |

Canonical corpus ≠ model cohort ≠ population. Sample prevalence is **not** a
population break probability (`SAMPLING_FRAME.md`).

## Locked model specification (unchanged)

`event_driven_v1` / `break_logit_v1` / `fs_v1`  
L2, C=1.0, lbfgs, max_iter=1000, class_weight=None, standardize=True,  
train-median + missingness indicators, **calibration = none**,  
MIN_SAMPLE_N=20, MIN_CLASS_N=2, COST_FN:FP = 15:1.

No hyperparameter tuning. No EVENT_RULES / fs_v1 change in this experiment.

## Walk-forward grid

Expanding chronological windows:

| Window | Train cutoff | Test end |
|---:|---|---|
| 0 | 2021-06-30 | 2023-06-30 |
| 1 | 2023-06-30 | 2025-06-30 |
| 2 | 2025-06-30 | 2026-09-26 (horizon) |

Per-window `dataset_fingerprint` values in `plan.json` are authoritative.
Execute re-computes them and **fails closed** on any drift. Thin out-of-sample
test counts are reported as-is (not padded, not fabricated);
`sufficient_oos_sample` is false when `n_test < MIN_SAMPLE_N`.

## How to regenerate the plan (no fit)

Prep refuses to rewrite the plan once `execution_authorized` is true:

```bash
cd pe-tracker
# only valid while execution_authorized is false
python -m src.model.experiment_prep
```

## How to execute (authorized)

```bash
cd pe-tracker
python -m src.model.experiment_execute
# writes results.json + RESULTS.md; sets protocol.status=EXECUTED
```

Execute sequence per window:

1. Reconstruct PIT training ⊆ cohort; assert fingerprint vs `plan.json`
2. Fit `BreakModel` (`break_logit_v1`)
3. Select cost-optimal `t*` on **training** predictions only; freeze
4. Grade untouched test window (ROC AUC, AP beside sample π, Brier, log loss,
   calibration bins as diagnostic only)
5. `register_model` → `model_run_id` + cohort + fingerprint + code commit

Still no calibration, no tuning, no population-probability claim, no alpha/P&L claim.
