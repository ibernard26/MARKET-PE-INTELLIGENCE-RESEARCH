# Preregistration: commodity-exposure coverage v2 (research only)

- **Status:** preregistered before any v2 labeling. This document is committed before the v2 implementation and before any v2 production label exists.
- **Owner approval:** Isaiah Bernard, 2026-10-09. It was approved strictly as a new, isolated research experiment.
- **Predecessor:** v1 (`docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v1.md`, PR #51). v1 failed its agreement gate (7/20 deals). PR #51 is preserved untouched, and its labels are not used by v2.

## 0. Scope and hard constraints
- **Research artifact only.** Outputs live under `data/research/` as CSV/JSON/Markdown.
  - No canonical SQLite write. No DB mutation of any kind.
  - No model fitting, backtesting, walk-forward, sweeps, or feature integration.
  - Nothing is wired into `event_driven_v1` / `break_logit_v1`.
- **Population.** All 129 deals in the reviewed `data/sec_deal_manifest.json`, with two parties per deal (target, acquirer) = 258 party rows.
- **SEC access.**
  - The contact address comes only from the runtime environment variable `SEC_CONTACT_EMAIL`. It has no default.
  - The tooling refuses any network fetch when the variable is unset.
  - The contact address is never written to the repository or to committed logs.
  - Requests are spaced ≥ 0.12 s, under SEC's 10 req/s fair-access limit.

## 1. Flags and exact criteria
v2 labels three flags per party: `producer`, `consumer` and `hedged`. `shipping_dependent` is out of scope for v2 (see §8).

Common requirements for any `yes` or `no_disclosed`:
- **First person.** The evidence sentence describes the filer itself (we/our/us/the Company).
- **No generic references.** Sentences whose only commodity-like term is a generic reference to *energy*, *power*, or *operating efficiency* never qualify. This covers phrases such as "time and energy", "market power", "energy efficiency", "power of our platform" and "efficiency".
- **No factor lists.** List-of-factors sentences are excluded:
  - three or more bullet markers;
  - three or more semicolon-separated items;
  - sentences introduced by "factors include", "risks include", "including but not limited to" or "such as" followed by ≥4 comma items;
  - any sentence longer than 700 characters.

### 1.1 producer = yes
The filer states that **it** produces, extracts, mines, drills for, refines, processes (meat/poultry/grain only) or is a producer/refiner/miner of a **named physical commodity**. Named physical commodities are: crude oil, natural gas, NGLs, coal, metals and ores (named), uranium, potash/phosphate, ethanol, timber/lumber, grains/oilseeds, livestock/meat/poultry, petrochemicals.

The filer may alternatively report proved reserves of oil, gas or minerals.

These do **not** qualify:
- buying, using, transporting, gathering, storing or hedging a commodity;
- servicing commodity producers;
- having price exposure as a purchaser;
- holding investments in energy companies.

### 1.2 consumer = yes
The sentence must show **commodity input-cost exposure**. It must name a specific commodity input or an explicit "raw materials"/"commodities" input:
- fuel, jet fuel, diesel, gasoline, natural gas, electricity, crude oil as feedstock;
- steel, aluminum, copper, other named metals;
- resin/plastics, pulp/paper/packaging materials;
- named agricultural inputs (corn, wheat, soybeans, sugar, coffee, cocoa, cotton, dairy, beef, pork, poultry, feed, grains).

The sentence must tie that input to the **filer's costs**: cost of/price of/prices we pay/purchases of/costs of the input, used as an input, or raw-material costs. It must also state an impact or variability (increase, volatility, fluctuation, adverse effect, inflation).

These do **not** qualify:
- the filer's own sales/realized-price exposure (producer-side price sentences);
- energy-sector credit or investment exposure;
- generic macro sentences;
- "energy" or "power" used alone. "Energy costs" and "cost of energy" also do not qualify unless the same sentence names a specific energy commodity such as electricity, natural gas or fuel.

### 1.3 hedged
**hedged = yes:** the filer states that it uses, has entered into, or holds **qualifying commodity derivatives**: futures, forwards, swaps, options or collars on a named commodity or "commodity"/"commodities", or hedges of forecasted commodity purchases or sales. Fixed-price physical supply contracts qualify only if the sentence calls them hedges or derivatives.

These do **not** qualify: interest-rate, currency, equity, credit or convertible-note hedges; and statements that hedging markets do not exist or that the filer *may* hedge in future.

**hedged = no_disclosed:** the filer explicitly states that it does not hedge its commodity (or named-commodity) exposure.

**Otherwise:** `unknown`.

### 1.4 Status and the no-silent-zero rule
Flag values are:
- producer: {yes, unknown}
- consumer: {yes, unknown}
- hedged: {yes, no_disclosed, unknown}

**Absence of evidence is `unknown`, never `no`.**

`exposure_status` is `labeled` if producer or consumer is `yes`; otherwise it is `unknown` with exactly one `unknown_reason` from this list:

| unknown_reason | Meaning |
|---|---|
| `no_qualifying_disclosure_in_reviewed_filings` | Filings were reviewed but none qualified |
| `no_preannouncement_annual_report_in_window` | No in-window annual report exists |
| `acquirer_not_identified_in_merger_filing` | The merger filing names no legal-entity acquirer |
| `acquirer_pe_buyer_unresolved` | Sponsor/fund acquisition vehicle; see §2 |
| `acquirer_no_unique_sec_registrant` | The legal entity matched zero or several registrants with an eligible annual report |
| `fetch_error` | A download failed (recorded, never hidden) |

`not_yet_reviewed` is reserved for rows not processed, and any such row fails coverage.

## 2. Entity resolution from merger filings
- **Targets** use the reviewed manifest `target_cik`.
- **Acquirers** are identified from the deal's **merger filing before** any SEC-record matching.
  1. **Source.** The source is the manifest `announcement_accession`, the complete submission with exhibits.
     - If that filing names no acquirer legal entity, the first of the target's DEFM14A, PREM14A, SC 14D9, SC TO-T or S-4 filed within 120 days after announcement is used instead.
     - These filings are used **only for identity**, never as exposure evidence. This is because they are dated on or after announcement.
  2. **Extraction.** Extract the acquiring legal entity from:
     - merger-agreement party clauses ("by and among A, B and C");
     - defined-term clauses ("X, a Delaware corporation (“Parent”)");
     - and, if present, "a wholly owned subsidiary of Y", which gives the ultimate parent.
     
     The extraction record stores: source accession, form, filing date, SEC acceptance timestamp and the quotation.
  3. **Matching.** Match the extracted name (ultimate parent first, then Parent) to SEC registrants by exact normalized name in SEC `cik-lookup-data.txt`. Accept only if exactly one candidate CIK has an eligible pre-announcement annual report (§3).
  4. **PE buyers.** If the acquiring entity is a sponsor or fund vehicle, the party is `unknown` / `acquirer_pe_buyer_unresolved`. Sponsor or fund vehicle means either of:
     - the filing describes it as owned/controlled by or affiliated with funds, investment partnerships or a private-equity sponsor;
     - the manifest `deal_type` is `take_private` and no unique registrant match exists.
     
     **The sponsor's listed management company is never substituted for the buyer**, and no identity is ever invented.
- The manifest's `acquirer` string is only a cross-check, recorded as `manifest_name_consistent` true/false. It is never used as the identity itself.

## 3. Evidence, chronology and provenance
- **Exposure evidence.**
  - The latest 10-K/10-K405/10-KT/10-KSB/20-F/40-F with filing date in [announce − 550 days, announce).
  - The latest 10-Q/10-QSB filed after it and strictly before announcement.
  - 8-Ks are not used as exposure evidence.
- **Chronology.** Every cited filing must have `filing_date < announce_date` and SEC `acceptanceDateTime` (converted to ET) on a date before the announce date.
  - The acceptance timestamp is recorded as the **historical availability timestamp**.
- **Each yes/no_disclosed cell stores:** accession, form, filing date, acceptance timestamp, primary document URL, Item locator, character offset and the verbatim quotation (≤ 400 chars).
- **SIC.**
  - SIC code and description from SEC submissions metadata are stored as **contextual metadata only**. They are never evidence of exposure and never used by any rule.
  - The submissions endpoint reports the *current* SIC, not a point-in-time value, and this is stated in the outputs.

## 4. Rule development and freezing
- The v1 20-deal sample is **development-only**. Regex implementation of §1 may be tuned only on that sample, using the v1 local cache with no network.
- The v2 validation sample is never inspected during development.
- Rules are frozen at the implementation commit. Production labeling records the SHA-256 of the labeler source in its outputs.
- Development dry-run results are reported as development, not v2 results.

## 5. Validation sample (fresh, blinded)
- **Procedure.** Let `ids` = sorted manifest deal_ids (129) and `v1` = `sorted(random.Random(20261009).sample(ids, 20))`.
  - Pool = `sorted(set(ids) - set(v1))` (109 deals).
  - Sample = `sorted(random.Random(2026100902).sample(pool, 20))`, run with Python 3.11 `random`.
- **The drawn sample** (committed with this prereg, before labeling):
  DEAL-ANN-ASCENA-2015, DEAL-APC-OXY-2019, DEAL-BARRY-MRGB-2014, DEAL-BLYTH-CARLYL-2015, DEAL-CEC-APOLLO-2014, DEAL-CERN-ORCL-2021, DEAL-CPRI-TPR-2023, DEAL-EA-PIFSLAFF-2025, DEAL-EINSTE-JAB-2014, DEAL-ENTROP-MAXLIN-2015, DEAL-IMPRIV-THOMA-2016, DEAL-INFORM-ITALIC-2015, DEAL-LNKD-MSFT-2016, DEAL-MKTG-AEGIS-2014, DEAL-MXIM-ADI-2020, DEAL-NUAN-MSFT-2021, DEAL-ODP-SPLS-2015, DEAL-ORBITZ-EXPEDI-2015, DEAL-REYNOL-IMPERI-2014, DEAL-STEINE-CATTER-2015.
- **Blinded packet.** For each sample deal and party, the packet gives:
  - the identity-resolution record;
  - the evidence filings, with URLs and acceptance timestamps;
  - character-offset references for the full Item 1, 1A, 7 and 7A sections of each filing;
  - evidence excerpts. These are all first-person sentences selected by a fixed broad vocabulary that is independent of the labeler's rules, in document order. A cap and truncation count are stated per document.
  
  It contains **no first-pass labels, no rule outputs, and no indication of which sentence any rule matched**.
- **Response template.** The packet includes a blank response template (deal_id, party, producer, consumer, hedged, evidence_ref, note).

## 6. Second reviewer (disclosure)
- The second review is performed separately by Isaiah Bernard using **another AI-assisted reviewer**, with first-pass labels concealed. It is described as **AI-assisted review, not independent human review**.
- The first-pass author does not score agreement. Scoring is done with the committed scorer after the reviewer's CSV exists.

## 7. Gates (all must pass; otherwise v2 FAILS)
**G0. Coverage and chronology**
- 258/258 party rows are `labeled` or `unknown` with a reason. Zero `not_yet_reviewed`.
- Every cited filing satisfies §3 chronology.

**Agreement unit.** For each sample deal, there are 6 cells (3 flags × 2 parties), giving 120 cells in total.

**G1. Exact agreement**
- At least **18/20** deals agree exactly on all 6 cells.

**G2. Shared-unknown rule**
- Agreement driven by shared unknowns does not count as substantive success.
- Let S = cells where at least one rater gives a non-`unknown` value.
- **Evaluability:** G2 requires |S| ≥ 15. If |S| < 15, the result is `not_evaluable`, which counts as **not passed**.
- **Pass condition:** agreement on S (both raters give the identical value) is ≥ 0.85.

**G3. Kappa floor**
- For each flag with ≥ 5 cells in S, Cohen's κ over all 40 cells of that flag must be ≥ 0.60.
- Flags with < 5 substantive cells are reported as `insufficient_substantive_labels` and do not satisfy G3 on their own.
- **G3 requires `consumer` to be evaluable and pass**, plus every other evaluable flag to pass.

**Always reported, outside the gates:**
- per-flag agreement (producer, consumer, hedged separately), overall and on S;
- per-rater unknown rates per flag;
- |S| per flag;
- the list of disagreements.

## 8. Deviations from v1 (motivated by v1's failure analysis, `docs/COMMODITY_EXPOSURE_COVERAGE_V1.md` on PR #51)
| v1 | v1 failure evidence | v2 |
|---|---|---|
| Broad input tokens incl. "energy", "power" | Consumer false positives on "time and energy" (CHNG-UNH acquirer), "market power" (CHNG, MDLA, MNTV) | Generic energy/power/efficiency excluded (§1) |
| Any first-person sentence with commodity + price + impact = consumer | Producer-side price sentences counted as consumer (ATHLON, CXO, COP, Encana); insurer energy portfolio (GNW) | Input-cost tie required; sales/realized-price and investment contexts excluded |
| List-of-factors sentences allowed | IRBT/AMZN, QUALIT, Blackstone false positives | Factor lists excluded |
| Producer verbs incl. "market(s)"; any commodity word nearby | Tecumseh (steel consumer) and Quality Distribution (crude transporter) flagged producer; Hillshire (meat processor) missed | Producer requires the filer as producer; processors of meat/poultry/grain included; transport/purchase excluded |
| Hedge = any derivative word + any commodity-ish word | Blackstone FSOC text; Athlon generic price sentence | Qualifying commodity derivative required |
| Acquirer identity = name match of manifest string; sponsor parents substituted | 72/129 unresolved; Blackstone/Apollo/Carlyle/Fortress parents substituted for fund vehicles | Identity from merger filing; PE buyers recorded unknown, never substituted |
| shipping_dependent flag | No tightened definition was requested; v1 agreement 87.5% with low substantive support | Dropped from v2 (out of scope) |
| Pass B by the same assistant on truncated packets | Kroger commodity hedge missed due to truncation | Packet adds full-section offsets + URLs; reviewer is a separate AI-assisted review run by Isaiah |
| Agreement 90% on 4 flags, no shared-unknown control | Shared unknowns inflated per-flag agreement | G1 18/20 + G2 shared-unknown rule + G3 κ floor; fresh sample excluding v1's |
| Placeholder SEC contact | — | `SEC_CONTACT_EMAIL` env var, no default, fetch refused if unset |
| No availability timestamps | — | SEC acceptance timestamps recorded |

## 9. Outputs (planned)
- `scripts/commodity_v2/`: entity resolution, labeler, packet generator, scorer.
- `data/research/commodity_exposure_v2_identities.csv`
- `data/research/commodity_exposure_v2_labels.csv`
- `data/research/commodity_exposure_v2_run.json`: coverage, unknown rates, rules hash; research_only flags.
- `data/research/commodity_exposure_v2_review_packet/`: blinded packets + response template.
- `docs/COMMODITY_EXPOSURE_V2_DEV_DRYRUN.md`: development notes on the v1 sample, labeled as development.

No v2 agreement score exists until the separate AI-assisted review is returned.
