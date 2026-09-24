# Canonical deal and lifecycle-event identity

Separates the **economic transaction** (one `canonical_deal_id`, stable forever) from the **events** that happen during it. Research staging rows map many-to-one onto deals. Lifecycle events attach to an existing deal and **never mint a deal ID**.

```
DEAL-BWMN-BCP-2026
  ├── announcement        2026-08-10  (SEC 8-K 1.01 metadata)
  ├── go_shop_started     2026-08-10  (known 2026-09-14, conservative)
  └── go_shop_expired     2026-09-13
```

## Code and outputs
- **Code:**
  - `src/research/canonical.py`: generic identity, event and label rules.
  - `src/research/canonical_q3_2026.py`: the Q3 2026 build, including reviewed party codes and curated sourced events.
  - `scripts/build_canonical_2026q3.py`: the CLI.
- **Inputs (staging only, never modified):** `data/research/deal_register_2026Q3.csv`, `data/research/sec_filings_2026Q3.json`, and the ChatGPT staging package plus `reconciliation.csv`.
- **Outputs (`data/research/`):**

| File | Contents |
|---|---|
| `canonical_deals_2026Q3.csv` | Identity and classification only. No status, outcome, terms or notes, so nothing from after the announcement can leak into announcement-time rows. |
| `canonical_deal_events_2026Q3.csv` | One row per lifecycle event, with `valid_at` and `known_at` kept separately, provenance, and `filing_content_verified` |
| `canonical_deal_outcomes_2026Q3.csv` | Outcome candidates as of 2026-09-24. `requires_review=yes` and `model_eligible=no` on every row. |
| `canonical_unlinked_events_2026Q3.csv` | Staging events with no deal record. They are kept, but they cannot create a deal. |
| `canonical_source_map_2026Q3.csv` | Every source row and what happened to it (mapped / superseded / unlinked) |

## Identity rules
- **Deal ID:** `{DEAL|PROP|UNVR}-{TARGET}-{ACQUIRER}-{YEAR}`
  - `DEAL`: a signed definitive agreement.
  - `PROP`: a proposal, talks or a rejected bid. Never a signed deal.
  - `UNVR`: reported only, or an unsigned intent.
  - Party codes: the ticker where one exists, otherwise a reviewed code.
  - Year: the year of the agreement or proposal. When that is unknown, the year of the earliest event, flagged `id_year_from_first_event`.
- **Event ID:** `EVT-` + the first 16 hex characters of `sha1(deal | event_type | valid_at)`. When several sources report the same fact, it becomes one event. The primary source is chosen by strength of known-time basis first, then verification level. The other sources are listed in `corroborating_sources`.
- **Times:**
  - Every time keeps its own precision (year / month / day / minute / second); no time of day is invented.
  - `valid_at` may precede `known_at` (for example, a ruling published days later). It may never follow it; the build fails if it does.
  - If a disclosure is timestamped before the stated agreement date, the agreement date is capped at the disclosure date, with a note.
  - `known_at_basis=event_date_assumed` means no publication time was sourced. Those rows are flagged `known_at_review_required=yes`.

## Label rules (research candidates only; nothing is trained automatically)
| Case | Treatment |
|---|---|
| Y=0 | Only a `closing` event on a `DEAL`, with `sec_metadata_confirmed` or `press_multi` evidence |
| Y=1 | Only a `termination` or `withdrawal` event on a `DEAL`, with the same evidence standard |
| Regulatory clearance | Censored, never Y=0 |
| Injunction, block or regulator abandonment notice | Censored, never Y=1 |
| `completion_indicated` (8-K item 2.01 metadata with the filing text unread) | Censored |
| Anything on a `PROP` or `UNVR` record | Never a label |

Nothing in this layer writes to the SQLite store or feeds `break_logit_v1`.
