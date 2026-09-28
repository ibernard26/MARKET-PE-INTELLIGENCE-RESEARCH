# spread_stress_v1 postmortem

The canonical historical-price coverage gate passed with 21 admitted deals.
The existing spread_stress_v1 panel was not executable because its feature-time
construction collides with date-only resolution timestamps, and the admitted
cohort also contains only one break-like outcome. No model fit or backtest was
performed.

This note does not define `spread_stress_v2` and does not change the v1
feature-time rule.

## Coverage gate passed

`PRICE_COVERAGE_READY = YES`.

The readiness population is `CANONICALLY_ADMITTED` deals with at least 3 raw
closes (`close_field_used = close`). That gate is separate from whether the
v1 panel constructor can turn those closes into labeled rows.

## v1 panel construction failed

`SPREAD_STRESS_V1_PANEL_VALID = NO`.

`build_spread_stress_panel` selects the last print at or before the cutoff and
then requires `feature_time < resolution_time`. It does not look for an earlier
print after that comparison fails.

## Why date-only resolution timestamps collide with 16:00 closes

SEC resolution timestamps in this corpus are mostly calendar dates. Ingest
normalizes a date-only timestamp to midnight (`00:00:00`). Tiingo session
closes are stamped `16:00` America/New_York. A resolution-day close is therefore
later than the stored resolution instant, and the selected feature time fails
`feature_time < resolution_time`.

`normalize_as_of` expands a bare date to end-of-day only when the stored value
is still 10 characters. Once the event has been normalized to midnight, the
clock time is kept and the same-day 16:00 close is not strictly before it.

`SPREAD_STRESS_V1_BLOCK_REASON = FEATURE_TIME_RESOLUTION_TIMESTAMP_COLLISION`.

Panel rows excluded for `feature_not_before_resolution`:
20.

Prints strictly before the stored resolution instant:
3273.

Deals with at least 3 such prints:
21.

Those counts show that pre-resolution closes exist. They are not a replacement
feature rule.

## Why last-pre-resolution-print is not an acceptable retroactive fix

Choosing the last print strictly before the resolution timestamp would use the
outcome time to decide which observation is the feature. That is future
information in the feature-time selection process. This remediation does not
do that, and it does not rename the modified rule `spread_stress_v1`.

## Class imbalance

The admitted cohort is 20 closed and
1 break-like. `MIN_CLASS_N` remains 2.
The existing v1 panel result is 1 labeled row
(pos=0, neg=1). Even a timestamp
correction would leave a single break-like outcome, which cannot clear
`MIN_CLASS_N`. The minimum is not lowered.

## What was not run

- `SPREAD_STRESS_V1_EXECUTED = NO`
- `SPREAD_STRESS_V1_MODEL_FIT = NO`
- No walk-forward prediction was produced.
- No economic backtest was run.
- No calibration was run.

The harness status `BLOCKED_INSUFFICIENT_PRICE_HISTORY` is the pre-existing
gate string. On this corpus it is not a finding that historical prices are
missing. The coverage gate passed. The panel rule then removed rows because of
the timestamp collision, and the class counts are below `MIN_CLASS_N`.

## What a later version has to freeze first

A future spread-stress version needs an independently frozen feature-time
policy, written down before any execution on this cohort. That policy is not
designed here. Same-day closes on date-only announcements and resolutions stay
flagged `ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS` and
`RESOLUTION_DAY_ORDERING_AMBIGUOUS`. Raw prints remain in the manifest.
