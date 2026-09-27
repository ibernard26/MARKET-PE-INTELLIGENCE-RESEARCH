# Target price coverage gaps

**Status:** Revolution 2 of the historical-price provider loop.  
**Gate:** still `BLOCKED_INSUFFICIENT_PRICE_HISTORY` (≥20 deals with ≥3 prints required).  
**Data file:** `data/target_price_coverage_matrix.json`

## Summary

| Metric | Value |
|---|---|
| Canonical SEC deals | 129 |
| Deals with ≥3 real prints | **14** |
| Uncovered deals | **115** |
| Accepted prints | 3806 |
| Dominant gap class | `DELISTED_NO_PROVIDER_HISTORY` (115) |

No tickers were invented. Symbols come only from:

1. `data/target_ticker_map.json` (reviewed overrides — currently empty)
2. SEC `company_tickers.json` (current filers)
3. `DEAL-{TICKER}-…` corpus naming convention

## Gap taxonomy

| Class | Meaning | Count (this snapshot) |
|---|---|---|
| `DELISTED_NO_PROVIDER_HISTORY` | Symbol resolved, but Yahoo (current free provider) returned no usable daily closes in the announce→resolve window | 115 |
| `HISTORICAL_TICKER_UNKNOWN` | No ticker established under the identity rules | 0 |
| `HISTORICAL_TICKER_AMBIGUOUS` | Conflicting symbol evidence — deferred | 0 |
| `PROVIDER_SYMBOL_MAPPING_FAILURE` | Provider rejected the symbol as unknown | 0 |
| `PROVIDER_TRANSIENT_FAILURE` | Retryable provider failure exhausted | 0 |
| `NO_PUBLIC_MARKET_HISTORY` | Target never had a public continuous listing in-window | 0 |
| `OTHER` | Residual | 0 |

## Why Yahoo fails for most closed deals

Taken-private / acquired targets are typically **delisted**. Yahoo’s public chart
API does not retain a usable daily history for most of those symbols. Free
endpoints reachable from this environment (Yahoo, Stooq with JS challenge,
Nasdaq historical for delisted names) do not close the gap.

This is a **data-licensing** problem, not a readiness-gate problem. The ≥20-deal
gate must not be lowered.

## Covered deals (n≥3)

See rows in `target_price_coverage_matrix.json` with `"gap_class": null`.
Examples include still-listed or long-pending names such as HUM, CPRI, ESI,
SSTK, WTW (via SEC current ticker), GNW, etc.

## Next resolvable action (all 115 uncovered)

> Procure a licensed delisted-equity history source (CRSP / Bloomberg /
> Polygon flat files / equivalent) and implement a secondary
> `HistoricalEquityPriceProvider` adapter under
> `src/ingest/equity_prices/`.

Do **not**:

* scrape paywalled sites
* invent closes from deal terms
* forward-fill or interpolate
* reuse the acquirer’s ticker for the target
* assign a modern reused ticker to an older issuer without evidence

## How to refresh the matrix

After any provider/identity change:

```bash
cd pe-tracker
SEC_USER_AGENT='…' python -m scripts.fetch_target_prices
# then regenerate the matrix (or re-run the Revolution 2 classifier)
```
