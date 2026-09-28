# spread_stress_v2 — frozen specification

| Field | Value |
|---|---|
| spec_id | `spread_stress_v2` |
| feature schema | `fs_spread_stress_v2` |
| status | **FROZEN** before any v2 panel was scored, fit or evaluated |
| machine-readable policy | `data/spread_stress_v2_pit_policy.json` (pins this file's sha256) |
| code | `src/model/spread_stress_v2/` |
| supersedes | nothing. `spread_stress_v1`, `fs_v1`, `break_logit_v1`, `first_walkforward_v1` and `price_reconcile_v2` are unchanged |

Any change to this document or the policy file after freeze is a new version
(`spread_stress_v3`). `spec.assert_frozen` refuses to run if this file's hash
no longer matches the policy.

## 1. Why v2 exists

The v1 panel took the last print at or before the cutoff as the feature time,
then required `feature_time < resolution_time`. With date-only resolutions
stored at midnight and closes stamped 16:00, 20 of 21 admitted deals collided
(`FEATURE_TIME_RESOLUTION_TIMESTAMP_COLLISION`; see
`SPREAD_STRESS_V1_POSTMORTEM.md`, PR #44).

Choosing "the last print before resolution" would pick the feature time using
the outcome time, so v2 does not do that. v2 fixes feature times ex ante, from
the announcement alone.

## 2. Candidate feature-time policies (compared before freeze)

| Criterion | P1 single snapshot at fixed session offset | P2 weekly calendar grid (e.g. Fridays) | P3 calendar-day offsets (A+30d, A+60d…) | P4 fixed session-offset grid, multi-snapshot |
|---|---|---|---|---|
| PIT safety | Safe (depends only on the announcement) | Safe | Safe | Safe |
| Sample efficiency | 1 row per deal; loses deals resolving before the offset | Many rows | Few rows | Several rows per deal, bounded by a cap |
| Duplicate-deal dependence | None | High (unbounded rows) | Low | Present; handled by deal grouping and 1/n weights |
| Event-time interpretation | Clean ("k sessions after announcement") | Poor: first-snapshot lag depends on the announcement weekday | Mixed: calendar days ≠ trading days | Clean: every snapshot is k sessions after S0 |
| Trading realism | Tradable at close | Tradable | Needs roll-forward to a session | Tradable at close |
| Label leakage | None | None | None | None (resolution only excludes, never selects) |
| Announcement-time ambiguity | Handled by S0 | Anchor unrelated to the announcement | Handled only if anchored at S0 | Handled by S0 |
| Irregular deal duration | Short deals dropped entirely | Long deals dominate | Moderate | Long deals capped (≤12 snapshots) and deal-weighted |
| Holidays | Session calendar | Friday holidays shift the grid | Needs a roll rule | Native (session calendar) |
| Resolution-day ambiguity | Excluded by the PIT rule | Same | Same | Same |

**Selected: P4.** It keeps P1's clean event-time meaning and PIT safety.
Unlike P1, it doesn't silently discard deals that resolve before a single
offset: in P1, early breaks and quick closes are exactly the deals lost. The
dependence it introduces is controlled by construction (§6). P1 is retained
only as a pre-registered sensitivity view: the first grid snapshot of each deal.

## 3. Session calendar

The calendar is a rule-based NYSE calendar for 2010–2030 (`calendar.py`),
including documented special closures (2012-10-29/30, 2018-12-05, 2025-01-09).
The grid is defined on exchange sessions, not on the dates a provider returned.
So a missing print never moves the grid; it only makes that snapshot missing.

## 4. Announcement-day policy (frozen)

`S0` is the first session whose close is provably after the announcement:

- **DATE_ONLY** (all 129 corpus announcements): `S0` is the first session
  strictly after the announcement calendar date. The announcement-date close is
  never used, because it cannot be ordered against a date-only event (PR #44
  flagged 13 such closes).
- **INTRADAY**: `S0` is the announcement session only if the announcement
  instant precedes that session's 16:00 America/New_York close. Otherwise it
  is the next session. A timezone offset is required.

Pre-S0 prints never enter features. The first delta is at the session after S0.

## 5. Snapshot grid and resolution-day policy (frozen)

- Grid: `t_k = S0 + (10 + 10k)` sessions, for k = 0…11. That is at most 12
  snapshots, every 10 sessions, starting 10 sessions after S0. It is generated
  from the announcement only (`schedule.snapshot_schedule` takes no resolution
  argument).
- **Resolution-day policy:** a snapshot is eligible only if its close is
  provably before resolution.
  - DATE_ONLY resolution (128/129): the snapshot date must be strictly earlier
    than the resolution calendar date. The resolution-date close is excluded
    (PR #44 flagged 20 such closes).
  - INTRADAY: the snapshot's 16:00 ET close must be earlier than the
    resolution instant.
  - Unresolved deals: all snapshots are active, and the label is censored.
- Resolution information only removes grid points. It never selects one.

## 6. Longitudinal panel, weighting and splits (frozen)

- **Panel:** multiple pre-specified snapshots per deal (policy B), each labelled
  with the deal's eventual outcome.
- **Weighting:** each eligible snapshot gets weight `1/n_i`, where `n_i` is the
  deal's eligible snapshots, so every deal carries total weight 1. Long deals
  cannot dominate.
- **Split:** deal-grouped expanding walk-forward with annual cutoffs
  (1 January). At cutoff c:
  - train = deals resolved strictly before c with a known label;
  - test = deals announced in [c, next cutoff);
  - deals announced before c and unresolved at c are in neither set.
  - Grouping is by `deal_id`, so a deal can never appear on both sides
    (`splits.assert_disjoint`).
- **Calibration** (if later authorized) is fit only on training deals of the
  same fold, with deal weights.

## 7. Features (`fs_spread_stress_v2`)

These are the v1 concepts only, redefined on the session grid. There are no new
features.

| Feature | Definition at snapshot t | Missing when |
|---|---|---|
| `pct_spread` | `(offer − close_t) / close_t` | no raw close on t |
| `delta_spread` | `pct_spread_t − pct_spread_{prev(t)}` | either close missing, or prev(t) < S0 |
| `spread_vol` | sample std of valid deltas over the 10 sessions ending at t | fewer than 3 valid deltas |
| `n_delta_obs` | count of valid deltas in that window | never |

Rules:
- Raw `close` only (`close_field_used == close`). Adjusted closes are never
  used.
- There is no fill, no interpolation, no carry-forward and no bridging of
  gaps.
- A snapshot with any of `pct_spread`, `delta_spread` or `spread_vol` missing
  is `INCOMPLETE_FEATURES`. The analysis is complete-case and pre-specified.
- `offer` is the announced cash `offer_price` from the reviewed SEC manifest,
  which is knowable at announcement.
  - Offer revisions are not modelled; the manifest has no revision history.
    This is a known limitation.

## 8. Eligibility (frozen)

The cohort is: `CANONICALLY_ADMITTED` deals (identity + `price_reconcile_v2`
gates, unchanged), with `consideration_type == cash`, a positive
`offer_price`, and at least 1 eligible snapshot.

**Stock and mixed deals are excluded** (`UNSUPPORTED_CONSIDERATION`). Their
spread needs the acquirer's price and an exchange ratio, and neither is in the
manifest. Supporting them requires a new version with acquirer-leg data under
the same identity rules.

**Outcome-knowledge disclosure:** when this rule was written, the author knew
the admitted outcome mix (20 closed / 1 break-like), because it was stated in
the task. The rule follows from which fields exist (no exchange ratios or
acquirer prices), not from that mix.

## 9. Labels

| Resolution | Label |
|---|---|
| terminated or withdrawn | y = 1 (broken; `STRATEGY.md`) |
| closed | y = 0 |
| anything else, or unresolved | censored, never a negative |

## 10. Gates (deal level; never lowered)

- `MIN_SAMPLE_N = 20` labelled deals.
- `MIN_CLASS_N = 2` for each class.
- PIT validation must pass.
- **Separately**, an explicit execution authorization record naming this
  spec's sha256 is required (`gates.authorize_execution`).

If either class is below 2: **STOP** and report the limitation.

## 11. Model (pre-specified; NOT executed)

`spread_stress_logit_v2` is a logistic regression on the four features.

- Standardization uses the training fold's weighted mean and std.
- L2 penalty with C = 1.0, deal weights, no class weighting.
- No hyperparameter search.
- Metrics: ROC AUC and PR AUC beside π, and the cost-based t* (FN:FP = 15:1),
  per `event_driven_v1`.

`break_logit_v1` is untouched. A combined model would need its own versioned
spec.

## 12. What v2 does not claim

With 21 admitted deals and a single break-like outcome (before the cash
restriction), no inference about break prediction is possible. v2 is a frozen
protocol waiting for sample: outcome-blind identity expansion (Phase C) must
come first.
