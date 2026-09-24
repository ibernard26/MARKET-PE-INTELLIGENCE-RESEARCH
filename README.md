# Market & PE Intelligence Research

An event-driven **merger-arbitrage research platform** — from raw market data to a
gradeable model of whether an announced M&A deal will **close or break**.

The project exists to fix one failure mode: research you can't grade. A directional
"stocks go up next week" call has no stated payoff, no resolution date, and no
observable condition committed to in advance, so it can never be scored. A merger has
all three. This repo turns that structure into a disciplined, testable pipeline — and
enforces, in code, the data invariants that separate a real back-test from a
flattering one.

> Research tooling and a portfolio project — **not investment advice.**

---

## The five invariants (enforced by tests, not just promised)

Every component below is built around the same non-negotiables:

| # | Invariant | Why it matters |
|---|---|---|
| 1 | **No fabrication** | a missing print is a true `NULL`/`n/d`, never `0.0`, forward-filled, or interpolated |
| 2 | **Calendar gate** | a price can never exist on a weekend or market holiday |
| 3 | **Point-in-time / no lookahead** | a deal's `p_break` is fixed at announce; a metric `as_of` date D uses only what was knowable on/before D |
| 4 | **Censored outcomes** | pending deals are excluded from evaluation, never counted as non-breaks |
| 5 | **Append-only & auditable** | deal history is versioned (SCD2 / Data-Vault), never mutated in place |

---

## What's inside

Three components, one thesis, the same invariants throughout.

### 1 · `pe-tracker/` — the research pipeline
A SQLite-backed Python pipeline that ingests market data from **FRED**
(S&P 500, NASDAQ, WTI, Brent), gates it against an NYSE calendar, and scores the
**deal-break** model. The evaluation is built for a rare positive class (breaks run
near a 10% base rate): **ROC AUC** (rank statistic, cross-checked against `sklearn`)
reported *beside* **PR AUC** and its baseline π, with a **cost-based operating point**
(a missed break costs ~15× a needless hedge, so the threshold sits far below 0.5).
The strategy is a **locked, versioned contract** (`STRATEGY.md`) that a test fails the
build on if any constant drifts. CI runs pytest (and the dbt tests) on every push and pull request.

**Data status.** The SQLite store (`pe-tracker/data/pe_tracker.db`) is the source of truth;
`MI_PE_Tracking_System.xlsx` is an output generated from it. The Q3 2026 deal register
(`pe-tracker/data/research/`) is research-only and never enters the model store. Historical
deals enter only through the reviewed `sec_deal_manifest.json`, which is currently empty, so the
break model has **no real labels** (`MODEL_DATA_STATUS = NO_REAL_LABELS`).

### 2 · `arb-intelligence/` — the production data architecture
The same estate rebuilt as a modern stack: **DuckDB + dbt + Dagster**. Raw → Silver →
Gold tiers, a dimensional model (`fact_price`, bitemporal `fact_deal_state`, conformed
dims) plus a Data-Vault-style deal satellite, and the invariants encoded as
**dbt tests** (calendar gate, no-lookahead, censoring, no-fabrication, resolution ≥
announce, pending-has-no-label). Verified end-to-end: **8 models build, 6 invariant
tests pass, the Dagster job returns `RUN_SUCCESS`** and exports the deal scorecard.

### 3 · `outputs/` — extension prompts
Ready-to-use handoff prompts that carry this project's real data and rules into other
tools: one for **ChatGPT** (build the `market-arb` quant engine) and one for **Gemini**
(design the target data architecture).

Plus the source intelligence layer: `MI_PE_Tracking_System.xlsx` (a 5-tab workbook that is an
output of the SQLite store), the daily `tracker/`, weekly `memos/`, the `automation/` loop, a
contrarian opportunities brief, and the full market-intelligence report.

---

## Architecture layers

The platform is organized as layers, each with a single job and the same invariants:

