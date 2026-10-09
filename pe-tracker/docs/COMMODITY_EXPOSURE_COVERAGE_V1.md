# Commodity-exposure coverage v1: descriptive report (research only)

**Status: v1 FAILED its preregistered success criteria (the agreement gate).**
This is a descriptive coverage experiment only. No model was fit, nothing was backtested or walk-forwarded, and nothing was written to the canonical SQLite store. The labels are not wired into `event_driven_v1` / `break_logit_v1` or into any feature. Preregistration: `docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v1.md`, committed before any labels were generated.

## Artifacts
| File | Contents |
|---|---|
| `data/research/commodity_exposure_labels_v1.csv` | Pass A (rule-based) labels: 129 deals × {target, acquirer} = 258 rows, with filing accession, filing date, Item locator, offset and quote for every `yes`/`no_disclosed` |
| `data/research/commodity_exposure_passB_v1.csv` | Pass B (blind second review) for the preregistered 20-deal sample (40 rows) |
| `data/research/commodity_exposure_coverage_v1.json` | Machine-readable coverage, agreement and success-criteria summary (`research_only: true`, `model_fit_executed: false`, `backtest_executed: false`, `canonical_store_written: false`) |
| `scripts/label_commodity_exposure_v1.py` | `fetch` / `label` / `packets` / `report` stages; the SEC cache goes to `data/cache/edgar_commodity_v1/` (gitignored, not committed) |
| `tests/test_commodity_exposure_labels_v1.py` | Structural validation (no silent zero, chronology, coverage, research-only flags) |

## Coverage (pass A, all 129 deals)
`not_yet_reviewed`: **0** rows. Every party is either `labeled` or `unknown`, with an explicit reason.

| Party | labeled | unknown | unknown share | unknown reasons |
|---|---|---|---|---|
| target | 84 | 45 | 34.9% | 44 no qualifying disclosure; 1 no pre-announcement annual report in window (DEAL-SABA-VECTOR-2015) |
| acquirer | 50 | 79 | 61.2% | 72 acquirer identity unresolved; 7 no qualifying disclosure |
| all party rows | 134 | 124 | 48.1% | |

Deals with at least one labeled party: 96 of 129. Deals with neither party labeled: 33.

**Flag counts** (from pass A; given the agreement failure below, treat these as upper-biased for `consumer`):

| Flag | target yes | acquirer yes |
|---|---|---|
| producer | 18 | 13 |
| consumer | 71 | 46 |
| shipping_dependent | 45 | 24 |
| hedged = yes | 26 | 20 |
| hedged = no_disclosed | 1 | 0 |

**By outcome** (party rows labeled / total): target break 12/20, target close 72/109; acquirer break 10/20, acquirer close 40/109. Deals with any labeled party: break 16/20, close 80/109. This is descriptive only. No association was tested and none should be inferred (n=20 breaks).

**By announcement year** (target labeled/total; acquirer labeled/total): 2014 26/39, 13/39 · 2015 22/33, 13/33 · 2016 5/7, 2/7 · 2017 1/1, 1/1 · 2018 1/3, 2/3 · 2019 1/1, 0/1 · 2020 5/7, 4/7 · 2021 8/12, 4/12 · 2022 8/14, 3/14 · 2023 3/5, 5/5 · 2024 2/3, 2/3 · 2025 0/2, 0/2 · 2026 2/2, 1/2. The sample is concentrated in 2014–2015 (72 of 129).

**By sector:** not reported. The manifest carries no sector field, and v1 deliberately did not derive one (SIC codes were not part of the preregistration). Sector is listed as an open item for v2.

## Second review (pass B) and agreement
Pass B independently re-labeled the 20 preregistered deals (seed 20261009) from filing-text packets, without opening the pass-A rows. Pass-A rows were read only after all 40 pass-B rows had been written.

| Metric | Value | Preregistered threshold |
|---|---|---|
| Primary: deals with exact match on all 4 flags for both parties | **7 / 20 = 35%** | ≥ 90%: **FAIL** |
| Secondary: per-party exact match | 23 / 40 = 57.5% | (reported) |
| producer | agreement 92.5%, κ 0.72 | |
| consumer | agreement 67.5%, κ 0.40 | |
| shipping_dependent | agreement 87.5%, κ 0.66 | |
| hedged | agreement 92.5%, κ 0.80 | |

