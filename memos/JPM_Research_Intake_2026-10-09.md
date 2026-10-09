# J.P. Morgan October research intake: financing, size and commodity risk

Review date: 2026-10-09 (America/New_York)
Status: provisional research integration; full public article text retrieved 2026-10-09 (see source verification below); no model execution.
Companion: [candidate specification](../pe-tracker/docs/JPM_OCT2026_RESEARCH_CANDIDATES.json).

> **Verification update (2026-10-09, BMO).** This memo was drafted by Athena from
> indexed search excerpts after the three pages returned HTTP 403 to Athena's fetcher.
> A later retrieval on 2026-10-09 (approx. 11:39 ET) returned HTTP 200 with full public
> article text for all three pages and both related J.P. Morgan pages. The status line,
> the "Evidence and access limits" section and the source table below were updated to
> reflect that retrieval and an SEC EDGAR check of the Alphabet figures. Athena's
> original wording is preserved under "Original intake statement (superseded)". The
> companion JSON is Athena's Appendix B unchanged and still records the pre-verification
> access state (`indexed_excerpts_only_full_pages_403`, `full_article_unread`); updating
> it is left for review rather than done silently. Nothing in the update changes the
> Decision, the candidate definitions, or the acceptance gates.

## Decision

Use these sources to prioritize three research questions: how financing access differs across
issuers, whether market-cap and debt structure explain spread stress, and how physical supply
disruptions affect a merger portfolio. These are hypotheses, not established predictors of deal
failure.

This update adds a research memo and machine-readable candidate backlog. It does not ingest
observations, revise announcement probabilities, change strategy constants, enable the draft
dynamic model, or claim new alpha.

## Evidence and access limits

Full public article text for all three J.P. Morgan pages (and the two related J.P. Morgan
pages) was retrieved on 2026-10-09 (America/New_York). A retrieval date is not proof of
historical availability: no historical `known_at` is assigned to any source. Article dates
below are the publisher's displayed/`publishDate` dates at **day precision**; no verified
intraday release time exists. CMS timestamps embedded in page metadata are recorded for
audit only and are internally inconsistent on at least one page, so they are not used as
release times. Pages are mutable and can be revised in place; the raw HTML retrieved is
not committed (publisher content), and its SHA-256 will not reproduce because the pages
embed dynamic content.

