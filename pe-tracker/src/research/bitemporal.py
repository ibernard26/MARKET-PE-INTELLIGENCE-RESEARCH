"""Shared bitemporal helpers.

Three distinct times per fact (see schema.sql):
  valid time  — when the fact was true / the event occurred;
  known_at    — when it became publicly knowable;
  ingestion   — when this system recorded it.

A point-in-time read as_of T admits a fact only if valid_time <= T AND
known_at <= T.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

KNOWN_AT_BASES = ("explicit", "source_timestamp", "ingestion")


def normalize_as_of(as_of: str) -> str:
    """A bare date `as_of` means "anything knowable through the end of that day"."""
    return as_of + "T23:59:59.999999" if len(as_of) == 10 else as_of


def normalize_ts(ts: str) -> str:
    """Canonical ISO form for stored timestamps: 'YYYY-MM-DDTHH:MM:SS[...]'.

    A bare date is stored as midnight (start of day) — the earliest instant it
    could be true/knowable is NOT assumed; callers stamp the real time when known.
    """
    if ts is None:
        raise ValueError("timestamp required")
    ts = ts.strip().replace(" ", "T", 1)
    if len(ts) == 10:
        ts += "T00:00:00"
    datetime.fromisoformat(ts)  # validate
    return ts


def now_iso() -> str:
    """Current UTC time as a normalized ISO timestamp (used as ingestion-time known_at)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def resolve_known_at(known_at: Optional[str], source_timestamp: Optional[str]
                     ) -> tuple[str, str]:
    """Pick known_at and its basis. Never infers an unsupported historical time:
    with neither an explicit publication time nor a source timestamp, the fact is
    known only from the moment we ingest it."""
    if known_at:
        return normalize_ts(known_at), "explicit"
    if source_timestamp:
        return normalize_ts(source_timestamp), "source_timestamp"
    return now_iso(), "ingestion"
