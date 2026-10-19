"""Deal-exposure research layer: geopolitical event -> M&A deal links.

Two link types are kept strictly apart:

  CONFIRMED_DEAL_SPECIFIC  a retrieved, trusted evidence record in the event
                           cluster names the deal (``affected_deal_ids``) and
                           the cluster is VERIFIED_PRIMARY / CORROBORATED_SECONDARY.
  SECTOR_HYPOTHESIS        a reviewer asserts that the deal's (controlled-
                           vocabulary) sector is among the event's sectors.
                           A hypothesis to be tested — not a relationship.

No link carries an effect size. ``effect_on_break_probability`` is always
"NOT_ESTIMATED": the layer never assumes an event changes P(break), and it
never reads, rewrites or re-labels deal outcomes (the manifest is opened
read-only and exposed as immutable tuples).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Optional

from .schema import ADMISSIBLE_STATUSES, SECTORS, SchemaError, parse_ts
from .verification import classify

CHANNELS = (
    "financing_risk",
    "regulatory_approval_risk",
    "sanctions_exposure",
    "energy_transport_costs",
    "currency_sovereign_risk",
    "supply_chain_disruption",
    "defense_procurement_infrastructure",
)
LINK_TYPES = ("CONFIRMED_DEAL_SPECIFIC", "SECTOR_HYPOTHESIS")
EFFECT_ON_BREAK_PROBABILITY = "NOT_ESTIMATED"

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data" / "sec_deal_manifest.json"


class IncorrectMatchError(SchemaError):
    """A proposed event->deal link is not supported by the data."""


@dataclass(frozen=True)
class DealRecord:
    deal_id: str
    target: str
    acquirer: str
    announcement_timestamp: str
    resolution_timestamp: Optional[str]
    resolution_type: Optional[str]   # read-only copy of the canonical label source


class DealUniverse:
    """Read-only view of the reviewed SEC manifest (the canonical intake)."""

    def __init__(self, deals: dict):
        self._deals = MappingProxyType(dict(deals))

    @classmethod
    def from_manifest(cls, path: Path = MANIFEST) -> "DealUniverse":
        data = json.loads(Path(path).read_text())
        deals = {}
        for d in data["deals"]:
            deals[d["deal_id"]] = DealRecord(
                d["deal_id"], d.get("target", ""), d.get("acquirer", ""),
                d.get("announcement_timestamp"), d.get("resolution_timestamp"),
                d.get("resolution_type"))
        return cls(deals)

    @property
    def deals(self):
        return self._deals

    def __contains__(self, deal_id: str) -> bool:
        return deal_id in self._deals


@dataclass(frozen=True)
class ExposureLink:
    event_id: str
    deal_id: str
    channel: str
    link_type: str
    rationale: str
    reviewer: str
    citation_evidence_id: Optional[str] = None   # required for CONFIRMED_DEAL_SPECIFIC
    deal_sector: Optional[str] = None            # required for SECTOR_HYPOTHESIS
    effect_on_break_probability: str = EFFECT_ON_BREAK_PROBABILITY

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def _window(deal: DealRecord, valid_utc: Optional[str]) -> str:
    if valid_utc is None:
        return "valid_time_unknown"
    ann = parse_ts(deal.announcement_timestamp)
    res = parse_ts(deal.resolution_timestamp) if deal.resolution_timestamp else None
    # compare at day granularity on the start of the announcement day
    if ann is not None and valid_utc[:10] < ann.raw[:10]:
        return "pre_announcement_context"
    if res is not None and valid_utc[:10] > res.raw[:10]:
        return "after_resolution"
    return "during_deal_life"


def validate_link(link: ExposureLink, ledger, universe: DealUniverse,
                  as_of: Optional[str] = None) -> dict:
    """Validate one proposed link; return it annotated with its deal window.
    Raises IncorrectMatchError for any unsupported match."""
    if link.channel not in CHANNELS:
        raise IncorrectMatchError(f"unknown channel {link.channel!r}")
    if link.link_type not in LINK_TYPES:
        raise IncorrectMatchError(f"unknown link_type {link.link_type!r}")
    if link.effect_on_break_probability != EFFECT_ON_BREAK_PROBABILITY:
        raise IncorrectMatchError("exposure links never carry a break-probability effect")
    if not (link.rationale or "").strip() or not (link.reviewer or "").strip():
        raise IncorrectMatchError("rationale and reviewer are required")
    if link.deal_id not in universe:
        raise IncorrectMatchError(f"deal {link.deal_id!r} is not in the reviewed manifest")
    recs = ledger.clusters().get(link.event_id)
    if not recs:
        raise IncorrectMatchError(f"event {link.event_id!r} is not in the evidence ledger")
    res = classify(recs, as_of=as_of, primary_registry=ledger.primary_registry)
    deal = universe.deals[link.deal_id]
    valid = max((r.valid_utc() for r in recs if r.valid_utc()), default=None)
    window = _window(deal, valid)
    if window == "after_resolution":
        raise IncorrectMatchError(
            f"event {link.event_id} is dated after {link.deal_id} resolved "
            f"({deal.resolution_timestamp}); it cannot have affected the deal")

    if link.link_type == "CONFIRMED_DEAL_SPECIFIC":
        if res.status not in ADMISSIBLE_STATUSES:
            raise IncorrectMatchError(
                f"confirmed link needs a verified/corroborated event (status {res.status})")
        cite = ledger.get(link.citation_evidence_id) if link.citation_evidence_id else None
        if cite is None or cite.event_id != link.event_id:
            raise IncorrectMatchError("confirmed link needs a citation record from this event")
        if not (cite.is_trusted_source() and cite.retrieved_by_reviewer):
            raise IncorrectMatchError("citation must be a retrieved, trusted source "
                                      "(Grok/X briefs cannot confirm a deal link)")
        if link.deal_id not in cite.affected_deal_ids:
            raise IncorrectMatchError("citation does not name this deal")
    else:
        if link.deal_sector not in SECTORS:
            raise IncorrectMatchError("sector hypothesis needs a controlled-vocabulary deal_sector")
        ev_sectors = {s for r in recs for s in r.sectors}
        if link.deal_sector not in ev_sectors:
            raise IncorrectMatchError(
                f"deal sector {link.deal_sector!r} is not among the event's sectors "
                f"{sorted(ev_sectors)}")
    out = asdict(link)
    out.update(event_status=res.status, deal_window=window,
               deal_resolution_type_readonly=deal.resolution_type)
    return out


def load_links(path: Path) -> list:
    if not Path(path).exists():
        return []
    return [ExposureLink(**json.loads(l)) for l in Path(path).read_text().splitlines()
            if l.strip()]
