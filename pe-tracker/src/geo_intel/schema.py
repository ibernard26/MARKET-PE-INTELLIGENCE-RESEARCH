"""Evidence-staging schema for geopolitical intelligence.

One EvidenceRecord = one source's statement about one (candidate) event.
Several records about the same real-world event share an ``event_key`` and are
grouped into an event cluster whose verification status is DERIVED
(verification.py) — never copied from the source.

Timestamps
----------
Every timestamp is optional and stays ``None`` when it is missing or
uncertain. Accepted inputs:

  * ``YYYY-MM-DD``                    day precision
  * ``YYYY-MM-DDTHH:MM[:SS[.f]]Z``    / ``±HH:MM`` offset — second precision

A time of day WITHOUT a UTC offset is rejected (ambiguous zone). Comparisons
use the LATEST instant consistent with the stated precision (a bare date
counts as 23:59:59.999999 that day, the repo-wide ``normalize_as_of``
convention), so precision loss can only make information look *later*, never
earlier.

``known_at`` (when the fact became publicly knowable) is resolved without
inference:
  explicit known_at  ->  publication_timestamp  ->  first_observed_timestamp
  ->  None (never admissible).
An explicit known_at earlier than the publication timestamp is rejected.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

SCHEMA_VERSION = "geo_evidence_v1"

# ------------------------------------------------------------ vocabularies
EVENT_CATEGORIES = (
    "sanctions",                       # US / EU / UK / other designations, waivers, delistings
    "russia_ukraine_energy_infrastructure",
    "iran_us_diplomacy",
    "strait_of_hormuz_maritime",
    "energy_supply_interruption",      # discrete supply events; PRICE SERIES live in FRED store
    "rates_and_acquisition_financing", # policy / financing-market events; RATE SERIES live in FRED store
    "government_procurement_regulatory",
    "sector_geopolitical_exposure",
)

VERIFICATION_STATUSES = (
    "VERIFIED_PRIMARY",
    "CORROBORATED_SECONDARY",
    "ATTRIBUTED_CLAIM",
    "UNCONFIRMED",
    "DISPUTED",
    "RETRACTED",
)
# Only these may ever be offered as (research) feature candidates.
ADMISSIBLE_STATUSES = ("VERIFIED_PRIMARY", "CORROBORATED_SECONDARY")

SOURCE_TYPES = (
    "primary_official",    # the issuing authority's own publication (OFAC notice, SEC filing, …)
    "reputable_secondary", # established news organisation / wire
    "ai_brief",            # Grok / X brief or any LLM summary — UNTRUSTED
    "social_post",         # a post on X or other social platform — UNTRUSTED
    "other",
)
UNTRUSTED_SOURCE_TYPES = ("ai_brief", "social_post", "other")

# What the statement asserts. Only "occurred" can describe a completed event.
CLAIM_TYPES = (
    "occurred",              # the event has happened (designation issued, strike occurred)
    "attributed_statement",  # "X said that …" — a claim attributed to a named party
    "scheduled",             # announced for the future (effective date, planned talks)
    "prediction",            # forecast / analyst expectation
    "rumor",                 # unattributed / sources-say reporting
)

STANCES = ("supports", "contradicts")
REVISION_TYPES = ("correction", "update", "retraction")

# Default primary-source domain registry. A record may claim
# source_type='primary_official' only if its URL host is (a subdomain of) one
# of these. Extending it is a reviewed change.
PRIMARY_DOMAINS = {
    "sec.gov": "US SEC (EDGAR)",
    "treasury.gov": "US Treasury (incl. OFAC)",
    "whitehouse.gov": "The White House",
    "federalregister.gov": "US Federal Register",
    "state.gov": "US Department of State",
    "commerce.gov": "US Department of Commerce",
    "bis.gov": "US Bureau of Industry and Security",
    "bis.doc.gov": "US Bureau of Industry and Security",
    "defense.gov": "US Department of Defense",
    "energy.gov": "US Department of Energy",
    "eia.gov": "US Energy Information Administration",
    "federalreserve.gov": "Board of Governors of the Federal Reserve",
    "ftc.gov": "US Federal Trade Commission",
    "justice.gov": "US Department of Justice",
    "sam.gov": "US System for Award Management",
    "europa.eu": "European Union institutions",
    "gov.uk": "UK Government (incl. OFSI, CMA)",
    "legislation.gov.uk": "UK legislation",
    "un.org": "United Nations",
    "iaea.org": "International Atomic Energy Agency",
    "imo.org": "International Maritime Organization",
}

# Controlled sector vocabulary for exposure research (no free text).
SECTORS = (
    "energy_upstream", "energy_midstream", "energy_refining", "utilities_power",
    "shipping_maritime", "logistics_transport", "airlines",
    "defense_aerospace", "government_services", "industrials", "chemicals",
    "metals_mining", "semiconductors", "technology_software", "telecom_media",
    "banking", "insurance", "asset_management", "fintech_payments",
    "healthcare", "biopharma", "consumer", "real_estate", "agriculture_food",
)

ISO_COUNTRY = re.compile(r"^[A-Z]{2}$")
REGION_CODES = ("EU", "GCC", "GLOBAL", "MENA", "EMEA", "APAC", "LATAM")


class SchemaError(ValueError):
    """A record violates the evidence-staging contract."""


class TimestampError(SchemaError):
    """A timestamp is malformed or zone-ambiguous."""


# ------------------------------------------------------------ timestamps
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class TimePoint:
    raw: str
    precision: str   # "day" | "second"
    latest_utc: str  # latest UTC instant consistent with `raw` (naive ISO, µs)

    def to_dict(self) -> dict:
        return {"raw": self.raw, "precision": self.precision, "latest_utc": self.latest_utc}


def parse_ts(value: Optional[str]) -> Optional[TimePoint]:
    """Parse an optional timestamp. ``None``/empty stays ``None`` (missing is
    preserved, never defaulted)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ("n/d", "nd", "unknown", "none", "null"):
        return None
    if _DATE_RE.match(s):
        datetime.strptime(s, "%Y-%m-%d")  # validates calendar date
        return TimePoint(s, "day", s + "T23:59:59.999999")
    t = s.replace(" ", "T", 1)
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError as exc:
        raise TimestampError(f"unparseable timestamp {value!r}") from exc
    if dt.tzinfo is None:
        raise TimestampError(
            f"timestamp {value!r} has a time of day but no UTC offset; supply an "
            "offset (or 'Z') or record the date only — the zone is never guessed")
    utc = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return TimePoint(s, "second", utc.strftime("%Y-%m-%dT%H:%M:%S.%f"))


