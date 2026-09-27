# Historical price provider loop — final report

**HISTORICAL_PRICE_PROVIDER_LOOP_COMPLETE = YES**  
(three engineering revolutions finished; licensed credentials are the remaining blocker)

## Phase 0

| Item | Value |
|---|---|
| START_MAIN_SHA | `2adfabbe5866682c0ad4f960be946b7c43e638fd` (#32 merged) |
| CANONICAL_N | 129 |
| PRICE_PRINT_COUNT | 3806 |
| DEALS_WITH_3PLUS_PRINTS | 14 |
| DEALS_WITH_NO_PRICE_HISTORY | 115 |
| HISTORICAL_PRICE_DATA_READY | NO |

## Revolutions

### 1 — Provider abstraction
PR: #33 (`cursor/equity-price-providers-097a`) — **merged**  
Delivered: `src/ingest/equity_prices/` protocol, schema, identity, Yahoo adapter,
orchestrator, normalizer, calendar gate, contract tests.  
Yahoo semantic data unchanged (3806 / 14).

### 2 — Coverage analysis
PR: #34 (`cursor/price-coverage-gaps-097a`) — **merged** onto main after #33  
Delivered: `target_price_coverage_matrix.json`, `TARGET_PRICE_COVERAGE_GAPS.md`.  
All 115 uncovered → `DELISTED_NO_PROVIDER_HISTORY`.

### 3 — Secondary provider / license
Same PR #34.  
No free `AVAILABLE_NOW` delisted source with license-compliant automation.  
Delivered: `DELISTED_PRICE_PROVIDER_REQUIREMENTS.md`.  
`DELISTED_PRICE_DATA_LICENSE_REQUIRED = YES`

## Ending metrics

| Item | Value |
|---|---|
| FINAL_MAIN_SHA | `bd0585ac6eb6fbc9ed3e67e9433dcce0e733eadb` (#33 + #34 merged) |
| PRICE_PRINTS | 3806 |
| DEALS_WITH_3PLUS_PRINTS | 14 |
| NO_PRICE_HISTORY | 115 |
| HISTORICAL_PRICE_DATA_READY | **NO** |
| SPREAD_STRESS_BACKTEST_STATUS | `BLOCKED_INSUFFICIENT_PRICE_HISTORY` |
| DELISTED_PRICE_DATA_LICENSE_REQUIRED | **YES** |

## Providers

| provider | status | delisted coverage | credentials | observations | deals unlocked |
|---|---|---|---|---|---|
| yahoo_finance_chart | AVAILABLE_NOW | weak | no | 3806 | 14 |
| licensed vendor (Polygon/CRSP/…) | REQUIRES_PAID_LICENSE / INSTITUTIONAL | required | yes | 0 | 0 |

## Invariants

| Flag | Value |
|---|---|
| SYNTHETIC_PRICES_ADDED | NO |
| EVENT_RULES_CHANGED | NO |
| FS_V1_CHANGED | NO |
| BREAK_LOGIT_V1_CHANGED | NO |
| REAL_MODEL_FIT_EXECUTED | NO |
| WALK_FORWARD_EXECUTED | NO |
| CALIBRATION_EXECUTED | NO |
| HYPERPARAMETER_TUNING | NO |

## Remaining blocker

Licensed delisted-equity history credentials + adapter implementation per
`docs/DELISTED_PRICE_PROVIDER_REQUIREMENTS.md`.

**STOP.** Do not lower the ≥20-deal gate. Do not execute models while blocked.
