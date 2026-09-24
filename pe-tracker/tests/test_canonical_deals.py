"""Canonical deal / lifecycle-event identity (src/research/canonical*.py).

Built from the committed Q3 2026 staging files; nothing here touches the SQLite
store or any model.
"""
import csv
import hashlib

import pytest

from src.research import canonical as C
from src.research import canonical_q3_2026 as Q


@pytest.fixture(scope="module")
def b():
    return Q.build()


def events_of(b, did):
    return {e.event_type: e for e in b.events.values() if e.canonical_deal_id == did}


def deal_of(b, register_row):
    return next(m["canonical_deal_id"] for m in b.source_map if m["source_row_id"] == register_row)


# ------------------------------------------------------------- required cases
def test_bowman_announcement_and_go_shop_map_to_one_deal(b):
    assert deal_of(b, "2026Q3-016") == deal_of(b, "2026Q3-049") == "DEAL-BWMN-BCP-2026"
    ev = events_of(b, "DEAL-BWMN-BCP-2026")
    assert {"announcement", "go_shop_started", "go_shop_expired"} <= set(ev)
    assert b.deals["DEAL-BWMN-BCP-2026"].source_rows == ["2026Q3-016", "2026Q3-049"]
    assert not any(d.startswith("DEAL-BWMN") and d != "DEAL-BWMN-BCP-2026" for d in b.deals)


def test_uber_agreement_and_offer_document_map_to_one_deal(b):
    ev = events_of(b, "DEAL-DHER-UBER-2026")
    assert ev["announcement"].valid_at.value == "2026-07-16"
    assert ev["offer_document_published"].valid_at.value == "2026-08-27"
    assert len([d for d in b.deals if "DHER" in d]) == 1


def test_getty_shutterstock_announcement_and_termination_one_deal(b):
    ev = events_of(b, "DEAL-SSTK-GETY-2025")
    assert {"announcement", "termination", "regulatory_abandonment_notice"} <= set(ev)
    assert ev["termination"].valid_at.value == "2026-07-07"
    assert ev["termination"].primary.source_identifier == "0001140361-26-028035"  # SSTK 8-K 1.02
    assert len([d for d in b.deals if "SSTK" in d]) == 1


def test_paramount_wbd_regulatory_events_attach_to_same_deal(b):
    ev = events_of(b, "DEAL-WBD-PSKY-2026")
    assert {"announcement", "regulatory_clearance", "regulatory_case_closed",
            "litigation_settlement"} <= set(ev)
    assert ev["announcement"].valid_at.value == "2026-02-27"
    # register row and Reuters staging row describe ONE settlement event
    refs = {x.staging_ref for x in ev["litigation_settlement"].evidence}
    assert refs == {"2026Q3-047", "MNA-20260921-PARAMOUNT-WBD-STATES"}
    assert len([d for d in b.deals if "WBD" in d]) == 1


def test_rejected_brown_forman_proposal_is_not_a_signed_deal(b):
    did = deal_of(b, "2026Q3-005")
    assert did == "PROP-BF-SAZERAC-2026" and b.deals[did].deal_kind == "proposal"
    assert not any(d.startswith("DEAL-BF") for d in b.deals)
    ev = events_of(b, did)
    assert "announcement" not in ev and {"proposal_submitted", "proposal_rejected"} <= set(ev)
    out = next(o for o in b.outcomes if o["canonical_deal_id"] == did)
    assert out["outcome_candidate"] == "censored"


def test_proposal_rejection_can_never_become_break_label():
    deal = C.Deal("PROP-X-Y-2026", "proposal")
    ev = C.Evidence("s", "id", "", "sec_metadata_confirmed", C.parse_stamp("2026-08-01"),
                    "source_stated", "t")
    e = C.make_event(deal.canonical_deal_id, "termination", C.parse_stamp("2026-08-01"), ev)
    assert C.outcome_as_of(deal, [e], "2026-12-31T00:00:00")["outcome_candidate"] == "censored"


