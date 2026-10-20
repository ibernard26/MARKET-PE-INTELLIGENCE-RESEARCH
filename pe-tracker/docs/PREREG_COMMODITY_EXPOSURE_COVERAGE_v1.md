# Preregistration: commodity-exposure coverage v1 (research only)

Registered: 2026-10-09 (America/New_York), before any labeling output was produced.
Status: **research artifact only.** Nothing here writes to the canonical SQLite store or
feeds `break_logit_v1`, `spread_stress_v2`, `RESEARCH_FEATURES`, the portfolio engine or
`STRATEGY.md`. No model fit, backtest, walk-forward or sweep is part of this protocol.
Origin: prioritized next experiment in
[`memos/JPM_Research_Intake_2026-10-09.md`](../../memos/JPM_Research_Intake_2026-10-09.md)
(section 3, "exposure first, stress magnitude second").

## Question

For the eligible labeled deals, how many targets and acquirers have **disclosed**
commodity exposure (producer, consumer, shipping-dependent) and commodity hedging in SEC
filings available **before** the announcement, and how many must stay unknown?

This measures evidence coverage. It does **not** estimate any effect on break probability.

## Population

The 129 `break_logit_v1`-eligible deals: every `deal_id` in the reviewed
`data/sec_deal_manifest.json` at commit `724da08`. A local rebuild of the store at that
commit (`python -m src.model.data_quality`, 2026-10-09) reported 129 eligible rows
(20 break, 109 close). This is a local rebuild, not the canonical store.

Parties: the **target** and the **acquirer** of each deal, labeled separately.

## Party identity

- **Target:** `target_cik` from the reviewed manifest.
- **Acquirer:** the manifest has no acquirer CIK. Normalize the acquirer name (lowercase;
  strip punctuation; drop trailing legal suffixes inc, incorporated, corp, corporation, co,
  company, ltd, limited, plc, sa, s a, ag, aktiengesellschaft, nv, se, llc, lp, l p, the) and
  match it exactly against SEC's `cik-lookup-data.txt` entity names, normalized the same way.
  Accept a CIK only if **exactly one** matching CIK has an eligible annual report (see
  below). Otherwise the acquirer is `unknown` with reason `acquirer_identity_unresolved`
  (no match, ambiguous, or no eligible filing). Field `identity_basis` records
  `reviewed_manifest_cik` or `exact_normalized_name_match`. Name matching uses current
  EDGAR identity metadata only. It is never used as exposure evidence.

## Allowed evidence

Only SEC EDGAR filings by the party's CIK with **filing date strictly before the
announcement date**. The manifest's `announcement_timestamp` is day-precision, so strict
`<` avoids same-day ordering ambiguity; this is within the "filing date <= announcement
date" constraint.

1. **Annual report:** the latest 10-K, 10-K405, 10-KT, 10-KSB, 20-F or 40-F with filing
   date in [announce − 550 days, announce). Primary document only; exhibits excluded.
2. **Latest 10-Q** filed after that annual report and before the announcement, if any.
   Primary document only.
3. 8-Ks are **excluded in v1.** They are event-driven, rarely describe structural
   exposure, and near the announcement they may contain deal information.

No post-announcement filing, news, today's knowledge, SIC code, sector map or the deal's
outcome may be used. The labeler never reads resolution fields.

Every positive or explicit-negative label records: accession number, form, filing date,
the nearest preceding `Item` heading, the character offset, and a verbatim quote of the
matching sentence (at most 400 characters). HTML documents have no stable page numbers,
so the Item heading plus offset is the locator.

## Labels (per party)

Flags are independent. A party can have several.

| Field | Values | Positive only when a sentence in an allowed filing states, in first person (we/our/us/the Company)… |
|---|---|---|
| `producer` | `yes` / `unknown` | …that the party produces, extracts, mines, drills for, refines or sells a physical commodity (crude oil, natural gas, NGLs, coal, metals, ores, steel, aluminum, chemicals feedstock, ethanol, timber, grain, livestock or meat protein), or reports proved reserves. |
| `consumer` | `yes` / `unknown` | …that prices or costs of raw materials, commodities, fuel or energy inputs affect or may affect its costs or results. |
| `shipping_dependent` | `yes` / `unknown` | …that freight, shipping or transportation costs, carriers, or disruption of them affect or may affect its costs or operations. |
| `hedged` | `yes` / `no_disclosed` / `unknown` | `yes`: it uses derivatives, swaps, futures, forwards or collars for commodity, fuel, energy or metal price risk. `no_disclosed`: it explicitly states it does not hedge or use derivatives for such commodity risk, with no affirmative hedging sentence. |
| `exposure_status` | `labeled` / `unknown` / `not_yet_reviewed` | `labeled` if any of producer, consumer or shipping_dependent is `yes`. |
| `unknown_reason` | see below | Required when `exposure_status` is not `labeled`. |

Unknown reasons: `no_qualifying_disclosure_in_reviewed_filings`,
`no_preannouncement_annual_report_in_window`, `acquirer_identity_unresolved`,
`fetch_error`. `not_yet_reviewed` is reserved for parties not processed in this run. It is
distinct from `unknown`.

