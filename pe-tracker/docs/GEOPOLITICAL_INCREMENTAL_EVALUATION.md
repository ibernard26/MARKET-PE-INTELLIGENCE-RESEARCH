# How geopolitical intelligence could eventually be evaluated (design only)

**Nothing in this document is authorized.** It describes the conditions under which a
future, separately approved experiment could ask: *does verified geopolitical
information add out-of-sample discrimination or calibration beyond the fs_v1 baseline?*

## Preconditions (all required)

1. `AUTHORIZE FIRST REAL WALKFORWARD` issued and the fs_v1 / `break_logit_v1` baseline
   walk-forward executed and registered under the existing protocol — the geo
   experiment is an *increment* over that baseline, not a replacement.
2. A populated ledger with primary-retrieved events and reviewed exposure links whose
   review was **outcome-blind** (links assigned without looking at deal labels).
3. A new feature-schema version (fs_v2 or `fs_v1_geo`), a new `MODEL_VERSION`, and a
   pre-registration committed *before* any fit.

## Pre-registered design

| Item | Rule |
|---|---|
| Hypothesis | Adding admissible geopolitical fields changes ROC AUC / AP-vs-π / Brier relative to fs_v1 on the same windows. Two-sided; no direction assumed. |
| Rows | Same deals, same cutoffs as `first_walkforward_v1` (or a later frozen grid). For announcement-time models, only events with valid ≤ feature time AND known_at ≤ feature time (`src/geo_intel/pit.py`). |
| Ablations | (a) fs_v1 alone; (b) fs_v1 + CONFIRMED_DEAL_SPECIFIC fields; (c) fs_v1 + SECTOR_HYPOTHESIS fields; (d) both. Confirmed and hypothesis fields are never pooled. |
| Validation | Chronological expanding walk-forward only; no random K-fold; t* selected on training predictions and frozen (FN:FP = 15:1 unchanged). |
| Inference | Deal-level paired comparison (e.g. paired bootstrap over test deals, clustered by deal); report intervals, not just point deltas. With ~20 breaks, expect wide intervals — "no detectable increment" is a valid, reportable result. |
| Multiplicity | The ablation set and metrics are fixed in advance; no feature search. |
| Missingness | "No reviewed mapping" is NULL (unknown), distinct from "reviewed, no exposure" = 0; indicators per the existing imputation contract. |
| Reporting | Sample prevalence only; no population probability, alpha or P&L claim. |

## V2 (`break_hazard_v1`, design only)

The draft in `data/geopolitical/fs_v2_geo_candidates_DRAFT.json` lists possible
time-varying fields for risk-set rows. If V2 is ever authorized, event-driven fields
enter interval *t* only when known by the start of *t*; rows for one deal stay in one
partition; effective sample size remains deal-level; break incidence is evaluated as a
competing risk against closing.

## Not allowed at any stage

Features from UNCONFIRMED / ATTRIBUTED_CLAIM / DISPUTED / RETRACTED clusters; Grok/X
sentiment or mention counts; back-filled known_at; re-labelling deals; any execution
or trading use.
