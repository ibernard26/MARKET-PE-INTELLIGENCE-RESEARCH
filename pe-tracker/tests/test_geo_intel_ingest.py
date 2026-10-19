"""Geopolitical evidence staging, verification, PIT gate and exposure tests.

ALL EVIDENCE BELOW IS SYNTHETIC FIXTURE DATA. Hosts end in `.invalid`
(RFC 2606) so no fixture can be mistaken for a real publication; the primary
registry is a fixture registry. No real-world event is asserted anywhere.
"""
from __future__ import annotations

import json
from dataclasses import replace

import pytest

from src.geo_intel.exposure import (DealUniverse, DealRecord, ExposureLink,
                                    IncorrectMatchError, validate_link)
from src.geo_intel.pit import LeakageError, assert_no_leakage, research_candidates
from src.geo_intel.reporting import NOT_AVAILABLE, build_report
from src.geo_intel.schema import (EvidenceRecord, SchemaError, TimestampError,
                                  parse_ts, primary_authority)
from src.geo_intel.store import (ClusterConflictError, DuplicateEvidenceError,
                                 EvidenceLedger, LedgerIntegrityError, RevisionError,
                                 records_from_grok_brief)
from src.geo_intel.verification import classify, status_history

REG = {"primary.fixture.invalid": "FIXTURE PRIMARY AUTHORITY"}
KEY = "fixture-sanctions-designation-001"


def clock():
    return "2030-01-01T00:00:00Z"


def led(path=None):
    return EvidenceLedger(path, clock=clock, primary_registry=REG)


def rec(**kw):
    base = dict(event_key=KEY, category="sanctions",
                original_statement="SYNTHETIC: designation of fixture entity",
                reporting_entity="Fixture Authority", publisher="Fixture Authority",
                source_url="https://primary.fixture.invalid/notice/1",
                source_type="primary_official", claim_type="occurred",
                publication_timestamp="2025-03-10T14:00:00Z",
                event_valid_timestamp="2025-03-10T13:00:00Z",
                retrieved_by_reviewer=True, geographies=("US",),
                sectors=("energy_upstream",), ingested_via="fixture")
    base.update(kw)
    return EvidenceRecord(**base)


def wire(n, **kw):
    d = dict(source_type="reputable_secondary", publisher=f"Fixture Wire {n}",
             reporting_entity=f"Fixture Wire {n}",
             source_url=f"https://wire{n}.fixture.invalid/story",
             original_statement=f"SYNTHETIC: wire {n} reports the designation",
             publication_timestamp=f"2025-03-1{n}T10:00:00Z")
    d.update(kw)
    return rec(**d)


# --------------------------------------------------------------- schema
def test_missing_timestamps_stay_missing_and_known_at_never_inferred():
    r = led().append(rec(publication_timestamp=None, event_valid_timestamp=None,
                         first_observed_timestamp=None))
    assert r.publication_timestamp is None and r.event_valid_timestamp is None
    # first-observed is OUR real observation time, not a guessed publication time
    assert r.first_observed_timestamp == clock()
    assert r.known_at_basis == "first_observed_timestamp"
    assert r.known_at_utc() == "2030-01-01T00:00:00.000000"


def test_zone_ambiguous_time_is_rejected_not_guessed():
    with pytest.raises(TimestampError):
        parse_ts("2025-03-10T14:00:00")
    with pytest.raises(SchemaError):
        rec(publication_timestamp="2025-03-10 14:00").validate(REG)


def test_bare_date_is_latest_instant_of_day():
    assert parse_ts("2025-03-10").latest_utc == "2025-03-10T23:59:59.999999"
    assert parse_ts("2025-03-10T09:00:00-04:00").latest_utc == "2025-03-10T13:00:00.000000"
    assert parse_ts(None) is None and parse_ts("n/d") is None


def test_known_at_before_publication_rejected():
    with pytest.raises(SchemaError, match="precedes publication"):
        rec(known_at="2025-03-09T00:00:00Z").validate(REG)


def test_primary_claim_requires_registered_authority_domain():
    with pytest.raises(SchemaError, match="not in the primary-source registry"):
        rec(source_url="https://lookalike-primary.invalid/x").validate(REG)
    assert primary_authority("https://www.sec.gov/Archives/x") == "US SEC (EDGAR)"
    assert primary_authority("https://sec.gov.evil.invalid/x") is None


def test_controlled_vocabularies():
    with pytest.raises(SchemaError):
        rec(category="weather").validate(REG)
    with pytest.raises(SchemaError):
        rec(sectors=("oil stuff",)).validate(REG)
    with pytest.raises(SchemaError):
        rec(geographies=("United States",)).validate(REG)


