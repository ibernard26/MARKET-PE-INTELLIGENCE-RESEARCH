"""Q3 2026 build: research register + ChatGPT staging -> canonical deals/events.

Inputs are STAGING ONLY and are never modified:
  data/research/deal_register_2026Q3.csv                (64 register rows)
  data/research/sec_filings_2026Q3.json                 (EDGAR metadata evidence)
  data/public_mna_intelligence/2026-07-01_2026-09-24/staging_chatgpt/public_mna_events.csv
  data/public_mna_intelligence/2026-07-01_2026-09-24/reconciliation.csv
Outputs (data/research/):
  canonical_deals_2026Q3.csv            identity + classification only (no outcome, no terms)
  canonical_deal_events_2026Q3.csv      one row per lifecycle event
  canonical_deal_outcomes_2026Q3.csv    outcome candidates as of the snapshot date
  canonical_unlinked_events_2026Q3.csv  staging events with no deal record (cannot mint deals)
  canonical_source_map_2026Q3.csv       every source row -> disposition
Nothing here writes to the SQLite store or feeds break_logit_v1.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .canonical import (Deal, Evidence, Event, NormalizationError, Stamp, attach,
                        canonical_deal_id, make_event, merge_events, normalize_name,
                        outcome_as_of, parse_stamp, party_code)

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "data" / "research"
STAGING_DIR = ROOT / "data" / "public_mna_intelligence" / "2026-07-01_2026-09-24"
REGISTER = RESEARCH / "deal_register_2026Q3.csv"
SEC_EVIDENCE = RESEARCH / "sec_filings_2026Q3.json"
STAGING = STAGING_DIR / "staging_chatgpt" / "public_mna_events.csv"
RECON = STAGING_DIR / "reconciliation.csv"
SNAPSHOT_AS_OF = "2026-09-24T23:59:59"

# Reviewed party codes for names without a ticker (keys are normalize_name()).
PARTY_CODES = {normalize_name(k): v for k, v in {
    "Vertex Pharmaceuticals": "VRTX", "Solstice Advanced Materials": "SOLS",
    "Lockheed Martin": "LMT", "Sazerac": "SAZERAC", "Wynnchurch Capital affiliates": "WYNNCHURCH",
    "Intercontinental Exchange": "ICE", "IonQ": "IONQ", "Khosla family-led group": "KHOSLA",
    "WDP": "WDP", "Curium US": "CURIUM", "KKR affiliate": "KKR", "Prologis": "PLD",
    "Apollo": "APOLLO", "Dream Finders Homes": "DFH", "Bernhard Capital Partners": "BCP",
    "EQT Infrastructure": "EQT", "EQT": "EQT", "Thoma Bravo": "THOMABRAVO", "Henkel": "HENKEL",
    "Star Equity Holdings": "STRR", "Uber": "UBER", "Aon": "AON", "Stripe": "STRIPE",
    "MARI Group": "MARI", "PIF / Silver Lake / Affinity Partners": "PIFSLAFF",
    "Diversified Energy": "DEC", "Nvidia": "NVDA",
    "Sequence Holdings + Dell Family Office": "SEQDFO", "Grab Holdings": "GRAB",
    "Enbridge": "ENB", "H.I.G. Capital": "HIG", "Atrium Health": "ATRIUM",
    "Journey Beyond": "JOURNEYB", "Taboola": "TBLA", "Telix Pharmaceuticals": "TELIX",
    "Investor group led by CEO Thomas Priore": "PRIOREGRP",
    "CVC + Nippon Sangyo Suishin Kiko": "CVCNSSK", "Merck KGaA": "MERCKKGAA",
    "Zymeworks": "ZYME", "Paramount Skydance": "PSKY", "eBay": "EBAY",
    "Ascension Health": "ASCENSION", "Adena Health": "ADENA", "Nuveen": "NUVEEN",
    "KONE": "KONE", "E.ON": "EON", "Sky": "SKY", "Warburg Pincus": "WARBURG",
    "Blackstone": "BX", "Beretta Holding": "BERETTA",
    # targets without a ticker
    "Ultra Maritime": "ULTRAMAR", "WildFire Energy": "WILDFIRE", "Seattle Seahawks": "SEAHAWKS",
    "Argan": "ARGAN", "A-Paint Topco": "LIQUIDNAILS", "Ambros Therapeutics": "AMBROS",
    "First Eagle Investments": "FIRSTEAGLE", "USI Insurance Services": "USI",
    "OpenRouter": "OPENROUTER", "Ambassador Theatre Group": "ATG",
    "Birch Permian Holdings": "BIRCH", "Hugging Face": "HUGGINGFACE",
    "Lincoln Bancorp": "LINCOLN", "Convergent Genomics": "CONVERGENT",
    "Atome Financial": "ATOME", "Tallgrass crude assets": "TALLGRASS", "WakeMed": "WAKEMED",
    "Kelsian SeaLink tourism portfolio": "SEALINK", "Dianomi": "DIANOMI",
    "ITM Isotope Technologies Munich": "ITM", "Carbonium Core": "CARBONIUM",
    "Kobayashi Pharmaceutical": "KOBAYASHI", "Depop": "DEPOP",
    "Momentum Midstream": "MOMENTUM", "AccuLynx": "ACCULYNX", "AmSurg": "AMSURG",
    "Fairfield Medical Center": "FMC", "Unilever Foods": "ULVRFOODS", "TK Elevator": "TKE",
    "OVO Energy": "OVO", "ITV Media & Entertainment": "ITVME",
}.items()}

# window_event text -> canonical event type (None = formation already covered)
WINDOW_EVENT_MAP = [
    (r"^announced\+terminated", "termination"), (r"^announced\+closed", "closing"),
    (r"^terminated", "termination"), (r"^closed", "closing"), (r"^blocked", "court_injunction"),
    (r"^rejected", "proposal_rejected"), (r"^litigation", "court_order_specific_performance"),
    (r"holder vote", "shareholder_vote"), (r"state AG settlement", "litigation_settlement"),
    (r"go-shop expired", "go_shop_expired"),
    (r"approvals; close scheduled", "regulatory_approvals_received"),
    (r"CMA Phase 1 launched", "regulatory_phase1_launched"),
    (r"CMA invitation to comment", "regulatory_invitation_to_comment"),
    (r"FTC proposed consent", "regulatory_consent_order_proposed"),
    (r"^(announced|proposal|reported|pending)", None),
]
RESOLUTION_TYPES = {"termination", "closing", "court_injunction", "proposal_rejected"}
# status_2026_09_24 prefix -> resolution event, used when window_event is only the
# announcement (e.g. Crinetics: window 'announced', status 'closed' on 2026-09-01)
STATUS_RESOLUTION = [("closed", "closing"), ("terminated", "termination"),
                     ("rejected", "proposal_rejected"), ("blocked", "court_injunction")]

STAGING_TYPE_MAP = {
    "merger_abandoned_cma_reference_cancelled": "regulatory_abandonment_notice",
    "cma_invitation_to_comment": "regulatory_invitation_to_comment",
    "cma_case_closed_phase2_clearance": "regulatory_clearance",
    "cma_phase1_clearance": "regulatory_clearance",
    "cma_phase1_inquiry_launched": "regulatory_phase1_launched",
    "acquisition_completed": "closing",
    "ftc_early_termination_review": "regulatory_early_termination",
    "acquisition_announced": "announcement", "recommended_takeover_announced": "announcement",
    "acquisition_announced_in_ftc_statement": "announcement",
    "definitive_take_private_announced": "announcement",
    "court_orders_buyer_to_attempt_completion": "court_order_specific_performance",
    "court_permanent_injunction_blocks_merger": "court_injunction",
    "cma_case_closed": "regulatory_case_closed",
    "cma_case_closed_full_decision_published": "regulatory_case_closed",
    "ftc_final_consent_order_with_divestitures": "regulatory_consent_order",
    "ftc_proposed_consent_order": "regulatory_consent_order_proposed",
    "cma_initial_enforcement_order": "regulatory_enforcement_order",
    "reported_state_antitrust_settlement": "litigation_settlement",
    "revised_takeover_bid_rejected": "proposal_rejected",
    "sweetened_takeover_proposal_rejected": "proposal_rejected",
    "regulatory_approvals_cleared_close_scheduled": "regulatory_approvals_received",
    "remedy_divestiture_completed_cma_case_closed": "remedy_divestiture_completed",
}
# A staging event carries its OWN source's strength. "confirmed_sec_metadata" in the
# reconciliation means EDGAR corroborated the deal fact (that SEC evidence lives on the
# register-derived event); the staging source itself (regulator page / wire) is press-grade.
STAGING_VERIFICATION = {"confirmed_sec_metadata": "press_multi",
                        "corroborated_press": "press_multi", "corrected": "press_multi",
                        "unverified_source_unreachable": "unverified_staging"}
# Staging rows whose stated facts were corrected by the register (kept out of events).
SUPERSEDED = {"MNA-20260808-VERISK-ACCULYNX":
              "ruling date 2026-08-08 is the report date; register records the 2026-08-07 order"}

# Curated events/known-times, each with its own source (row_ref = register deal_id).
EXTRA = [
    dict(row_ref="2026Q3-016", event_type="go_shop_started", valid="2026-08-10", known="2026-09-14",
         basis="source_stated", verification="press_multi", source_name="Bowman go-shop release",
         url="https://www.globenewswire.com/news-release/2026/09/14/3360984/0/en/bowman-consulting-group-announces-expiration-of-go-shop-period.html",
         note="35-day go-shop ending 2026-09-13 17:00 ET => started at signing; known_at is the "
              "expiry release (conservative - the Aug-10 disclosure text was not read)"),
    dict(row_ref="2026Q3-049", event_type="go_shop_expired", valid="2026-09-13", known="2026-09-14",
         basis="source_stated", verification="press_multi", source_name="Bowman go-shop release",
         url="https://www.globenewswire.com/news-release/2026/09/14/3360984/0/en/bowman-consulting-group-announces-expiration-of-go-shop-period.html",
         note="expired 17:00 ET 2026-09-13; no proposals received"),
    dict(row_ref="2026Q3-023", event_type="offer_document_published", valid="2026-08-27",
         known="2026-08-27", basis="source_stated", verification="press_multi",
         source_name="Uber investor relations",
         url="https://investor.uber.com/news-events/news/press-release-details/2026/Uber-Publishes-Offer-Document-for-its-Takeover-Offer-for-Delivery-Hero/default.aspx",
         note="acceptance period 2026-08-27 to 2026-11-05; a milestone, not the announcement"),
    dict(row_ref="2026Q3-005", event_type="proposal_submitted", valid="2026-05-01", known="2026-07-26",
         basis="source_stated", verification="press_multi", source_name="Brown-Forman board statement",
         url="https://www.brown-forman.com/article/brown-forman-board-issues-statement-july-26-2026",
         note="private proposal; first public disclosure is the 2026-07-26 board statement"),
    dict(row_ref="2026Q3-063", event_type="proposal_submitted", valid="2026-09-09", known="2026-09-22",
         basis="source_stated", verification="press_multi", source_name="MarketScreener",
         url="https://www.marketscreener.com/news/idp-education-rejects-blackstone-s-takeover-proposal-ce785ad9d98ef02d",
         note="revised A$2.50 proposal submitted 2026-09-09, disclosed with the rejection"),
    dict(row_ref="2026Q3-043", event_type="termination", valid="2026-09-20", known="2026-09-21",
         basis="source_stated", verification="press_multi", source_name="GlobeNewswire (TOMI)",
         url="https://www.globenewswire.com/news-release/2026/09/21/3365883/34752/en/tomi-environmental-solutions-announces-mutual-termination-of-merger-agreement-with-carbonium-core.html",
         note="board approved 2026-09-20; announced 2026-09-21"),
    dict(row_ref="2026Q3-053", event_type="litigation_appeal", valid="2026-08-18", known="2026-08-18",
         basis="event_date_assumed", verification="press_single", source_name="search summary",
         url="https://www.hsfkramer.com/insights/2026-08/verisk-analytics-v-acculynx-sorry-you-actually-do-have-to-comply-with-that-second-request",
         note="Verisk appealed the specific-performance order"),
]


@dataclass
class Build:
    deals: dict
    events: dict
    outcomes: list
    unlinked: list
    source_map: list
    stats: dict


# ------------------------------------------------------------------ helpers
def _urls(cell: str) -> list[str]:
    return [u.strip() for u in (cell or "").split(";") if u.strip().startswith("http")]


def _domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else "research register"


def _deal_kind(r: dict) -> str:
    dt, we = r["deal_type"].lower(), r["window_event"].lower()
    if "proposal" in dt or "talks" in dt or we in ("rejected", "proposal") or we.startswith("reported"):
        return "proposal"
    if r["verification"] == "reported_only" or r["status_2026_09_24"].startswith("planned"):
        return "unverified"
    return "signed_definitive"


def _formation_type(kind: str, r: dict) -> str:
    if kind == "proposal":
        return "talks_reported" if "talks" in r["deal_type"].lower() else "proposal_submitted"
    return "announcement" if kind == "signed_definitive" else "reported_announcement"


def _press_level(r: dict) -> str:
    if r["verification"] in ("press_multi", "press_single", "reported_only"):
        return r["verification"]
    return "press_multi" if len(_urls(r["sources"])) >= 2 else "press_single"


def _accepted(acc: str, sec: dict) -> Stamp:
    for comp in sec.values():
        for f in comp["filings"]:
            if f["accession"] == acc:
                return parse_stamp(f["accepted"].replace(".000Z", "Z"))
    raise NormalizationError(f"accession {acc} not in EDGAR evidence")


def _window_type(we: str):
    for pat, et in WINDOW_EVENT_MAP:
        if re.search(pat, we):
            return et
    raise NormalizationError(f"unmapped window_event {we!r}")


# ------------------------------------------------------------------ build
def build() -> Build:
    reg = list(csv.DictReader(REGISTER.open()))
    sec = json.loads(SEC_EVIDENCE.read_text())
    staging = {r["record_id"]: r for r in csv.DictReader(STAGING.open())}
    recon = list(csv.DictReader(RECON.open()))

    # 1. identity: group register rows by (kind, target code, acquirer code)
    groups, row_key = defaultdict(list), {}
    for r in reg:
        kind = _deal_kind(r)
        key = (kind, party_code(r["target"], r["target_ticker"], PARTY_CODES),
               party_code(r["acquirer"], "", PARTY_CODES, allow_paren_ticker=True))
        groups[key].append(r)
        row_key[r["deal_id"]] = key

    # 2. candidate events per register row (deal id resolved after year is known)
    raw = []   # (key, row, event_type, valid Stamp, Evidence, note)
    for r in reg:
        key = row_key[r["deal_id"]]
        kind = key[0]
        urls = _urls(r["sources"])
        purls = [u for u in urls if "sec.gov" not in u] or urls   # press evidence cites press
        press = Evidence(_domain(purls[0]) if purls else "research register", r["deal_id"],
                         purls[0] if purls else "", _press_level(r), None, "event_date_assumed",
                         r["deal_id"])
        # formation event
        v = parse_stamp(r["announce_date"])
        if v is None and r["window_event"].startswith(("announced", "reported")):
            v = parse_stamp(r["window_event_date"])
        if v is not None:
            if r["sec_announce_accession"] and r["announce_known_at_utc"]:
                k = parse_stamp(r["announce_known_at_utc"])
                ev = Evidence("SEC EDGAR (metadata)", r["sec_announce_accession"],
                              f"https://www.sec.gov/Archives/edgar/data/{r['sec_cik']}/"
                              f"{r['sec_announce_accession'].replace('-', '')}/",
                              "sec_metadata_confirmed", k, "sec_acceptance", r["deal_id"])
                note = ""
                if v.earliest > k.latest:      # an agreement cannot be public before it exists
                    note = f"valid_at capped from {v.value} to disclosure date {k.value[:10]}"
                    v = Stamp(k.value[:10], "day")
            else:
                ev, note = replace_known(press, v), ""
            raw.append((key, r, _formation_type(kind, r), v, ev, note))
        # window / resolution event
        et = _window_type(r["window_event"])
        if r["status_2026_09_24"].startswith("likely closed") and r["sec_resolution_accession"]:
            k = _accepted(r["sec_resolution_accession"], sec)
            raw.append((key, r, "completion_indicated", Stamp(k.value[:10], "day"),
                        Evidence("SEC EDGAR (metadata)", r["sec_resolution_accession"], "",
                                 "sec_metadata_confirmed", k, "sec_acceptance", r["deal_id"]),
                        "8-K item 2.01 metadata only; filing text unread - not a closing label"))
        if et is None and r["resolution_date"]:
            et = next((t for pre, t in STATUS_RESOLUTION
                       if r["status_2026_09_24"].startswith(pre)), None)
        if et:
            v = parse_stamp(r["resolution_date"] if et in RESOLUTION_TYPES else r["window_event_date"])
            if v is None:
                raise NormalizationError(f"{r['deal_id']}: {et} without a date")
            if r["sec_resolution_accession"] and et in ("closing", "termination"):
                k = _accepted(r["sec_resolution_accession"], sec)
                ev = Evidence("SEC EDGAR (metadata)", r["sec_resolution_accession"], "",
                              "sec_metadata_confirmed", k, "sec_acceptance", r["deal_id"])
            else:
                ev = replace_known(press, v)
            raw.append((key, r, et, v, ev, ""))

    for x in EXTRA:
        r = next(r for r in reg if r["deal_id"] == x["row_ref"])
        raw.append((row_key[r["deal_id"]], r, x["event_type"], parse_stamp(x["valid"]),
                    Evidence(x["source_name"], x["url"], x["url"], x["verification"],
                             parse_stamp(x["known"]), x["basis"] if x["basis"] != "source_stated"
                             else "source_stated", x["row_ref"]), x["note"]))

    # 3. deal ids: agreement/proposal year, else earliest event year (flagged)
    deals, key_to_id = {}, {}
    for key, rows in sorted(groups.items()):
        kind, t, a = key
        years = sorted(s.value[:4] for rr in rows for s in [parse_stamp(rr["announce_date"])] if s)
        basis = "agreement_year" if kind == "signed_definitive" else f"{kind}_year"
        if not years:
            years = sorted(v.value[:4] for k2, _, _, v, _, _ in raw if k2 == key)
            basis = "first_event_year"
        did = canonical_deal_id(kind, t, a, years[0])
        attrs = {c: next((r[c] for r in sorted(rows, key=lambda r: r["deal_id"]) if r[c]), "")
                 for c in ("target", "target_ticker", "acquirer", "sponsor", "deal_type",
                           "consideration_type", "sector", "geography", "sec_cik")}
        flags = ["id_year_from_first_event"] if basis == "first_event_year" else []
        deals[did] = Deal(did, kind, attrs, sorted(r["deal_id"] for r in rows), basis, flags)
        key_to_id[key] = did

    events = []
    for key, r, et, v, ev, note in raw:
        did = key_to_id[key]
        e = make_event(did, et, v, ev, note)
        attach(deals, e)
        events.append(e)

    # 4. staging events attach through the reconciliation link; they never mint deals
    reg_to_deal = {rid: key_to_id[k] for rid, k in row_key.items()}
    source_map, unlinked = [], []
    for r in reg:
        source_map.append(dict(source="register", source_row_id=r["deal_id"],
                               canonical_deal_id=reg_to_deal[r["deal_id"]], disposition="mapped",
                               note=""))
    for rc in recon:
        s = staging[rc["record_id"]]
        rid = rc["record_id"]
        if rid in SUPERSEDED:
            source_map.append(dict(source="staging_chatgpt", source_row_id=rid,
                                   canonical_deal_id=reg_to_deal.get(rc["register_deal_id"], ""),
                                   disposition="superseded", note=SUPERSEDED[rid]))
            continue
        et = STAGING_TYPE_MAP[s["event_type"]]
        ev = Evidence(s["source_name"], rid, s["source_url"],
                      STAGING_VERIFICATION[rc["reconciliation_status"]],
                      parse_stamp(s["known_at_date"]) or parse_stamp(s["event_date"]),
                      "source_stated" if s["known_at_date"] else "event_date_assumed", rid)
        if not rc["register_deal_id"]:
            unlinked.append(dict(staging_record_id=rid, deal_key=s["deal_key"], event_type=et,
                                 valid_at=s["event_date"], known_at=s["known_at_date"],
                                 source_name=s["source_name"], source_url=s["source_url"],
                                 verification_level=ev.verification_level,
                                 reason="regulator-only event with no verified deal record; "
                                        "events cannot create deals"))
            source_map.append(dict(source="staging_chatgpt", source_row_id=rid, canonical_deal_id="",
                                   disposition="unlinked_regulator_only", note=s["deal_key"]))
            continue
        did = reg_to_deal[rc["register_deal_id"]]
        if et in ("announcement",) and deals[did].deal_kind != "signed_definitive":
            raise NormalizationError(f"{rid}: announcement on non-signed deal {did}")
        if et == "proposal_rejected" and deals[did].deal_kind != "proposal":
            raise NormalizationError(f"{rid}: proposal_rejected on signed deal {did}")
        e = make_event(did, et, parse_stamp(s["event_date"]), ev)
        attach(deals, e)
        events.append(e)
        source_map.append(dict(source="staging_chatgpt", source_row_id=rid, canonical_deal_id=did,
                               disposition="mapped", note=""))

    merged = merge_events(events)
    per_deal = defaultdict(list)
    for e in merged.values():
        per_deal[e.canonical_deal_id].append(e)
    outcomes = [outcome_as_of(deals[d], per_deal[d], SNAPSHOT_AS_OF) for d in sorted(deals)]

    kinds = Counter(d.deal_kind for d in deals.values())
    oc = Counter(o["outcome_candidate"] for o in outcomes if deals[o["canonical_deal_id"]].deal_kind
                 == "signed_definitive")
    stats = {
        "source research rows": f"{len(reg)} register + {len(staging)} staging = {len(reg) + len(staging)}",
        "unique canonical deals": len(deals),
        "lifecycle events": len(merged),
        "duplicate deal rows collapsed": sum(len(g) - 1 for g in groups.values()),
        "signed definitive deals": kinds["signed_definitive"],
        "proposals only": kinds["proposal"],
        "unverified (reported-only / unsigned intent)": kinds["unverified"],
        "closed": oc["Y0_closed"], "broken": oc["Y1_broken"], "pending": oc["censored"],
        "regulator-only events": len(unlinked),
        "staging events attached to deals": sum(1 for m in source_map
                                                if m["source"] == "staging_chatgpt" and m["disposition"] == "mapped"),
        "staging rows superseded": sum(1 for m in source_map if m["disposition"] == "superseded"),
        "events needing known_at review": sum(1 for e in merged.values()
                                              if e.primary.known_at_basis == "event_date_assumed"),
    }
    return Build(deals, merged, outcomes, unlinked, source_map, stats)


def replace_known(ev: Evidence, valid: Stamp) -> Evidence:
    """Press evidence without a stated publication time: known_at = event date,
    flagged event_date_assumed (needs review before point-in-time use)."""
    from dataclasses import replace
    return replace(ev, known_at=valid, known_at_basis="event_date_assumed")


# ------------------------------------------------------------------ writers
DEAL_COLS = ["canonical_deal_id", "deal_kind", "target", "target_ticker", "acquirer", "sponsor",
             "deal_type", "consideration_type", "sector", "geography", "sec_cik", "id_basis",
             "source_register_rows", "normalization_flags"]
EVENT_COLS = ["event_id", "canonical_deal_id", "event_type", "valid_at", "valid_at_precision",
              "known_at", "known_at_precision", "known_at_basis", "source_name", "source_identifier",
              "source_url", "verification_level", "filing_content_verified", "corroborating_sources",
              "staging_refs", "known_at_review_required", "note"]
OUTCOME_COLS = ["canonical_deal_id", "as_of", "outcome_candidate", "resolution_event_id",
                "resolution_valid_at", "basis", "requires_review", "model_eligible"]


def rows(b: Build):
    deals = [dict(canonical_deal_id=d.canonical_deal_id, deal_kind=d.deal_kind, **d.attrs,
                  id_basis=d.id_basis, source_register_rows=";".join(d.source_rows),
                  normalization_flags=";".join(d.flags)) for d in
             sorted(b.deals.values(), key=lambda d: d.canonical_deal_id)]
    events = []
    for e in sorted(b.events.values(), key=lambda e: (e.canonical_deal_id, e.valid_at.earliest,
                                                       e.event_type)):
        p = e.primary
        others = [x for x in e.evidence if x is not p]
        events.append(dict(
            event_id=e.event_id, canonical_deal_id=e.canonical_deal_id, event_type=e.event_type,
            valid_at=e.valid_at.value, valid_at_precision=e.valid_at.precision,
            known_at=p.known_at.value, known_at_precision=p.known_at.precision,
            known_at_basis=p.known_at_basis, source_name=p.source_name,
            source_identifier=p.source_identifier, source_url=p.source_url,
            verification_level=e.verification_level, filing_content_verified="no",
            corroborating_sources="; ".join(f"{x.source_name}|{x.source_identifier}|"
                                            f"{x.verification_level}" for x in others),
            staging_refs=";".join(sorted({x.staging_ref for x in e.evidence})),
            known_at_review_required="yes" if p.known_at_basis == "event_date_assumed" else "no",
            note=e.note))
    return deals, events


def write(b: Build, out_dir: Path = RESEARCH) -> dict:
    deals, events = rows(b)
    files = {
        "canonical_deals_2026Q3.csv": (DEAL_COLS, deals),
        "canonical_deal_events_2026Q3.csv": (EVENT_COLS, events),
        "canonical_deal_outcomes_2026Q3.csv": (OUTCOME_COLS, b.outcomes),
        "canonical_unlinked_events_2026Q3.csv": (list(b.unlinked[0]) if b.unlinked else [], b.unlinked),
        "canonical_source_map_2026Q3.csv": (["source", "source_row_id", "canonical_deal_id",
                                             "disposition", "note"], b.source_map),
    }
    for name, (cols, data) in files.items():
        with (out_dir / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    return {n: len(d) for n, (_, d) in files.items()}
