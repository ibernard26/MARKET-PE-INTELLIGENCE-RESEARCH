# Bitemporal point-in-time semantics (research layer)

## Three times per fact
| Time | Column | Meaning |
|---|---|---|
| Valid time | `observation_timestamp` / `event_timestamp` | when the fact was true / the event occurred |
| Known-at | `known_at` (+ `known_at_basis`) | when the information became publicly knowable |
| Ingestion | `ingestion_timestamp` | when this system recorded it |

`known_at` resolution (`src/research/bitemporal.py::resolve_known_at`):
1. explicit, reliable publication timestamp passed by the caller → `explicit`
2. else `source_timestamp` → `source_timestamp`
3. else ingestion time (live capture) → `ingestion`

A historical known time is **never inferred**. An unsupported backfill is therefore
known only from its ingestion time and is invisible to every past `as_of` read.

## Read rule
Every historical read as of T admits a row only if **valid_time <= T AND known_at <= T**:
`observations.visible_as_of / latest_as_of / state_as_of`, `events.events_as_of`,
`features.build_features_for_deal`, `market_context.PointInTimeMarketContext.snapshot`.

## Sparse state reconstruction (`state_as_of`)
* **Deal terms** (offer consideration, expected close, exchange ratio, sponsor,
  consideration type, regulatory/financing attributes, status …) persist until a
  later sourced row supersedes them. A later `None` means "not reported", not "cleared".
  Each term carries its source/timestamp/known_at in `state_sources`.
* **Market prints** (`target_price`, `acquirer_price`) are **not forward-filled**:
  the latest visible print is used only if no older than `max_print_age_days`
  (default 3, covering a weekend) and is exposed with `<field>_timestamp` and
  `<field>_source`; otherwise None.

## Market context
Raw `market_ctx` dicts are rejected (`TypeError`). `PointInTimeMarketContext`
holds append-only records `(field, timestamp, value, source, known_at)`;
`known_at` is mandatory.

## Consideration types
`features.offer_value`: cash → offer_price; stock → exchange_ratio × acquirer_price;
mixed → cash component + ratio × acquirer price; unknown → None (never a silent cash formula).
The backtester is **scoped to cash** and raises `UnsupportedConsiderationError` otherwise.

## Break exits (backtester `bt_v2`)
1. actual sourced post-break price (`break_exit_price` + source + timestamp ≥ break date) → `realized_pnl`
2. modeled fallback to unaffected price (config flag) → `modeled_break_pnl`, never realized
3. otherwise `unresolved_exit` → no P&L

## Integrity (DB layer, SQLite)
* `deal_id REFERENCES deals(deal_id)` plus a `BEFORE INSERT` trigger, so orphans are
  rejected even when `PRAGMA foreign_keys` is off.
* `BEFORE UPDATE` / `BEFORE DELETE` triggers abort: append-only is enforced by the
  database, not only application code. (A user with raw file access can still drop
  triggers; git + backups remain the audit backstop.)
* Legacy pre-bitemporal tables are recreated only if empty; non-empty ones are
  refused rather than back-filled with invented known times.

## Known limitation
`src/arb/merger.py::rank_live_deals` and `src/compute/metrics.py` read the live
`deals` ledger (a current-state table, not bitemporal). They are live helpers,
not historical research readers; `metrics.resolved_deals` gates on
`resolution_date <= as_of` only.