def test_regulator_only_events_cannot_create_a_deal(b):
    unlinked = {u["staging_record_id"] for u in b.unlinked}
    assert "MNA-20260714-ABF-HOVIS" in unlinked and len(unlinked) == 8
    for m in b.source_map:
        if m["disposition"] == "unlinked_regulator_only":
            assert m["canonical_deal_id"] == ""                        # no deal minted
    assert len(b.deals) == len({m["canonical_deal_id"] for m in b.source_map
                                if m["source"] == "register"})       # only register rows mint deals
    staging_deals = {m["canonical_deal_id"] for m in b.source_map
                     if m["source"] == "staging_chatgpt" and m["canonical_deal_id"]}
    assert staging_deals <= set(b.deals)                               # attached, never new
    orphan = C.make_event("DEAL-NOPE-NOPE-2026", "regulatory_clearance", C.parse_stamp("2026-07-14"),
                          C.Evidence("CMA", "x", "", "unverified_staging",
                                     C.parse_stamp("2026-07-14"), "source_stated", "x"))
    with pytest.raises(C.NormalizationError, match="cannot create deals"):
        C.attach(b.deals, orphan)


def test_event_ids_unique_and_deterministic(b):
    ids = [e.event_id for e in b.events.values()]
    assert len(ids) == len(set(ids))
    e = next(iter(b.events.values()))
    raw = f"{e.canonical_deal_id}|{e.event_type}|{e.valid_at.value}".encode()
    assert e.event_id == "EVT-" + hashlib.sha1(raw).hexdigest()[:16].upper()


def test_canonical_ids_stable_across_rebuilds(b, tmp_path):
    b2 = Q.build()
    assert sorted(b.deals) == sorted(b2.deals)
    assert sorted(b.events) == sorted(b2.events)
    Q.write(b, tmp_path)
    for name in ("canonical_deals_2026Q3.csv", "canonical_deal_events_2026Q3.csv",
                 "canonical_deal_outcomes_2026Q3.csv", "canonical_source_map_2026Q3.csv"):
        committed = (Q.RESEARCH / name).read_bytes()
        assert (tmp_path / name).read_bytes() == committed, f"{name} drifted from committed build"
    # pinned identities (change only deliberately)
    for did in ("DEAL-BWMN-BCP-2026", "DEAL-DHER-UBER-2026", "DEAL-SSTK-GETY-2025",
                "DEAL-WBD-PSKY-2026", "DEAL-ESI-SOLS-2026", "PROP-BF-SAZERAC-2026"):
        assert did in b2.deals


def test_valid_time_vs_known_time(b):
    for e in b.events.values():
        assert C.valid_not_after_known(e.valid_at, e.primary.known_at), e.event_id
    henkel = events_of(b, "DEAL-LIQUIDNAILS-HENKEL-2025")["court_injunction"]
    assert henkel.valid_at.value == "2026-08-14" and henkel.primary.known_at.value == "2026-08-17"
    nvda = events_of(b, "DEAL-HUGGINGFACE-NVDA-2026")["announcement"]
    assert (nvda.valid_at.value, nvda.primary.known_at.value) == ("2026-09-02", "2026-09-03T12:03:56Z")
    with pytest.raises(C.NormalizationError, match="precedes valid_at"):
        C.make_event("DEAL-A-B-2026", "closing", C.parse_stamp("2026-09-10"),
                     C.Evidence("s", "i", "", "press_multi", C.parse_stamp("2026-09-09"),
                                "source_stated", "r"))


def test_duplicate_ingest_is_idempotent(b):
    once = C.merge_events(b.events.values())
    twice = C.merge_events(list(b.events.values()) + list(b.events.values()))
    assert once == twice == b.events


# ------------------------------------------------------------- label rules
def _deal_with(event_type, level="sec_metadata_confirmed", kind="signed_definitive"):
    d = C.Deal("DEAL-T-A-2026", kind)
    ev = C.Evidence("s", "i", "", level, C.parse_stamp("2026-08-02"), "source_stated", "r")
    return d, [C.make_event(d.canonical_deal_id, event_type, C.parse_stamp("2026-08-01"), ev)]