# --------------------------------------------------------------- dedup
def test_duplicate_ingestion_rejected():
    L = led()
    L.append(rec())
    with pytest.raises(DuplicateEvidenceError):
        L.append(rec())
    # same source re-ingested with reworded text / tracking params is still a duplicate
    with pytest.raises(DuplicateEvidenceError):
        L.append(rec(original_statement="SYNTHETIC: reworded",
                     source_url="https://primary.fixture.invalid/notice/1/?utm_source=x"))
    assert len(L.records) == 1


def test_same_statement_cannot_describe_two_events():
    L = led()
    L.append(rec())
    with pytest.raises(ClusterConflictError):
        L.append(rec(event_key="fixture-other-event"))


def test_ledger_is_append_only_and_tamper_evident(tmp_path):
    p = tmp_path / "ledger.jsonl"
    L = led(p)
    L.append(rec())
    assert not hasattr(L, "update") and not hasattr(L, "delete")
    assert len(led(p).records) == 1               # reload round-trips
    line = json.loads(p.read_text())
    line["original_statement"] = "SYNTHETIC: edited in place"
    p.write_text(json.dumps(line) + "\n")
    with pytest.raises(LedgerIntegrityError):
        led(p)


# --------------------------------------------------------------- verification
def test_grok_brief_is_never_verified_even_if_it_says_so():
    brief = {"brief_id": "FIXTURE-1", "source_url": "https://grok.fixture.invalid/brief/1",
             "generated_at": "2025-03-10T15:00:00Z",
             "items": [{"event_key": KEY, "category": "sanctions",
                        "statement": "SYNTHETIC: sanctions imposed", "claim_type": "occurred",
                        "status": "VERIFIED_PRIMARY",
                        "cited_urls": ["https://primary.fixture.invalid/notice/1"]},
                       {"event_key": "fixture-2", "category": "iran_us_diplomacy",
                        "statement": "SYNTHETIC: talks", "status": "confirmed!!"}]}
    L = led()
    recs = L.extend(records_from_grok_brief(brief))
    assert all(r.source_type == "ai_brief" and not r.retrieved_by_reviewer for r in recs)
    assert recs[0].claimed_status_by_source == "VERIFIED_PRIMARY"
    assert "lead_urls" in recs[0].notes and "claimed_status_raw" in recs[1].notes
    for eid, cl in L.clusters().items():
        r = classify(cl, primary_registry=REG)
        assert r.status == "UNCONFIRMED" and r.untrusted_only
    # a Grok brief cannot be staged as a trusted source
    with pytest.raises(SchemaError):
        rec(ingested_via="grok_brief").validate(REG)


def test_many_grok_briefs_do_not_corroborate():
    L = led()
    for i in range(5):
        L.append(rec(source_type="ai_brief", ingested_via="grok_brief", retrieved_by_reviewer=False,
                     publisher=f"Grok brief {i}", source_url=f"https://grok.fixture.invalid/{i}",
                     original_statement=f"SYNTHETIC grok {i}"))
    assert classify(L.records, primary_registry=REG).status == "UNCONFIRMED"


def test_status_ladder():
    L = led()
    L.append(wire(1))
    assert classify(L.records, primary_registry=REG).status == "ATTRIBUTED_CLAIM"
    L.append(wire(2, syndicated_from="Fixture Wire 1"))   # syndication counts once
    assert classify(L.records, primary_registry=REG).status == "ATTRIBUTED_CLAIM"
    L.append(wire(3))
    assert classify(L.records, primary_registry=REG).status == "CORROBORATED_SECONDARY"
    L.append(rec())
    assert classify(L.records, primary_registry=REG).status == "VERIFIED_PRIMARY"


def test_rumor_prediction_and_unretrieved_are_never_completed_events():
    for kw in ({"claim_type": "rumor"}, {"claim_type": "prediction"},
               {"retrieved_by_reviewer": False}):
        L = led()
        L.append(rec(**kw))
        L.append(wire(1, **kw)); L.append(wire(3, **kw))
        assert classify(L.records, primary_registry=REG).status == "UNCONFIRMED", kw
    L = led()
    L.append(rec(claim_type="scheduled"))     # an announced FUTURE action
    assert classify(L.records, primary_registry=REG).status == "ATTRIBUTED_CLAIM"
    assert research_candidates(L, "2026-01-01")["admitted"] == []


def test_conflicting_sources():
    L = led()
    L.append(wire(1)); L.append(wire(3, stance="contradicts"))
    assert classify(L.records, primary_registry=REG).status == "DISPUTED"
    L.append(rec())                            # primary resolves it; conflict kept
    r = classify(L.records, primary_registry=REG)
    assert r.status == "VERIFIED_PRIMARY" and len(r.conflicts) == 1
    L.append(rec(source_url="https://primary.fixture.invalid/notice/2", stance="contradicts",
                 original_statement="SYNTHETIC: authority denies"))
    assert classify(L.records, primary_registry=REG).status == "DISPUTED"


