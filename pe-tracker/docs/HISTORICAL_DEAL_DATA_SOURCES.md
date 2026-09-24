# Historical deal data sources

**Goal:** an auditable history of resolved M&A deals (announcement, terms and outcome,
each with the time it became public), so `break_logit_v1` can be trained on real
labels. An auditable set matters more than a large one.

**Status (this branch):** the `SECEdgarProvider` is implemented and tested against mocked
EDGAR responses. **0 real deals are ingested.** `data.sec.gov` metadata checks have already
run for the Q3 2026 research register (`scripts/verify_deals_sec.py`). What remains blocked is
**filing text**: the cited documents on `www.sec.gov` cannot be read from this environment, and a
manifest entry requires the filing to be read. The manifest therefore stays empty (reviewed
entries only). Every claim below about a source's API or policy needs checking against that
source's current documentation.

## What a real provider must supply
Enforced by `HistoricalDealRecord.validate()` in `src/ingest/historical.py`. A record
missing any required field is quarantined, never written.

| Required | Optional (reported as missing, never filled) |
|---|---|
| deal_id, target, acquirer | unaffected price, with its own date and source |
| announcement timestamp, plus a source with **known_at** | deal value (USD mm) |
| deal type; consideration type (cash / stock / mixed) | sector, geography |
| offer price (cash, mixed) and/or exchange ratio (stock, mixed) | sponsor (PE) vs strategic |
| terms source (the document the terms were read from) | expected close date |
| if resolved: resolution type (closed / terminated / withdrawn), resolution timestamp, source with known_at | regulatory attributes, financing attributes |

Every written fact also gets a `record_provenance` row with source_name,
source_identifier (URL/URI), accession number, docket reference, company identifier
(CIK), source_timestamp, known_at and ingestion timestamp.

Deal terms, market prints and lifecycle events are stored separately. Terms become an
observation at the announcement time. The unaffected price becomes its own observation,
because it is a market print. Announcement and resolution become `deal_events`.

## Candidate sources

| Source | What it provides | Archive | Timestamps | Outcome coverage | Machine access / limits | Provenance | Licensing | Complexity | Gaps |
|---|---|---|---|---|---|---|---|---|---|
| **SEC EDGAR** (8-K, 425, DEFM14A, SC TO-T, Form 25/15) | Filing metadata (form, 8-K items); full merger agreement (EX-2.1) and press release (EX-99.1) as documents | Electronic filings from the mid-1990s | **Acceptance date-time per filing** (to the second) | Announcement (8-K Item 1.01 / 425), completion (Item 2.01, Form 25/15), termination (Item 1.02) for **US-registered** issuers | JSON `data.sec.gov/submissions`, full-text search; no key; **descriptive User-Agent required; ≤10 requests/second** | Primary; accession numbers are permanent identifiers | U.S. government public data | Medium. Metadata is structured, but **terms are in prose**, so they need human review or careful extraction | Private or foreign targets; the terms still have to be read from the text |
| **FTC** (press releases, cases & proceedings, HSR early-termination notices) | Challenges, consent orders, abandoned deals, second requests (when announced) | Online archive of releases and case pages | Publication date (usually no time of day) | Regulatory actions only, not closes | Web pages; no dedicated merger-case API | Primary | U.S. government public data | Medium: HTML, and cases must be matched to deals | Most deals have no FTC record; announcements are dated, not timed |
| **DOJ Antitrust Division** | Complaints, settlements, abandoned-deal statements | justice.gov press releases and case filings | Date | Regulatory actions only | justice.gov press releases (a JSON feed exists; confirm current endpoint) | Primary | U.S. government public data | Medium | Same as FTC |
| **CFIUS / Treasury** | Aggregate annual reports only | Annual | Year | **No deal-level public data** | — | — | Public | — | Deal-level CFIUS outcomes only appear in the parties' own filings (e.g. 8-K) |
| **UK CMA** (case pages) | Phase 1/2 decisions, undertakings, abandonments | gov.uk case archive | Publication timestamp on gov.uk | UK-reviewed deals: clearance, prohibition, abandonment | GOV.UK Search/Content API (JSON) | Primary | Open Government Licence | Low–medium | Only deals the CMA reviewed |
| **European Commission** (DG COMP merger cases) | Notifications, Phase I/II decisions, prohibitions, withdrawals | Case search back to the 1990s | Decision dates | EU-notified deals | Case search site (no stable public API confirmed) | Primary | Commission reuse policy (reuse permitted with attribution) | Medium–high | Dates only; matching cases to deals is needed |
| **Company IR / newswires** | Press releases with price, premium and timeline | Varies by company | Wire timestamps (often to the minute) | Everything the company announces | Heterogeneous HTML; no common API | Primary (issuer), but hosting varies | Terms of use vary by site | High | No uniform format or access |
| **Commercial** (SDC / LSEG, FactSet, Bloomberg, Dealogic) | Structured terms, outcomes, dates | Decades | Announcement/completion dates | Broad, global | Licensed APIs | Secondary (vendor-compiled) | **Paid licence; redistribution restricted** | Low once licensed | Cost; the vendor's own dates may lack known_at |

## Recommendation: SEC EDGAR first
1. **Most reliable timestamps of any free source.** The acceptance time is recorded to
   the second, which gives a defensible `known_at` for both the announcement and the
   resolution.
2. **It covers both labels.** Item 2.01 / Form 25 mark completion (y=0) and Item 1.02
   marks termination (y=1). Every label can be traced to an accession number.
3. **No licensing ambiguity and no key**, only the fair-access rules.
4. **Honest limitation:** EDGAR does not structure the deal terms. The provider takes terms
   from a **reviewed manifest** (`data/sec_deal_manifest.json`), where each value cites the
   accession it was read from. The provider then checks every cited filing against EDGAR,
   so its form and items must match the claimed event, and uses EDGAR's timestamps.
   Nothing is parsed out of prose automatically.

Regulator sources (FTC, DOJ, CMA, EC) should be added next as *event* providers. They
supply second requests, challenges and prohibitions, which drive break risk, but they
cannot supply the full deal record.

## Manifest entry format
```json
{"deal_id": "…", "target": "…", "acquirer": "…", "target_cik": 1234567,
 "announcement_accession": "0001234567-24-000012",
 "terms_accession": "0001234567-24-000012",
 "deal_type": "strategic", "consideration_type": "cash", "offer_price": 25.00,
 "deal_value_usd_mm": 1500, "sector": "…", "geography": "US",
 "resolution_type": "closed",
 "resolution_accession": "0001234567-24-000040",
 "resolution_timestamp": "optional: cited valid time if earlier than the filing",
 "unaffected_price": 20.10, "unaffected_price_date": "2024-02-29",
 "unaffected_price_source": {"source_name": "…", "source_identifier": "…", "known_at": "…"}}
```

## Timestamp caveats (documented, not guessed)
* EDGAR's `acceptanceDateTime` carries a trailing `Z` but is widely reported to be U.S.
  Eastern time. It is stored naive (the `Z` is stripped), the same way as the rest of the store.
* When a closing happens days before its 8-K is filed, the filing time is its known_at.
  The valid time is the cited `resolution_timestamp` if the manifest gives one, otherwise
  the filing time.

## To activate
1. Allow `www.sec.gov` (filing text) in the environment's network settings. `data.sec.gov`
   (metadata) is already reachable.
2. Set `SEC_USER_AGENT` (for example `"Your Name your@email"`). It is required by SEC policy
   and never committed.
3. Add reviewed manifest entries, then run the provider and the dataset-quality report.
   Model fitting stays a separate, manual step.
