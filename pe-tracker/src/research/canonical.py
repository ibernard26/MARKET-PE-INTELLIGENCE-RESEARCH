"""Canonical deal / lifecycle-event identity.

Separates the ECONOMIC TRANSACTION (one canonical_deal_id, forever) from the
EVENTS that happen during it (announcement, go-shop, regulatory steps, votes,
resolution). Research staging rows are many-to-one onto deals; lifecycle events
never mint deal IDs.

Identity rules
--------------
canonical_deal_id = {PREFIX}-{TARGET}-{ACQUIRER}-{YEAR}
  PREFIX  DEAL  signed definitive agreement
          PROP  proposal / talks / rejected bid (never a signed deal)
          UNVR  reported-only or unsigned intent (not verified as signed)
  TARGET / ACQUIRER  ticker where one exists, else a reviewed party code
  YEAR    year of the agreement (or proposal); when unknown, year of the
          earliest dated event, recorded as id_basis=first_event_year
event_id = EVT-sha1(canonical_deal_id | event_type | valid_at)[:16]
  The same fact reported by several sources is ONE event: the best-evidenced
  source is primary, the rest are kept as corroborating provenance.

Label rules (research candidates only; never auto-trained)
----------------------------------------------------------
  Y=0 candidate  only a `closing` event on a DEAL, from a verified source
  Y=1 candidate  only a `termination`/`withdrawal` event on a DEAL, verified
  everything else is censored - including regulatory clearance (not Y=0),
  injunctions/blocks (not Y=1), completion merely indicated by filing metadata,
  and anything on PROP / UNVR records (proposals are never labels).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

# ----------------------------------------------------------------- vocabulary
EVENT_TYPES = {
    # transaction formation
    "announcement", "proposal_submitted", "talks_reported", "reported_announcement",
    "proposal_rejected",
    # process milestones
    "go_shop_started", "go_shop_expired", "offer_document_published", "board_recommendation",
    "shareholder_vote",
    # regulatory (never labels)
    "regulatory_invitation_to_comment", "regulatory_phase1_launched", "regulatory_clearance",
    "regulatory_case_closed", "regulatory_early_termination", "regulatory_consent_order",
    "regulatory_consent_order_proposed", "regulatory_enforcement_order",
    "regulatory_approvals_received", "regulatory_abandonment_notice",
    "remedy_divestiture_completed",
    # litigation (never labels)
    "court_injunction", "court_order_specific_performance", "litigation_appeal",
    "litigation_settlement",
    # resolution
    "completion_indicated",          # e.g. 8-K item 2.01 metadata, text unread: NOT a label
    "closing", "termination", "withdrawal",
}
Y0_EVENTS = {"closing"}
Y1_EVENTS = {"termination", "withdrawal"}
FORMATION_EVENTS = {"announcement", "proposal_submitted", "talks_reported", "reported_announcement"}

VERIFICATION_RANK = {"sec_metadata_confirmed": 4, "press_multi": 3, "press_single": 2,
                     "unverified_staging": 1, "reported_only": 0}
LABEL_GRADE = {"sec_metadata_confirmed", "press_multi"}   # "verified" for label candidates
KNOWN_BASIS_RANK = {"sec_acceptance": 3, "source_stated": 2, "event_date_assumed": 1}
DEAL_KINDS = {"signed_definitive": "DEAL", "proposal": "PROP", "unverified": "UNVR"}

_DATE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2}))?Z?)?)?)?")


class NormalizationError(ValueError):
    """Raised when a record cannot be normalized without guessing."""


# ------------------------------------------------------------------ time
@dataclass(frozen=True)
class Stamp:
    """A timestamp with explicit precision; never padded with invented time."""
    value: str          # as recorded: YYYY | YYYY-MM | YYYY-MM-DD | YYYY-MM-DDTHH:MM[:SS]Z
    precision: str      # year | month | day | minute | second

    @property
    def earliest(self) -> str:
        """Start of the interval the stamp denotes (for valid time)."""
        return _expand(self, start=True)

    @property
    def latest(self) -> str:
        """End of the interval the stamp denotes (conservative known time)."""
        return _expand(self, start=False)


def parse_stamp(text: Optional[str]) -> Optional[Stamp]:
    """Parse the LEADING date/time token of a free-text cell; None if absent."""
    if not text:
        return None
    m = _DATE.match(text.strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss = m.groups()
    if ss is not None:
        return Stamp(f"{y}-{mo}-{d}T{hh}:{mi}:{ss}Z", "second")
    if mi is not None:
        return Stamp(f"{y}-{mo}-{d}T{hh}:{mi}Z", "minute")
    if d is not None:
        return Stamp(f"{y}-{mo}-{d}", "day")
    if mo is not None:
        return Stamp(f"{y}-{mo}", "month")
    return Stamp(y, "year")


def _expand(s: Stamp, start: bool) -> str:
    v = s.value.rstrip("Z")
    if s.precision == "second":
        return v
    if s.precision == "minute":
        return v + (":00" if start else ":59")
    if s.precision == "day":
        return v + ("T00:00:00" if start else "T23:59:59")
    if s.precision == "month":
        y, mo = map(int, v.split("-"))
        last = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mo - 1]
        return f"{v}-01T00:00:00" if start else f"{v}-{last:02d}T23:59:59"
    return f"{v}-01-01T00:00:00" if start else f"{v}-12-31T23:59:59"


def valid_not_after_known(valid: Stamp, known: Stamp) -> bool:
    """An event cannot become public before it happens. Valid time MAY precede
    known time (a ruling published days later); compare the earliest instant the
    event could have occurred with the latest instant it was known."""
    return valid.earliest <= known.latest


# ------------------------------------------------------------------ identity
def party_code(name: str, ticker: str = "", codes: Optional[dict] = None,
               allow_paren_ticker: bool = False) -> str:
    """Ticker column (exchange suffix stripped) > reviewed code. A parenthesised
    ticker such as 'Victory Capital (VCTR)' is used only when allowed (acquirer
    cells), so a qualifier like 'Argan (FR)' is never mistaken for a ticker."""
    if ticker:
        return re.sub(r"[^A-Z0-9]", "", ticker.split(".")[0].upper())
    key = normalize_name(name)
    if codes and key in codes:
        return codes[key]
    paren = re.search(r"\(([A-Z]{2,5})\)", name or "") if allow_paren_ticker else None
    if paren:
        return paren.group(1)
    raise NormalizationError(f"no reviewed party code for {name!r} (key {key!r})")


def normalize_name(name: str) -> str:
    s = re.sub(r"\([^)]*\)", " ", (name or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9&+ ]", " ", s)).strip()


def canonical_deal_id(kind: str, target_code: str, acquirer_code: str, year: str) -> str:
    if kind not in DEAL_KINDS:
        raise NormalizationError(f"unknown deal kind {kind!r}")
    for part in (target_code, acquirer_code):
        if not re.fullmatch(r"[A-Z0-9]{1,16}", part):
            raise NormalizationError(f"bad code {part!r}")
    if not re.fullmatch(r"\d{4}", year):
        raise NormalizationError(f"bad year {year!r}")
    return f"{DEAL_KINDS[kind]}-{target_code}-{acquirer_code}-{year}"


def event_id(deal_id: str, event_type: str, valid_at: Stamp) -> str:
    h = hashlib.sha1(f"{deal_id}|{event_type}|{valid_at.value}".encode()).hexdigest()[:16]
    return f"EVT-{h.upper()}"


# ------------------------------------------------------------------ records
@dataclass(frozen=True)
class Evidence:
    """One source's report of an event."""
    source_name: str
    source_identifier: str
    source_url: str
    verification_level: str
    known_at: Stamp
    known_at_basis: str
    staging_ref: str            # register deal_id or staging record_id it came from


