# pe-tracker

Market-intelligence pipeline tracking equity indices, crude benchmarks, and
private-equity deal flow, with an **event-driven / merger-arb** research thesis:
score whether an announced deal will **break**, and grade the score after it
resolves.

Replaces a hand-maintained workbook in which every derived value was typed by
hand, weekend rows carried fabricated closes, and the BUY/HOLD/SELL column had
no written rule.

## Design rules
1. **One source of truth.** SQLite. The spreadsheet is an output, never an input.
2. **Nothing derived is stored.** Δ%, MAs, MTD, spreads are computed on read.
3. **A gap stays a gap.** A missing observation is `NULL`. Never carried forward.
4. **The calendar gates ingestion.** A non-session date cannot receive a price.
5. **The signal rule is code.** Versioned by ruleset, so a threshold change is a
   new version, not a silent rewrite.

The live strategy is defined once in **`STRATEGY.md`** (`event_driven_v1`) and
pinned in `src/config.py`; `tests/test_strategy_contract.py` fails the build if
any constant drifts.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add a free FRED key
```

## Usage
```bash
python -m src.cli init                                   # schema + trading calendar
python -m src.cli migrate data/MI_PE_Phase0_Clean.xlsx   # seed from the workbook (optional)
python -m src.cli pull                                   # authoritative FRED data
python -m src.cli gaps --series SP500
python -m src.cli signals --tail 15
python -m src.cli sweep                                  # threshold grid (thin-flagged)
python seed_deals.py                                     # seed the deal ledger
python -m src.cli scorecard --group-by all               # deal-break scorecard
python -m src.cli arb                                    # arbitrage opportunities (all engines)
pytest -q
```

## Arbitrage engines (`src/arb/`)
- **Merger arb** (`merger.py`) — for each live (pending) deal: gross spread,
  annualized return, and **break-adjusted EV** `= (1-p_break)·upside − p_break·downside`,
  ranked by annualized break-adjusted EV. Point-in-time (only deals pending as-of
  the date; horizon measured from it). Deals without a stored live quote surface as
  `awaiting_quote`, never fabricated. (Seed quotes are illustrative.)
- **Crude spread** (`crude_spread.py`) — Brent−WTI spread from the store, rolling
  z-score + percentile, mean-reversion entry flags. Fully data-backed; a missing leg
  stays NaN, never filled.
- **Index RV** (`index_rv.py`) — S&P 500 / NASDAQ ratio z-score, explicitly a weak
  **baseline** (exists to be beaten, not traded).

## Data (FRED)
| Series | FRED id |
|---|---|
| S&P 500 | `SP500` |
| NASDAQ Composite | `NASDAQCOM` |
| WTI Cushing spot | `DCOILWTICO` |
| Brent Europe spot | `DCOILBRENTEU` |

## Deal-break model (the live thesis)
`deals` ledger + `src/compute/metrics.py`: ROC AUC (rank statistic,
sklearn-verified) and PR AUC beside π, on the imbalanced break-vs-close problem,
with a cost-based operating point (FN:FP = 15:1). Pending deals are censored;
everything is point-in-time. See `STRATEGY.md`.

## Status
- Phase 0 — workbook cleanup, calendar guard, rule codified ✅
- Phase 1 — SQLite store, FRED ingestion, gap reporting, backtest harness ✅
- Phase 2 — threshold sweep with overfitting guard ✅
- Phase 3 — deal-break evaluation (metrics, scorecard, strategy contract) ✅
- Phase 4 — generated workbook (`generate_workbook.py`) ✅

_Research tooling, not investment advice._