### Disagreements (24 flag-level, across 13 deals)
| Deal | Party | Flag | A | B | Diagnosis (after unblinding) |
|---|---|---|---|---|---|
| ATHLON-ENCANA-2014 | target | consumer | yes | unknown | A false positive: "lower the cost of operating our oil and natural gas properties" (producer revenue context) |
| ATHLON-ENCANA-2014 | target | hedged | yes | unknown | A weak evidence: quote is a generic oil/gas price-volatility sentence, not a hedge statement. B may have missed a hedge sentence due to packet truncation. |
| ATHLON-ENCANA-2014 | acquirer | consumer | yes | unknown | A false positive: price exposure as a seller counted as an input cost |
| CHNG-UNH-2021 | target | consumer | yes | unknown | A false positive: "market power" |
| CHNG-UNH-2021 | acquirer | consumer | yes | unknown | A false positive: "time and energy" |
| CXO-COP-2020 | target | consumer | yes | unknown | A false positive: producer-side commodity-price sentence |
| CXO-COP-2020 | target | shipping_dependent | yes | unknown | Arguable: oil gathering/transportation costs. B was conservative here. |
| CXO-COP-2020 | acquirer | consumer | yes | unknown | A false positive: producer-side |
| GNW-OCEANWIDE-2016 | target | consumer | yes | unknown | A false positive: insurer's energy-bond portfolio |
| HILLSH-TYSON-2014 | target | producer | unknown | yes | A false negative: pass A matched no producer sentence for a meat processor |
| HILLSH-TYSON-2014 | target | shipping_dependent | unknown | yes | A false negative |
| IRBT-AMZN-2022 | acquirer | consumer | yes | unknown | A false positive: list-of-factors sentence |
| MDLA-TB-2021 | target | consumer | yes | unknown | A false positive: "market power" |
| MNTV-ZEN-2021 | target | consumer | yes | unknown | A false positive: "market power" |
| PROCER-FRANCI-2015 | target | shipping_dependent | yes | unknown | Arguable: freight costs in COGS (an accounting policy, not a dependency statement) |
| QUALIT-FUNDS-2015 | target | producer | yes | unknown | A false positive: a crude-oil *transport* service, not a producer |
| QUALIT-FUNDS-2015 | target | consumer, shipping_dependent | yes | unknown | A weak evidence: generic list-of-factors sentence |
| STRATE-BLACKS-2015 | target | consumer | yes | unknown | Arguable: "increases in energy costs" in a hotel REIT's risk list. B missed it (truncation). |
| STRATE-BLACKS-2015 | acquirer | consumer | yes | unknown | A false positive: macro-factor sentence for an asset manager |
| STRATE-BLACKS-2015 | acquirer | hedged | yes | unknown | A false positive: FSOC asset-management text |
| TECUMS-MUELLE-2015 | target | producer | yes | unknown | A false positive: a steel *consumer* triggered the producer rule |
| VITACO-KROGER-2014 | acquirer | shipping_dependent | unknown | yes | A false negative, or B lenient: weather could interrupt deliveries to stores |
| VITACO-KROGER-2014 | acquirer | hedged | yes | unknown | **A correct**: Kroger 7A cites commodity-price derivatives. B missed it (packet truncation). |

Summary: most disagreements are pass-A **false positives on `consumer`**, caused by overly broad tokens: "energy" in "time and energy", "power" in "market power", producer-side price sentences, and generic list-of-factors sentences. A smaller set comes from pass-B misses due to packet truncation, and pass-A producer-rule misses. The v1 regex rules are therefore **not reliable enough** for research use. Under the preregistration, the v1 labels must not be tuned post hoc to pass the gate.

## Preregistered success criteria
| Criterion | Result |
|---|---|
| 100% of party rows labeled or explicit unknown (`not_yet_reviewed` counts as failure) | **PASS** (258/258; 0 `not_yet_reviewed`) |
| Every cited filing date < announcement date | **PASS** (checked by the report stage and the new test) |
| Primary agreement ≥ 90% | **FAIL** (35%) |
| **Overall** | **FAIL** |

## Limitations
- **Reviewer independence.** Pass B was done by the same AI assistant (BMO) that wrote the pass-A rules. It was blind to pass-A outputs, but it is not an independent human reviewer, and the reviewer's knowledge of the rule design may correlate errors.
- **Packet truncation.** Pass B saw filtered packets (a business-section opening plus up to 25 keyword-matched sentences per document), not full filings. At least one pass-B miss (the Kroger hedge) is attributable to this.
- **Acquirer identity is name-based.** It relies on an exact normalized-name match against SEC `cik-lookup-data.txt`, which leaves 72/129 acquirers unresolved (private, foreign, consortium or ambiguous names). Sponsor acquirers resolve to the listed sponsor parent (e.g., Blackstone, Apollo), whose filings describe an asset manager rather than the acquiring fund.
- **Evidence scope.** v1 uses 10-K-family annual reports in [announce−550d, announce) plus the latest subsequent pre-announcement 10-Q. 8-Ks were excluded by the preregistration. One target (DEAL-SABA-VECTOR-2015) has no in-window annual report.
- **SEC User-Agent.** Fetches used a placeholder contact email in the SEC User-Agent (`research-contact@example.com`). Set a real contact address before any re-run.
- **No sector field.** No sector field is available, so no sector breakdown is reported.
- **Prices.** FRED/price data were not used. The FRED floor remains 2026-04-20 by decision.

## Recommended next step
Preregister **v2** before touching the rules:
1. Tighten pass-A rules: drop bare "energy"/"power" tokens; require input-cost phrasing for `consumer` and output/sales phrasing for `producer`; exclude list-of-factors sentences; restrict `hedged` to commodity-derivative statements.
2. Draw a **fresh** agreement sample (new seed), keeping the v1 sample as a development set only.
3. Give the second reviewer full Item 1/1A/7A text instead of truncated packets, and ideally use a human reviewer.
4. Add SIC-based sector from SEC submissions.
5. Improve acquirer resolution via the manifest/merger-agreement parties rather than name matching.

Do not use the v1 labels in any model.
