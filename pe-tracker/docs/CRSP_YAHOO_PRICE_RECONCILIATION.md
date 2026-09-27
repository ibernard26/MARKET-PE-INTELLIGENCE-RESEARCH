# CRSP ↔ Yahoo price reconciliation

**Status:** blocked — `CRSP_ACCESS_AVAILABLE = NO`

This document is the landing place for session-level close comparisons between
CRSP (`provider=crsp`) and Yahoo (`provider=yahoo_finance_chart`) on the
existing 14 Yahoo-covered deals.

## Preconditions

- WRDS/CRSP credentials or licensed flat files configured per `CRSP_ACCESS.md`
- PERMNO mappings for the validation sample in `data/crsp_security_map.json`
- Live fetch that produces overlapping `NormalizedEquityObservation` rows

Until those exist, no reconciliation numbers are fabricated.

## Planned metrics (populate when access exists)

| Metric | Value |
|---|---|
| Validation deals attempted | n/d |
| PERMNO matched | n/d |
| Overlapping session observations | n/d |
| Exact matches (`abs(diff) == 0`) | n/d |
| Tolerable differences (≤ $0.0001 or 1e-6 rel) | n/d |
| Material conflicts | n/d |
| Conflicts explained by `DlyPrcFlg` | n/d |
| Conflicts explained by corporate actions / splits | n/d |

## Policy

- Do **not** silently overwrite conflict rows.
- Prefer CRSP for the canonical research path when identity and coverage are valid.
- Record material disagreements; status `DEFER_PRICE_CONFLICT` when unresolved.
- Yahoo remains fallback where CRSP has no usable window.

## How to regenerate (once credentials exist)

```bash
cd pe-tracker
export CRSP_ACCESS_MODE=wrds   # or flat_file
export WRDS_USERNAME='…'
export SEC_USER_AGENT='…'
python -m scripts.fetch_target_prices
# then run the reconciliation helper / notebook that writes this file
```
