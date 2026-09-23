"""Append-only, bitemporal market/deal observations.

Every observation carries valid time (`observation_timestamp`), a publication
time (`known_at`) and provenance (`source`). Observations are never overwritten:
re-recording the same (deal_id, observation_timestamp, source) key raises, and
the DB rejects UPDATE/DELETE (append-only & auditable). A point-in-time read as
of T admits only rows with observation_timestamp <= T AND known_at <= T.

`state_as_of` reconstructs a deal's knowable state from sparse rows: deal TERMS
persist until a later sourced amendment supersedes them; market PRINTS are never
forward-filled beyond a short, explicit staleness window.

Missing fields stay missing (None) — nothing is fabricated.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from dataclasses import asdict, dataclass, field
from typing import Optional

from ..db import connect
from .bitemporal import normalize_as_of, normalize_ts, resolve_known_at

# Columns that make up an observation, in table order (excluding ingestion_timestamp).
OBS_FIELDS = [
    "deal_id", "observation_timestamp", "source",
    "target_price", "offer_price", "unaffected_price", "acquirer_price",
    "announce_date", "expected_close_date", "resolution_date", "status",
    "deal_type", "consideration_type", "exchange_ratio", "deal_value_usd_mm",
    "sector", "geography", "sponsor", "regulatory_attrs", "financing_attrs",
    "shareholder_vote_state", "regulatory_milestones", "source_timestamp",
    "known_at", "known_at_basis",
]

# Deal terms: persist until superseded by a later sourced amendment.
STATE_FIELDS = [
    "offer_price", "unaffected_price", "announce_date", "expected_close_date",
    "resolution_date", "status", "deal_type", "consideration_type",
    "exchange_ratio", "deal_value_usd_mm", "sector", "geography", "sponsor",
    "regulatory_attrs", "financing_attrs", "shareholder_vote_state",
    "regulatory_milestones",
]
# Market prints: valid only near their own timestamp; never forward-filled.
PRINT_FIELDS = ["target_price", "acquirer_price"]
DEFAULT_MAX_PRINT_AGE_DAYS = 3   # covers a weekend; older prints read as None

VALID_STATUS = {"announced", "pending", "closed", "broken", "withdrawn", "superseded"}
_JSON_FIELDS = ("regulatory_attrs", "financing_attrs", "regulatory_milestones")


class ObservationOverwriteError(RuntimeError):
    """Raised when an insert would overwrite an existing observation key."""


@dataclass
class Observation:
    deal_id: str
    observation_timestamp: str
    source: str
    target_price: Optional[float] = None
    offer_price: Optional[float] = None
    unaffected_price: Optional[float] = None
    acquirer_price: Optional[float] = None
    announce_date: Optional[str] = None
    expected_close_date: Optional[str] = None
    resolution_date: Optional[str] = None
    status: Optional[str] = None
    deal_type: Optional[str] = None
    consideration_type: Optional[str] = None
    exchange_ratio: Optional[float] = None
    deal_value_usd_mm: Optional[float] = None
    sector: Optional[str] = None
    geography: Optional[str] = None
    sponsor: Optional[str] = None
    regulatory_attrs: Optional[dict] = None
    financing_attrs: Optional[dict] = None
    shareholder_vote_state: Optional[str] = None
    regulatory_milestones: Optional[dict] = None
    source_timestamp: Optional[str] = None
    known_at: Optional[str] = None       # explicit, reliable publication time

    def __post_init__(self):
        if not self.deal_id or not self.observation_timestamp or not self.source:
            raise ValueError("deal_id, observation_timestamp and source are required")
        self.observation_timestamp = normalize_ts(self.observation_timestamp)
        if self.status is not None and self.status not in VALID_STATUS:
            raise ValueError(f"invalid status {self.status!r}; allowed: {sorted(VALID_STATUS)}")

    def _row(self):
        d = asdict(self)
        d["known_at"], d["known_at_basis"] = resolve_known_at(self.known_at,
                                                              self.source_timestamp)
        for k in _JSON_FIELDS:
            if d[k] is not None:
                d[k] = json.dumps(d[k], sort_keys=True)
        return [d[k] for k in OBS_FIELDS]


def record_observation(obs: Observation, conn: sqlite3.Connection = None) -> None:
    """Append one observation. Raises ObservationOverwriteError on a key clash —
    history is never silently mutated."""
    placeholders = ",".join("?" for _ in OBS_FIELDS)
    sql = f"INSERT INTO deal_market_observations ({','.join(OBS_FIELDS)}) VALUES ({placeholders})"

    def _do(c):
        try:
            c.execute(sql, obs._row())
        except sqlite3.IntegrityError as exc:
            if "orphan" in str(exc) or "FOREIGN KEY" in str(exc):
                raise
            raise ObservationOverwriteError(
                f"observation already exists for ({obs.deal_id}, "
                f"{obs.observation_timestamp}, {obs.source}) — history is append-only"
            ) from exc

    if conn is not None:
        _do(conn)
    else:
        with connect() as c:
            _do(c)


def record_many(observations, conn: sqlite3.Connection = None) -> int:
    n = 0
    if conn is not None:
        for o in observations:
            record_observation(o, conn=conn)
            n += 1
        return n
    with connect() as c:
        for o in observations:
            record_observation(o, conn=c)
            n += 1
    return n


def _decode(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in _JSON_FIELDS:
        if d.get(k):
            d[k] = json.loads(d[k])
    return d


_VISIBLE = ("deal_id = ? AND observation_timestamp <= ? AND known_at <= ?")


def visible_as_of(deal_id: str, as_of: str, conn: sqlite3.Connection = None) -> list[dict]:
    """All observations knowable at `as_of` (valid <= T AND known_at <= T),
    oldest first by valid time then publication time."""
    sql = (f"SELECT * FROM deal_market_observations WHERE {_VISIBLE} "
           "ORDER BY observation_timestamp, known_at, ingestion_timestamp")
    cutoff = normalize_as_of(as_of)

    def _q(c):
        return [_decode(r) for r in c.execute(sql, (deal_id, cutoff, cutoff))]

    if conn is not None:
        return _q(conn)
    with connect() as c:
        return _q(c)


def latest_as_of(deal_id: str, as_of: str, conn: sqlite3.Connection = None) -> Optional[dict]:
    """The single most recent observation ROW knowable at `as_of` (audit view).

    Bitemporal: requires observation_timestamp <= as_of AND known_at <= as_of.
    NOTE: a row is sparse — for the reconstructed deal state use `state_as_of`.
    """
    rows = visible_as_of(deal_id, as_of, conn=conn)
    return rows[-1] if rows else None


def _age_days(ts: str, as_of: str) -> float:
    return (datetime.fromisoformat(normalize_as_of(as_of)[:19])
            - datetime.fromisoformat(ts[:19])).total_seconds() / 86400.0


def reconstruct_state(rows: list[dict], as_of: str,
                      max_print_age_days: float = DEFAULT_MAX_PRINT_AGE_DAYS
                      ) -> Optional[dict]:
    """Pure reconstruction from already-visible rows (ordered oldest first).

    * STATE_FIELDS: latest non-null value wins (a term persists until a later
      sourced row supersedes it). None in a later row means "not reported", not
      "cleared".
    * PRINT_FIELDS: the latest non-null print, only if it is no older than
      `max_print_age_days`; otherwise None. Each carries `<field>_timestamp`
      and `<field>_source` so staleness is auditable.
    """
    if not rows:
        return None
    st: dict = {"deal_id": rows[-1]["deal_id"], "as_of": as_of,
                "state_sources": {}}
    for f in STATE_FIELDS:
        st[f] = None
        for r in reversed(rows):
            if r.get(f) is not None:
                st[f] = r[f]
                st["state_sources"][f] = {"source": r["source"],
                                          "observation_timestamp": r["observation_timestamp"],
                                          "known_at": r["known_at"]}
                break
    for f in PRINT_FIELDS:
        st[f] = st[f + "_timestamp"] = st[f + "_source"] = None
        for r in reversed(rows):
            if r.get(f) is not None:
                if _age_days(r["observation_timestamp"], as_of) <= max_print_age_days:
                    st[f] = r[f]
                    st[f + "_timestamp"] = r["observation_timestamp"]
                    st[f + "_source"] = r["source"]
                break
    return st


def state_as_of(deal_id: str, as_of: str, conn: sqlite3.Connection = None,
                max_print_age_days: float = DEFAULT_MAX_PRINT_AGE_DAYS) -> Optional[dict]:
    """Reconstructed point-in-time deal state knowable at `as_of`."""
    return reconstruct_state(visible_as_of(deal_id, as_of, conn=conn), as_of,
                             max_print_age_days=max_print_age_days)


def history(deal_id: str, conn: sqlite3.Connection = None) -> list[dict]:
    """Full ordered observation history for a deal (audit view)."""
    sql = ("SELECT * FROM deal_market_observations WHERE deal_id = ? "
           "ORDER BY observation_timestamp, known_at, ingestion_timestamp")

    def _q(c):
        return [_decode(r) for r in c.execute(sql, (deal_id,))]

    if conn is not None:
        return _q(conn)
    with connect() as c:
        return _q(c)
