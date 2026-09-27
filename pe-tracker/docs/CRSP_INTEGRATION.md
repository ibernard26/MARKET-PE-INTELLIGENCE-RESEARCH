# CRSP integration report

**CRSP_INTEGRATION_COMPLETE = YES** (adapter + identity + tests + access docs)  
**CRSP_ACCESS_AVAILABLE = NO**  
**CRSP_ACCESS_MODE = none**  
**CRSP_LICENSE_DATA_COMMITTED_TO_GIT = NO**

## Delivered (PR1 — architecture)

| Artifact | Role |
|---|---|
| `src/ingest/equity_prices/crsp.py` | `CRSPEquityPriceProvider` |
| `src/ingest/equity_prices/crsp_access.py` | WRDS / flat-file detection |
| `src/ingest/equity_prices/crsp_identity.py` | deal → PERMNO resolution |
| `data/crsp_security_map.json` | empty evidence-backed map scaffold |
| `docs/CRSP_ACCESS.md` | user credential / license instructions |
| `docs/CRSP_YAHOO_PRICE_RECONCILIATION.md` | reconciliation stub (blocked) |
| `tests/test_crsp_equity_prices.py` | mocked contract tests |

Provider precedence: **CRSP → Yahoo → NO_HISTORY**.

## Mapping (no live CRSP)

| Metric | Value |
|---|---|
| TARGETS_ATTEMPTED | 0 (credentials required) |
| PERMNO_MATCHED | 0 |
| IDENTITY_AMBIGUOUS | 0 |
| NO_MATCH | 0 |

## Prices

| Metric | Value |
|---|---|
| CRSP_DEALS_COVERED | 0 |
| CRSP_PRICE_PRINTS | 0 |
| YAHOO_DEALS_COVERED | 14 |
| TOTAL_DEALS_WITH_3PLUS_PRINTS | 14 |
| TOTAL_PRICE_PRINTS | 3806 |

## Gate

| Flag | Value |
|---|---|
| HISTORICAL_PRICE_DATA_READY | **NO** |
| SPREAD_STRESS_BACKTEST_STATUS | `BLOCKED_INSUFFICIENT_PRICE_HISTORY` |

## Contract invariants

| Flag | Value |
|---|---|
| SYNTHETIC_PRICES_ADDED | **NO** |
| EVENT_RULES_CHANGED | NO |
| FS_V1_CHANGED | NO |
| BREAK_LOGIT_V1_CHANGED | NO |
| REAL_MODEL_FIT_EXECUTED | NO |
| FIRST_WALKFORWARD_EXECUTED | NO |
| CALIBRATION_EXECUTED | NO |
| HYPERPARAMETER_TUNING | NO |

## Action required from user

Provide WRDS credentials (`WRDS_USERNAME` + password via secure channel) **or**
a licensed CRSP flat-file directory (`CRSP_DATA_DIR`), then re-run mapping (PR2)
and backfill (PR3). See `docs/CRSP_ACCESS.md`.

**STOP** at `CREDENTIALS_REQUIRED` until access exists. Do not lower the ≥20-deal gate.
