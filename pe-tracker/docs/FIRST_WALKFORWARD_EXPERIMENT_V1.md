# First chronological walk-forward — preparation freeze (`first_walkforward_v1`)

**Status: `PREPARED_NOT_EXECUTED`**

This phase freezes the dataset identity and the expanding-window protocol for
the first real chronological walk-forward. It does **not** authorize fitting.

Required later command (not issued here):

```text
AUTHORIZE FIRST REAL WALKFORWARD
```

Until that authorization flips `protocol.json → execution_authorized` and an
execution path is intentionally implemented, agents must not call
`BreakModel.fit`, `walk_forward`, `chronological_split`, or `fit_and_score` on
the real cohort.

## Frozen artifacts

| Path | Role |
|---|---|
| `data/experiments/first_walkforward_v1/cohort.json` | Exact `ModelCohort` membership (N=62) |
| `data/experiments/first_walkforward_v1/protocol.json` | Locked model contract + cutoff grid + auth gate |
| `data/experiments/first_walkforward_v1/plan.json` | No-fit prep output: per-window counts + fingerprints |
| `src/model/experiment_prep.py` | Prep machinery (`python -m src.model.experiment_prep`) |

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

No hyperparameter tuning. No EVENT_RULES / fs_v1 change in this phase.

## Walk-forward grid (prepared)

Expanding chronological windows:

| Window | Train cutoff | Test end |
|---:|---|---|
| 0 | 2021-06-30 | 2023-06-30 |
| 1 | 2023-06-30 | 2025-06-30 |
| 2 | 2025-06-30 | 2026-09-26 (horizon) |

Rationale: 2021-06-30 is the earliest month-end at which the reconstructed
training set reaches `MIN_SAMPLE_N` with both classes present. Later cutoffs
expand by ~24 months to keep windows coarse enough for an honest first run.

Per-window `dataset_fingerprint` values are computed in `plan.json` from
point-in-time training rows only. Thin out-of-sample test counts are reported
as-is (not padded, not fabricated).

## How to regenerate the plan (still no fit)

```bash
cd pe-tracker
python -m src.model.experiment_prep
# writes data/experiments/first_walkforward_v1/plan.json
```

`--execute` is refused while `execution_authorized` is false.

## After human authorization (future)

Only then:

1. Independently re-run readiness / prep checks
2. Fit each window under `break_logit_v1` with frozen t* chronology
3. Register each artifact with `model_run_id` + cohort + fingerprint + code commit
4. Report ROC AUC, AP beside sample π, Brier, log loss, reliability diagnostics
5. Still no calibration, no tuning, no population-probability claim, no alpha/P&L claim