def as_of_cutoff(prediction_time: str) -> str:
    """Normalize a prediction time. A bare date means end of that day (UTC);
    a time of day must carry an offset."""
    tp = parse_ts(prediction_time)
    if tp is None:
        raise TimestampError("prediction_time is required")
    return tp.latest_utc


# ------------------------------------------------------------ provenance
def url_host(url: str) -> str:
    p = urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.hostname:
        raise SchemaError(f"source_url must be an absolute http(s) URL: {url!r}")
    return p.hostname.lower()


def primary_authority(url: str, registry: Optional[dict] = None) -> Optional[str]:
    """Return the registered authority for a URL host, else None."""
    host = url_host(url)
    reg = PRIMARY_DOMAINS if registry is None else registry
    for dom, name in reg.items():
        if host == dom or host.endswith("." + dom):
            return name
    return None


def _sha(*parts) -> str:
    return hashlib.sha1("|".join("" if p is None else str(p) for p in parts)
                        .encode("utf-8")).hexdigest()


def event_id_for(category: str, event_key: str) -> str:
    """Deterministic cluster id: the same (category, reviewed event_key) is
    always the same event, whichever source reported it first."""
    return "GEO-" + _sha(category, event_key.strip().lower())[:12].upper()


# ------------------------------------------------------------ record
@dataclass(frozen=True)
class EvidenceRecord:
    """One source's statement about one candidate geopolitical event."""

    event_key: str                  # reviewed cluster key, e.g. "ofac-sdn-2026-xx-yy-designation"
    category: str
    original_statement: str         # verbatim (or verbatim excerpt) of what the source said
    reporting_entity: str           # who made the statement (agency, named official, outlet)
    source_url: str
    publisher: str
    source_type: str
    claim_type: str
    stance: str = "supports"
    publication_timestamp: Optional[str] = None
    event_valid_timestamp: Optional[str] = None   # when the event occurred / takes effect
    first_observed_timestamp: Optional[str] = None  # when THIS system first saw the source
    known_at: Optional[str] = None                 # explicit public-knowability time, if any
    retrieved_by_reviewer: bool = False            # the URL was actually fetched and read
    geographies: tuple = ()
    sectors: tuple = ()
    affected_deal_ids: tuple = ()                  # candidate links only — see exposure.py
    affected_company_ids: tuple = ()
    syndicated_from: Optional[str] = None          # e.g. wire story re-run by another outlet
    revises_evidence_id: Optional[str] = None
    revision_type: Optional[str] = None
    claimed_status_by_source: Optional[str] = None  # what the input asserted; NEVER trusted
    ingested_via: str = "manual"                    # "manual" | "grok_brief" | "fixture"
    notes: str = ""

    # derived (filled by validate())
    event_id: str = ""
    evidence_id: str = ""
    known_at_basis: str = ""
    schema_version: str = SCHEMA_VERSION

    # -------------------------------------------------------------- checks
    def validate(self, primary_registry: Optional[dict] = None) -> "EvidenceRecord":
        """Return a validated copy with derived ids and known_at basis.
        Raises SchemaError on any contract violation."""
        errs = []
        if not (self.event_key or "").strip():
            errs.append("event_key required")
        if self.category not in EVENT_CATEGORIES:
            errs.append(f"unknown category {self.category!r}")
        if not (self.original_statement or "").strip():
            errs.append("original_statement required")
        if not (self.reporting_entity or "").strip():
            errs.append("reporting_entity required")
        if not (self.publisher or "").strip():
            errs.append("publisher required")
        if self.source_type not in SOURCE_TYPES:
            errs.append(f"unknown source_type {self.source_type!r}")
        if self.claim_type not in CLAIM_TYPES:
            errs.append(f"unknown claim_type {self.claim_type!r}")
        if self.stance not in STANCES:
            errs.append(f"unknown stance {self.stance!r}")
        if self.claimed_status_by_source is not None and \
                self.claimed_status_by_source not in VERIFICATION_STATUSES:
            errs.append(f"unknown claimed_status_by_source {self.claimed_status_by_source!r}")
        if (self.revises_evidence_id is None) != (self.revision_type is None):
            errs.append("revises_evidence_id and revision_type go together")
        if self.revision_type is not None and self.revision_type not in REVISION_TYPES:
            errs.append(f"unknown revision_type {self.revision_type!r}")
        for s in self.sectors:
            if s not in SECTORS:
                errs.append(f"unknown sector {s!r} (controlled vocabulary)")
        for g in self.geographies:
            if not (ISO_COUNTRY.match(g) or g in REGION_CODES):
                errs.append(f"geography {g!r} must be ISO-3166 alpha-2 or one of {REGION_CODES}")
        try:
            url_host(self.source_url)
        except SchemaError as exc:
            errs.append(str(exc))
        if self.ingested_via == "grok_brief" and self.source_type not in UNTRUSTED_SOURCE_TYPES:
            errs.append("a Grok/X brief must be staged as ai_brief/social_post, never as "
                        "primary or reputable secondary — cite the underlying source as "
                        "its own record once it has been retrieved")
        if self.source_type == "primary_official" and not errs:
            if primary_authority(self.source_url, primary_registry) is None:
                errs.append(f"primary_official URL host {url_host(self.source_url)!r} is not "
                            "in the primary-source registry")
        # timestamps
        tps = {}
        for name in ("publication_timestamp", "event_valid_timestamp",
                     "first_observed_timestamp", "known_at"):
            try:
                tps[name] = parse_ts(getattr(self, name))
            except TimestampError as exc:
                errs.append(f"{name}: {exc}")
        if errs:
            raise SchemaError("; ".join(errs))

        pub, obs, kat = (tps["publication_timestamp"], tps["first_observed_timestamp"],
                         tps["known_at"])
        if kat is not None and pub is not None and kat.latest_utc < pub.latest_utc:
            raise SchemaError("known_at precedes publication_timestamp — would infer "
                              "public knowledge before publication")
        if kat is not None:
            basis = "explicit"
        elif pub is not None:
            basis = "publication_timestamp"
        elif obs is not None:
            basis = "first_observed_timestamp"
        else:
            basis = "missing"

        eid = event_id_for(self.category, self.event_key)
        vid = "EVD-" + _sha(eid, self.source_url, self.original_statement.strip(),
                            self.publication_timestamp, self.revises_evidence_id,
                            self.stance)[:16].upper()
        d = asdict(self)
        d.update(event_id=eid, evidence_id=vid, known_at_basis=basis,
                 geographies=tuple(self.geographies), sectors=tuple(self.sectors),
                 affected_deal_ids=tuple(self.affected_deal_ids),
                 affected_company_ids=tuple(self.affected_company_ids))
        return EvidenceRecord(**d)

    # -------------------------------------------------------------- derived times
    def known_at_utc(self) -> Optional[str]:
        """Effective known_at (latest consistent instant), or None if missing."""
        for name in ("known_at", "publication_timestamp", "first_observed_timestamp"):
            tp = parse_ts(getattr(self, name))
            if tp is not None:
                return tp.latest_utc
        return None

    def valid_utc(self) -> Optional[str]:
        tp = parse_ts(self.event_valid_timestamp)
        return tp.latest_utc if tp else None

    def is_trusted_source(self) -> bool:
        return self.source_type not in UNTRUSTED_SOURCE_TYPES

    def to_json(self) -> str:
        d = asdict(self)
        for k in ("geographies", "sectors", "affected_deal_ids", "affected_company_ids"):
            d[k] = list(d[k])
        return json.dumps(d, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict) -> "EvidenceRecord":
        d = dict(d)
        for k in ("geographies", "sectors", "affected_deal_ids", "affected_company_ids"):
            d[k] = tuple(d.get(k) or ())
        allowed = set(EvidenceRecord.__dataclass_fields__)
        unknown = set(d) - allowed
        if unknown:
            raise SchemaError(f"unknown fields {sorted(unknown)}")
        return EvidenceRecord(**d)
