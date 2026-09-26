# pe-tracker architecture

This is a merger-arbitrage research system. Its one design rule is that
**nothing may use information that was not public at the time being studied.**
Each layer below enforces that rule on its own, so no layer has to trust the
one above it.

```
PRIMARY SOURCES     SEC EDGAR · market-data providers (FRED, …)
        ↓
CANONICAL WRITE     SQLite pe-tracker (deals, observations, events,
STORE               valid_time, known_at, provenance, model_registry,
                    immutable predictions)
        ↓ read-only analytical replication
DUCKDB / DBT        arb-intelligence — projection, not a competing SoT
        ↓
PIT RECONSTRUCTION  valid ≤ T AND known_at ≤ T
        ↓
FEATURES / DATASETS announcement snapshots (fs_v1);
                    future risk-set snapshots (fs_v2 — design only)
        ↓
MODELS              break_logit_v1 (baseline);
                    future break_hazard_v1 (design only — see MODEL_ARCHITECTURE_V2.md)
        ↓
VALIDATION          chronological walk-forward
        ↓
REGISTRY            cohort + dataset_fingerprint + sample_prevalence metadata
        ↓
DECISION / RISK     EV, portfolio, simulation (separate from P(break))
```

Dagster may orchestrate replication/transformation into DuckDB but must not
become an alternate canonical writer.

## Layer by layer

| Layer | Where | What it guarantees |
|---|---|---|
| Storage | `schema.sql`, `src/db.py` | Research tables are append-only. UPDATE/DELETE are blocked by triggers, and orphan deal IDs are rejected. Legacy tables are rebuilt only if they are empty. |
| Time rule | `src/research/bitemporal.py` | Every fact has three times: *valid* (when it was true), *known_at* (when it became public) and *ingestion* (when we recorded it). A read as of T sees a fact only if valid ≤ T and known_at ≤ T. known_at is never guessed. |
| Deal state | `src/research/observations.py`, `events.py` | Deal terms carry forward until a sourced amendment replaces them. Market prices do **not** carry forward beyond a short staleness window. Event order is validated when events are written. |
| Market data | `src/research/market_context.py` | Every market value has a timestamp, source and publication time. Raw dictionaries are rejected. |
| Features | `src/research/features.py` | A pure function of what was knowable. A missing input gives `None`, never `0`. Offer value depends on the consideration type (cash, stock or mixed). |
| Training data | `src/model/dataset.py` | One row per deal, taken at the exact moment its announcement became public. Label: break = 1, close = 0, pending = censored (never treated as a negative). |
| Sampling / cohort | `docs/SAMPLING_FRAME.md`, `src/model/cohort.py` | Canonical corpus ≠ model cohort. Convenience / outcome-enriched samples are not silently treated as population draws. |
| Fingerprint | `src/model/fingerprint.py` | SHA-256 of a canonical serialization of training rows for reconstructibility. |
| Model | `src/model/logistic.py` | L2 logistic regression with fixed C. Imputation uses training-set medians plus missingness indicators. Outputs are raw (uncalibrated) probabilities in v1. |
| Validation | `src/model/validation.py`, `evaluate.py` | Splits are chronological only. The threshold t* is chosen on training data and **frozen** before the test period. Results are compared against constant and spread-only baselines. |
| FRED store | `src/ingest/fred.py`, `src/research/market_data.py` | FRED data flows into the append-only `market_observations` table with known_at and provenance, then into point-in-time returns, levels and spreads, then into `PointInTimeMarketContext`. None of these are active model features. See `MARKET_DATA.md`. |
| Historical deals | `src/ingest/historical.py`, `providers/sec_edgar.py` | Strict record contract. Incomplete records are quarantined. Every fact gets a `record_provenance` row. Ingestion never fits the model. See `HISTORICAL_DEAL_DATA_SOURCES.md`. |
| Data readiness | `src/model/data_quality.py` | Dataset-quality report and `MODEL_DATA_STATUS` gate. |
| Registry | `src/model/registry.py` | Fitted models store version, cutoff, n, sample prevalence, cohort ids, dataset fingerprint, hyperparameters, calibration JSON, code commit. Predictions are immutable; DB rejects lookahead. |
| Use | `decision.py`, `backtest.py`, `bridge.py` | Trade decisions are kept separate from the probability model. The backtester only uses a p_break that was available at entry. Break losses without a sourced exit price are labelled *modeled*, never *realized*. |

## Where to start reading
1. `schema.sql`: the data contract.
2. `src/research/bitemporal.py`: the time rule, in about 50 lines.
3. `src/research/features.py`: what the model sees.
4. `src/model/validation.py`: how the model is judged.
5. `docs/SAMPLING_FRAME.md`, `docs/MODEL_ARCHITECTURE_V2.md`, `docs/BITEMPORAL_POINT_IN_TIME.md`, `docs/BREAK_PROBABILITY_MODEL_V1.md`.

## Locked strategy
The research contract (`event_driven_v1`) lives in `STRATEGY.md` and `src/config.py`.
`tests/test_strategy_contract.py` fails the build if it drifts.

## Current status (at this commit)

Distinguish carefully:

| Claim | Status |
|---|---|
| Research infrastructure | Built and tested |
| Validated software (pytest / dbt gates) | Yes |
| Validated probability model (population-calibrated) | **No** |
| Proven alpha | **No** |

At base commit `82638705278ca5da14fa1dd47cb585ce71adafd5`,
`python -m src.model.data_quality` reported a reviewer-curated corpus with
**24** eligible labeled rows (12 close / 12 break) and
`MODEL_DATA_STATUS = READY_FOR_EXPERIMENTAL_WALK_FORWARD`. That gate means an
experiment *may* be authorized later — not that a model has been fit or that
sample prevalence is a population break rate. See `SAMPLING_FRAME.md`.