## Decision rules (pass A, automated)

Pass A applies fixed regular-expression rules (implemented in
`scripts/label_commodity_exposure_v1.py`) sentence by sentence to the allowed documents:

- **producer:** a first-person subject plus a production verb (produce, extract, mine,
  drill, refine, explore for, market) followed within the sentence by a listed commodity;
  or the phrase "proved reserves" / "proved developed reserves".
- **consumer:** a first-person term, a listed input term (raw material(s), commodities,
  fuel, jet fuel, diesel, gasoline, energy, natural gas, electricity, power, steel,
  aluminum, copper, resin(s), plastic(s), packaging materials, corn, wheat, soybean(s),
  sugar, coffee, cocoa, cotton, tobacco, grain(s), feed, pulp, paper), a price/cost term,
  and a change/impact term (increase, rise, fluctuate, volatile, higher, affect, impact,
  adversely).
- **shipping_dependent:** a first-person term, a freight term (freight, shipping, ocean
  carrier(s), common carrier(s), third-party carrier(s), transportation costs, trucking,
  fuel surcharge(s)), and a cost/dependence/disruption term.
- **hedged:** a hedge term plus a commodity term (commodity, fuel, diesel, natural gas,
  crude, oil, aluminum, copper, steel, corn, wheat, soybean, electricity, power, metal)
  in a first-person sentence. A sentence only about interest-rate or foreign-currency
  hedging does not qualify. `no_disclosed` needs an explicit negation ("do/does/did not
  (currently) hedge / use / enter into") in such a sentence. Statements that derivatives
  are not used "for trading/speculative purposes" are not negations.
- **No-silent-zero rule:** no flag is ever set to `no` for lack of evidence. Absence of a
  qualifying sentence means `unknown`. Only `hedged` can be negative, and only through an
  explicit, quoted negation.

The rules are fixed before labeling. Any later change is a new version (v2), and the v1
output stays as produced.

## Second review (pass B)

- **Sample:** 20 deals drawn with `random.Random(20261009).sample(sorted(deal_ids), 20)`
  over the 129 manifest deal IDs. Drawn at registration time:

  DEAL-ATHLON-ENCANA-2014, DEAL-CHNG-UNH-2021, DEAL-CLDR-KKRCDR-2021, DEAL-CXO-COP-2020,
  DEAL-FRISCH-NRD-2015, DEAL-GNW-OCEANWIDE-2016, DEAL-HILLSH-TYSON-2014,
  DEAL-IRBT-AMZN-2022, DEAL-MDLA-TB-2021, DEAL-MNTV-ZEN-2021, DEAL-OM-APOLLO-2015,
  DEAL-PROCER-FRANCI-2015, DEAL-QUALIT-FUNDS-2015, DEAL-SAPIEN-PUBLIC-2014,
  DEAL-SIGMA-MERCK-2014, DEAL-STRATE-BLACKS-2015, DEAL-TECUMS-MUELLE-2015,
  DEAL-TWC-CMCSA-2014, DEAL-TWTR-XHOLDINGS-2022, DEAL-VITACO-KROGER-2014.

- **Procedure:** a separate pass produces review packets from the same allowed filings:
  the opening of the business section plus every sentence that matches a broad commodity,
  fuel, freight or hedging vocabulary, with none of pass A's structural conditions
  applied. The packets contain no pass-A output. The reviewer applies the label
  definitions above by judgment and writes the labels before pass-A labels are opened.
  Party identity and filing selection are shared with pass A. Agreement therefore measures
  labeling, not filing selection.
- **Reviewer disclosure:** in v1 the second reviewer is the same AI assistant that wrote
  pass A, working blind to pass-A output with a different (judgment-based) procedure. It
  is not an independent human reviewer, and the report must say so.

## Success criteria (all required)

1. **Coverage:** 100% of the 129 deals have, for both parties, `exposure_status` in
   {`labeled`, `unknown`} with an `unknown_reason` where unknown. `not_yet_reviewed` counts
   as a failure of this criterion.
2. **Chronology:** every `yes` / `no_disclosed` value cites an allowed filing with
   `filing_date < announce_date`, validated by test.
3. **Agreement (primary):** ≥ 90% of the 20 sampled deals have an exact match between pass A
   and pass B on all four fields (`producer`, `consumer`, `shipping_dependent`, `hedged`) for
   **both** parties. Secondary, reported but not gating: per-party exact agreement and
   per-flag agreement with Cohen's kappa.

## Reporting (descriptive only)

Counts by label and unknown share, broken down by announcement year, outcome (close/break)
and sector (sector is unknown for 129 of 129 in the store, so reported as unknown). No break
rates conditional on exposure, no significance tests, no modeling. Pending deals are not in
the population.

## Outputs (research artifacts, not the store)

- `data/research/commodity_exposure_labels_v1.csv`: one row per (deal, party).
- `data/research/commodity_exposure_coverage_v1.json`: summary and agreement.
- `docs/COMMODITY_EXPOSURE_COVERAGE_V1.md`: report.
