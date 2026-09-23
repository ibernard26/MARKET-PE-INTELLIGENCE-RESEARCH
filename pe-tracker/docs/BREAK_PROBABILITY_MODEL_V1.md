# Break probability model v1 (`break_logit_v1`, features `fs_v1`)

**Status: MODEL INFRASTRUCTURE VALIDATED — INSUFFICIENT DATA FOR ALPHA CLAIM.**
The real research store currently holds 6 ledger deals and 0 bitemporal
announcement/resolution events, so there are **0 labeled rows**. Every metric below
comes from clearly-labeled SYNTHETIC test fixtures and only shows that the mechanics work.

## Contract (unchanged: `event_driven_v1`)
y = 1 ⇔ the deal breaks (termination/withdrawal); y = 0 ⇔ closing; pending ⇒ **censored**.
Graded with ROC AUC and PR AUC beside π, Brier, log loss, calibration; operating
point t* is cost-based (FN:FP = 15:1) and withheld when n < `MIN_SAMPLE_N` (20).

## Pipeline
| Module | Role |
|---|---|
| `src/model/dataset.py` | Point-in-time rows: features as of the day the announcement became knowable; label from resolution events **known** by the cutoff |
| `src/model/logistic.py` | L2 logistic, fixed C=1.0 on standardized inputs; train-median imputation + missingness indicators (no zero-fill); Platt/isotonic calibration only when the sample allows it |
| `src/model/evaluate.py` | π, ROC AUC, PR AUC (beside π), Brier, log loss, calibration bins, cost-based t* |
| `src/model/validation.py` | Chronological split + expanding walk-forward; baselines: constant base rate, spread-only logistic |
| `src/model/registry.py` | `model_registry` (model_id, version, feature schema, cutoff, n, pos/neg, prevalence, hyperparameters, calibration, fit_timestamp, code_commit) + immutable `model_predictions` |
| `src/model/bridge.py` | Attaches the contemporaneous stored p_break to backtest trades |
| `src/model/decision.py` | EV = (1−p)·U − p·D, kept separate from the model; no trade without a validated t* |
| `src/ingest/historical.py` | Provider interface; no concrete provider ships (it never fabricates) |
| `src/model/report.py` | `python -m src.model.report` — honest counts on the real store |

## Leakage controls
* Bitemporal reads (valid ≤ T and known_at ≤ T) for features **and** labels.
* A row is admissible at cutoff C only if feature date ≤ C, label known ≤ C, and the feature date is before the resolution.
* Imputation/standardization parameters are frozen at fit time (training fold only).
* DB triggers reject predictions from a model whose training cutoff is after the prediction's as_of, predictions from unregistered models, and any UPDATE/DELETE.
* The backtester rejects a p_break dated after trade entry.

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
The out-of-time walk-forward must then beat both baselines on ROC AUC, PR AUC vs π
and Brier with n ≥ `MIN_SAMPLE_N` in each test window.
