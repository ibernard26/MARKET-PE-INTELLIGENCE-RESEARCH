# Copy-paste research prompt — spread-stress challenger + authorized PIT backtest

Paste everything inside the code block into the research agent. This is the
**updated** contract: the workflow no longer stops at model architecture.
A controlled real-data walk-forward and historical backtest are authorized
**only after** point-in-time, leakage, provenance, sample-size, and
historical-price readiness gates pass.

This document replaces any prior draft that ended at “No real fitting yet.”

---

```
ROLE
You are a senior quantitative research engineer implementing a spread-stress
challenger on top of the locked merger-arb break model in
ibernard26/MARKET-PE-INTELLIGENCE-RESEARCH (pe-tracker/).

LOCKED BASELINE (DO NOT MUTATE)
- STRATEGY_VERSION = event_driven_v1
- FEATURE_SCHEMA_VERSION = fs_v1
- MODEL_VERSION = break_logit_v1
- experiment freeze first_walkforward_v1 (cohort/protocol/plan) — do not rewrite

INVARIANTS (must remain NO)
FS_V1_CHANGED = NO
BREAK_LOGIT_V1_CHANGED = NO
FIRST_WALKFORWARD_V1_CHANGED = NO

============================================================
1. RESEARCH IDEA
============================================================

Beyond announcement-time features, stress in the live deal spread may carry
incremental break risk. For unresolved deal i at information time t, define
the contemporaneous percent spread from point-in-time offer and target price:

  S_{i,t} = (O_{i,t} - P_{i,t}) / P_{i,t}

Then:

  ΔS_{i,t} = S_{i,t} - S_{i,t-1}

and a rolling volatility of those changes:

  σ_{ΔS,i,t} = StdDev(ΔS_{i,u} for u in the last w admissible prints ≤ t)

All prints must satisfy valid_time ≤ t AND known_at ≤ t. Never fabricate
missing prices. Never forward-fill beyond the repository’s explicit print
staleness window.

============================================================
2. CHALLENGER MODEL
============================================================

Introduce a separately versioned challenger:

  model_id      = spread_stress
  model_version = spread_stress_v1
  feature schema = fs_spread_stress_v1  (NOT fs_v1)

p^{stress}_{i,t} = P(break | ΔS, σ_ΔS, and any other fs_spread_stress_v1 fields
                     knowable at t)

Do not edit break_logit_v1 or fs_v1 to absorb these features.

============================================================
3. BASELINE
============================================================

Keep break_logit_v1 as:

  p^{base}_{i,t}

(announcement-time / fs_v1 contract). Use the model registry and immutable
predictions. Prefer model_run_id for research-grade attachment to trades.

============================================================
4. COMBINED MODEL (OPTIONAL, SEPARATELY VERSIONED)
============================================================

Only if sample size and price history support it, create a NEW specification:

  break_logit_v2 / fs_v2

producing p^{combined}_{i,t}.

Do NOT modify break_logit_v1 to create the combined model.

============================================================
5. DIAGNOSTIC
============================================================

Preserve:

  D^{model}_{i,t} = p^{stress}_{i,t} - p^{base}_{i,t}

as a research diagnostic, not by itself a trading rule.

============================================================
6. POINT-IN-TIME / BITEMPORAL
============================================================

Enforce the repository’s bitemporal readers. Features and labels at prediction
time t admit only facts with valid_time ≤ t and known_at ≤ t.

============================================================
7. PROVENANCE
============================================================

Every target-price print used in ΔS / σ_ΔS must carry source, source_identifier,
valid time, and known_at. Quarantine unsourced prints; never invent them.

============================================================
8. SAMPLE-SIZE GATES
============================================================

Respect MIN_SAMPLE_N / MIN_CLASS_N. Thin windows: report insufficient_data;
do not cite operating points.

============================================================
9. NO LOOKAHEAD
============================================================

Future prices, future breaks, future amendments, and post-break exits must not
influence earlier features, fits, thresholds, or trade decisions.

============================================================
10. MODEL REGISTRY
============================================================

Register every real fit under model_run_id. Predictions are append-only and
must satisfy training_cutoff ≤ prediction_time ≤ trade_time.

============================================================
11. DECISION LAYER SEPARATION
============================================================

Probability models do not trade. EV and portfolio rules live separately
(see §17).

============================================================
12. DATA-READINESS BEFORE ANY CLAIM
============================================================

Before claiming a spread-stress backtest, audit longitudinal target-price
history. If insufficient, do not fabricate and do not pretend (§13).

⸻

13. AUTHORIZE CONTROLLED REAL-DATA WALK-FORWARD + BACKTEST

This task is authorized to execute a controlled real-data walk-forward and
historical backtest, provided all point-in-time, leakage, provenance,
sample-size, and data-readiness checks pass first.

Do not execute the backtest merely because code exists.

Execution sequence must be:

  data audit
    → PIT validation
    → feature construction
    → chronological fitting
    → out-of-time prediction
    → trading decision
    → historical P&L

If the longitudinal target-price history required for ΔS_{i,t} and
σ_{ΔS,i,t} is not sufficiently available, do not fabricate it and do not
pretend the spread-stress strategy was backtested.

In that case:

1. backtest only the components supported by valid historical data;
2. report SPREAD_STRESS_BACKTEST_STATUS = BLOCKED_INSUFFICIENT_PRICE_HISTORY;
3. identify exactly what historical price data is missing;
4. implement the ingestion architecture required to unblock the test.

⸻

14. Backtest objective

The backtest must determine whether the proposed strategy produces incremental
out-of-time economic value, not merely whether its regression coefficients
look plausible.

Test:

  H_0: spread-stress information does not improve the strategy

against the research alternative:

  H_1: spread-stress information improves out-of-time prediction and/or
       economic performance

Do not describe rejection or non-rejection of H_0 unless an appropriate
statistical test is actually performed.

The practical comparison must include:

  Baseline  vs  Spread Stress  vs  Combined

Specifically:

A — Existing baseline
    break_logit_v1 → p^{base}_{i,t}

B — Challenger
    spread_stress_v1 → p^{stress}_{i,t}

C — Combined model
    Only if enough data exists and a separately versioned specification is
    created: break_logit_v2 / fs_v2 → p^{combined}_{i,t}

Do not modify break_logit_v1 to create C.

⸻

15. Absolutely no in-sample trading backtest

A model may never trade observations on which that fitted artifact was trained.

For each historical test period:

  Past data → fit
  followed by
  future untouched data → predict → trade

Use expanding or otherwise explicitly justified chronological walk-forward
windows. Test observations and test outcomes must not influence:

* model coefficients;
* standardization;
* imputation;
* feature selection;
* rolling-volatility window selection;
* calibration;
* decision thresholds;
* transaction-cost assumptions;
* model combination weights.

Freeze all such choices using pre-test information.

⸻

16. Generate genuinely historical predictions

Every trade must use p_{i,t} generated using the model artifact that would
actually have existed at t.

Enforce:

  training_cutoff ≤ prediction_time ≤ trade_time

A probability calculated later and retroactively attached to an earlier trade
is invalid. Continue using the repository’s model registry and immutable
prediction infrastructure.

⸻

17. Strategy decision layer

Keep prediction and portfolio decision-making separate.

For an all-cash deal, define the contemporaneous upside:

  U_{i,t} = O_{i,t} - P_{i,t}

and estimated downside D_{i,t} > 0. Then:

  EV_{i,t} = (1 - p_{i,t}) U_{i,t} - p_{i,t} D_{i,t}

A probability model alone does not constitute a trading strategy.

The strategy must define: when to enter; when not to enter; position sizing;
exit on successful close; exit on break; treatment of withdrawals; treatment
of unresolved exits; transaction costs; slippage; capital constraints;
concurrent-deal limits; exposure limits.

No rule may be chosen using final test-period results.

⸻

18. Spread-stress challenger decision logic

Preserve D^{model}_{i,t} = p^{stress}_{i,t} - p^{base}_{i,t} as a research
diagnostic.

Also test whether the spread-stress layer improves decisions such as enter /
reduce / avoid / exit relative to the baseline strategy.

Do not invent arbitrary thresholds after looking at test results. Thresholds
must either be economically specified beforehand, or learned exclusively from
prior training/validation periods and frozen before each test period.

⸻

19. Historical P&L integrity

Continue the repository’s existing break-exit hierarchy.

For broken deals:
1. use an actual sourced post-break exit price when available;
2. otherwise use a clearly labeled modeled fallback only when the existing
   backtest configuration permits it;
3. otherwise mark the trade unresolved_exit.

Never call modeled break P&L realized P&L.

Successful deal-close proceeds must likewise use the contemporaneous deal
terms applicable to the strategy. No future amendment may be retroactively
applied to an earlier trade decision.

⸻

20. Transaction costs and implementation realism

Report both Gross P&L and Net P&L.

Net results should incorporate explicit assumptions for commissions (if
applicable), bid/ask spread, slippage, financing/borrow costs where relevant,
short-leg costs for stock consideration if eventually supported, and capital
tied up through the deal duration.

All assumptions must be documented and sensitivity-tested. Do not optimize
transaction-cost assumptions to improve the strategy.

⸻

21. Backtest benchmarks

At minimum compare against:

1. Eligible-deal baseline (enter every investable deal without model
   discrimination)
2. Existing break_logit_v1 strategy
3. Spread-only / spread-dynamics challenger (spread_stress_v1)
4. Combined model (only if legitimately supported)

All strategies must trade the same eligible universe wherever comparison is
intended. If universes differ because of missing features, report both
common-universe and full available-universe results. Do not compare two
strategies on materially different samples without disclosing it.

⸻

22. Economic backtest metrics

Report at minimum: number of eligible deals; number of trades; number of
closes traded; number of breaks traded; gross P&L; net P&L; average P&L per
trade; median P&L per trade; win rate; loss rate; average winner; average
loser; profit factor; maximum drawdown; realized volatility; Sharpe ratio
where mathematically appropriate; Sortino ratio where appropriate; downside
deviation; capital utilization; average holding period; return on committed
capital; worst deal loss; best deal gain.

Also show results by calendar period and, where sample size permits: sector;
deal type; sponsor vs strategic; cash vs other consideration; regulatory-risk
category. Never overinterpret tiny subsamples.

⸻

23. Statistical model metrics remain separate

Report ROC AUC, AP versus π, Brier, LogLoss, and calibration diagnostics
separately from trading performance.

Explicitly separate predictive quality from economic utility.

⸻

24. Determine incremental value

Quantify:

  ΔBrier = Brier_challenger - Brier_baseline
  ΔAP    = AP_challenger - AP_baseline
  ΔP&L   = P&L_challenger - P&L_baseline

(and similarly for the combined model).

Most importantly determine whether ΔS and σ_ΔS provide information that the
baseline model does not already capture. Do not interpret a higher backtest
return alone as proof of incremental alpha.

⸻

25. Sensitivity and robustness

Run pre-specified robustness checks where sample size permits (e.g. w=5, 10,
20 for volatility windows) as a small prespecified sensitivity grid, not an
unrestricted hyperparameter search. Also test reasonable transaction-cost
assumptions and threshold perturbations. If changing one small assumption
destroys performance, state that explicitly.

⸻

26. Prevent repeated-deal pseudo-sample inflation

Multiple daily observations from one deal are repeated measurements of the
same economic transaction. Validation, uncertainty estimation, and any
resampling must respect deal_id. Prefer deal-level/block resampling.

⸻

27. Backtest tests that must exist

Add regression tests proving that:

1. a future price cannot change an earlier trade;
2. a future break event cannot change an earlier prediction;
3. a model trained after a trade date cannot supply that trade’s probability;
4. thresholds are frozen before the test period;
5. changing future labels cannot alter prior model/threshold decisions;
6. transaction costs are applied exactly once;
7. post-break prices cannot influence pre-break decisions;
8. modeled break exits are never reported as realized exits;
9. unresolved exits do not silently receive fabricated P&L;
10. baseline and challenger comparisons use a disclosed common universe;
11. repeated observations retain deal_id grouping;
12. the new backtest does not mutate first_walkforward_v1;
13. serialized break_logit_v1 remains reproducible;
14. all generated predictions satisfy
    training_cutoff ≤ prediction_time ≤ trade_time.

⸻

28. Final research verdict

Do not simply say STRATEGY WORKS or STRATEGY DOES NOT WORK.

Produce an evidence-based research conclusion such as:

BACKTEST_EXECUTED = YES/NO
POINT_IN_TIME_VALIDATION = PASS/FAIL
COMMON_TEST_UNIVERSE_N = ...
BASELINE_NET_PNL = ...
STRESS_NET_PNL = ...
COMBINED_NET_PNL = ...
BASELINE_BRIER = ...
STRESS_BRIER = ...
COMBINED_BRIER = ...
BASELINE_SHARPE = ...
STRESS_SHARPE = ...
COMBINED_SHARPE = ...
MAX_DRAWDOWN_BASELINE = ...
MAX_DRAWDOWN_STRESS = ...
MAX_DRAWDOWN_COMBINED = ...
INCREMENTAL_OUT_OF_TIME_IMPROVEMENT = YES / NO / INCONCLUSIVE

Then explain why. If the sample is too small, the correct conclusion is
INCONCLUSIVE rather than forcing an alpha claim.

⸻

29. Updated final contract flags

Final reporting must include:

MAIN_SHA_START =
MAIN_SHA_END =
BRANCH =
FS_V1_CHANGED =
BREAK_LOGIT_V1_CHANGED =
FIRST_WALKFORWARD_V1_CHANGED =
SPREAD_STRESS_V1_IMPLEMENTED =
HISTORICAL_PRICE_DATA_READY =
REAL_MODEL_FIT_EXECUTED =
WALK_FORWARD_EXECUTED =
BACKTEST_EXECUTED =
CALIBRATION_EXECUTED =
BASELINE_BACKTEST_COMPLETE =
SPREAD_STRESS_BACKTEST_COMPLETE =
COMBINED_BACKTEST_COMPLETE =
DATA_LEAKAGE_TESTS =
PYTEST =
INCREMENTAL_OUT_OF_TIME_IMPROVEMENT =

Expected invariants:

FS_V1_CHANGED = NO
BREAK_LOGIT_V1_CHANGED = NO
FIRST_WALKFORWARD_V1_CHANGED = NO

Unlike the prior specification, a real-data model fit and walk-forward/backtest
are now authorized, but only after the point-in-time and historical-price
readiness gates pass.

The purpose is not to engineer a profitable-looking historical chart. The
purpose is to determine whether the strategy survives a realistic simulation
of what could actually have been known and traded at each historical point
in time.

Hierarchy:

  Theory → PIT Data → Model → Walk-Forward Predictions → Trading Rules
        → Backtest → Evidence

Only that last step tells whether Δ-spread/volatility adds something
economically useful.
```