def test_corrections_and_retractions_are_appended_not_mutated():
    L = led()
    w1, w3 = L.append(wire(1)), L.append(wire(3))
    assert classify(L.records, primary_registry=REG).status == "CORROBORATED_SECONDARY"
    corr = L.append(wire(1, revises_evidence_id=w1.evidence_id, revision_type="correction",
                         claim_type="rumor", original_statement="SYNTHETIC: correction — only reported",
                         publication_timestamp="2025-03-14T09:00:00Z"))
    assert L.get(w1.evidence_id) == w1                         # original untouched
    assert classify(L.records, primary_registry=REG).status == "ATTRIBUTED_CLAIM"
    # bitemporal: the status as of a date reflects only what was public then
    assert classify(L.records, as_of="2025-03-11T12:00:00Z",
                    primary_registry=REG).status == "ATTRIBUTED_CLAIM"   # w3 not yet out
    assert classify(L.records, as_of="2025-03-13T12:00:00Z",
                    primary_registry=REG).status == "CORROBORATED_SECONDARY"
    assert classify(L.records, as_of="2025-03-14T12:00:00Z",
                    primary_registry=REG).status == "ATTRIBUTED_CLAIM"   # after correction
    assert len(research_candidates(L, "2025-03-13T12:00:00Z")["admitted"]) == 1
    assert research_candidates(L, "2025-03-14T12:00:00Z")["admitted"] == []
    L.append(wire(3, revises_evidence_id=w3.evidence_id, revision_type="retraction",
                  original_statement="SYNTHETIC: retracted", publication_timestamp="2025-03-15T09:00:00Z"))
    L.append(wire(1, revises_evidence_id=corr.evidence_id, revision_type="retraction",
                  original_statement="SYNTHETIC: retracted 1", publication_timestamp="2025-03-16T09:00:00Z"))
    assert classify(L.records, primary_registry=REG).status == "RETRACTED"
    hist = L.revision_history(w1.evidence_id)
    assert [h["revision_type"] for h in hist] == [None, "correction", "retraction"]
    assert [h["status"] for h in status_history(L.records, REG)][-1] == "RETRACTED"


def test_only_original_publisher_can_revise():
    L = led()
    w1 = L.append(wire(1))
    with pytest.raises(RevisionError):
        L.append(wire(3, revises_evidence_id=w1.evidence_id, revision_type="retraction"))
    with pytest.raises(RevisionError):
        L.append(wire(1, revises_evidence_id="EVD-NOPE", revision_type="correction",
                      original_statement="x"))


# --------------------------------------------------------------- PIT / leakage
def test_post_event_information_cannot_leak_into_earlier_prediction():
    L = led()
    L.append(rec())   # valid 2025-03-10T13:00Z, published 14:00Z
    assert research_candidates(L, "2025-03-10T13:30:00Z")["admitted"] == []   # not yet public
    assert research_candidates(L, "2025-03-09")["admitted"] == []
    got = research_candidates(L, "2025-03-10T14:00:00Z")["admitted"]
    assert len(got) == 1 and got[0]["known_at_utc"] <= "2025-03-10T14:00:00.000000"


def test_status_upgrade_is_dated_by_when_it_happened():
    L = led()
    L.append(wire(1)); L.append(wire(3))     # corroborated once wire 3 published 2025-03-13
    assert research_candidates(L, "2025-03-12")["admitted"] == []
    rej = research_candidates(L, "2025-03-12")["rejected"]
    assert rej[0]["reason"] == "status_ATTRIBUTED_CLAIM"
    a = research_candidates(L, "2025-03-14")["admitted"][0]
    assert a["known_at_utc"] == "2025-03-13T10:00:00.000000"


def test_missing_valid_time_is_never_admitted():
    L = led()
    L.append(rec(event_valid_timestamp=None))
    r = research_candidates(L, "2026-01-01")
    assert r["admitted"] == [] and r["rejected"][0]["reason"] == "missing_valid_time"


def test_scheduled_future_effective_date_not_admitted():
    L = led()
    L.append(rec(event_valid_timestamp="2025-06-01"))   # occurred-claim but future-dated
    assert research_candidates(L, "2025-04-01")["rejected"][0]["reason"] == \
        "valid_time_after_prediction_time"