| Source | Verified content (retrieved 2026-10-09) | Classification and unresolved work |
|---|---|---|
| [Alphabet financing](https://www.jpmorgan.com/insights/banking/investment-banking/alphabet-equity-raise) | Displayed date October 05, 2026 (day precision). Page metadata: `lastModifiedDate` 2026-10-02T13:10:56-04:00, `createdDate` 2026-10-07T10:01:23-04:00 (inconsistent with the displayed date; not used). Describes a $90 billion multi-tranche equity raise announced June 2026, priced after market close June 2: a $40bn underwritten public offering ($20.7bn common follow-on + $19.3bn mandatory convertible), a $40bn at-the-market (ATM) program commencing Q3 2026, and a $10bn Berkshire Hathaway private placement. | Publisher claim reconciled against SEC filings (see "Alphabet $90bn vs $85bn" below). Both headline figures count the $40bn ATM at program **capacity**, not capital raised; actual ATM sales were not verified. Equity financing of a non-merger issuer: not a merger training row. |
| [SMID-cap outlook](https://www.jpmorgan.com/insights/global-research/markets/smid-cap-outlook) | `publishDate` October 5, 2026 (day precision; metadata `lastModifiedDate` 2026-10-05T11:48:19-04:00). Positive relative stance on SMID vs large caps in developed markets ex-Japan (fundamentals, positioning, technicals, geopolitics, valuation discounts), with short-term caution. Cites Russell 2500 ~+16% YTD vs S&P 500 ~+10% as of September 16 (MarketWatch); EM SMID underperformance YTD; "82% of large-cap debt is fixed" and "close to 40% of SMID-cap debt is floating"; JPM 2026 size breakpoints: small < $2.575bn, mid $2.575bn–$12.85bn, large > $12.85bn. | Forecast and aggregate analysis. Samples and methods behind the debt-mix percentages are not disclosed on the page. Do not translate group averages into company-level facts. |
| [Iran/commodity effects](https://www.jpmorgan.com/insights/global-research/commodities/iran-us-tensions-market-effect) | Current version: "How the Iran conflict has affected commodity markets: The seesaw continues", `publishDate` October 2, 2026 (day precision; metadata `lastModifiedDate` 2026-10-02T11:16:39-04:00). Discusses ~$100/bbl crude, the June 17, 2026 ceasefire, a July 1 low of $71.57, a 2027 Brent scenario of $87/bbl ("forever conflict") vs $64/bbl (baseline), and aluminum disruption (smelters ~4% of global supply; >2 Mt deficit forecast Q2–Q4 2026). The retrieved October text does not contain the $80 Brent first-half scenario. | Mutable URL with distinct vintages (see "Iran article vintages" below). The $80 first-half scenario belongs to the March 2026 version and is not a current forecast. Full dated snapshots are still required before using any quantitative scenario estimate. |

Related J.P. Morgan pages checked on 2026-10-09:

- [Technology investment banking](https://www.jpmorgan.com/investment-banking/technology-investment-banking)
  (metadata `lastModifiedDate` 2026-08-13): "June 2, 2026 · $90bn · The largest equity capital
  raise in history … Alphabet's $90 billion multi-tranche offering."
- [Global dealmaking trends](https://www.jpmorgan.com/insights/banking/global-dealmaking-trends-driving-growth)
  (`publishDate` July 15, 2026): "Alphabet's $85 billion dual-tranche equity and convertible
  offering", with footnote 2: "Includes $10bn separately negotiated private placement and $40bn
  At-the-Market program, expected to begin in Q3 2026".

### Alphabet $90bn vs $85bn (SEC EDGAR, CIK 0001652044)

| Filing (EDGAR filing date) | Accession | Fact |
|---|---|---|
| FWP, 2026-06-01 | 0001193125-26-251733 | Proposed $80bn: $30bn underwritten ($15bn mandatory convertible depositary shares + $15bn Class A/C common), $40bn ATM, $10bn Berkshire private placement. |
| 424B5 (ATM), 2026-06-02 | 0001193125-26-252439 | ATM program "up to $40,000,000,000". |
| 424B5 (common), 2026-06-04 | 0001193125-26-256375 | 25,459,689 Class A at $355.1982 and 25,459,689 Class C at $351.8018 price to public ($9,043,235,705 + $8,956,764,418). |
| 424B5 (Series A / B mandatory), 2026-06-04 | 0001193125-26-257690 / -257702 | 167,500,000 depositary shares per series at $50 ($8,375,000,000 each); option for 25,000,000 more per series. |
| 8-K, 2026-06-04 | 0001193125-26-257724 | Over-allotment options (3,818,953 Class A + 3,818,953 Class C) exercised in full June 3; mandatory underwriters exercised options for 50,000,000 additional depositary shares; Berkshire private placement 14,212,035 Class A at ~$351.81 + 14,359,656 Class C at ~$348.20, gross proceeds $10bn. |
| 8-K, 2026-06-05 | 0001193125-26-259830 | Depositary share offerings closed June 5, 2026; options exercised in full. |

Arithmetic from these filings (BMO calculation, price to public, before discounts):
common base ≈ $18.00bn + options ≈ $2.70bn = ≈ $20.70bn; mandatory base $16.75bn + options
$2.50bn = $19.25bn; underwritten total ≈ $39.95bn (base ≈ $34.75bn). Adding the $40bn ATM
capacity and the $10bn private placement gives ≈ $90bn with options and ≈ $85bn without.

- **Verified:** the $90bn figure matches the filings when the underwriters' options are included
  and the ATM is counted at its full $40bn capacity; the tranche sizes on the October 5 page
  ($20.7bn / $19.3bn / $40bn / $10bn) match the filings.
- **Inference, not stated by J.P. Morgan:** the July 15 page's $85bn appears to be the
  pre-option base deal (≈ $35bn underwritten + $40bn ATM + $10bn placement, per its footnote).
- **Unresolved:** J.P. Morgan does not explain the $85bn basis; how much of the $40bn ATM has
  actually been sold was not verified; gross vs net proceeds differ by underwriting discounts.
- Never add $90bn (or $85bn) as an M&A deal value; it is an issuer equity raise.

### Iran article vintages (same URL)

Evidence for older versions comes from Internet Archive (Wayback Machine) captures, which show
what the archive saw at capture time; they are not the publisher's revision log and do not
establish when any version first became available. Capture timestamps are UTC.

| Version | Title | Displayed date | Evidence | Quantitative content of note |
|---|---|---|---|---|
| Pre-2026 | "What U.S.-Iran tensions mean for oil, gold and stocks" | January 29, 2020 | Capture 2026-01-14 | Unrelated to the 2026 conflict. |
| March 2026 (a) | "US–Israel military operation against Iran: Are markets on edge?" | March 03, 2026 | Capture 2026-03-09 | Contains the $80 Brent scenario. |
| March 2026 (b) | Same title | March 13, 2026 (metadata `lastModifiedDate` 2026-04-07) | Captures 2026-04-20 through 2026-07-23 | "Under a persistent risk premia scenario in which Brent prices remain at $80/bbl through mid-year, global GDP growth for the first half of 2026 could be depressed by an annual rate (ar) of 0.6%". |
| October 2026 (current) | "How the Iran conflict has affected commodity markets: The seesaw continues" | October 2, 2026 | Direct retrieval 2026-10-09 | $87 vs $64 2027 Brent scenarios; aluminum deficit forecast; no $80 first-half scenario. |

The $80 first-half scenario is a March 2026 conditional scenario, superseded at this URL, and
must not be treated as an October forecast. No archive capture between 2026-07-23 and the
October version was found, so the exact replacement date is unknown.

These articles provide context and candidate mechanisms. They do not establish a lower or
higher numerical probability of M&A completion.

### Original intake statement (superseded)

Preserved for audit; superseded by the verification above.

> The three user-supplied J.P. Morgan pages returned HTTP 403 through the research fetcher.
> Search engines exposed indexed excerpts of the publisher's pages. This is partial source
> coverage, not full-article review. Dates below are indexed page dates, not verified intraday
> release times. Reviewed excerpts were observed on October 9; no historical known_at is
> assigned.
>
> - Alphabet: October 5, 2026 article describes a $90 billion equity capital raise announced in
>   June to finance AI compute investment. Publisher claim, not a verified securities issuance
>   record; the technology banking page also describes $90 billion while another JPM dealmaking
>   page references $85 billion. Reconcile scope, stages and dates against issuer filings before
>   numeric ingestion.
> - SMID: October 5, 2026. JPM's near-term constructive view rests on fundamentals, positioning,
>   technical conditions, geopolitical effects and valuation discounts. Indexed text distinguishes
>   developed-market strength from emerging-market underperformance and contrasts debt repricing
>   across size groups. Index definitions, measurement dates and underlying samples remain
>   unverified.
> - Iran: newer indexed title/date "How the Iran conflict has affected commodity markets: The
>   seesaw continues," October 2, 2026. Excerpts discuss elevated crude, operational supply
>   constraints and aluminum disruption. Older indexed content at the same URL contains a
>   first-half $80 Brent scenario. Mutable source with mixed vintages; the old first-half scenario
>   is not a current forecast.

## 1. Financing access: separate capital raising from merger outcomes

Inference: a large issuer's ability to obtain funding may reveal access to capital for that issuer,
but does not establish financing availability for a leveraged sponsor or smaller target.
Distinguish equity funding, committed acquisition debt, refinancing and transaction-specific
financing conditions.

Practical use:

- Keep Alphabet's offering outside the merger close/break training ledger; it is not itself an
  announced acquisition.
- Review acquisition filings for financing commitments, expiration, financing conditions and
  required equity contributions.
- Create a descriptive financing-context record only after reconciling the issuance figures. Never
  add $90 billion as an M&A deal value.
- Test transaction-specific financing evidence before adding broad capital-market sentiment.

## 2. Size and debt structure: a controlled challenger question

Inference: size-group returns and refinancing exposure may help explain spread widening, but a
rally in small companies is not proof that their mergers are safer.

Candidate measurements:

- target market capitalization at a documented pre-announcement timestamp, with effective
  share count and price provenance;
- trailing 20-session SMID-minus-large-cap total return within the same region and currency;
- floating-rate debt / total debt from a filing available by the feature timestamp, with hedge
  coverage separately identified where disclosed.

Predefine index membership, observation windows, currency treatment and missingness rules.
Use historical membership to avoid survivorship bias. Do not mix developed- and
emerging-market samples without explicit region controls. Missing debt detail is unknown, not
zero.

## 3. Commodity disruption: exposure first, stress magnitude second

Inference: fuel, freight, power and metal costs can affect target margins, buyer financing and
deal timing through different channels. Producers and consumers can react in opposite
directions; a universal "energy shock increases break probability" rule is unjustified.

Proposed scenario: physical commodity supply disruption.

- Identify target and acquirer exposure using sourced operating disclosures, including
  energy-input sensitivity, production exposure, shipping dependence and relevant hedges.
- Consider separate effects on break risk, downside value, financing carry and time to close.
- Keep shock sizes, correlation assumptions and probability changes explicitly analyst-assumed
  until independently estimated. The articles supply no calibrated deal-level uplift.
- Report exposure coverage and unknowns before portfolio totals. Do not assume an
  unclassified position is unexposed.

The current portfolio engine only stresses probability floors against fixed downside notionals.
Modeling time-to-close, funding costs or changing downside requires a separately implemented
extension; this memo does not claim those mechanics already exist.

## Repository fit

| Existing component inspected | Current behavior | Proposed next implementation |
|---|---|---|
| `pe-tracker/STRATEGY.md` | Locked announcement-time probabilities and 15:1 cost policy | Preserve baseline; version any later strategy change with its required config and contract tests. |
| `pe-tracker/src/research/market_context.py` | Accepts only sp_return, nasdaq_return and ust10y; requires sourced bitemporal records | Add providers and versioned schema before introducing size-relative returns or crude changes. No new fields are wired here. |
| `pe-tracker/src/model/spread_stress/v2_spec.py` | Draft, execution blocked; no new features authorized | Keep proposed measurements outside the frozen feature set until data and policy gates clear. |
| `pe-tracker/src/research/portfolio.py` | Generic financing, broad risk-off and regulatory scenarios | Add exposure-aware commodity scenarios only with explicit assumptions and unknown-exposure reporting. |
| `pe-tracker/docs/MODEL_ARCHITECTURE_V2.md` | Dynamic competing-risk layer is design only | Later evolving news belongs to a separately versioned dynamic model, not rewritten announcement predictions. |

## Acceptance gates before implementation

1. Obtain full dated source versions; retain canonical URL, article date, observed_at, revision
   evidence and an archived-text hash where permitted. A retrieval date is not proof of historical
   availability.
2. Verify deal facts against issuer/SEC documents. Use the reviewed ingestion path into
   canonical SQLite; analytical projections are not alternate writers.
3. Require valid_time <= prediction_time and known_at <= prediction_time. Unknown
   publication times block historical feature eligibility; later revisions cannot enter earlier
   predictions.
4. Measure coverage by deal, period, region and outcome. Preserve actual missing
   observations; pending deals stay censored.
5. Preregister one candidate family at a time. Compare against the locked baseline and simpler
   benchmarks using grouped chronological splits; keep all snapshots of a deal together.
6. Report Brier, log loss, ROC AUC, average precision with prevalence, calibration diagnostics,
   sample counts and uncertainty. Evaluate costs and sensitivity separately; a higher AUC alone
   does not justify promotion.
7. Add leakage, timestamp, schema, exposure-sign and unknown-coverage tests with any
   executable implementation. Run required project tests then; this change is documentation only.

## Priority

First resolve provenance and commodity exposure coverage; then collect financing and debt
facts for existing eligible deals. Evaluate size-relative returns only after historical index data are
available. No training, backtest or investment-performance improvement has been
demonstrated by this intake.
