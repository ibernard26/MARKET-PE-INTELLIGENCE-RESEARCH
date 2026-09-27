# Claude Code → ChatGPT (audit layer): status report, 2026-09-27 ~14:00 UTC

**Repo:** `ibernard26/MARKET-PE-INTELLIGENCE-RESEARCH`
**main:** `11eeff3` (after Cursor PR #41)
**Open PR (Claude):** #40 `fix: gate free price stack on security identity and reconciliation`
- head `949d016`, CI green (`pe-tracker-tests`, `arb-intelligence-dbt`)
- mergeable against current main (no conflict), **not merged**

## 1. Pipeline position (AUTO_ADVANCE authorization)

| Phase | Status |
|---|---|
| 1 OpenFIGI integration | DONE: Cursor #37 merged; Claude #40 fixes the identity rule (open) |
| 2 Tiingo integration | DONE: Cursor #37 merged; Claude #40 adds the identity check (open) |
| 3 Live provider smoke | **FAILED GATE → dependent phases stopped** |
| 4–14 | NOT RUN (depend on phase 3) |

Why phase 3 failed, verified in Claude's cloud container:
- `TIINGO_API_TOKEN` is not present.
- `OPENFIGI_API_KEY` is not present.
- The network policy denies `api.tiingo.com`, `api.openfigi.com`, `query1.finance.yahoo.com` and `query2.finance.yahoo.com` (proxy 403 on CONNECT).

Only variable names were checked or reported. No credential values were seen or logged.

Cursor independently recorded the same blocker in #41 (`docs/FREE_THESIS_CREDENTIAL_BLOCKER.md`, `scripts/resume_free_thesis_stack.py`).

**Current readiness:** 129 SEC-manifest deals; 14 with ≥3 real price prints (Yahoo only). The existing gate needs ≥20.
- `HISTORICAL_PRICE_DATA_READY = NO`
- `SPREAD_STRESS_BACKTEST_STATUS = BLOCKED_INSUFFICIENT_PRICE_HISTORY`

## 2. What happened this cycle

1. Claude built an offline Tiingo + OpenFIGI + reconciliation stack.
2. Cursor opened and self-merged its own equivalent stack at the same time (#37 architecture, #38 .env.example, #39 smoke / bias audit / cohort freeze scripts).
3. Claude discarded its parallel implementation to avoid two stacks.
4. Claude reviewed Cursor's merged code against the locked contract and rebuilt PR #40 as a focused fix on top of it.

## 3. Contract defects found in merged Cursor code (fixed in #40)

Hard rule at stake: *"never guess security mappings."* The corpus is mostly 2014–2015 deals, so reused tickers are a real risk.

| # | File | Defect on main | Fix in #40 |
|---|---|---|---|
| D1 | `equity_prices/tiingo.py` | "Soft identity consistency check" compared nothing. Any Tiingo series for the ticker was attributed to the deal target. | `identity_problems()`: the Tiingo issuer name must agree with the SEC target name, AND the Tiingo listing interval `[startDate, endDate]` must cover the announcement date. Otherwise `IDENTITY_AMBIGUOUS`, and no price call is made. |
| D2 | `equity_prices/orchestrator.py` | After a provider identity failure it fell through to Yahoo on the **same** ticker. | It stops on `IDENTITY_AMBIGUOUS`; the deal is deferred. |
| D3 | `security_identity/openfigi.py` | The name filter only ran when there were ≥2 candidates. A single wrong-issuer candidate became `MATCHED`. | New status `NAME_MISMATCH` when the single hit's name disagrees with the SEC target. |
| D4 | `scripts/run_free_price_coverage.py` | Wrote **every** combined observation into the canonical `target_price_manifest.json`. That included OpenFIGI `AMBIGUOUS` deals and deals with material Tiingo/Yahoo conflicts, and all of them counted toward the ≥20 gate. Conflicted deals were classified `TIINGO_COVERED`. | `admit_prints()`: prints enter the manifest only when there's no OpenFIGI `AMBIGUOUS`/`NAME_MISMATCH`, no Tiingo `IDENTITY_AMBIGUOUS`, and `material_conflicts == 0`. New classes `SECURITY_IDENTITY_NAME_MISMATCH` and `DEFER_PRICE_CONFLICT`. `deals_not_admitted` is reported. |
| D5 | `scripts/audit_free_price_coverage.py` | The bias audit counted non-admitted deals as covered. | Respects `prints_admitted`. |
| D6 | `tests/test_tiingo_openfigi.py` | `test_no_future_leakage_in_tiingo_window` would pass with zero observations. Its `all(...)` over an empty list is vacuous. | The fixture now has a valid identity, and the test asserts `AVAILABLE` + non-empty. |

**Name rule** (`security_identity/name_match.names_agree`): lowercase, strip punctuation, drop legal-form/filler words (inc, corp, co, ltd, plc, holdings, group, class, common, …). Then one name's significant tokens must be a non-empty subset of the other's.
- It's deterministic, with no fuzzy scoring.
- It was fixed before any live provider data was seen.
- Examples: "American Airlines Group" vs "American Express Co" → FALSE. "Procter & Gamble Co" vs "PROCTER AND GAMBLE" → TRUE.

**Deliberate choice for audit:** OpenFIGI `NO_MATCH` is **admissible**, because it's common for delisted names and isn't negative evidence. Such deals still need the Tiingo name + listing-interval check to pass.

**Downstream effect:** `freeze_thesis_price_cohort.py` derives eligibility from the manifest (≥3 prints). Gating the manifest (D4) therefore also gates the cohort freeze and the ≥20 count. `resume_free_thesis_stack.py` (#41) calls `run_free_price_coverage`, so it inherits the gate.

**Tests:** 341 passed, 7 skipped; 20 new offline cases in `tests/test_price_identity_gate.py`.

## 4. Unchanged / invariants

| Flag | Value |
|---|---|
| STRATEGY.md / src/config.py / test_strategy_contract.py changed | NO |
| src/model/** changed | NO |
| EVENT_RULES / fs_v1 / break_logit_v1 / first_walkforward_v1 changed | NO |
| Gate thresholds (≥20 deals, ≥3 prints, MIN_SAMPLE_N=20, MIN_CLASS_N=2) changed | NO |
| Cost ratio FN:FP = 15:1 changed | NO |
| price_reconcile_v1 tolerance (abs 1e-4 / rel 1e-6) changed | NO |
| Synthetic / interpolated / forward-filled prices | NO |
| Model fit / walk-forward / calibration / backtest executed | NO |
| CRSP work deleted | NO (kept; status FUTURE_INSTITUTIONAL_ROBUSTNESS_PROVIDER, not in active chain) |

## 5. Process findings (for audit)

- **Cursor self-merges within 1–3 minutes** (#31–#39, #41 were all merged by Cursor under the owner account). Pre-merge review is impossible. D1–D4 reached main unreviewed.
- **Recommendation:** Cursor opens PRs without merging, or branch protection on `main` requires 1 approval plus the `pe-tracker-tests` and `arb-intelligence-dbt` checks.
- **Still owed:** post-merge review of earlier self-merged Cursor PRs.
  - #31: "authorize gated spread_stress_v1 walk-forward/backtest"
  - #32: Yahoo target closes
  - #27–#29: deferred-resolution batches to N=129. Check against the rule "only deals whose filing text was actually read enter the manifest".
- **Tolerance question:** `price_reconcile_v1` is abs $0.0001 / rel 1e-6, which is very tight for cross-vendor closes. Tiingo raw close vs Yahoo split-adjusted `close` may produce many `DEFER_PRICE_CONFLICT`s.
  - Per the no-retroactive-change rule, any loosening must be decided **before** live data is seen, as a new rule version (`price_reconcile_v2`). It must never be tuned after the first run.
  - Recommend the audit layer decide this now.

## 6. Next actions

1. Owner: review/merge PR #40 **before** any live coverage run, so D1–D4 can't admit wrong-issuer prices.
2. Owner: make the credentials visible and allow the provider hosts, in the Claude cloud environment settings or wherever Cursor runs.
3. Then: `python -m scripts.resume_free_thesis_stack` (smoke → coverage → audit → freeze if ≥20).
   - If fewer than 20 deals pass identity + reconciliation, it stops at `BLOCKED_INSUFFICIENT_PRICE_HISTORY`. The gate is not lowered.
4. spread_stress_v1 execution (phase 11+) only via the existing gated harness, and only if every gate passes.
