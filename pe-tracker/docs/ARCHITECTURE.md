# pe-tracker architecture

This is a merger-arbitrage research system. Its one design rule is that
**nothing may use information that was not public at the time being studied.**
Each layer below enforces that rule on its own, so no layer has to trust the
one above it.

```
                ┌──────────────────────────── sources (never fabricated) ─────────────────────────────┐
                │  FRED prices      sourced deal filings / prints      HistoricalDealProvider (TBD)   │
                └───────┬───────────────────────────┬───────────────────────────────┬─────────────────┘
                        ▼                           ▼                               ▼
  STORAGE  (schema.sql, SQLite)                                                                
   prices / market_calendar      deals (ledger)   deal_market_observations   deal_events
                                                  └── bitemporal + append-only (DB triggers, FK) ──┘
                        │                           │
  RESEARCH (src/research)                           ▼
   market_context ──► features.build_features ◄── observations.state_as_of + events.events_as_of
                                   │                      (valid ≤ T AND known_at ≤ T)
                                   ▼
  MODEL (src/model)
   dataset ─► logistic (fit) ─► validation (walk-forward, frozen t*) ─► registry (immutable predictions)
                                                                            │
  USE                                                                       ▼
   decision (EV = (1−p)U − pD)        backtest (+ bridge: p_break knowable at entry)      portfolio / simulation
```

## Layer by layer

| Layer | Where | What it guarantees |
|---|---|---|
| Storage | `schema.sql`, `src/db.py` | Research tables are append-only. UPDATE/DELETE are blocked by triggers, and orphan deal IDs are rejected. Legacy tables are rebuilt only if they are empty. |
| Time rule | `src/research/bitemporal.py` | Every fact has three times: *valid* (when it was true), *known_at* (when it became public) and *ingestion* (when we recorded it). A read as of T sees a fact only if valid ≤ T and known_at ≤ T. known_at is never guessed. |
| Deal state | `src/research/observations.py`, `events.py` | Deal terms carry forward until a sourced amendment replaces them. Market prices do **not** carry forward beyond a short staleness window. Event order is validated when events are written. |
| Market data | `src/research/market_context.py` | Every market value has a timestamp, source and publication time. Raw dictionaries are rejected. |
| Features | `src/research/features.py` | A pure function of what was knowable. A missing input gives `None`, never `0`. Offer value depends on the consideration type (cash, stock or mixed). |
| Training data | `src/model/dataset.py` | One row per deal, taken at the exact moment its announcement became public. Label: break = 1, close = 0, pending = censored (never treated as a negative). |
| Model | `src/model/logistic.py` | L2 logistic regression with fixed C. Imputation uses training-set medians plus missingness indicators. Outputs are raw (uncalibrated) probabilities in v1. |
| Validation | `src/model/validation.py`, `evaluate.py` | Splits are chronological only. The threshold t* is chosen on training data and **frozen** before the test period. Results are compared against constant and spread-only baselines. |
| FRED store | `src/ingest/fred.py`, `src/research/market_data.py` | FRED data flows into the append-only `market_observations` table with known_at and provenance, then into point-in-time returns, levels and spreads, then into `PointInTimeMarketContext`. None of these are active model features. See `MARKET_DATA.md`. |
| Historical deals | `src/ingest/historical.py`, `providers/sec_edgar.py` | Strict record contract. Incomplete records are quarantined. Every fact gets a `record_provenance` row. Ingestion never fits the model. See `HISTORICAL_DEAL_DATA_SOURCES.md`. |
| Data readiness | `src/model/data_quality.py` | Dataset-quality report and `MODEL_DATA_STATUS` gate. |
| Registry | `src/model/registry.py` | Each fitted model is stored with its metadata. Predictions are immutable, and the database rejects any prediction made by a model trained after the prediction time. |
| Use | `decision.py`, `backtest.py`, `bridge.py` | Trade decisions are kept separate from the probability model. The backtester only uses a p_break that was available at entry. Break losses without a sourced exit price are labelled *modeled*, never *realized*. |

## Where to start reading
1. `schema.sql`: the data contract.
2. `src/research/bitemporal.py`: the time rule, in about 50 lines.
3. `src/research/features.py`: what the model sees.
4. `src/model/validation.py`: how the model is judged.
5. `docs/BITEMPORAL_POINT_IN_TIME.md` and `docs/BREAK_PROBABILITY_MODEL_V1.md`: the detail behind both.

## Locked strategy
The research contract (`event_driven_v1`) lives in `STRATEGY.md` and `src/config.py`.
`tests/test_strategy_contract.py` fails the build if it drifts.

## Current status
The infrastructure is built and tested (pytest plus 6 dbt invariants in CI). The real store
has **0 labelled deals**, so no predictive claim is made: *model infrastructure validated,
insufficient data for alpha claim.*
