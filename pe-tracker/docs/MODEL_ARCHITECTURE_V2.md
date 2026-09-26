# Model architecture v2 (design only for the dynamic layer)

**Status:** design documentation. This PR does **not** implement or fit
`break_hazard_v1`. `break_logit_v1` / `fs_v1` / `event_driven_v1` remain the
locked announcement-time baseline.

## Layer stack

```
PRIMARY SOURCES          SEC EDGAR, market-data providers
        ↓
CANONICAL WRITE STORE    SQLite pe-tracker (identity, observations, events,
                         valid_time, known_at, provenance, model registry,
                         immutable predictions)
        ↓ read-only
ANALYTICAL PROJECTION    DuckDB / dbt (arb-intelligence) — not a competing SoT
        ↓
PIT STATE RECONSTRUCTION valid_time ≤ T AND known_at ≤ T
        ↓
FEATURE / DATASET        announcement snapshots (fs_v1);
                         future risk-set snapshots (fs_v2 — not built here)
        ↓
MODEL LAYER              break_logit_v1 (baseline);
                         future break_hazard_v1 (design only)
        ↓
CHRONOLOGICAL VALIDATION walk-forward; no random deal-row K-fold
        ↓
MODEL REGISTRY           version, cutoff, cohort, dataset fingerprint, …
        ↓
DECISION / PORTFOLIO     EV / risk (separate from probability estimation)
        ↓
future execution adapter
```

Dagster may orchestrate replication into DuckDB; it must not become an
alternate canonical writer.

---

## A. Announcement model — `break_logit_v1`

Estimates:

> P(eventual break | information knowable at announcement)

One independent outcome per deal. Purpose:

- simple reference model
- interpretability
- software / leakage validation
- baseline discrimination and calibration diagnostics

Locked: L2, C=1.0, lbfgs, train-fold median + missingness indicators, no
class weight, no calibration in v1, `MIN_SAMPLE_N=20`, `MIN_CLASS_N=2`,
cost FN:FP = 15:1.

---

## B. Dynamic model — future `break_hazard_v1` (not implemented)

Discrete-time **competing risks** while a deal remains unresolved.

For unresolved deal *i* in interval *t*:

```
Z_{i,t} ∈ {continue, close, break}
```

Model:

```
P(Z_{i,t} | unresolved at t, X_{i,t})
```

with the three state probabilities summing to 1.

Let `h_break(i,t)` and `h_close(i,t)` be interval event probabilities. Survival
through the interval requires neither terminal event. **Cumulative incidence**
of break must treat closing as a competing terminal event (do not treat
1 − S(t) as break risk alone).

Estimator, fitting code, and fs_v2 schema are **out of scope** for this PR.

---

## C. Time-varying features (future risk-set rows)

Legitimately point-in-time candidates (when sourced):

- pct_spread, annualized_spread
- deal age, days to expected close
- acquirer / target returns
- financing / shareholder state
- second-request, DOJ/FTC challenge, CFIUS, CMA/EU state
- sourced amendments

Every value must satisfy:

```
valid_time ≤ prediction_time
known_at  ≤ prediction_time
```

---

## D. Row dependence

Multiple weekly/daily rows for one transaction **do not** create additional
independent merger outcomes. Effective outcome sample size remains **deal-level**.

Rules:

- no random row-level train/test split
- all rows for one deal stay in one chronological research partition
- future uncertainty estimates must account for deal clustering

---

## E. Validation

Retain chronological walk-forward only. No random K-fold across deal-period rows.

Probability-model metrics:

- Brier, log loss
- ROC AUC
- Average Precision beside prevalence
- calibration / reliability diagnostics (diagnostic only in v1; no
  `calibrate()` in this architecture PR)

Future competing-risk evaluation should add horizon-specific cumulative
incidence scoring when `break_hazard_v1` is implemented under a separate
authorization.