@dataclass(frozen=True)
class Event:
    canonical_deal_id: str
    event_type: str
    valid_at: Stamp
    evidence: tuple[Evidence, ...]
    note: str = ""

    @property
    def event_id(self) -> str:
        return event_id(self.canonical_deal_id, self.event_type, self.valid_at)

    @property
    def primary(self) -> Evidence:
        return sorted(self.evidence, key=_evidence_order)[0]

    @property
    def verification_level(self) -> str:
        return max((e.verification_level for e in self.evidence), key=VERIFICATION_RANK.__getitem__)


def _evidence_order(e: Evidence):
    # strongest known-time basis first, then verification, then earliest known, then id
    return (-KNOWN_BASIS_RANK[e.known_at_basis], -VERIFICATION_RANK[e.verification_level],
            e.known_at.latest, e.source_identifier, e.source_url)


def make_event(deal_id: str, event_type: str, valid_at: Stamp, ev: Evidence, note: str = "") -> Event:
    if event_type not in EVENT_TYPES:
        raise NormalizationError(f"unknown event type {event_type!r}")
    if ev.verification_level not in VERIFICATION_RANK:
        raise NormalizationError(f"unknown verification level {ev.verification_level!r}")
    if ev.known_at_basis not in KNOWN_BASIS_RANK:
        raise NormalizationError(f"unknown known_at basis {ev.known_at_basis!r}")
    if not valid_not_after_known(valid_at, ev.known_at):
        raise NormalizationError(
            f"{deal_id} {event_type}: known_at {ev.known_at.value} precedes valid_at {valid_at.value}")
    return Event(deal_id, event_type, valid_at, (ev,), note)


