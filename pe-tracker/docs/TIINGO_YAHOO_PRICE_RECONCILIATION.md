# Tiingo ↔ Yahoo price reconciliation

**Rule:** `price_reconcile_v2` (see `src/ingest/equity_prices/reconciliation.py`)

| Metric | Value |
|---|---|
| OVERLAPPING_DEALS | 10 |
| OVERLAPPING_SESSIONS | 3289 |
| EXACT_MATCH_COUNT | 183 |
| TOLERABLE_MATCH_COUNT | 3106 |
| CORPORATE_ACTION_EXPLAINED_COUNT | n/d (manual review) |
| MATERIAL_CONFLICT_COUNT | 0 |
| TIINGO_ONLY_COUNT | 49 |
| YAHOO_ONLY_COUNT | 3 |

## Overlap versus canonical admission

Overlapping Tiingo/Yahoo sessions are not the admitted cohort. A zero material-conflict count is computed only on deals that have both series. It does not independently validate admitted Tiingo series that have no Yahoo overlap.

Per-deal `exact_matches` + `tolerable_matches` + `material_conflicts` equal `meta.reconcile`. `historical_debug` is not added to those totals.

| Metric | Value |
|---|---|
| OVERLAP_DEALS_CANONICALLY_ADMITTED | 10 |
| OVERLAP_DEALS_IDENTITY_DEFERRED | 0 |
| OVERLAP_DEALS_NO_PRICE_HISTORY | 0 |
| ADMITTED_DEALS_WITH_SECONDARY_OVERLAP | 10 |

## Raw vs canonical coverage (readiness uses CANONICALLY_ADMITTED only)

| Status | Deals |
|---|---|
| RAW_PROVIDER_COVERED | 62 |
| CANONICALLY_ADMITTED | 59 |
| DEFERRED_IDENTITY | 5 |
| DEFERRED_PRICE_CONFLICT | 0 |
| NO_PRICE_HISTORY | 65 |
| INSUFFICIENT_CANONICAL_PRINTS | 0 |
| identity deferral reasons | {'YAHOO_TICKER_REUSE_UNVALIDATED': 1, 'OPENFIGI_AMBIGUOUS': 3, 'TIINGO_IDENTITY_AMBIGUOUS': 1} |

## Material conflict samples

_No material conflicts recorded._

Conflicts are never averaged. Unexplained conflicts stay deferred.

