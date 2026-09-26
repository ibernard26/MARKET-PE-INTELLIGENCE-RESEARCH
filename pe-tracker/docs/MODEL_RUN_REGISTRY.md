# Model run registry

## Identity layers

| Layer | Example | Meaning |
|---|---|---|
| `model_id` | `break_logit` | Model family |
| `model_version` | `break_logit_v1` | **Predictive specification** (algorithm, `fs_v1`, fixed C, no calibration, …) |
| `model_run_id` | 64-hex SHA-256 | **One concrete fitted artifact** |

Many runs may share the same `model_version`. The primary key of
`model_registry` is `model_run_id`, not `(model_version, training_cutoff)`.

## How `model_run_id` is computed

Deterministic SHA-256 over a canonical JSON payload of:

- `model_id`, `model_version`, `feature_schema_version`
- `training_cutoff`
- `cohort_id`, `cohort_version`
- `dataset_fingerprint`
- `code_commit`
- `hyperparameters`, `calibration`
- serialized `artifact`

Timestamps alone are never the scientific identity. The same logical fit
always yields the same `model_run_id` (stdlib `hashlib` only).

## Registration invariants

When `register_model` is called:

1. Training rows must be non-empty.
2. `n_train` / `n_pos` / `n_neg` / `sample_prevalence` are derived from rows and
   checked against any caller-supplied counts.
3. `dataset_fingerprint` is **computed** from rows and is authoritative; a
   caller-supplied fingerprint must match exactly or registration fails.
4. If a `ModelCohort` is provided: every training `deal_id` must be in the
   cohort (`training ⊆ cohort`). Equality is not required — chronological
   cutoffs legitimately omit cohort members whose labels are not yet known.
5. Predictions reference `model_run_id` (DB FK). Lookahead
   (`training_cutoff > as_of`) remains rejected.

## Loading

- Preferred: `load_model_run(model_run_id, conn)`
- Legacy: `load_model(model_version, training_cutoff, conn)` — succeeds only
  when **exactly one** run matches; otherwise `AmbiguousModelRunError`
  (never silent `LIMIT 1`)

## Predictions

- Preferred query: `prediction_as_of(..., model_run_id=...)`
- Version-only query: allowed only when a single run has admissible
  predictions for that deal; otherwise ambiguous

## Walk-forward (`first_walkforward_v1`)

`docs/FIRST_WALKFORWARD_EXPERIMENT_V1.md` and
`data/experiments/first_walkforward_v1/` freeze the cohort, cutoff grid, and
per-window dataset fingerprints. After `AUTHORIZE FIRST REAL WALKFORWARD`,
`python -m src.model.experiment_execute` fits each window, registers each
artifact by `model_run_id`, and writes `results.json` / `RESULTS.md`.

Each chronological window records at least:

`model_run_id`, train/test bounds, cohort id/version, dataset fingerprint,
code commit, n_train/n_test, sample prevalences, frozen threshold, calibration
method (`none` for v1). The registry identity is the anchor for that
reconstructible experiment chain.

## Sampling terminology

`prevalence` / `sample_prevalence` = observed fraction in the training rows.
Not a population break rate. See `SAMPLING_FRAME.md`.
