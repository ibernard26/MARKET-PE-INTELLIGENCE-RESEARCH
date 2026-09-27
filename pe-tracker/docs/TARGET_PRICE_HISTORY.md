# Target price history for `spread_stress_v1`

## Why this exists
`ΔS` / `σ_ΔS` need **longitudinal target prints** between announcement and
resolution. The SEC reviewed deal manifest supplies terms and outcomes, not
daily closes. FRED supplies index/commodity series, not single-name equities.

## Provider architecture (Revolution 1)

```
Yahoo ──────┐
            │
Provider B ─┼──► NORMALIZER ─► NormalizedEquityObservation
            │                  ─► target_price_manifest.json
Provider C ─┘
```

| Module | Role |
|---|---|
| `src/ingest/equity_prices/protocol.py` | `HistoricalEquityPriceProvider` |
| `src/ingest/equity_prices/schema.py` | normalized observation + `ProviderStatus` |
| `src/ingest/equity_prices/identity.py` | security identity (separate from prices) |
| `src/ingest/equity_prices/yahoo.py` | Yahoo adapter |
| `src/ingest/equity_prices/orchestrator.py` | ordered fallback; no blind merges |
| `src/ingest/equity_prices/normalize.py` | provider → manifest bridge |

Yahoo-specific fields do **not** leak into modeling code. Failure states are
explicit (`AVAILABLE`, `NO_HISTORY`, `DELISTED_UNAVAILABLE`, …).

## Sources used

| Source | Role | Provenance |
|---|---|---|
| `data/sec_deal_manifest.json` | deal universe, CIK, announce/resolve window | reviewed SEC accessions |
| `https://www.sec.gov/files/company_tickers.json` | CIK → ticker for **current** filers | SEC; requires `SEC_USER_AGENT` |
| `data/target_ticker_map.json` | optional reviewed ticker overrides | empty unless a human verifies a correction |
| `DEAL-{TICKER}-…` deal_id convention | fallback ticker guess | corpus naming heuristic |
| Yahoo Finance chart API (`query2…/v8/finance/chart`) | daily close prints | `source_name=yahoo_finance_chart` |

## What is NOT claimed
* Yahoo is **not** a licensed CRSP/Bloomberg archive. Delisted / taken-private
  targets usually return **no history** from this endpoint.
* Missing history stays missing. No interpolation, no carry-forward beyond the
  observation layer’s existing print-staleness rules.
* Unit tests use **mocked** chart payloads only. They never write real prices
  into the canonical store.

## known_at rule
For each session close:

* `observation_timestamp` = `YYYY-MM-DDT16:00:00` (America/New_York regular close)
* `known_at` = same instant (`explicit` basis)

A daily exchange close was publicly knowable at that session’s close.

## How to refresh
```bash
cd pe-tracker
export SEC_USER_AGENT='MARKET-PE-INTELLIGENCE-RESEARCH you@example.com'
python -m scripts.fetch_target_prices
```

Writes:

* `data/target_price_manifest.json` — accepted prints only
* `data/target_price_fetch_audit.json` — per-deal status (`ok` / `no_price_history` / …)

## Readiness
`spread_stress` backtest stays
`BLOCKED_INSUFFICIENT_PRICE_HISTORY` until ≥ `MIN_SAMPLE_N` deals have
≥ 3 sourced target prints in-window. With Yahoo alone, that bar is typically
missed because most closed targets are delisted. Unblocking the full corpus
requires a licensed delisted-equity history vendor (not configured here).

### Latest fetch snapshot (this branch)

| Metric | Value |
|---|---|
| SEC manifest deals | 129 |
| Deals with ≥3 Yahoo prints | **14** |
| Accepted prints in manifest | 3806 |
| `no_price_history` (incl. delisted 404/400) | 115 |
| Gate | `BLOCKED_INSUFFICIENT_PRICE_HISTORY` |

Only Yahoo-sourced rows are committed (`source_name=yahoo_finance_chart`).
Test fixtures remain synthetic/mocked and do not enter the manifest.
