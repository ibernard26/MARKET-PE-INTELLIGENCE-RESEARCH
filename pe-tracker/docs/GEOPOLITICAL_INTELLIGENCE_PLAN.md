# Geopolitical intelligence integration — audit & implementation plan

**Status: RESEARCH STAGING ONLY.** Branch `feature/geopolitical-event-intelligence`,
base `origin/main` @ `724da08` (merge of PR #50). `break_logit_v1` and the proposed
`break_hazard_v1` remain **NON-EXECUTABLE FOR LIVE TRADING AND UNVALIDATED FOR
EMPIRICAL PREDICTION.** No model was fitted, no walk-forward was executed, and the
`first_walkforward_v1` authorization flag is unchanged (`execution_authorized: false`).

## 1. Audit of the existing architecture

| Area | Finding | Consequence for this phase |
|---|---|---|
| Canonical store | SQLite (`schema.sql`, `src/db.py`) is the only source of truth; research files "never enter the store" (`CLAUDE.md`). Append-only triggers on every research table. | Geopolitical evidence is **not** written to SQLite. It lives in an append-only JSONL ledger under `data/geopolitical/` (same posture as `data/public_mna_intelligence/` and the Q3 canonical research files). |
| Time rule | `src/research/bitemporal.py`: valid ≤ T AND known_at ≤ T; known_at never guessed; ingestion-time fallback. | Reused as the design rule. `geo_intel` adds day/second precision and rejects zone-less times so a precision loss can only make information *later*. |
| Deal lifecycle events | `src/research/events.py` has a closed vocabulary that already includes `cfius_review`, `doj_challenge`, `eu_clearance`, `uk_cma_action`, … | Deal-specific regulatory actions stay **deal events**. `geo_intel` handles macro / geopolitical events and links them to deals separately; it does not duplicate the deal-event vocabulary. |
| Canonical research identity | `src/research/canonical.py` + `canonical_q3_2026.py`: deal/event identity, primary-vs-corroborating provenance, label rules (clearances are never labels). | Same philosophy adopted: one event cluster, many sources; status derived, never copied. |
| Third-party AI staging | `data/public_mna_intelligence/…/staging_chatgpt/` kept byte-for-byte, reconciled by `scripts/reconcile_chatgpt_staging_2026q3.py` (`confirmed_sec_metadata`, `corroborated_press`, `unverified_source_unreachable`, `corrected`). | Grok/X briefs get the same treatment, formalised: staged as `ai_brief`, never trusted (mapping in §4). |
| Market data | FRED → `market_observations` (incl. `DGS10`, WTI, Brent) with known_at + provenance; `market_data.RESEARCH_FEATURES` are **not** fs_v1 features. | Treasury-rate and energy-price **series** are not re-ingested. `geo_intel` only stages discrete *events* in those categories (e.g. a sanctions waiver, a financing-market disruption). |
| fs_v1 / break_logit_v1 | `src/model/dataset.py` FEATURES = 5 numeric + 9 binary = **14**; L2, C=1.0, lbfgs, max_iter=1000, no class weight, no calibration; FN:FP = 15:1 (`src/config.py`, `STRATEGY.md`, `test_strategy_contract.py`). | Untouched. Byte-level SHA-256 pins added in `tests/test_geo_intel_isolation.py`. |
| first_walkforward_v1 | `protocol.json` `PREPARED_NOT_EXECUTED`, `execution_authorized: false`, cohort N=62. | Untouched and pinned. No fit / walk-forward / registration call path exists in `geo_intel` (tested with monkeypatched hard failures). |
| V2 | `MODEL_ARCHITECTURE_V2.md`: `break_hazard_v1` design-only; fs_v2 "not built here". | Geopolitical fs_v2 extension drafted as a separate design-only JSON (`data/geopolitical/fs_v2_geo_candidates_DRAFT.json`). |
| Sector data | Manifest (129 deals) has **no sector field**; the store copy has sector NULL for 129/135; only 4 manifest deals carry a free-text sector in the research-only 2026Q3 register. | Sector exposure requires a reviewed controlled-vocabulary assignment. None is fabricated; the report shows the gap. |
| arb-intelligence | DuckDB/dbt projection of SQLite; 8 models, 6 singular tests, fixture fallback. | No change needed: geo staging is not in SQLite, so nothing to project yet. A future dbt source is listed under milestones. |
| Dependencies | `docs/DEPENDENCY_ARCHITECTURE.md`: matplotlib is "future optional, not added until code imports it". | `geo_intel` core is stdlib-only. PNG rendering imports matplotlib lazily and is optional; `requirements.txt` unchanged. |
| Open work | PRs #51/#52 (commodity-exposure coverage v1/v2) are unmerged and label company commodity exposure. | Not duplicated: `geo_intel` does not label company commodity exposure. A later milestone can consume reviewed commodity labels as sector-hypothesis inputs. |

## 2. Conflicts between the directive and the current implementation

None is material (no constraint had to be bent). Minor conflicts, resolved in favour of existing governance:

1. **"Ingest into the repository" vs. SQLite-as-sole-SoT.** Resolved by staging outside the canonical store (JSONL ledger). Promotion of any geopolitical fact into SQLite would need a reviewed schema change, which this phase does not make.
2. **"Verified geopolitical event timelines" / "exposure by sector" from existing data.** The repository contains **no** primary-source-verified geopolitical events (the tracker/memos contain secondary, unretrieved claims). Per the no-fabrication rule, the ledger ships **empty** and these charts render an explicit empty state. Tracker items can later be staged as `UNCONFIRMED` leads and verified one by one.
3. **Treasury rates / energy prices categories** overlap the FRED store. Series stay in FRED; only discrete events are staged.
4. **Sector exposure** needs sector data the canonical corpus does not have (4/129). No automatic free-text → taxonomy mapping is done.
5. **dbt checks**: CI runs dbt against the 6-deal fixture (no committed SQLite). The checks were run that way; the real store was only read via a local copy (read-only).

## 3. What was built (all isolated under `src/geo_intel/`)

| Module | Role |
|---|---|
| `schema.py` | Categories, statuses, source/claim types, controlled sectors & geographies, primary-domain registry, timestamp parser, `EvidenceRecord` (see `GEOPOLITICAL_EVIDENCE_SCHEMA.md`). |
| `store.py` | Append-only JSONL ledger, dedup, cluster-conflict detection, publisher-only revisions, tamper check on load, Grok/X brief staging. |
| `verification.py` | Derives status as of T; status history. |
| `pit.py` | Anti-leakage gate (valid ≤ T AND known_at ≤ T, admissible statuses only). |
| `exposure.py` | Event → deal links (`CONFIRMED_DEAL_SPECIFIC` vs `SECTOR_HYPOTHESIS`), 7 channels, read-only manifest view, `effect_on_break_probability = NOT_ESTIMATED`. |
| `reporting.py` | Read-only report (JSON + Markdown, optional PNG); reserved V1/V2 charts read **NOT AVAILABLE — MODEL NOT EXECUTED**. |
| `ingest.py` | CLI to stage Grok briefs or reviewer records. |

## 4. Status mapping to the existing reconciliation vocabulary

| Existing (`reconcile_chatgpt_staging_2026q3.py`) | `geo_intel` |
|---|---|
| `confirmed_sec_metadata` (primary metadata read) | `VERIFIED_PRIMARY` only if the primary document was retrieved and states the event occurred |
| `corroborated_press` | `CORROBORATED_SECONDARY` if ≥ 2 independent retrieved outlets, else `ATTRIBUTED_CLAIM` |
| `unverified_source_unreachable` | `UNCONFIRMED` (`retrieved_by_reviewer = false`) |
| `corrected` | a new revision record; original kept |

## 5. Recommended next milestones

1. Reviewer workflow to stage existing tracker/memo geopolitical items as `UNCONFIRMED` leads, then retrieve primary sources (OFAC recent actions, Federal Register, EU OJ, gov.uk OFSI) and append primary records with real URLs and publication times.
2. Reviewed controlled-vocabulary sector assignment for the 129 manifest deals (outcome-blind: assign before looking at labels), optionally consuming the commodity-exposure labels if PR #51/#52 pass their agreement gates.
3. Pre-registration of the incremental-value experiment (`GEOPOLITICAL_INCREMENTAL_EVALUATION.md`) — only after `AUTHORIZE FIRST REAL WALKFORWARD` and the fs_v1 baseline exist.
4. Optional dbt source over the ledger (read-only projection) once it has content.
