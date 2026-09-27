"""Longitudinal target-price ingestion architecture.

Unblocks ΔS / σ_ΔS construction for spread_stress_v1. Every print is an
append-only `deal_market_observations` row with target_price + provenance.
Nothing is fabricated: a provider that cannot source a print must omit it.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Protocol

from ..research.bitemporal import normalize_as_of, normalize_ts
from ..research.observations import Observation, ObservationOverwriteError, record_observation
from .historical import SourceRef, _prov

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = ROOT / "data" / "target_price_manifest.json"


@dataclass(frozen=True)
class TargetPricePrint:
    """One sourced target-price print for a deal."""
    deal_id: str
    observation_timestamp: str
    target_price: float
    source: SourceRef

    def validate(self) -> list[str]:
        p = []
        if not self.deal_id:
            p.append("missing deal_id")
        if self.target_price is None or not (self.target_price > 0):
            p.append("target_price must be a positive float")
        if not self.observation_timestamp:
            p.append("missing observation_timestamp")
        if self.source is None or not self.source.source_name or not self.source.source_identifier:
            p.append("missing source")
        if self.source is not None and not self.source.known_at:
            p.append("known_at missing (never inferred for historical prints)")
        return p


class TargetPriceProvider(Protocol):
    """Contract for a sourced longitudinal target-price feed."""
    name: str

    def prints(self) -> Iterable[TargetPricePrint]:
        """Yield sourced prints. Must never synthesize a missing value."""


class UnconfiguredTargetPriceProvider:
    """Fails loudly instead of inventing a price path."""
    name = "unconfigured"

    def prints(self):
        raise NotImplementedError(
            "no target-price provider configured — supply sourced prints; "
            "data is never fabricated")


class ManifestTargetPriceProvider:
    """Reviewed JSON manifest of target prints (human/vendor curated).

    Manifest schema (version 1)::

        {
          "schema_version": 1,
          "_doc": "...",
          "prints": [
            {
              "deal_id": "...",
              "observation_timestamp": "ISO8601",
              "target_price": 12.34,
              "source_name": "nyse_close|vendor|...",
              "source_identifier": "URL|URI|ticker@date",
              "known_at": "ISO8601",
              "accession_number": null,
              "source_timestamp": null
            }
          ]
        }
    """
    name = "target_price_manifest"

    def __init__(self, path: Path = DEFAULT_MANIFEST):
        self.path = Path(path)

    def prints(self) -> Iterable[TargetPricePrint]:
        if not self.path.exists():
            return
        data = json.loads(self.path.read_text())
        for row in data.get("prints") or []:
            ref = SourceRef(
                source_name=row["source_name"],
                source_identifier=row["source_identifier"],
                known_at=row["known_at"],
                accession_number=row.get("accession_number"),
                source_timestamp=row.get("source_timestamp"),
                company_identifier=row.get("company_identifier"),
            )
            yield TargetPricePrint(
                deal_id=row["deal_id"],
                observation_timestamp=row["observation_timestamp"],
                target_price=float(row["target_price"]),
                source=ref,
            )


def write_print(p: TargetPricePrint, conn: sqlite3.Connection) -> dict:
    """Write one VALIDATED print. Idempotent on (deal, ts, source)."""
    problems = p.validate()
    if problems:
        return {"accepted": False, "quarantined": True, "problems": problems}
    exists = conn.execute(
        "SELECT 1 FROM deals WHERE deal_id = ?", (p.deal_id,)).fetchone()
    if not exists:
        return {"accepted": False, "quarantined": True,
                "problems": [f"orphan deal_id {p.deal_id!r}"]}
    known = normalize_ts(p.source.known_at)
    obs = Observation(
        p.deal_id, normalize_ts(p.observation_timestamp), p.source.source_name,
        target_price=float(p.target_price),
        source_timestamp=p.source.source_timestamp,
        known_at=known,
    )
    try:
        record_observation(obs, conn=conn)
    except ObservationOverwriteError:
        return {"accepted": False, "duplicate": True, "problems": []}
    _prov(conn, "observation", p.deal_id,
          f"observation:{obs.observation_timestamp}", p.source, known,
          field="target_price")
    return {"accepted": True, "duplicate": False, "problems": []}


def ingest_target_prices(provider: TargetPriceProvider,
                         conn: sqlite3.Connection) -> dict:
    """Ingest all prints from `provider`. Quarantine invalid rows; never fill."""
    accepted = quarantined = duplicates = 0
    problems: list[dict] = []
    for p in provider.prints():
        r = write_print(p, conn)
        if r.get("accepted"):
            accepted += 1
        elif r.get("duplicate"):
            duplicates += 1
        else:
            quarantined += 1
            problems.append({"deal_id": p.deal_id, "problems": r.get("problems")})
    return {"provider": getattr(provider, "name", type(provider).__name__),
            "accepted": accepted, "quarantined": quarantined,
            "duplicates": duplicates, "problems": problems}


def count_target_prints(conn: sqlite3.Connection,
                        deal_id: Optional[str] = None) -> int:
    """Count observations that carry a non-NULL target_price."""
    if deal_id:
        return conn.execute(
            "SELECT COUNT(*) FROM deal_market_observations "
            "WHERE deal_id = ? AND target_price IS NOT NULL",
            (deal_id,)).fetchone()[0]
    return conn.execute(
        "SELECT COUNT(*) FROM deal_market_observations "
        "WHERE target_price IS NOT NULL").fetchone()[0]


def deal_print_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """deal_id → count of target_price prints (any known_at)."""
    rows = conn.execute(
        "SELECT deal_id, COUNT(*) AS n FROM deal_market_observations "
        "WHERE target_price IS NOT NULL GROUP BY deal_id").fetchall()
    return {r["deal_id"] if isinstance(r, sqlite3.Row) else r[0]:
            (r["n"] if isinstance(r, sqlite3.Row) else r[1]) for r in rows}


def ensure_empty_manifest(path: Path = DEFAULT_MANIFEST) -> Path:
    """Create an empty reviewed manifest scaffold if missing (no fabricated rows)."""
    path = Path(path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 1,
        "_doc": (
            "Reviewed longitudinal target-price prints for spread_stress_v1. "
            "Each print needs deal_id, observation_timestamp, target_price, "
            "source_name, source_identifier, known_at. Never invent prices."
        ),
        "prints": [],
    }, indent=2) + "\n")
    return path
