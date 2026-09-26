# Break probability model v1 (`break_logit_v1`, features `fs_v1`)

**Status: MODEL INFRASTRUCTURE VALIDATED — NO ALPHA CLAIM.**

At base commit `82638705278ca5da14fa1dd47cb585ce71adafd5`, the reviewed SEC
manifest / canonical store supports **24 eligible labeled rows**
(`MODEL_DATA_STATUS = READY_FOR_EXPERIMENTAL_WALK_FORWARD` per
`python -m src.model.data_quality`). That is a **reviewer-curated research
corpus**, not a population sample (see `SAMPLING_FRAME.md`). No real-data fit,
calibration, or walk-forward has been authorized in the architecture remediation
PR. Metrics in unit tests still come from clearly labeled **SYNTHETIC**
fixtures and only show that the mechanics work.

## Contract (unchanged: `event_driven_v1`)
y = 1 ⇔ the deal breaks (termination/withdrawal); y = 0 ⇔ closing; pending ⇒ **censored**.
Graded with ROC AUC and Average Precision (AP) beside π, Brier, log loss, calibration table.
The operating point t* is cost-based (FN:FP = 15:1), is **selected on pre-test data and frozen**,
and is withheld when n < `MIN_SAMPLE_N` (20).

**Terminology:** "AP" is `sklearn.metrics.average_precision_score`, the step-wise sum of
precision weighted by recall increments. It is not a trapezoidal area under the PR curve.
The repository's older "PR AUC" label (`compute/metrics.aucs` → `pr_auc`) refers to this
same AP quantity. Its no-skill reference is π.

## Pipeline
| Module | Role |
|---|---|
| `src/model/dataset.py` | Point-in-time rows: features as of the day the announcement became knowable; label from resolution events **known** by the cutoff |
| `src/model/logistic.py` | L2 logistic, fixed C=1.0 on standardized inputs; train-median imputation + missingness indicators (no zero-fill); Platt/isotonic calibration only when the sample allows it |
| `src/model/evaluate.py` | `probability_metrics` (π, ROC AUC, AP beside π, Brier, log loss, calibration table — no threshold); `select_threshold` (pre-test data only); `evaluate_frozen_threshold` (applies a frozen t*, cannot re-optimize) |
| `src/model/validation.py` | Chronological split + expanding walk-forward; baselines: constant base rate, spread-only logistic; per-window metadata |
| `src/model/registry.py` | `model_registry` (model_id, version, feature schema, cutoff, n, pos/neg, **sample** prevalence, cohort_id/version, dataset_fingerprint, hyperparameters, calibration, fit_timestamp, code_commit) + immutable `model_predictions` |
| `src/model/cohort.py` | Non-destructive model-cohort membership (canonical store unchanged) |
| `src/model/fingerprint.py` | Deterministic SHA-256 fingerprint of canonical training rows |
| `src/model/bridge.py` | Attaches the contemporaneous stored p_break to backtest trades |
| `src/model/decision.py` | EV = (1−p)·U − p·D, kept separate from the model; no trade without a validated t* |
| `src/ingest/historical.py` | Provider interface; no concrete provider ships (it never fabricates) |
| `src/model/report.py` | `python -m src.model.report` — honest counts on the real store |

## Leakage controls
* Bitemporal reads (valid ≤ T and known_at ≤ T) for features **and** labels.
* A row is admissible at cutoff C only if feature date ≤ C, label known ≤ C, and the feature date is before the resolution.
* Imputation/standardization parameters are frozen at fit time (training fold only).
* DB triggers reject predictions from a model whose training cutoff is after the prediction's as_of, predictions from unregistered models, and any UPDATE/DELETE.
* The backtester rejects a p_break dated after trade entry (normalized timestamp comparison).
* The operating threshold is chosen from training data and frozen before the test window.

## Validation sequence (per window)
```
training rows (labels known by cutoff) → fit model → in-sample training predictions
→ select_threshold → FREEZE t* → predict untouched future test window
→ probability_metrics + evaluate_frozen_threshold(t*)
```
Test labels never influence t*. A regression test flips every future test label and
asserts that the selected threshold is identical.
Each window records train_start, train_end/cutoff, threshold_source_period,
calibration_source_period (None in v1), test_start, test_end, n_train, n_test, train
and test prevalence, model_version, feature_schema_version and the frozen t*.

## Calibration decision
`break_logit_v1` is an **uncalibrated** logistic model (option A). Validation, the registry
and stored predictions all use raw logistic probabilities. Calibration bins are a reliability
diagnostic only. `BreakModel.calibrate()` exists for a future version and must be fit on a
chronologically earlier calibration slice, never on test data. Current sample sizes do
not justify applying it.

## Temporal contract
* Feature time defaults to the **exact** instant the announcement became knowable, i.e. the later
  of its valid timestamp and known_at. It is never truncated to a date, because a bare date
  means end-of-day and would admit later same-day information.
* An explicit `feature_dates` entry that predates the knowable announcement raises
  `FeatureDateError`. A deal with no known announcement produces no row.
* `model_predictions.as_of` and `training_cutoff` (and `model_registry.training_cutoff`)
  are stored as normalized ISO timestamps, with bare dates stored as end-of-day. CHECK constraints
  reject non-normalized values, and a trigger rejects `training_cutoff > as_of` for both
  date and timestamp inputs.

## Regularization rationale
Small n → ridge keeps coefficients finite under separation. Collinear spread
features → L2 shares weight instead of arbitrarily picking one. C is **fixed**,
because cross-validating C on tens of deals would itself overfit. Changing it bumps `MODEL_VERSION`.

## Interpretation
`coefficients()` reports log-odds and odds ratios per 1 SD. These are
**associations, not causal effects**.

## What is needed for an alpha claim
A sourced, point-in-time history of resolved deals (announcement, terms and
resolution with publication times), loaded through a `HistoricalDealProvider`.
The out-of-time walk-forward must then beat both baselines on ROC AUC, AP vs π
and Brier with n ≥ `MIN_SAMPLE_N` in each test window, with t* frozen from pre-test data.
