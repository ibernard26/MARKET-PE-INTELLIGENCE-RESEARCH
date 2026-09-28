# spread_stress_v2 — frozen methodology

**Status:** `frozen`, **not executable**. This freeze does not fit a model, run a
walk-forward, calibrate probabilities, or run an economic backtest.

Baseline main at freeze design: `a94b525219031b23eecf65ba404ea40550ec3201`
(PR #46). The canonical SEC corpus remains 129 deals; the current price-admitted
population is 59 deals (45 closed, 14 break-like) with 10,759 real prints. Those
counts do **not** guarantee the T+10 panel clears its gates; the panel must be
constructed and frozen separately before execution.

## Locked artifacts

This specification does not mutate `event_driven_v1`, `first_walkforward_v1`,
`EVENT_RULES`, `fs_v1`, `break_logit_v1`, `spread_stress_v1`, or
`price_reconcile_v2`. `price_reconcile_v2` remains ABS 0.01 USD / REL 0.0001.
`MIN_SAMPLE_N=20` and `MIN_CLASS_N=2` remain unchanged.

## Frozen feature-time policy

`ann_tplus_10_session`

The feature session is the tenth PIT-safe **XNYS/NYSE trading session** generated
from the announcement clock alone. Resolution time is not an input.

- DATE_ONLY announcement: announcement-day close is never eligible. Session 1 is
  the first XNYS session strictly after the announcement calendar date.
- Intraday announcement: an explicit timezone offset is mandatory. The timestamp
  is converted to `America/New_York` and compared with the **actual XNYS session
  close**, including early closes. If strictly before close, that session may be
  session 1; at/after close, session 1 is the next XNYS session.
- Holidays, weekends, and special/early closes come from `exchange_calendars`
  calendar `XNYS`; a Mon–Fri proxy is prohibited in the frozen policy.

The draft alternatives (T+5, T+20, weekly grid, calendar offsets, active-deal
panel) remain documented as historical candidates but cannot be selected under
`spread_stress_v2_frozen_1`. Choosing one requires a new version.

## Active-at-feature-time / PIT censoring

Feature dates are generated **before** resolution information is consulted.
Resolution `known_at` can only censor the frozen T+10 snapshot; it can never
move or replace the feature date.

At the aware feature close:

- no resolution `known_at` -> `ACTIVE`;
- aware resolution `known_at <= feature_time` -> `RESOLVED_KNOWN`;
- aware resolution `known_at > feature_time` -> `ACTIVE`;
- DATE_ONLY or naive resolution `known_at` on an earlier calendar date ->
  `RESOLVED_KNOWN`;
- DATE_ONLY or naive resolution `known_at` on a later date -> `ACTIVE`;
- DATE_ONLY or naive resolution `known_at` on the same date ->
  `ORDERING_AMBIGUOUS` and censored.

This is deliberately conservative. No same-day order is inferred without an
explicit offset.

## Feature schema `fs_spread_stress_v2`

The feature names remain `pct_spread`, `delta_spread`, `spread_vol`, and
`n_delta_obs`, but the schema version is new.

- `pct_spread`: `(offer - raw_close) / raw_close`; both terms must satisfy
  valid_time <= feature_time and known_at <= feature_time.
- `delta_spread`: first difference of PIT `pct_spread`.
- `spread_vol`: sample standard deviation of **up to** the last 10 non-null PIT
  deltas, requiring at least 3; otherwise missing.
- `n_delta_obs`: number of non-null PIT deltas available by feature time.

Important: ten post-announcement closes can produce at most nine deltas.
`VOL_WINDOW_DEFAULT=10` is therefore a maximum window, not a requirement that
T+10 contain ten deltas. Missing history remains missing; no synthetic,
interpolated, forward-filled, or backfilled price is permitted.

## Frozen model/evaluation policy

The challenger model is a separately versioned `spread_stress_v2` L2 logistic
model using the same fixed preprocessing/hyperparameters as the existing
`BreakModel`: C=1.0, `lbfgs`, max_iter=1000, no class weighting, standardized,
training-fold median imputation plus missing indicators. Calibration is `none`.
No hyperparameter search is authorized.

Validation is grouped chronological **60/40 by deal announcement chronology**.
Ordering primary key is America/New_York announcement market date.
Offset-aware intraday events within a market date are ordered by UTC
instant. DATE_ONLY announcements have no inferred clock time and are
ordered by deal_id in a separate deterministic precision bucket
(INTRADAY before DATE_ONLY on the same market date).
The precision bucket is a split tie convention, not an assertion of
actual intraday ordering. The split uses no label, resolution timestamp,
resolution `known_at`, or resolution type. Every row for a deal remains
on one side. All preprocessing, coefficients, and the cost threshold are
training-only. The untouched later 40% is the out-of-time test population.

Threshold selection remains the existing training-only cost policy:
`COST_FP=1`, `COST_FN=15`, with sensitivity ratios 5/10/15/20. Baselines remain
training prevalence and pct-spread-only logistic on the same test universe.

After T+10 PIT censoring, both train and test populations are reported. Model
fit is still blocked unless `MIN_SAMPLE_N=20` and `MIN_CLASS_N=2` are satisfied
where required. The frozen split is not changed to rescue a failed gate.

## Freeze versus execution

Methodology freeze blockers are cleared by this specification. Execution stays
explicitly disabled. A later PR must:

1. construct the T+10 panel from the 59-deal admitted price universe;
2. persist/fingerprint the exact v2 cohort and all exclusions/censor reasons;
3. re-run sample/class/PIT gates after T+10 censoring;
4. implement the separately versioned `spread_stress_v2` model without changing
   v1 artifacts;
5. obtain explicit execution authorization.

Until then `authorize_execution().authorized == False` and `fit()` raises.

## Coverage-bias warning

The underlying price-admitted population is selected: closed coverage is 41.3%
versus 70.0% for break-like deals, with substantial year/consideration/deal-type
skew. Do not rebalance it. Predictive results on the observed v2 cohort must not
be presented as an unbiased estimate of the 129-deal population break rate.
