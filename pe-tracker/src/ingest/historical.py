"""Historical deal ingestion: record contract, validation, provenance.

A provider yields `HistoricalDealRecord`s. Each record is validated; records
missing anything the research chain needs are QUARANTINED (returned with
reasons, never written, never "completed" by guessing). Valid records are
written through the bitemporal, append-only writers:

    deal terms        -> deal_market_observations (valid = announcement time,
                         known_at = announcement known_at)
    unaffected price  -> its own observation (a market print, kept separate
                         from deal terms), valid/known at the end of its date
    announcement      -> deal_events 'announcement'
    resolution        -> deal_events 'closing' | 'termination' | 'withdrawal'
    every fact        -> record_provenance (source, identifier, accession, ...)

Ingestion never fits or refits a model. The chain is:
ingestion -> validation -> dataset-quality report -> readiness gate -> reviewed
model run (see src/model/data_quality.py).

No concrete data ships with the repo; nothing is fabricated.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict, dataclass
from typing import Iterable, Optional, Protocol

from ..research import events as ev
from ..research.bitemporal import normalize_as_of, normalize_ts
from ..research.observations import Observation, record_observation

RESOLUTION_TYPES = {"closed": "closing", "terminated": "termination",
                    "withdrawn": "withdrawal"}
CONSIDERATION = {"cash", "stock", "mixed"}

# ---------------------------------------------------------------------------
# The ONLY legal path for real historical deals into the canonical/model store:
#
#   HistoricalDealRecord.validate() -> data/sec_deal_manifest.json (reviewed,
#   filing text read) -> SECEdgarProvider -> record_provenance
#
# Research / staging material is never a source for deals, deal_events or
# deal_market_observations (the tables the training set is built from):
PROHIBITED_SOURCE_MARKERS = (
    "deal_register_2026Q3",            # Q3 research register (research-only)
    "public_mna_intelligence",         # ChatGPT / public-source staging tree
    "canonical_deal",                  # canonical_* research outputs (PR #8)
    "seed_deals",                      # illustrative ledger quotes
    "automation/", "outputs/",         # loop prompts and generated deliverables
)


class ProhibitedSourceError(RuntimeError):
    """A non-reviewed source tried to write into the canonical/model store."""


def prohibited_source(r: "HistoricalDealRecord") -> Optional[str]:
    """Return the offending marker if any source reference of `r` points at
    research/staging material, else None."""
    refs = [r.announcement_source, r.terms_source, r.unaffected_price_source,
            r.resolution_source]
    for ref in refs:
        if ref is None:
            continue
        text = " ".join(str(v) for v in (ref.source_name, ref.source_identifier) if v)
        for marker in PROHIBITED_SOURCE_MARKERS:
            if marker in text:
                return marker
    return None


def _is_on_disk_store(conn: sqlite3.Connection) -> bool:
    """True when `conn` is the real SQLite store (not a test/in-memory db)."""
    from ..config import DB_PATH
    for _, name, path in conn.execute("PRAGMA database_list"):
        if name == "main" and path:
            try:
                return os.path.samefile(path, DB_PATH)
            except FileNotFoundError:
                return False
    return False


@dataclass
class SourceRef:
    """Pointer to the exact document a fact came from."""
    source_name: str                      # e.g. 'SEC EDGAR'
    source_identifier: str                # URL / URI of the document
    source_timestamp: Optional[str] = None
    known_at: Optional[str] = None        # when the document became public
    accession_number: Optional[str] = None
    docket_reference: Optional[str] = None
    company_identifier: Optional[str] = None


@dataclass
class HistoricalDealRecord:
    """Everything a real provider must supply for one deal.

    REQUIRED (quarantined if missing): deal_id, target, acquirer,
    announcement_timestamp, announcement_source (with known_at), deal_type,
    consideration_type, offer terms matching the consideration
    (cash -> offer_price; stock -> exchange_ratio; mixed -> both),
    terms_source. If resolved: resolution_type, resolution_timestamp and
    resolution_source (with known_at).

    OPTIONAL (reported as missingness, never filled): unaffected price
    (+ date + source), deal value, sector, geography, sponsor,
    expected close, regulatory and financing attributes.
    """
    deal_id: str
    target: str
    acquirer: str
    announcement_timestamp: str
    announcement_source: SourceRef
    deal_type: str                        # strategic | LBO | take_private | ...
    consideration_type: str               # cash | stock | mixed
    terms_source: SourceRef
    offer_price: Optional[float] = None
    exchange_ratio: Optional[float] = None
    unaffected_price: Optional[float] = None
    unaffected_price_date: Optional[str] = None
    unaffected_price_source: Optional[SourceRef] = None
    deal_value_usd_mm: Optional[float] = None
    sector: Optional[str] = None
    geography: Optional[str] = None
    sponsor: Optional[str] = None         # sponsor name if PE-backed, else None
    expected_close_date: Optional[str] = None
    regulatory_attrs: Optional[dict] = None
    financing_attrs: Optional[dict] = None
    resolution_type: Optional[str] = None       # closed | terminated | withdrawn | None
    resolution_timestamp: Optional[str] = None
    resolution_source: Optional[SourceRef] = None

    def validate(self) -> list[str]:
        """Blocking problems. Empty list = admissible."""
        p = []
        for f in ("deal_id", "target", "acquirer", "announcement_timestamp",
                  "deal_type", "consideration_type"):
            if not getattr(self, f):
                p.append(f"missing {f}")
        for name in ("announcement_source", "terms_source"):
            ref = getattr(self, name)
            if ref is None or not ref.source_name or not ref.source_identifier:
                p.append(f"missing {name}")
        if self.announcement_source and not self.announcement_source.known_at:
            p.append("announcement known_at missing (never inferred)")
        if self.consideration_type and self.consideration_type not in CONSIDERATION:
            p.append(f"unknown consideration_type {self.consideration_type!r}")
        if self.consideration_type in ("cash", "mixed") and self.offer_price is None:
            p.append("offer_price required for cash/mixed consideration")
        if self.consideration_type in ("stock", "mixed") and self.exchange_ratio is None:
            p.append("exchange_ratio required for stock/mixed consideration")
        if self.unaffected_price is not None and (
                not self.unaffected_price_date or self.unaffected_price_source is None):
            p.append("unaffected_price needs its own date and source")
        if self.resolution_type is not None:
            if self.resolution_type not in RESOLUTION_TYPES:
                p.append(f"unknown resolution_type {self.resolution_type!r}")
            if not self.resolution_timestamp:
                p.append("resolution_timestamp missing")
            rs = self.resolution_source
            if rs is None or not rs.source_identifier or not rs.known_at:
                p.append("resolution source/known_at missing")
            if self.resolution_timestamp and self.announcement_timestamp and \
                    normalize_ts(self.resolution_timestamp) < normalize_ts(self.announcement_timestamp):
                p.append("resolution precedes announcement")
        return p

    def missing_optional(self) -> list[str]:
        return [f for f in ("unaffected_price", "deal_value_usd_mm", "sector", "geography",
                            "expected_close_date", "regulatory_attrs", "financing_attrs")
                if getattr(self, f) is None]


class HistoricalDealProvider(Protocol):
    """Contract a real, sourced historical-deal feed must satisfy."""
    name: str

    def records(self) -> Iterable[HistoricalDealRecord]:
        """Yield sourced records. Must never synthesize a missing value."""


class UnconfiguredProvider:
    """Placeholder that fails loudly instead of inventing history."""
    name = "unconfigured"

    def records(self):
        """Raise: an unconfigured provider must never return invented data."""
        raise NotImplementedError(
            "no historical deal provider configured — supply a sourced provider; "
            "data is never fabricated")


def _prov(conn, record_type, deal_id, record_key, ref: SourceRef, known_at, field=None):
    conn.execute(
        "INSERT INTO record_provenance (record_type, deal_id, record_key, field, source_name, "
        "source_identifier, accession_number, docket_reference, company_identifier, "
        "source_timestamp, known_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (record_type, deal_id, record_key, field, ref.source_name, ref.source_identifier,
         ref.accession_number, ref.docket_reference, ref.company_identifier,
         ref.source_timestamp, known_at))


def write_record(r: HistoricalDealRecord, provider_name: str, conn: sqlite3.Connection) -> dict:
    """Write one VALIDATED record. Idempotent for already-stored facts."""
    ann_ts = normalize_ts(r.announcement_timestamp)
    ann_known = normalize_ts(r.announcement_source.known_at)
    status = {"closed": "closed", "terminated": "broken", "withdrawn": "broken"}.get(
        r.resolution_type, "pending")
    cur = conn.execute(
        "INSERT OR IGNORE INTO deals (deal_id, announce_date, acquirer, target, sponsor, "
        "value_usd_mm, sector, geography, deal_type, resolution_date, status, offer_price, "
        "unaffected_price, expected_close_date, source_note) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (r.deal_id, ann_ts[:10], r.acquirer, r.target, r.sponsor, r.deal_value_usd_mm,
         r.sector, r.geography, r.deal_type,
         r.resolution_timestamp[:10] if r.resolution_timestamp else None, status,
         r.offer_price, r.unaffected_price, r.expected_close_date,
         f"{provider_name}:{r.terms_source.source_identifier}"))
    wrote = {"deal": cur.rowcount == 1, "observations": 0, "events": 0, "duplicates": 0}
    if wrote["deal"]:
        _prov(conn, "deal", r.deal_id, "deal", r.terms_source, ann_known)

    terms = Observation(
        r.deal_id, ann_ts, r.terms_source.source_name,
        offer_price=r.offer_price, exchange_ratio=r.exchange_ratio,
        consideration_type=r.consideration_type, deal_type=r.deal_type,
        deal_value_usd_mm=r.deal_value_usd_mm, sector=r.sector, geography=r.geography,
        sponsor=r.sponsor, expected_close_date=r.expected_close_date,
        regulatory_attrs=r.regulatory_attrs, financing_attrs=r.financing_attrs,
        announce_date=ann_ts[:10], source_timestamp=r.terms_source.source_timestamp,
        known_at=r.terms_source.known_at or ann_known)
    _obs(conn, terms, r, r.terms_source, wrote, "terms")

    if r.unaffected_price is not None:
        ref = r.unaffected_price_source
        o = Observation(r.deal_id, normalize_as_of(r.unaffected_price_date[:10]),
                        ref.source_name, unaffected_price=r.unaffected_price,
                        source_timestamp=ref.source_timestamp,
                        known_at=ref.known_at or normalize_as_of(r.unaffected_price_date[:10]))
        _obs(conn, o, r, ref, wrote, "unaffected_price")

    _event(conn, r.deal_id, ann_ts, "announcement", r.announcement_source, wrote)
    if r.resolution_type:
        _event(conn, r.deal_id, normalize_ts(r.resolution_timestamp),
               RESOLUTION_TYPES[r.resolution_type], r.resolution_source, wrote)
    return wrote


def _obs(conn, o: Observation, r, ref: SourceRef, wrote, fld):
    from ..research.observations import ObservationOverwriteError
    try:
        record_observation(o, conn=conn)
    except ObservationOverwriteError:
        wrote["duplicates"] += 1
        return
    wrote["observations"] += 1
    _prov(conn, "observation", r.deal_id, f"observation:{o.observation_timestamp}",
          ref, o.known_at, field=fld)


def _event(conn, deal_id, ts, etype, ref: SourceRef, wrote):
    try:
        ev.record_event(deal_id, ts, etype, ref.source_name, conn=conn,
                        source_timestamp=ref.source_timestamp,
                        known_at=normalize_ts(ref.known_at),
                        attributes={"source_identifier": ref.source_identifier,
                                    "accession_number": ref.accession_number})
    except ev.EventOverwriteError:
        wrote["duplicates"] += 1
        return
    wrote["events"] += 1
    _prov(conn, "event", deal_id, f"event:{etype}:{ts}", ref, normalize_ts(ref.known_at))


def ingest(provider: HistoricalDealProvider, conn: sqlite3.Connection) -> dict:
    """Validate and write a provider's records. Returns counts plus the
    quarantined records and their reasons. Never triggers model fitting.

    The on-disk store accepts records ONLY from the reviewed SEC path
    (SECEdgarProvider over data/sec_deal_manifest.json). Any record citing a
    research/staging source is quarantined on every connection."""
    from .providers.sec_edgar import SECEdgarProvider   # lazy: providers import this module
    if _is_on_disk_store(conn) and not isinstance(provider, SECEdgarProvider):
        raise ProhibitedSourceError(
            f"provider {getattr(provider, 'name', provider)!r} may not write to the canonical "
            f"store; the only legal path is the reviewed sec_deal_manifest.json via "
            f"SECEdgarProvider")
    written, quarantined = [], []
    for r in provider.records():
        marker = prohibited_source(r)
        if marker:
            quarantined.append({"deal_id": r.deal_id,
                                "problems": [f"prohibited source ({marker}): research/staging "
                                             f"data never enters the canonical store"]})
            continue
        problems = r.validate()
        if problems:
            quarantined.append({"deal_id": r.deal_id, "problems": problems})
            continue
        res = write_record(r, provider.name, conn)
        written.append({"deal_id": r.deal_id, "missing_optional": r.missing_optional(), **res})
    return {"provider": provider.name, "written": written, "quarantined": quarantined,
            "n_written": len(written), "n_quarantined": len(quarantined)}


def as_dict(r: HistoricalDealRecord) -> dict:
    return asdict(r)