def merge_events(events: Iterable[Event]) -> dict[str, Event]:
    """Idempotent: collapse by event_id, union evidence (deduplicated)."""
    out: dict[str, Event] = {}
    for e in events:
        cur = out.get(e.event_id)
        if cur is None:
            out[e.event_id] = e
            continue
        ev = tuple(sorted(set(cur.evidence) | set(e.evidence), key=_evidence_order))
        note = "; ".join(sorted({n for n in (cur.note, e.note) if n}))
        out[e.event_id] = replace(cur, evidence=ev, note=note)
    return out


@dataclass
class Deal:
    canonical_deal_id: str
    deal_kind: str
    attrs: dict = field(default_factory=dict)       # announcement-time attributes only
    source_rows: list = field(default_factory=list)
    id_basis: str = "agreement_year"
    flags: list = field(default_factory=list)


def attach(deals: dict[str, Deal], event: Event) -> None:
    """Events attach to an EXISTING deal; they never create one."""
    if event.canonical_deal_id not in deals:
        raise NormalizationError(f"event {event.event_type} references unknown deal "
                                 f"{event.canonical_deal_id}; events cannot create deals")


# ------------------------------------------------------------------ outcomes
def events_as_of(events: Iterable[Event], as_of: str) -> list[Event]:
    """Point-in-time view: an event is visible only if it had happened AND was
    publicly known by `as_of` (primary evidence's conservative known time)."""
    return sorted((e for e in events
                   if e.valid_at.earliest <= as_of and e.primary.known_at.latest <= as_of),
                  key=lambda e: (e.valid_at.earliest, e.event_type))


def outcome_as_of(deal: Deal, events: Iterable[Event], as_of: str) -> dict:
    visible = events_as_of(events, as_of)
    base = {"canonical_deal_id": deal.canonical_deal_id, "as_of": as_of,
            "outcome_candidate": "censored", "resolution_event_id": "",
            "resolution_valid_at": "", "basis": "", "requires_review": "yes",
            "model_eligible": "no"}
    if deal.deal_kind != "signed_definitive":
        base["basis"] = f"{deal.deal_kind}: never a signed-deal label"
        return base
    y0 = [e for e in visible if e.event_type in Y0_EVENTS and e.verification_level in LABEL_GRADE]
    y1 = [e for e in visible if e.event_type in Y1_EVENTS and e.verification_level in LABEL_GRADE]
    if y0 and y1:
        raise NormalizationError(f"{deal.canonical_deal_id}: both closing and termination")
    hit = (y0 or y1)
    if hit:
        e = hit[0]
        base.update(outcome_candidate="Y0_closed" if y0 else "Y1_broken",
                    resolution_event_id=e.event_id, resolution_valid_at=e.valid_at.value,
                    basis=f"{e.event_type} ({e.verification_level})")
        return base
    unresolved = sorted({e.event_type for e in visible} &
                        {"court_injunction", "completion_indicated", "regulatory_clearance",
                         "regulatory_approvals_received", "court_order_specific_performance",
                         "litigation_settlement", "closing", "termination"})
    base["basis"] = "pending" + (f" (seen: {', '.join(unresolved)})" if unresolved else "")
    return base
