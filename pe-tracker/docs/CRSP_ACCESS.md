# CRSP / WRDS access for historical target prices

CRSP is the **preferred** historical research provider for delisted U.S. equities.
Yahoo remains a secondary fallback.

## Current status

| Flag | Value |
|---|---|
| CRSP_ACCESS_AVAILABLE | **NO** (this environment) |
| CRSP_ACCESS_MODE | `none` |
| CRSP_LICENSE_DATA_COMMITTED_TO_GIT | **NO** |
| Adapter implemented | YES (`src/ingest/equity_prices/crsp.py`) |
| Live backfill | blocked — `CREDENTIALS_REQUIRED` |

## What the user must provide

Pick **one** legitimate access path:

### Option A — WRDS

1. Institutional WRDS account with CRSP subscription (CIZ / Flat File 2.0 preferred).
2. Export credentials into the environment (never commit):

```bash
export CRSP_ACCESS_MODE=wrds
export WRDS_USERNAME='your_wrds_user'
# password via WRDS_PASSWORD, ~/.pgpass, or wrds interactive — not Git
```

3. Optional table overrides if your library layout differs:

```bash
export CRSP_DAILY_TABLE='crsp.dsf_v2'
export CRSP_NAMES_TABLE='crsp.stocknames_v2'
export CRSP_DELIST_TABLE='crsp.dlstdt_v2'
```

4. Install the WRDS Python client in the runtime used for fetches (`pip install wrds`).

### Option B — Licensed flat files

1. Obtain CRSP daily + name-history + delisting files under your license.
2. Place them **outside Git** (or under the gitignored path below):

```bash
export CRSP_ACCESS_MODE=flat_file
export CRSP_DATA_DIR='/licensed/crsp'   # or pe-tracker/data/licensed/crsp
```

3. Confirm redistribution terms before writing any vendor rows into a shared repo.

## License-safe storage

| Path | Purpose | Git |
|---|---|---|
| `pe-tracker/data/licensed/crsp/` | raw vendor extracts | **ignored** |
| `pe-tracker/data/crsp_security_map.json` | deal→PERMNO metadata only | commit when evidence-backed |
| `pe-tracker/data/target_price_manifest.json` | normalized research prints | only if license permits redistribution |

Do **not** commit passwords, `.pgpass`, or raw CRSP dumps.

## Provider precedence

```
1. CRSP   (when credentials_required() is False)
2. Yahoo
3. NO_HISTORY / CREDENTIALS_REQUIRED / DEFER
```

Overlapping CRSP vs Yahoo sessions are compared (`compare_provider_series`);
material conflicts → `DEFER_PRICE_CONFLICT` (never silent min/max pick).
CRSP is preferred for the canonical research path when identity + coverage are valid.

## Price acceptance (`crsp_dlyprc_acceptance_v1`)

| Field | Rule |
|---|---|
| `DlyPrc` | unadjusted session price → `NormalizedEquityObservation.close` |
| `DlyPrcFlg` blank / null / `T` | **accepted** as traded close |
| `DlyPrcFlg` = `A` | **rejected** for spread_stress (bid/ask average ≠ trade) |
| other flags | rejected until a versioned rule permits them |
| delisting `DelDtPrc` / delisting return | **not** mixed into the daily close series |

`spread_stress_v1` continues to use **unadjusted** close unless a separate
versioned contract changes that.

## After credentials are available

1. Resolve PERMNOs → update `data/crsp_security_map.json` (PR2).
2. Backfill announce→resolution windows for uncovered deals (PR3).
3. Recompute `DEALS_WITH_3PLUS_PRINTS`; keep gate ≥20.
4. Do **not** auto-run model fit / walk-forward / spread_stress.

## Absolute prohibitions

No fabricated credentials, fabricated CRSP responses, paywall bypass,
interpolation, forward-fill, or deal-consideration substitution.
