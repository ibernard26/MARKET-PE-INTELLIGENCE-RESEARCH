"""Point-in-time market context provider.

Replaces the raw `market_ctx` dict. Every market datum is a timestamped, sourced
record with its own known-at time; a snapshot as of T returns only values whose
valid timestamp <= T AND known_at <= T, and only if no older than a short
staleness window (market prints are never forward-filled). Each value carries
its provenance so a feature vector is auditable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .bitemporal import normalize_as_of, normalize_ts

MARKET_FIELDS = ("sp_return", "nasdaq_return", "ust10y")


class MarketDataOverwriteError(RuntimeError):
    """Raised when a (field, timestamp, source) record already exists."""


@dataclass(frozen=True)
class MarketRecord:
    """One immutable market print: what (field), when true (timestamp), value, source, when public (known_at)."""
    field: str
    timestamp: str       # valid time of the print (e.g. the session close)
    value: float
    source: str
    known_at: str        # when the print became publicly knowable


class PointInTimeMarketContext:
    """Append-only, bitemporal store of market context prints."""

    def __init__(self, max_age_days: float = 3.0):
        self.max_age_days = max_age_days
        self._records: dict[tuple, MarketRecord] = {}

    def add(self, field: str, timestamp: str, value: float, source: str,
            known_at: str) -> MarketRecord:
        """Append one print. `known_at` is required: a market print's publication
        time is never inferred."""
        if field not in MARKET_FIELDS:
            raise ValueError(f"unknown market field {field!r}; allowed: {MARKET_FIELDS}")
        if not source:
            raise ValueError("source is required")
        if not known_at:
            raise ValueError("known_at is required (never inferred)")
        if value is None:
            raise ValueError("value is required; record gaps by omission, not None")
        rec = MarketRecord(field, normalize_ts(timestamp), float(value), source,
                           normalize_ts(known_at))
        key = (rec.field, rec.timestamp, rec.source)
        if key in self._records:
            raise MarketDataOverwriteError(f"market record exists: {key} — append-only")
        self._records[key] = rec
        return rec

    def snapshot(self, as_of: str) -> dict:
        """Values knowable at `as_of`, with provenance. Missing -> None."""
        cutoff = normalize_as_of(as_of)
        out: dict = {}
        for f in MARKET_FIELDS:
            best: Optional[MarketRecord] = None
            for r in self._records.values():
                if r.field != f or r.timestamp > cutoff or r.known_at > cutoff:
                    continue
                if best is None or (r.timestamp, r.known_at) > (best.timestamp, best.known_at):
                    best = r
            if best is not None and _age_days(best.timestamp, cutoff) > self.max_age_days:
                best = None
            out[f] = best.value if best else None
            out[f + "_meta"] = ({"timestamp": best.timestamp, "source": best.source,
                                 "known_at": best.known_at} if best else None)
        return out


def _age_days(ts: str, cutoff: str) -> float:
    """Age of a print relative to the snapshot cutoff, in fractional days."""
    return (datetime.fromisoformat(cutoff[:19])
            - datetime.fromisoformat(ts[:19])).total_seconds() / 86400.0
