# Tiingo ↔ Yahoo price reconciliation

**Status:** blocked — `CREDENTIAL_ENVIRONMENT_NOT_VISIBLE`

Required env (presence only; values never logged):

- `OPENFIGI_API_KEY`
- `TIINGO_API_TOKEN`

Canonical thesis rule: `price_reconcile_v2` (`ABS_EPS=$0.01`, `REL_EPS=1e-4` = 1 bp;
TOLERABLE_MATCH if either limit holds, else MATERIAL_CONFLICT → `DEFER_PRICE_CONFLICT`).
Specified 2026-09-27 **before** the first live Tiingo/Yahoo reconciliation; any
change after observing results is a new version (`price_reconcile_v3`), never an
edit. `price_reconcile_v1` (`ABS_EPS=1e-4`, `REL_EPS=1e-6`) is preserved
unchanged. Raw close vs raw close only (`close_field_used == "close"` enforced);
adjusted closes are never compared. Note: Yahoo chart `close` is split-adjusted,
so a split inside a deal window surfaces as a conflict (deferred, not explained
away). Never average conflicts.

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
