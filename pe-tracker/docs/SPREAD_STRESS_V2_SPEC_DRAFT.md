# spread_stress_v2 — draft specification

**Status:** `draft`. Not executable. This document does not fit a model, does
not run a walk-forward, and does not run a backtest.

`spread_stress_v1` is unchanged. The v1 postmortem
(`docs/SPREAD_STRESS_V1_POSTMORTEM.md`) required an independently frozen
feature-time policy *before* any later version runs on the thesis cohort.
This is that policy, still draft.

Machine-readable copy: `data/spread_stress_v2_pit_policy_draft.json`.
Code gate: `src/model/spread_stress/v2_spec.py` (`SPEC_STATUS = "draft"`).

## Locked artifacts this draft must not modify

| Artifact | Version | Flag |
|---|---|---|
| Walk-forward freeze | `first_walkforward_v1` | `FIRST_WALKFORWARD_CHANGED=NO` |
| EDGAR event map | `EVENT_RULES` | `EVENT_RULES_CHANGED=NO` |
| Announcement features | `fs_v1` | `FS_V1_CHANGED=NO` |
| Announcement model | `break_logit_v1` | `BREAK_LOGIT_V1_CHANGED=NO` |
| Prior challenger | `spread_stress_v1` | `SPREAD_STRESS_V1_CHANGED=NO` |
| Price rule | `price_reconcile_v2` | `PRICE_RECONCILE_V2_THRESHOLDS_CHANGED=NO` |
| Sample floor | `MIN_SAMPLE_N=20` | `MIN_SAMPLE_N_CHANGED=NO` |
| Class floor | `MIN_CLASS_N=2` | `MIN_CLASS_N_CHANGED=NO` |

`ABS_EPS=0.01`, `REL_EPS=0.0001` for `price_reconcile_v2`.

## Why v1 cannot be patched in place

v1 chooses the last knowable print at or before the training cutoff and then
requires `feature_time < resolution_time`. On this corpus most resolution
timestamps are date-only (normalized to midnight) while session closes are
16:00 ET, so the selected print fails the inequality. Pulling the print back
to “last close strictly before resolution” would use the outcome time to pick
the feature. That is not a v1 fix and is not a v2 feature-time rule.

## Feature-time invariant

**Resolution timestamps are not used to choose feature dates.**

Snapshot dates are a function of the announcement timestamp (and a frozen
session calendar). After dates are generated, a snapshot whose feature time
is not strictly before the *known-as-of-that-date* resolution is unlabeled /
excluded. That is label censoring. It is not a license to pick a different
feature date from the outcome clock.

## DATE_ONLY announcements

If `announcement_timestamp` is a bare `YYYY-MM-DD`, the same-day session close
is `ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS`. v2 does not use that close as a
feature print unless an *intraday* announcement timestamp proves the 16:00
close is later. No synthetic, interpolated, forward-filled, or backfilled
print is substituted.

## Feature-time policy candidates (evaluated, not executed)

All four families are deterministic and ex-ante.

### 1. Fixed trading-day offsets after announcement

`ann_tplus_N_session`: the N-th eligible NYSE session after announcement.
Announcement-day is ineligible for DATE_ONLY events. Candidates recorded:
N = 5, 10, 20. One snapshot per deal. Short deals that resolve before T+N
simply have no snapshot; the date is not pulled forward.

### 2. Weekly grid

`weekly_grid_5_60`: snapshots at T+5, 10, 15, 20, 25, 30, 40, 60 sessions,
still generated from announcement only.

### 3. Calendar offsets

`calendar_7_14_30`: first eligible session on or after announcement + 7 / 14 /
30 calendar days. If that lands on the DATE_ONLY announcement date, skip to
the next session.

### 4. Multi-snapshot active-deal panel

`active_deal_weekly_panel`: the weekly grid, kept as a panel of snapshots.
Pending-vs-resolved at a snapshot is evaluated as-of that snapshot.

If multiple snapshots are used:

- the same `deal_id` must never appear on both sides of a train/test split
- splits are **grouped chronological by announcement date**
- long-duration deals must not dominate: weighting is
  `deal_equal_snapshot_weight = (1/n_deals) × (1/n_snapshots_deal)`,
  **defined here, before any execution**
- snapshot-equal weighting is rejected

## Recommended policy (still draft; not run)

**`ann_tplus_10_session`**

Ten post-announcement sessions matches `VOL_WINDOW_DEFAULT=10`, so `spread_vol`
can be computed on a PIT-safe window that does not include a DATE_ONLY
announcement-day close. A single snapshot per deal avoids duration dominance
without weights. Grouped chronological splits reduce to a deal-level
announcement-date cutoff.

The weekly grid remains specified as the multi-snapshot alternative, with
deal-equal weights, if a later frozen spec chooses it. It is not executed here.

## Features

Start from the v1 challenger names (new schema id `fs_spread_stress_v2`; v1
schema `fs_spread_stress_v1` is not edited):

| Feature | Economic rationale | PIT definition |
|---|---|---|
| `pct_spread` | Gross arb spread remaining in the market | `(offer − raw close)/close` at feature_time; offer `known_at` ≤ feature_time |
| `delta_spread` | Stress as spread widening | First difference of PIT `pct_spread` |
| `spread_vol` | Path through which financing/antitrust stress usually appears | Sample stdev of last 10 PIT ΔS values |
| `n_delta_obs` | Transparency for sparse paths | Count of non-null PIT ΔS ≤ feature_time |

No additional features are added in this draft. Any later feature needs its
own economic rationale and PIT definition in a version bump.

Prices: raw `close` only, `price_reconcile_v2`, no synthetic / interpolated /
forward-filled / backfilled prints.

## Execution gate

`authorize_execution()` returns `authorized=False` while `SPEC_STATUS=draft`.
`fit()` raises. `MODEL_FIT_EXECUTED=NO`. `BACKTEST_EXECUTED=NO`.

A later commit that freezes this spec must bump `SPEC_STATUS` off `draft` in
the same change that records the freeze. Until then v2 cannot run, including
if identity expansion later clears `MIN_CLASS_N`.

## Identity expansion is separate

Proof C review of `DEFERRED_IDENTITY` deals is outcome-blind (lexicographic
`deal_id`) and does not authorize v2 execution. If `ADMITTED_BREAK_LIKE < 2`
after that review, v2 still must not be fit. Gates are not lowered.
