"""Append-only deal lifecycle events with chronology validation.

Each event is a sourced, timestamped fact about a deal's life (announcement,
regulatory milestones, votes, resolution). Events reconstruct exactly what was
knowable at any historical date. Lifecycle ordering is validated on insert:
a resolution (closing/termination) can never precede the announcement, and a
duplicate (deal, timestamp, type, source) is rejected — history is append-only.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from ..db import connect
from .observations import normalize_as_of

# Canonical event vocabulary. Extend deliberately; unknown types are rejected so
# the lifecycle stays analyzable.
EVENT_TYPES = {
    "announcement",
    "financing_secured",
    "shareholder_approval",
    "hsr_filing",
    "hsr_clearance",
    "second_request",
    "doj_challenge",
    "ftc_challenge",
    "cfius_review",
    "cfius_clearance",
    "eu_clearance",
    "uk_cma_action",
    "tender_threshold_achieved",
    "shareholder_vote",
    "amended_consideration",
    "expected_close_revision",
    "termination",
    "closing",
    "withdrawal",
}

# Events that mark a terminal resolution — must never precede the announcement.
RESOLUTION_EVENTS = {"closing", "termination", "withdrawal"}


class LifecycleError(ValueError):
    """Raised when an event would violate lifecycle ordering."""


class EventOverwriteError(RuntimeError):
    """Raised when an event key already exists (append-only)."""


def _announcement_ts(deal_id: str, c: sqlite3.Connection) -> Optional[str]:
    r = c.execute(
        "SELECT MIN(event_timestamp) FROM deal_events "
        "WHERE deal_id = ? AND event_type = 'announcement'",
        (deal_id,),
    ).fetchone()
    return r[0] if r and r[0] else None


def record_event(deal_id: str, event_timestamp: str, event_type: str, source: str,
                 source_timestamp: str = None, attributes: dict = None,
                 conn: sqlite3.Connection = None) -> int:
    """Append one lifecycle event. Validates type and ordering; returns event_id."""
    if not deal_id or not event_timestamp or not source:
        raise ValueError("deal_id, event_timestamp and source are required")
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event_type {event_type!r}; allowed: {sorted(EVENT_TYPES)}")

    attr_json = json.dumps(attributes, sort_keys=True) if attributes else None

    def _do(c) -> int:
        # ordering guard: a resolution cannot precede the announcement
        ann = _announcement_ts(deal_id, c)
        if event_type in RESOLUTION_EVENTS and ann is not None and event_timestamp < ann:
            raise LifecycleError(
                f"{event_type} at {event_timestamp} precedes announcement at {ann} "
                f"for {deal_id}")
        if ann is not None and event_type != "announcement" and event_timestamp < ann:
            raise LifecycleError(
                f"{event_type} at {event_timestamp} precedes announcement at {ann} "
                f"for {deal_id}")
        try:
            cur = c.execute(
                """INSERT INTO deal_events
                   (deal_id, event_timestamp, event_type, source, source_timestamp, attributes)
                   VALUES (?,?,?,?,?,?)""",
                (deal_id, event_timestamp, event_type, source, source_timestamp, attr_json),
            )
            return cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise EventOverwriteError(
                f"event already exists: ({deal_id}, {event_timestamp}, {event_type}, "
                f"{source}) — history is append-only") from exc

    if conn is not None:
        return _do(conn)
    with connect() as c:
        return _do(c)


def events_as_of(deal_id: str, as_of: str, conn: sqlite3.Connection = None) -> list[dict]:
    """Chronological events for a deal knowable on/before `as_of` (no lookahead)."""
    sql = ("SELECT * FROM deal_events WHERE deal_id = ? AND event_timestamp <= ? "
           "ORDER BY event_timestamp, event_id")

    cutoff = normalize_as_of(as_of)

    def _q(c):
        out = []
        for r in c.execute(sql, (deal_id, cutoff)):
            d = dict(r)
            if d.get("attributes"):
                d["attributes"] = json.loads(d["attributes"])
            out.append(d)
        return out

    if conn is not None:
        return _q(conn)
    with connect() as c:
        return _q(c)
