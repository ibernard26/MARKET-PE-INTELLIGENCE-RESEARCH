# Tiingo ↔ Yahoo price reconciliation

**Rule:** `price_reconcile_v2` (see `src/ingest/equity_prices/reconciliation.py`)

| Metric | Value |
|---|---|
| OVERLAPPING_DEALS | 11 |
| OVERLAPPING_SESSIONS | 3638 |
| EXACT_MATCH_COUNT | 215 |
| TOLERABLE_MATCH_COUNT | 3423 |
| CORPORATE_ACTION_EXPLAINED_COUNT | n/d (manual review) |
| MATERIAL_CONFLICT_COUNT | 0 |
| TIINGO_ONLY_COUNT | 44 |
| YAHOO_ONLY_COUNT | 3 |

## Raw vs canonical coverage (readiness uses CANONICALLY_ADMITTED only)

| Status | Deals |
|---|---|
| RAW_PROVIDER_COVERED | 58 |
| CANONICALLY_ADMITTED | 21 |
| DEFERRED_IDENTITY | 56 |
| DEFERRED_PRICE_CONFLICT | 0 |
| NO_PRICE_HISTORY | 52 |
| INSUFFICIENT_CANONICAL_PRINTS | 0 |
| identity deferral reasons | {'OPENFIGI_AMBIGUOUS': 46, 'OPENFIGI_NAME_MISMATCH': 7, 'TIINGO_IDENTITY_AMBIGUOUS': 3} |

## Material conflict samples

_No material conflicts recorded._

Conflicts are never averaged. Unexplained conflicts stay deferred.

