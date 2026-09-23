"""Append-only, point-in-time market/deal observations.

Every observation carries its own business time (`observation_timestamp`) and
provenance (`source`). Observations are never overwritten: re-recording the same
(deal_id, observation_timestamp, source) key raises rather than mutating history
(Invariant: append-only & auditable). A point-in-time read returns only what was
knowable on or before an `as_of` date (Invariant: no lookahead).

Missing fields stay missing (None) — nothing is fabricated or forward-filled.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Optional

from ..db import connect

# Columns that make up an observation, in table order (excluding ingestion_timestamp).
OBS_FIELDS = [
    "deal_id", "observation_timestamp", "source",
    "target_price", "offer_price", "unaffected_price", "acquirer_price",
    "announce_date", "expected_close_date", "resolution_date", "status",
    "deal_type", "consideration_type", "exchange_ratio", "deal_value_usd_mm",
    "sector", "geography", "sponsor", "regulatory_attrs", "financing_attrs",
    "shareholder_vote_state", "regulatory_milestones", "source_timestamp",
]

VALID_STATUS = {"announced", "pending", "closed", "broken", "withdrawn", "superseded"}
_JSON_FIELDS = ("regulatory_attrs", "financing_attrs", "regulatory_milestones")


class ObservationOverwriteError(RuntimeError):
    """Raised when an insert would overwrite an existing observation key."""


def normalize_as_of(as_of: str) -> str:
    """A bare date `as_of` means "anything knowable through the end of that day".

    Without this, string comparison would exclude an intraday observation stamped
    `2026-02-01T09:30:00` from an `as_of` of `2026-02-01`. Full timestamps pass
    through unchanged.
    """
    return as_of + "T23:59:59.999999" if len(as_of) == 10 else as_of


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

    def __post_init__(self):
        if not self.deal_id or not self.observation_timestamp or not self.source:
            raise ValueError("deal_id, observation_timestamp and source are required")
        if self.status is not None and self.status not in VALID_STATUS:
            raise ValueError(f"invalid status {self.status!r}; allowed: {sorted(VALID_STATUS)}")

    def _row(self):
        d = asdict(self)
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


def latest_as_of(deal_id: str, as_of: str, conn: sqlite3.Connection = None) -> Optional[dict]:
    """Most recent observation for a deal knowable on/before `as_of`.

    Uses observation_timestamp <= as_of only — a fact recorded later (higher
    ingestion_timestamp) but with an earlier business time is still admissible;
    a fact whose business time is after `as_of` is NOT (no lookahead).
    """
    sql = """
        SELECT * FROM deal_market_observations
        WHERE deal_id = ? AND observation_timestamp <= ?
        ORDER BY observation_timestamp DESC, ingestion_timestamp DESC
        LIMIT 1
    """

    cutoff = normalize_as_of(as_of)

    def _q(c):
        r = c.execute(sql, (deal_id, cutoff)).fetchone()
        return _decode(r) if r else None

    if conn is not None:
        return _q(conn)
    with connect() as c:
        return _q(c)


def history(deal_id: str, conn: sqlite3.Connection = None) -> list[dict]:
    """Full ordered observation history for a deal (audit view)."""
    sql = ("SELECT * FROM deal_market_observations WHERE deal_id = ? "
           "ORDER BY observation_timestamp, ingestion_timestamp")

    def _q(c):
        return [_decode(r) for r in c.execute(sql, (deal_id,))]

    if conn is not None:
        return _q(conn)
    with connect() as c:
        return _q(c)
