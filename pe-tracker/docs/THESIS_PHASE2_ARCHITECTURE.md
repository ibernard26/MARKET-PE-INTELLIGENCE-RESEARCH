# Thesis phase 2 — architecture memo (after PR #44)

- **Base:** `main` @ `1f21aa32ba1304f8011ef56c4e77162aa36ec528`.
- **PR #44:** reviewed at head `a792d01`, where it is **still a draft and
  unmerged**. Its artifacts were read from that branch and are not included
  here.
- **Scope:** design only. No model fit, walk-forward, backtest or calibration.
  No live price run.

## 1. Independently verified state (from #44 artifacts, not the PR text)

| Item | Value |
|---|---|
| Canonical corpus | 129 deals: 109 closed, 19 terminated, 1 withdrawn |
| Consideration | 108 cash / 11 mixed / 10 stock |
| `CANONICALLY_ADMITTED` | 21 deals (16 cash, 4 stock, 1 mixed); 3,293 Tiingo raw closes |
| `DEFERRED_IDENTITY` | 56 deals: OpenFIGI `AMBIGUOUS` 46, OpenFIGI `NAME_MISMATCH` 7, Tiingo `IDENTITY_AMBIGUOUS` 3 |
| `NO_PRICE_HISTORY` | 52 deals |
| Timestamps | 129/129 announcements DATE_ONLY; 128/129 resolutions DATE_ONLY |
| v1 panel | `FEATURE_TIME_RESOLUTION_TIMESTAMP_COLLISION` (20/21 deals) |

## 2. Reusable unchanged

- **Price stack:**
  - Tiingo/Yahoo adapters, session calendar gate, normalized manifest schema.
  - `price_reconcile_v2`, including the $0.01 / 1 bp thresholds.
- **Identity rule v1:**
  - Tiingo name + listing-window proof (B).
  - `names_agree`.
  - Reviewed-SEC-mapping basis (C) in `identity.py`.
- **Admission and cohort code:**
  - Canonical admission (`run_free_price_coverage.canonical_status`).
  - `ModelCohort` / fingerprint utilities.
- **Strategy constants:** `STRATEGY.md`, including `MIN_SAMPLE_N` / `MIN_CLASS_N` and cost t*.

## 3. Requires a new version (created in this PR)

| Area | Status | Where |
|---|---|---|
| **spread_stress_v2 / fs_spread_stress_v2** | **Frozen** | `docs/SPREAD_STRESS_V2_SPEC.md`, `data/spread_stress_v2_pit_policy.json`, `src/model/spread_stress_v2/` |
| **identity_admission_v2** | **Proposed, not active** | `src/ingest/security_identity/admission_v2.py` |
| **Proof C evidence tooling** | New module and script | `proof_c.py`, `scripts/identity_resolution_round_v2.py` |

Nothing in `spread_stress_v1`, `fs_v1`, `break_logit_v1`, `first_walkforward_v1`,
`EVENT_RULES` or `price_reconcile_v2` is modified.

## 4. Assumptions frozen before any v2 result

These were frozen before any v2 panel was scored or fit (see the spec for full
definitions):

- **Feature times:**
  - Session grid anchored at S0.
  - First session strictly after a DATE_ONLY announcement.
  - Snapshots at +10, +20, … up to 12.
- **Resolution:** DATE_ONLY resolution dates exclude same-day and later
  snapshots. They never select one.
- **Features and eligibility:**
  - v1's four feature concepts.
  - Raw closes, no fill, complete-case.
  - Cash-only eligibility, because the manifest has no exchange ratio or
    acquirer price.
- **Evaluation:**
  - Deal-equal weights, deal-grouped annual walk-forward.
  - Deal-level gates `MIN_SAMPLE_N = 20` / `MIN_CLASS_N = 2`.
  - A pre-specified L2 logistic regression with C = 1.0.
  - An explicit execution authorization record, in addition to the gates.

## 5. v2 cohort result (gates only; nothing fit)

`data/spread_stress_v2_cohort.json` was built from the #44 artifacts at
`a792d01`, with input sha256s recorded. It must be regenerated and its
fingerprint compared after #44 merges.

| Metric | Value |
|---|---|
| Admitted deals | 21 |
| Excluded as `UNSUPPORTED_CONSIDERATION` (stock/mixed) | 5 |
| Cash deals with ≥1 eligible snapshot | 16 |
| Eligible snapshots | 136 |
| Labels | 16 closed / **0 break-like** |
| `MIN_SAMPLE_N` (16 < 20) | **fail** |
| `MIN_CLASS_N` (0 < 2) | **fail** |
| Status | **STOP** |

The only admitted break-like deal (MNTV-ZEN) is an all-stock deal. Its spread
is undefined without the acquirer's price, so the cash rule removes it.

That rule follows from which fields exist, not from the outcome. The outcome mix
was known when the rule was written, and the spec discloses this (§8).

## 6. Sample limitations preventing inference

- Even before the cash rule there is 1 break among 21 admitted deals. No
  discrimination metric, calibration or threshold can be estimated.
