# Strategy Contract — `event_driven_v1`

This is the **single, canonical definition of the strategy**. Every recurring
loop cycle and every fresh session reads the strategy from here and from
`src/config.py` — never re-derives, re-tunes, or reinterprets it ad hoc. That
is what keeps the strategy from *differentiating* run to run: one contract, one
version, one set of constants, enforced by a test.

Changing anything in this file is a deliberate, versioned act:
1. bump `STRATEGY_VERSION` in `src/config.py`,
2. update this document,
3. update `tests/test_strategy_contract.py` in the **same commit**.

If those three fall out of sync, the contract test fails. The strategy cannot
drift silently.

---

## Thesis (fixed)

Event-driven / merger-arbitrage analysis, because every position carries a
**stated payoff, a resolution date, and observable conditions** — so the call
can be *graded* after it resolves. Directional index-momentum calls are
retired: `ma5_v1` scored no edge (p = 0.44) and is kept only as a gradeable
baseline (`MOMENTUM_RULESET_STATUS = "retired_baseline"`). Focus is markets.

## The gradeable object (fixed)

The `deals` ledger. The rare **positive class is the deal BREAKING**
(`y = 1 ⇔ status == 'broken'`).

- **Pending deals are censored, never negatives.** Excluded from every
  evaluation set until they resolve — what makes each cycle point-in-time honest.
- **Point-in-time discipline everywhere.** A metric computed `as_of` date D may
  only use deals with `resolution_date <= D`. No lookahead, ever.
- **No fabrication.** Unpublished prints stay `n/d`; unresolved deals stay
  `pending`. `p_break` is set once, at announce, and never revised with hindsight.

## Evaluation framework (fixed)

Imbalanced binary classification, graded with **both** AUCs — never one alone:

- **ROC AUC** — Mann–Whitney rank statistic (averaged ties), cross-checked
  against `sklearn` on every call. Prevalence-invariant.
- **PR AUC** — always reported beside its baseline **π**.

## Operating point (fixed)

Cost-based, never 0.5. `t* = argmin FP·COST_FP + FN·COST_FN`.

| Constant | Value | Meaning |
|---|---|---|
| `POSITIVE_CLASS` | `broken` | y = 1 |
| `CENSOR_STATUS` | `pending` | excluded until resolved |
| `COST_FP` | 1.0 | spread forgone hedging a deal that closes |
| `COST_FN` | 15.0 | unhedged break → full drawdown (15:1 default) |
| `COST_RATIO_GRID` | 5, 10, 15, 20 | sensitivity sweep every cycle |
| `MIN_SAMPLE_N` | 20 | cohorts below this are flagged, never cited |

## What every loop cycle runs (fixed procedure)

1. Update `deals` statuses **only** from sourced, verified resolutions.
2. `python -m src.cli scorecard --group-by all` → append to the day's brief.
3. `python generate_workbook.py` → the Python formula gate must report **0 failures**.
4. `pytest -q` must be green — including `test_strategy_contract.py`.
5. Commit. Git history is the non-destructive change log.
