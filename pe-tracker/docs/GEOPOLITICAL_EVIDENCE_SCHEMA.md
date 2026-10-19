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