- Survivorship in free price data is severe: break-like coverage is 1/20 (5%)
  versus 20/109 closed (18%). Coverage in 2014–2015 is 1/72.
- Any future positive result on a class-balanced cohort must be read against
  this availability bias. The bias audit is to be regenerated after expansion.
  No rebalancing.

## 7. Remaining PIT risks

- All announcement and resolution times are **date-only**. v2 uses
  S0 = next session and excludes resolution-day closes. That is conservative
  but gives up one session of information at each end.
- **Offer revisions** are not in the manifest. `pct_spread` uses the announced
  cash terms throughout, so bumped deals carry a mis-measured spread. This is
  recorded as a limitation; there is no fix without reviewed revision events.
- **Tiingo `known_at`** equals the session close. That is fine for EOD research,
  but there is no vendor-restatement history.

## 8. Phase C finding 1: false OpenFIGI ambiguity (resolver defect)

- **The defect:** the v1 resolver (`openfigi.py`, the `uniq_figi` set) counts
  distinct **venue-level** `figi` values. It also queries without `exchCode`.
  OpenFIGI returns one FIGI per US venue (plus the composite), so an ordinary
  single-listed stock reads as `AMBIGUOUS`.
- **The evidence:**
  - 46/56 deferred deals are `OPENFIGI_AMBIGUOUS`.
  - 29 of those 46 passed Tiingo's name and listing-window proof.
  - Deals like CRNX (Crinetics, a single Nasdaq listing) are among them.
- **Proposed fix (`identity_admission_v2`):**
  - Count distinct `compositeFIGI` among name-agreeing equity rows.
  - It can be recomputed from the cached raw OpenFIGI responses without new API
    calls (`--openfigi-v2-from-cache`).
- **Why it's label-blind/outcome-type-blind:** it's a symbology fix applied
  uniformly. Resolution dates stay available for the filing window. Resolution
  type and outcome labels are not read. It is not outcome-blind.
- **Why it isn't active:** it changes an identity rule after #44's coverage was
  observed, so it needs audit approval first (`RULE_STATUS =
  PROPOSED_PENDING_AUDIT`).

## 9. Phase C finding 2: under v1 rules, Proof C cannot admit any deferred deal

`canonical_status` applies vetoes **before** proofs. Every one of the 56
deferred deals carries a veto, so a new Proof C alone admits nothing.

`identity_admission_v2` (proposed) lets Proof C (contemporaneous, target-filed
SEC evidence) **together with** Proof B (Tiingo issuer name + listing window)
override an OpenFIGI veto for the historical window. The rationale: OpenFIGI
reflects today's symbology, and the SEC filing plus the matching price-source
issuer describe the deal window itself.

The override has limits:

- Tiingo `IDENTITY_AMBIGUOUS` is never overridden, because that series belongs
  to another issuer.
- Yahoo-only series cannot use the override.

## 10. Phase C status in this PR

- **Review queue:**
  - 56 `DEFERRED_IDENTITY` deals, ordered by **deal_id ascending**.
  - The queue exposes deal_id, target, CIK, ticker, announcement date and
    resolution date. It is label-blind/outcome-type-blind: resolution type and
    outcome labels are never loaded. Resolution date remains available. A test
    enforces this.
- **Plan (run here):**
  - Built from `data.sec.gov` submission metadata, which is reachable from the
    Claude environment.
  - 56/56 deals have candidate target-filed filings in the window. 54 include
    a merger document (DEFM14A / PREM14A / 14D-9 / 13E-3).
- **Filing text:** `www.sec.gov` is blocked in the Claude environment, so no
  document was read. `DEFERRED_IDENTITIES_REVIEWED = 0`: no statuses are
  assigned and nothing is forced.

## 11. What Cursor should run (after this PR is reviewed)

1. **Fetch and classify:**
   `python -m scripts.identity_resolution_round_v2 --fetch`.
   - This needs `www.sec.gov` and a real `SEC_USER_AGENT` contact string.
   - It writes RESOLVED_PROOF_C / STILL_AMBIGUOUS / NO_SUFFICIENT_EVIDENCE for
     each deal, with accession, form, date, document sha256 and snippet.
   - Commit the result, and spot-check every RESOLVED row by hand.
2. **Recompute OpenFIGI v2 status:**
   `python -m scripts.identity_resolution_round_v2 --openfigi-v2-from-cache`,
   using the cached raw responses. Commit the result.
3. **Stop and ask for an audit decision on `identity_admission_v2`.** Only an
   approved, separately reviewed commit may:
   - add RESOLVED rows to `data/target_ticker_map.json` (with `sec_accession` /
     `sec_filed_date`);
   - switch admission to v2;
   - re-run coverage with `price_reconcile_v2` unchanged.
4. **Re-run the gates:**
   - Rebuild `spread_stress_v2_cohort.json`.
   - If either class is below `MIN_CLASS_N = 2`: **STOP** and report.
   - Regenerate the bias audit.

No model execution is authorized by this PR.