| Layer | Where | What it does |
|---|---|---|
| **Research** | `pe-tracker/` (Python / SQLite) | ingestion, deal-break scoring, arbitrage engines, evaluation |
| **Production data** | `arb-intelligence/` (DuckDB / dbt / Dagster) | Raw→Silver→Gold estate with invariants as dbt tests |
| **Historical research** | `pe-tracker/src/research/` | point-in-time observations & events, feature layer, event-driven backtester |
| **Portfolio / risk** | `pe-tracker/src/research/portfolio.py` | exposure, concentration, expected loss, event-driven stress scenarios |
| **Simulation** | `pe-tracker/src/research/simulation.py` | Python-first NumPy Monte Carlo (correlated breaks, VaR/ES), seeded |
| **Future native** | *(none yet)* | C++ quant-core — **only** after benchmark justification (`docs/CPP_QUANT_CORE_CRITERIA.md`) |

The historical research layer is append-only and strictly point-in-time: a feature
vector or backtest decision at date *t* uses only what was knowable at *t*, pending
deals are censored, and missing observations stay missing. See
`pe-tracker/src/research/` and `pe-tracker/benchmarks/` (synthetic, performance-only).

**C++ status: NOT JUSTIFIED YET** — Monte Carlo is the identified hotspot but runs
sub-second at real book size; criteria and measured benchmarks are in
`docs/CPP_QUANT_CORE_CRITERIA.md`.

---

## Worked example — reading the break risk in the EA buyout

**Electronic Arts, $55B take-private** (PIF / Silver Lake / Affinity, $210/share) — the
largest LBO on record. Shareholders had already approved it with ~99% of votes, so the
deal-economics risk was near zero. The merger data pointed to exactly one break vector:
a **foreign-sovereign buyer (PIF)** acquiring a US publisher with sensitive player data
→ a **CFIUS** national-security review, not antitrust or financing.

The point-in-time discipline: hold it as `pending` (censored) through the review rather
than guess. It resolved **closed on 2026-08-04** after CFIUS cleared on 2026-07-30. In
the scorecard the deal scores a Brier of `0.28² = 0.0784`, while the five still-pending
deals are correctly censored (no label, no error term). The actionable read a headline
never gives you: the spread that mattered was pricing *CFIUS headline risk*, and an arb
book would have sized it to the review calendar.

---

## Quickstart

**Research pipeline**
```bash
cd pe-tracker
pip install -r requirements.txt
cp .env.example .env            # add a free FRED key (fred.stlouisfed.org)
python -m src.cli init
python -m src.cli pull
python seed_deals.py
python -m src.cli scorecard --group-by all
pytest -q
```

**Data architecture (DuckDB + dbt + Dagster)**
```bash
cd arb-intelligence
pip install -e .
python scripts/migrate_sqlite_to_silver.py
dbt run --profiles-dir . --project-dir . && dbt test --profiles-dir . --project-dir .
dagster dev -m orchestrator.pipeline     # launch the orchestrator UI
```

---

## Repository map
```
pe-tracker/          research pipeline (SQLite) + locked strategy contract + tests
arb-intelligence/    DuckDB + dbt + Dagster data estate + invariant tests
outputs/             ChatGPT (quant engine) & Gemini (data architecture) prompts
MI_PE_Tracking_System.xlsx        5-tab market/deal workbook (output; SQLite is the source of truth)
tracker/  memos/  automation/     daily working layer, weekly memos, loop config
MI_PE_Market_Intelligence_Report.md         full intelligence report
Asymmetric_PE_MA_Opportunities_Mid2026.md   contrarian opportunities brief
```

## Skills this project demonstrates
- **Signal extraction from primary deal data** — locating a deal's break vector from its structure before the market prices the outcome.
- **Evaluation literacy on imbalanced problems** — ROC vs. PR AUC, base-rate awareness, cost-asymmetric operating points instead of a naïve 0.5.
- **Point-in-time rigor** — censoring, no lookahead, no fabricated inputs.
- **End-to-end data engineering** — SQLite → DuckDB/dbt/Dagster, with quality tests that encode the domain's real rules.
