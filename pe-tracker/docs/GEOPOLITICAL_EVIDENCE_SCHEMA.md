# Geopolitical evidence schema & verification workflow (`geo_evidence_v1`)

Code: `src/geo_intel/schema.py`, `store.py`, `verification.py`, `pit.py`.
Tests: `tests/test_geo_intel_ingest.py` (fixtures are SYNTHETIC, `.invalid` hosts).

## EvidenceRecord (one source's statement about one candidate event)

| Field | Meaning | Rule |
|---|---|---|
| `event_id` | `GEO-` + sha1(category, reviewed `event_key`) | derived; same key ⇒ same event regardless of who reported first |
| `evidence_id` | `EVD-` + sha1(event, URL, statement, publication time, revision, stance) | derived; tamper-checked on load |
| `category` | one of 8 monitored categories | closed vocabulary |
| `original_statement` | verbatim statement / excerpt | required |
| `reporting_entity` | who made the statement (agency, official, outlet) | required |
| `source_url`, `publisher` | where it was published / by whom | absolute http(s) URL; `primary_official` only on registered authority hosts |
| `source_type` | `primary_official`, `reputable_secondary`, `ai_brief`, `social_post`, `other` | Grok/X ⇒ `ai_brief`/`social_post`, enforced |
| `claim_type` | `occurred`, `attributed_statement`, `scheduled`, `prediction`, `rumor` | only `occurred` can describe a completed event |
| `stance` | `supports` / `contradicts` | conflicting sources are recorded, not discarded |
| `publication_timestamp` | when the source was published | optional; **missing stays missing** |
| `event_valid_timestamp` | when the event occurred / takes effect | optional; missing ⇒ never admissible |
| `first_observed_timestamp` | when this system first saw the source | stamped with the real ingestion time if absent |
| `known_at` (+ `known_at_basis`) | when the fact became public | explicit → publication → first-observed → missing; explicit earlier than publication is rejected |
| `retrieved_by_reviewer` | a person/agent actually fetched and read the URL | unretrieved sources never count toward verification |
| `geographies`, `sectors` | ISO-3166 alpha-2 / region codes; controlled sectors | no free text |
| `affected_deal_ids`, `affected_company_ids` | candidate links (validated in `exposure.py`) | a mention is not a confirmed link |
| `syndicated_from` | origin of a re-run wire story | syndicated copies count once |
| `revises_evidence_id`, `revision_type` | correction / update / retraction chain | only the original publisher; originals never mutated |
| `claimed_status_by_source` | what the input asserted | audit only, never used |

Timestamp inputs: `YYYY-MM-DD` (day precision → compared as 23:59:59.999999 that day) or a
time with `Z`/offset. A time of day without an offset is rejected — the zone is never guessed.

## Workflow

```
Grok/X brief ─┐                                  reviewer retrieves cited URL(s)
reviewer rec ─┴─> validate ─> dedup ─> append ─────────────┐
                                                           v
               classify(cluster, as_of T)  <── corrections / retractions (append)
                    │
                    ├─ VERIFIED_PRIMARY / CORROBORATED_SECONDARY ──> pit gate (valid≤T, known_at≤T)
                    │                                                  └─> research candidate (not a feature)
                    └─ ATTRIBUTED_CLAIM / UNCONFIRMED / DISPUTED / RETRACTED ──> stays in staging
```

Status rules (first match): RETRACTED → DISPUTED (primary contradiction, or trusted
conflict without primary) → VERIFIED_PRIMARY (retrieved registered primary, published,
`occurred`) → CORROBORATED_SECONDARY (≥ 2 independent retrieved outlets) →
ATTRIBUTED_CLAIM (one retrieved trusted source / attributed / scheduled) → UNCONFIRMED.
Status is recomputed from evidence knowable at T, so an upgrade is dated by when it happened.

## Dedup

Exact duplicate, or same (event, canonical URL, stance, revision) ⇒ rejected.
Same (URL, statement) under two events ⇒ `ClusterConflictError`.

## Upstream-provenance fields (relayed feeds)

`relayed_by`, `upstream_source_kind`, `upstream_claim_type`, `upstream_geography`,
`upstream_sectors`, `lead_urls` (primary-source LEADS — never evidence), `provenance`
(`file#Lline sha256=<raw line>`). Records with `ingested_via` in {`grok_brief`,
`todd_feed`} must be untrusted (`ai_brief`/`social_post`/`other`) and
`retrieved_by_reviewer = false` — enforced by the schema.

## Todd feed mapping (`src/geo_intel/todd_adapter.py`)

| Todd `source_kind` | `source_type` | | Todd `claim_type` | `claim_type` |
|---|---|---|---|---|
| `primary_official` | `other` (a relayed official link is a lead) | | `reported_fact` | `occurred` |
| `news_outlet` | `other` | | `official_document` | `occurred` |
| `law_firm_analysis` | `other` | | `attributed_claim` | `attributed_statement` |
| `x_post` | `social_post` | | `unconfirmed_report` | `rumor` |
| `x_trend_summary` | `ai_brief` | | `market_data` | rejected (series belong in FRED) |

| Todd field | Ledger field |
|---|---|
| `category` | `category` (`russia_ukraine_energy`→`russia_ukraine_energy_infrastructure`, `hormuz_maritime`→`strait_of_hormuz_maritime`, `energy_supply`→`energy_supply_interruption`, `rates_financing`→`rates_and_acquisition_financing`, `procurement_regulatory`→`government_procurement_regulatory`, `sector_exposure`→`sector_geopolitical_exposure`) |
| `statement`, `reporting_entity`, `publisher`, `source_url` | same |
| `published_at` / `event_time` | `publication_timestamp` / `event_valid_timestamp` (null stays null; zone-less rejects the item) |
| `first_observed_at` | `first_observed_timestamp` (Todd's retrieval/brief-run time) |
| `geography` | ISO codes for exact country names; raw list kept in `upstream_geography` |
| `sectors` | not mapped (`sectors = ()`); raw kept in `upstream_sectors` |
| `companies` | `affected_company_ids` (absent → empty; never inferred) |
| `primary_source_leads` | `lead_urls` (absent → empty) |
| `brief_date` | `relayed_by = "Todd news brief <date>"` |
| `notes` | `notes` + detected flags (truncated, syndicated copy, standfirst, paywalled, lower confidence, blocked) |

Cluster key per item = category + canonical URL + first 60 normalized characters of the
statement (no automatic cross-source clustering). Same key + URL with different text ⇒
appended as an `update` revision; identical ⇒ duplicate (idempotent re-ingest).
Known limit: a correction that changes the first 60 characters opens a new cluster.
