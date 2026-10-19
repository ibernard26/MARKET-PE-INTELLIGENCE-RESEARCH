# V1 readiness report — data and method limits

**Date:** 2026-10-19 (America/New_York)
**Scope:** What currently limits a defensible V1 on the historical merger-arb set.
**Status:** Research readiness only. **V1 is NOT fitted. Walk-forward is NOT authorized.
`execution_authorized` remains `false` in `data/experiments/first_walkforward_v1/protocol.json`.
No performance claims. V2 remains design-only.**

Numbers below are grounded in repository or shared research files cited inline.
Anything not verified from those files is marked **unverified**.

---

## 1. Historical deal corpus

| Fact | Value | Source |
|---|---:|---|
| Reviewed SEC-filed deals in manifest | 129 | `data/sec_deal_manifest.json` |
| Closed | 109 | `resolution_type=closed` |
| Terminated | 19 | `resolution_type=terminated` |
| Withdrawn | 1 | `resolution_type=withdrawn` |

**Class imbalance.** Breaks are rare: 19 terminated + 1 withdrawn vs 109 closed.
The frozen first-walkforward cohort is smaller still (N=62: 43 closed / 19 terminated
per `protocol.json`); it is prepared but not executed.

## 2. Sector (SIC) labels — point-in-time gap

SIC labels assigned on 2026-10-19 are **current EDGAR company SIC codes**, not
as-of-announcement codes. A historical (announcement-date) check is still pending
(Todd P2). Until that lands, sector features must not be treated as point-in-time.

Acquirer coverage from `/home/box/shared/sector-labeling/todd_sic_research_2026-10-19.csv`
(129 acquirer rows):

| Bucket | Count | Notes |
|---|---:|---|
| High-confidence CIK/SIC | 63 | `match_confidence=high`, SIC present |
| Medium-confidence, human group-adjudicated | 5 | see §2a |
| UNKNOWN (no usable SIC) | 61 | sponsors, shells, foreign issuers, unresolved names |

Targets: 129/129 LABELED (given CIK) — still current-EDGAR, not as-of-announcement.

### 2a. Medium-confidence acquirer adjudication (2026-10-19)

Isaiah signed off on the five medium-confidence acquirer SIC matches **as a set**
(one human approval covering all five together, **not** five separate one-by-one
reviews). Recorded on each CSV row:
`adjudicated_by=Isaiah`, `adjudicated_date=2026-10-19`, `adjudication_note=group approval`.
`match_confidence` remains `medium` (near_name / single-word exact); the sign-off
accepts the proposed CIK/SIC for labeling use.

| deal_id | SIC | list name → EDGAR name |
|---|---:|---|
| DEAL-APC-OXY-2019 | 1311 | Occidental Petroleum Corporation → OCCIDENTAL PETROLEUM CORP /DE/ |
| DEAL-BORDER-PITNEY-2015 | 3579 | Pitney Bowes Inc → PITNEY BOWES INC /DE/ |
| DEAL-COR-AMT-2021 | 6798 | American Tower Corporation → AMERICAN TOWER CORP /MA/ |
| DEAL-CRNX-VRTX-2026 | 2834 | Vertex Pharmaceuticals Incorporated → VERTEX PHARMACEUTICALS INC / MA |
| DEAL-ELECSY-LINDSA-2014 | 3523 | Lindsay → LINDSAY CORP |

Two other medium-confidence acquirer rows (AVANIR-OTSUKA, MON-BAYER) have empty SIC
and were **not** included in this group approval.

## 3. Geopolitical evidence ledger

Ingest of `/home/box/shared/todd-news-brief/events-2026-10-19.jsonl` into
`data/geopolitical/evidence_ledger.jsonl` via `src.geo_intel.todd_adapter`
(2026-10-19, after PR #53 on `main`):

| Metric | Value |
|---|---:|
| Feed lines | 17 |
| Accepted | 12 (all `UNCONFIRMED`) |
| Rejected | 5 (`market_data` — not discrete events) |
| Re-ingest new lines | 0 (12 duplicates; idempotent) |
| Verified / corroborated | 0 |
| Null `publication_timestamp` (of 12) | 2 |
| Null `event_valid_timestamp` (of 12) | 11 |
| `retrieved_by_reviewer` | false on all 12 |

Evidence IDs match the earlier staging pilot under `/workspace/geo_staging/2026-10-19/`.
No status upgrades yet: primary-source verification waits on Todd's
`primary_source_leads` (none present under `/home/box/shared/todd-news-brief/` as of
this report). Cluster keying uses category + canonical URL + first-60-char statement
prefix; cross-source clustering is a reviewed step, not automatic.

Provenance stored on ledger rows is `events-2026-10-19.jsonl#L<n> sha256=<…>`
(filename only). Acceptable for a public repo; no absolute home paths or personal
identifiers in committed ledger fields. Adapter reconciliation reports may echo the
absolute feed path locally; those reports are **not** committed.

Isolation: geo ledger is outside SQLite / fs_v1; `tests/test_geo_intel_isolation.py`
pins 17 locked files and asserts no `geo_*` features in the active contract.
`execution_authorized` unchanged (`false`).

## 4. Other method limits

| Limit | State |
|---|---|
| Single-machine lock | Ledger writes use a POSIX `flock` on one host; no multi-machine writer coordination yet (`GEOPOLITICAL_INTELLIGENCE_PLAN.md` §3b). |
| Market-data staging policy | Undecided. Feed still emits `claim_type=market_data`; adapter rejects them cleanly. Dedicated non-event staging type is low priority. |
| Paid / licensed data (CRSP, etc.) | Deferred. Free-provider coverage remains the working path; spread-stress backtest stays blocked on price history. |
| First walk-forward | Protocol `PREPARED_NOT_EXECUTED`; requires explicit human authorization string. Not run. |
| Model fitting / calibration | Not performed. `break_logit_v1` is specified and tested as software only. |
| V2 (`break_hazard_v1`, fs_v2 geo candidates) | Design-only (`MODEL_ARCHITECTURE_V2.md`, `fs_v2_geo_candidates_DRAFT.json`). |

## 5. What would have to change before claiming V1 readiness

1. Historical (as-of-announcement) SIC check completed and documented.
2. Primary-source retrieval for geo events (Todd leads → reviewer retrieve → status upgrade); missing timestamps filled only from sourced pages (nulls stay null otherwise).
3. Explicit decision on market-data staging vs continued rejection.
4. Human authorization of first walk-forward **if and only if** Isaiah issues the required command; fitting still does not happen in this report or this PR.

Until then: dataset and controls only. No backtest, no trading, no performance claim.
