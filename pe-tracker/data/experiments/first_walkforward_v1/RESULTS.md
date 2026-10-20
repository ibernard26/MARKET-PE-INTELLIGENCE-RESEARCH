# first_walkforward_v1 — out-of-time metrics

**Status:** `EXECUTED`
**Cohort:** `sec_reviewed_corpus_batch8` `v1` (N=62)
**Model:** `break_logit_v1` / `fs_v1` / `event_driven_v1`
**Calibration:** `none` (not applied)
**Code commit at execute:** `3037ff7edb13baa2bbd98fb15684a3fee600cd5c`

Claims explicitly **not** made: population-calibrated probabilities, alpha / P&L, hyperparameter tuning, EVENT_RULES or fs_v1 changes.

## Per-window out-of-time results

| W | Train cutoff | n_train | π_train | n_test | π_test | ROC AUC | AP | AP baseline π | Brier | log loss | t* | model_run_id |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | 2021-06-30 | 20 | 0.5500 | 23 | 0.1739 | 0.3421 | 0.1935 | 0.1739 | 0.3530 | 0.9252 | 0.3627 | `a625bb89203c80bc…` |
| 1 | 2023-06-30 | 47 | 0.3191 | 8 † | 0.2500 | 0.5833 | 0.2917 | 0.2500 | 0.2005 | 0.5864 | 0.0000 | `242d5873468f68a1…` |
| 2 | 2025-06-30 | 57 | 0.2982 | 3 † | 0.3333 | 1.0000 | 1.0000 | 0.3333 | 0.1191 | 0.4018 | 0.0000 | `0f23710600415f97…` |

† `n_test` < `MIN_SAMPLE_N` — metrics reported, but `sufficient_oos_sample=false`.

## Registered artifacts

- Window 0 (`2021-06-30`): `model_run_id=a625bb89203c80bcc4a42ce4cfdcbb6bd4f854b2f4c6c709251bee13d6514a2b` fingerprint=`8d0e153c4285a130…`
- Window 1 (`2023-06-30`): `model_run_id=242d5873468f68a1429f2d3b47ea234be3a932ea14bb3bf31c50fbacb90af8dc` fingerprint=`369cf517055a18cf…`
- Window 2 (`2025-06-30`): `model_run_id=0f23710600415f97a35a9dffd46bed375418c7a1cc609e811d1d4275bc884778` fingerprint=`a15992b40875b645…`

## Baselines (same OOS rows)

Constant = training prevalence; spread = L2 logit on `pct_spread` alone.

- W0: constant ROC=0.5 AP=0.17391304347826086; spread ROC=0.5 AP=0.17391304347826086
- W1: constant ROC=0.5 AP=0.25; spread ROC=0.5 AP=0.25
- W2: constant ROC=0.5 AP=0.3333333333333333; spread ROC=0.5 AP=0.3333333333333333

