# Free thesis data stack — OpenFIGI + Tiingo + Yahoo

**ACTIVE** historical research stack for the thesis-data phase.

```
SEC EDGAR → deal identity
    → OpenFIGI (FIGI mapping)
    → Tiingo (primary EOD)
    → Yahoo (reconcile / fallback)
    → NormalizedEquityObservation
```

## Credential environment variables

| Variable | Role |
|---|---|
| `OPENFIGI_API_KEY` | OpenFIGI mapping |
| `TIINGO_API_TOKEN` | Tiingo EOD (`TIINGO_API_KEY` accepted as alias) |
| `SEC_USER_AGENT` | SEC company_tickers lookup |

Never commit values. Presence helpers return YES/NO only.

## CRSP freeze

| Flag | Value |
|---|---|
| CRSP_STATUS | `FROZEN_FUTURE_ROBUSTNESS_PROVIDER` |
| CRSP_ACTIVE_INGESTION | **NO** |
| CRSP_REQUIRED_FOR_THESIS | **NO** |

CRSP adapter/tests remain in-tree for future institutional replication.

## Provider precedence

1. Tiingo (when token present)
2. Yahoo
3. NO_HISTORY / CREDENTIALS_REQUIRED / DEFER

Yahoo observations are preserved for reconciliation. Conflicts are never averaged.

Reconciliation rule: `price_reconcile_v1` (`ABS_EPS=1e-4`, `REL_EPS=1e-6`).

## Commands

```bash
cd pe-tracker
# presence only — exits 3 if missing
python -m scripts.run_free_price_coverage
```

Writes:

- `data/free_price_coverage_matrix.json`
- `data/target_price_manifest.json` (normalized; license-safe free providers)
- `data/free_price_fetch_audit.json`

## Gates

Keep ≥20 deals with ≥3 real prints. Do not auto-run `spread_stress` / model fit.
