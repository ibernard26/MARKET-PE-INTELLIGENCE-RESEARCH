# Tiingo ↔ Yahoo price reconciliation

**Status:** blocked — `CREDENTIAL_ENVIRONMENT_NOT_VISIBLE`

Required env (presence only; values never logged):

- `OPENFIGI_API_KEY`
- `TIINGO_API_TOKEN`

Rule: `price_reconcile_v1` (`ABS_EPS=1e-4`, `REL_EPS=1e-6`) — fixed before any
performance inspection. Never average conflicts.

## Metrics (populate after live coverage pass)

| Metric | Value |
|---|---|
| OVERLAPPING_DEALS | n/d |
| OVERLAPPING_SESSIONS | n/d |
| EXACT_MATCH_COUNT | n/d |
| TOLERABLE_MATCH_COUNT | n/d |
| CORPORATE_ACTION_EXPLAINED_COUNT | n/d |
| MATERIAL_CONFLICT_COUNT | n/d |
| TIINGO_ONLY_COUNT | n/d |
| YAHOO_ONLY_COUNT | n/d |

Regenerate via `python -m scripts.run_free_price_coverage` once credentials are
visible to the runtime.