def test_leakage_assertion_trips_on_tampered_output():
    bad = {"cutoff_utc": "2025-01-01T23:59:59.999999", "admitted": [
        {"event_id": "X", "valid_time_utc": "2025-02-01T00:00:00.000000",
         "known_at_utc": "2024-12-01T00:00:00.000000", "status_as_of": "VERIFIED_PRIMARY"}]}
    with pytest.raises(LeakageError):
        assert_no_leakage(bad)
    bad["admitted"][0].update(valid_time_utc="2024-12-01T00:00:00.000000", status_as_of="UNCONFIRMED")
    with pytest.raises(LeakageError):
        assert_no_leakage(bad)


# --------------------------------------------------------------- exposure
def universe():
    return DealUniverse({
        "DEAL-FIXTURE-A": DealRecord("DEAL-FIXTURE-A", "SYNTH T", "SYNTH A", "2025-01-15",
                                     "2025-09-30", "closed"),
        "DEAL-FIXTURE-OLD": DealRecord("DEAL-FIXTURE-OLD", "SYNTH T2", "SYNTH A2", "2020-01-15",
                                       "2020-09-30", "terminated")})


def link(L, **kw):
    eid = L.records[0].event_id
    d = dict(event_id=eid, deal_id="DEAL-FIXTURE-A", channel="sanctions_exposure",
             link_type="CONFIRMED_DEAL_SPECIFIC", rationale="SYNTHETIC", reviewer="fixture",
             citation_evidence_id=L.records[0].evidence_id)
    d.update(kw)
    return ExposureLink(**d)


def test_confirmed_link_requires_citation_naming_the_deal():
    L = led()
    L.append(rec(affected_deal_ids=("DEAL-FIXTURE-A",)))
    out = validate_link(link(L), L, universe())
    assert out["effect_on_break_probability"] == "NOT_ESTIMATED"
    assert out["deal_window"] == "during_deal_life"
    with pytest.raises(IncorrectMatchError, match="not in the reviewed manifest"):
        validate_link(link(L, deal_id="DEAL-NOT-REAL"), L, universe())
    with pytest.raises(IncorrectMatchError, match="after"):
        validate_link(link(L, deal_id="DEAL-FIXTURE-OLD"), L, universe())
    with pytest.raises(IncorrectMatchError, match="unknown channel"):
        validate_link(link(L, channel="vibes"), L, universe())
    with pytest.raises(IncorrectMatchError, match="break-probability"):
        validate_link(link(L, effect_on_break_probability="+5pp"), L, universe())


def test_confirmed_link_rejected_when_citation_does_not_name_deal_or_event_unverified():
    L = led()
    L.append(wire(1, affected_deal_ids=("DEAL-FIXTURE-A",)))   # ATTRIBUTED_CLAIM only
    with pytest.raises(IncorrectMatchError, match="verified/corroborated"):
        validate_link(link(L), L, universe())
    L2 = led()
    L2.append(rec())                                           # verified, names no deal
    with pytest.raises(IncorrectMatchError, match="does not name this deal"):
        validate_link(link(L2), L2, universe())


def test_sector_hypothesis_must_match_event_sector():
    L = led()
    L.append(rec())
    ok = validate_link(link(L, link_type="SECTOR_HYPOTHESIS", citation_evidence_id=None,
                            deal_sector="energy_upstream"), L, universe())
    assert ok["link_type"] == "SECTOR_HYPOTHESIS"
    with pytest.raises(IncorrectMatchError, match="not among"):
        validate_link(link(L, link_type="SECTOR_HYPOTHESIS", citation_evidence_id=None,
                           deal_sector="banking"), L, universe())


def test_deal_universe_is_read_only_and_preserves_labels():
    u = DealUniverse.from_manifest()
    assert len(u.deals) == 129
    with pytest.raises(TypeError):
        u.deals["X"] = None
    d = next(iter(u.deals.values()))
    with pytest.raises(Exception):
        d.resolution_type = "broken"


# --------------------------------------------------------------- report
def test_report_uses_only_real_data_and_reserves_model_charts(tmp_path):
    rep = build_report(ledger_path=tmp_path / "none.jsonl", links_path=tmp_path / "none2.jsonl")
    assert rep["synthetic_values"] is False
    assert rep["charts"]["resolved_deal_outcomes"]["by_resolution_type"] == \
        {"closed": 109, "terminated": 19, "withdrawn": 1}
    assert rep["charts"]["verified_geo_event_timeline"]["events"] == []
    assert len(rep["reserved_charts"]) == 9
    assert all(v["status"] == NOT_AVAILABLE for v in rep["reserved_charts"].values())


def test_committed_report_is_reproducible():
    from pathlib import Path
    from src.geo_intel.reporting import GEO_DIR
    committed = json.loads((GEO_DIR / "report" / "geo_research_report.json").read_text())
    assert committed == json.loads(json.dumps(build_report()))
