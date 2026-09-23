"""Historical deal ingestion — provider interface only.

No concrete provider ships with v1: we do not have a licensed, point-in-time
source of historical merger outcomes wired in, and records are NEVER fabricated
to fill the gap. A provider must return fully sourced records; `ingest` writes
them through the bitemporal, append-only writers, which require a source and
derive known_at from an explicit publication time (else source timestamp, else
ingestion time).
"""
from __future__ import annotations

import sqlite3
from typing import Iterable, Protocol

from ..research import events as ev
from ..research.observations import Observation, record_observation


class HistoricalDealProvider(Protocol):
    name: str

    def deals(self) -> Iterable[dict]:
        """dicts with deal_id, announce_date (+ optional ledger fields), source."""

    def observations(self) -> Iterable[Observation]:
        ...

    def events(self) -> Iterable[dict]:
        """dicts accepted by events.record_event (must include source)."""


class UnconfiguredProvider:
    """Placeholder that fails loudly instead of inventing history."""
    name = "unconfigured"

    def _fail(self):
        raise NotImplementedError(
            "no historical deal provider configured — supply a sourced provider; "
            "data is never fabricated")

    def deals(self):
        self._fail()

    def observations(self):
        self._fail()

    def events(self):
        self._fail()


def ingest(provider: HistoricalDealProvider, conn: sqlite3.Connection) -> dict:
    n_d = n_o = n_e = 0
    for d in provider.deals():
        if not d.get("source"):
            raise ValueError(f"deal {d.get('deal_id')} has no source")
        conn.execute("INSERT OR IGNORE INTO deals (deal_id, announce_date, status, "
                     "source_note) VALUES (?,?,?,?)",
                     (d["deal_id"], d["announce_date"], d.get("status", "pending"),
                      f"{provider.name}:{d['source']}"))
        n_d += 1
    for o in provider.observations():
        record_observation(o, conn=conn)
        n_o += 1
    for e in provider.events():
        if not e.get("source"):
            raise ValueError("event has no source")
        ev.record_event(conn=conn, **e)
        n_e += 1
    return {"provider": provider.name, "deals": n_d, "observations": n_o, "events": n_e}
