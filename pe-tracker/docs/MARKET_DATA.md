# Market data (FRED) → point-in-time market context

```
FRED API ──► parse ("." → NULL) ──► prices              (current value per date; legacy signals)
                                └─► market_observations (append-only: valid time, value|NULL,
                                                         source, source_identifier, known_at,
                                                         known_at_basis, ingestion time)
                                          │
                     research/market_data.series_as_of(T)   (valid ≤ T and known_at ≤ T)
                                          │
              returns / levels / changes / spreads (each carries its provenance)
                                          │
                  market_context_from_store ──► PointInTimeMarketContext ──► features X[t]
```

## Series
| Series | Meaning | Registry |
|---|---|---|
| SP500 | S&P 500 | `config.SERIES` |
| NASDAQCOM | NASDAQ Composite | `config.SERIES` |
| DCOILWTICO | WTI crude, Cushing spot | `config.SERIES` |
| DCOILBRENTEU | Brent crude, Europe spot | `config.SERIES` |
| **DGS10** | 10-Year Treasury constant maturity (%) | `ingest/market_series.RATE_SERIES` |
| **DFF** | Effective Federal Funds Rate (%) | `ingest/market_series.RATE_SERIES` |

DGS10 lives outside `config.py` because that file holds the locked strategy contract. It
follows the bond-market (SIFMA) calendar, so on days when NYSE is open but the bond market
is closed it stays **NULL**.

DFF sits in the same registry. FRED publishes it for every calendar day, weekends included.
It is **research context only**: you can query it point-in-time through `series_as_of`,
`level` and `change`, but it is not in `RESEARCH_FEATURES`, `PointInTimeMarketContext` or
`fs_v1`.

## Coverage window (project policy)
Every FRED pull is **floored at `config.START_DATE` = 2026-04-20**, the tracker's first logged
session, so the project covers April 20, 2026 to the present. `fetch_series` raises an
earlier `start` to that date instead of returning an error. A later `start` is kept.

This is a **project data-coverage policy, not a FRED limitation.** FRED's own history goes
much further back:

| Series | FRED history begins |
|---|---|
| DFF | 1954-07-01 |
| DGS10 | 1962-01-02 |
| NASDAQCOM | 1971-02-05 |
| DCOILWTICO | 1986-01-02 |
| DCOILBRENTEU | 1987-05-20 |
| SP500 | rolling 10 years (licensing) |

Widening the window means changing `START_DATE` on purpose and rebuilding the trading
calendar (`python -m src.cli init`).

## Rules
* **Key:** read only from the `FRED_API_KEY` environment variable. Error messages are
  redacted (`api_key=***`). It never appears in the repo, CI, logs or command output. A test
  scans tracked files for anything that looks like a key.
* **Missing data:** FRED's `"."` becomes NULL and stays NULL. Returns skip gaps (they use
  the last two *real* prints) and never fill them.
* **Duplicates and revisions:** re-pulling an identical value adds nothing. A *changed*
  value (a FRED revision) is appended with its own known_at, so earlier as-of views still
  see the original value.
* **known_at:**
  * Live pulls (`--vintage current`) use the ingestion time.
  * `--vintage first_release` uses ALFRED's initial-release date, stored as the **end of
    that day**, because FRED does not publish the time of day.
  * Nothing else is inferred. Backfilled history pulled today is known from today unless
    first-release vintages are requested. Some series (licensed indices such as SP500) may
    have no ALFRED vintages; check this after network access is granted.
* **Calendar:** observations are stored for every date FRED returns. The NYSE
  `market_calendar` gate applies wherever the signal code joins against it.

## Research features (not in the active model)
`research/market_data.RESEARCH_FEATURES`:

* sp_return, nasdaq_return, wti_return, brent_return
* brent_wti_spread
* ust10y (level), ust10y_change

Only `sp_return`, `nasdaq_return` and `ust10y` are fed to `PointInTimeMarketContext`.
**None of them is in the break model's feature schema `fs_v1`.** Adding any of them requires
an empirical case and a new `feature_schema_version`.

## Crude spread percentile (fixed)
`arb/crude_spread.add_zscore` previously computed `pctile = s.rank(pct=True)` over the whole
sample, so a past value depended on future spreads. It is now an **expanding** percentile:
the share of real spreads seen on or before t that are ≤ the spread at t. The z-score is
unchanged; its trailing window was already point-in-time. A regression test appends future
data and asserts that the past signal does not change.

## Running
```
export FRED_API_KEY=…          # never commit it
python -m src.cli pull                               # current values, 2026-04-20 → today
python -m src.cli pull --vintage first_release
python -m src.cli pull --start 2026-09-01            # later starts are kept; earlier ones are floored
FRED_LIVE=1 python -m pytest tests/test_fred_live.py # optional live check
```
Requires network access to `https://api.stlouisfed.org`.
