# Delisted equity price provider requirements

**Status:** Revolution 3 — no free `AVAILABLE_NOW` secondary provider found that
covers delisted US merger targets with automated, license-compliant access from
this environment.

`DELISTED_PRICE_DATA_LICENSE_REQUIRED = YES`

## Why this document exists

After provider abstraction (Revolution 1) and full-corpus gap classification
(Revolution 2), **115 / 129** deals remain without ≥3 Yahoo session closes.
The readiness gate (≥20 deals) must not be lowered. Closing the gap requires
a licensed historical equity source with **delisted** coverage.

## Candidate provider survey (research snapshot)

| Provider | Delisted US equities | API | Classification | Notes |
|---|---|---|---|---|
| Yahoo Finance chart | Partial / weak | Public chart API | `AVAILABLE_NOW` (already integrated) | No usable history for most taken-private names |
| Stooq | Mixed | CSV download | `UNSUITABLE` here | JS anti-bot challenge blocks automation |
| Nasdaq Data Link / API | Limited for delisted | API key | `REQUIRES_API_KEY` / often paid | Delisted symbols frequently 400/404 |
| Polygon.io | Yes (flat files / aggregates) | API key + paid plans | `REQUIRES_PAID_LICENSE` | Strong candidate once credentials exist |
| Tiingo | Some | API key | `REQUIRES_API_KEY` | Confirm delisted depth before purchase |
| Alpha Vantage | Limited | API key | `REQUIRES_API_KEY` / `UNSUITABLE` for delisted depth | Not sufficient for corpus unblock |
| CRSP (WRDS) | Yes (authoritative academic) | Institutional | `INSTITUTIONAL_ONLY` | Best scientific standard; needs WRDS access |
| Bloomberg / FactSet / LSEG | Yes | Terminal / licensed API | `INSTITUTIONAL_ONLY` | Full corporate-action stack |

No paid credentials are configured in this repository. Do not pretend retrieval succeeded.

## Minimum procurement specification

### Universe
- All uncovered deal targets in `data/target_price_coverage_matrix.json`
  with `gap_class = DELISTED_NO_PROVIDER_HISTORY` (115 as of this writing)
- Prefer coverage for the full SEC reviewed corpus (N=129) for future refreshes

### Identifiers (required)
For each security, at least one of:
- CIK (`target_cik` from `sec_deal_manifest.json`)
- Historical ticker **as of announcement date**
- FIGI / PERMNO / Bloomberg ID (preferred for delisted)

Must support mapping **historical** ticker → price series without confusing
reused modern tickers.

### Fields (required)
| Field | Required |
|---|---|
| session_date (exchange calendar) | YES |
| unadjusted close | YES |
| adjusted close | YES if available (store separately) |
| currency | YES |
| exchange / mic | YES when known |
| corporate action flags / notes | YES when available |

### Window
For each deal, announce date → resolution date inclusive, plus ≤5 calendar-day
pad (matches current orchestrator `pad_days=3` default; document any change).

Do **not** download arbitrary multi-decade history unless needed for corporate-action reconstruction.

### Session rules
- Daily regular-session closes only
- Must align with NYSE/Nasdaq trading calendar (no weekend/holiday fabrications)

### Corporate actions
Preserve raw vs adjusted. `spread_stress_v1` uses **unadjusted close** for
`ΔS` / `σ_ΔS` unless a separately versioned rule says otherwise. Never mix
adjusted and unadjusted in one spread calculation without a version bump.

### Volume estimate
- ~115 deals × ~60–400 sessions ≈ **7k–50k** daily bars for a first backfill
- Refresh: only new deals / extended windows (low hundreds of requests/day)

### Licensing
- Redistribution of vendor prints into this private research repo must be
  allowed by the license, or prints must remain behind an access-controlled
  store that the license permits
- Do not scrape HTML or bypass auth

## Adapter to implement once credentials exist

Implement:

```
src/ingest/equity_prices/<vendor>.py
```

conforming to `HistoricalEquityPriceProvider`, then register it **after** Yahoo
in `default_providers()`:

```
[YahooEquityPriceProvider(), LicensedVendorProvider(...)]
```

Normalized output must be `NormalizedEquityObservation` — no vendor schema
leakage. On credential absence:

```
credentials_required() -> True
status -> CREDENTIALS_REQUIRED
```

Never fabricate responses.

## Readiness after integration

Re-run:

```bash
SEC_USER_AGENT=… python -m scripts.fetch_target_prices
```

Expect:

- `DEALS_WITH_3PLUS_PRINTS >= 20` → `HISTORICAL_PRICE_DATA_READY = YES`
- Do **not** auto-execute `spread_stress` / walk-forward / model fit
- Report `SPREAD_STRESS_READY_FOR_EXECUTION = YES` only when the separate
  execution gate authorizes it

## Absolute prohibitions (unchanged)

No synthetic closes, interpolation, forward-fill, deal-term substitution,
acquirer-ticker reuse, or gate lowering.