@pytest.mark.parametrize("et", ["regulatory_clearance", "regulatory_approvals_received",
                                "regulatory_early_termination", "completion_indicated"])
def test_clearance_or_indicated_completion_is_not_y0(et):
    assert C.outcome_as_of(*_deal_with(et), "2026-12-31T00:00:00")["outcome_candidate"] == "censored"


@pytest.mark.parametrize("et", ["court_injunction", "regulatory_abandonment_notice"])
def test_block_is_not_y1_without_verified_termination(et):
    assert C.outcome_as_of(*_deal_with(et), "2026-12-31T00:00:00")["outcome_candidate"] == "censored"


def test_only_verified_resolution_becomes_a_label():
    assert C.outcome_as_of(*_deal_with("closing"), "2026-12-31T00:00:00")["outcome_candidate"] == "Y0_closed"
    assert C.outcome_as_of(*_deal_with("termination"), "2026-12-31T00:00:00")["outcome_candidate"] == "Y1_broken"
    for weak in ("press_single", "reported_only", "unverified_staging"):
        assert C.outcome_as_of(*_deal_with("closing", weak), "2026-12-31T00:00:00")[
            "outcome_candidate"] == "censored"


def test_q3_label_candidates_and_censoring(b):
    oc = {o["canonical_deal_id"]: o["outcome_candidate"] for o in b.outcomes}
    assert oc["DEAL-ESI-SOLS-2026"] == oc["DEAL-SSTK-GETY-2025"] == "Y1_broken"
    assert oc["DEAL-CRNX-VRTX-2026"] == oc["DEAL-SKYT-IONQ-2026"] == "Y0_closed"
    for pending in ("DEAL-LIQUIDNAILS-HENKEL-2025", "DEAL-WILDFIRE-MGY-2026",
                    "DEAL-WBD-PSKY-2026", "DEAL-ACCULYNX-VRSK-2025", "DEAL-SDR-NUVEEN-2026"):
        assert oc[pending] == "censored", pending
    assert all(o["model_eligible"] == "no" and o["requires_review"] == "yes" for o in b.outcomes)


# ------------------------------------------------------------- leakage guards
def test_announcement_time_view_has_no_future_outcome(b):
    did = "DEAL-ESI-SOLS-2026"
    evs = [e for e in b.events.values() if e.canonical_deal_id == did]
    ann = next(e for e in evs if e.event_type == "announcement")
    at = ann.primary.known_at.latest
    visible = {e.event_type for e in C.events_as_of(evs, at)}
    assert visible == {"announcement"}
    assert C.outcome_as_of(b.deals[did], evs, at)["outcome_candidate"] == "censored"


def test_canonical_deals_file_carries_no_outcome_or_later_terms():
    cols = next(csv.reader((Q.RESEARCH / "canonical_deals_2026Q3.csv").open()))
    banned = {"status", "status_2026_09_24", "resolution_date", "outcome_candidate", "notes",
              "headline_value", "offer_terms", "expected_close", "window_event"}
    assert not banned & set(cols)


def test_no_duplicate_economic_transactions(b):
    pairs = [tuple(d.split("-")[1:3]) for d in b.deals]
    assert len(pairs) == len(set(pairs))
    reg_rows = [m for m in b.source_map if m["source"] == "register"]
    assert len({m["source_row_id"] for m in reg_rows}) == len(reg_rows) == 64


def test_staging_inputs_are_not_modified(tmp_path):
    before = {p: hashlib.sha1(p.read_bytes()).hexdigest() for p in (Q.REGISTER, Q.STAGING, Q.RECON,
                                                                    Q.SEC_EVIDENCE)}
    Q.write(Q.build(), tmp_path)
    after = {p: hashlib.sha1(p.read_bytes()).hexdigest() for p in before}
    assert before == after
