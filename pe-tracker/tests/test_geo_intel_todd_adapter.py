"""Todd feed adapter + concurrency-safe ledger tests.

ALL FEED LINES BELOW ARE SYNTHETIC FIXTURES in Todd's events-YYYY-MM-DD.jsonl
shape. Article hosts end in `.invalid`; two items deliberately use real
official hosts (whitehouse.gov / sec.gov) to prove that a relayed official
link still cannot promote status. No real-world event is asserted.
"""
from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from src.geo_intel.pit import research_candidates
from src.geo_intel.schema import EvidenceRecord, SchemaError
from src.geo_intel.store import EvidenceLedger, LedgerLockTimeout, ledger_lock
from src.geo_intel.todd_adapter import ingest_todd_file, map_item
from src.geo_intel.verification import classify


def item(**kw):
    d = {"category": "hormuz_maritime",
         "statement": "SYNTHETIC: fixture agency reports vessel incidents",
         "reporting_entity": "Fixture Agency", "publisher": "Fixture News",
         "source_url": "https://news.fixture.invalid/a1",
         "published_at": "2030-01-02T10:00:00-05:00", "event_time": None,
         "first_observed_at": "2030-01-02T11:00:00-05:00",
         "claim_type": "reported_fact", "source_kind": "news_outlet",
         "geography": ["Iran", "Strait of Hormuz"], "sectors": ["shipping"],
         "brief_date": "2030-01-02", "notes": "SYNTHETIC fixture"}
    d.update(kw)
    return {k: v for k, v in d.items() if v is not ...}


FEED = [
    item(),
    item(statement="SYNTHETIC: law firm note", source_kind="law_firm_analysis",
         category="procurement_regulatory", publisher="Fixture LLP", published_at=None,
         source_url="https://law.fixture.invalid/n"),
    item(statement="SYNTHETIC: fixture desk says a fixture agreement could be announced this week and negotiators are reportedly working to narrow", source_kind="x_post",
         claim_type="unconfirmed_report", publisher="X: @fixture",
         source_url="https://x.fixture.invalid/status/1", notes="post text truncated by X API"),
    item(statement="SYNTHETIC: trend summary", source_kind="x_trend_summary",
         claim_type="unconfirmed_report", publisher="X", published_at=None,
         source_url="https://x.fixture.invalid/trend/1",
         notes="lower confidence: rests only on X trend summary"),
    item(statement="SYNTHETIC: official order text", source_kind="primary_official",
         claim_type="official_document", category="sanctions", publisher="White House",
         source_url="https://www.whitehouse.gov/fixture-not-a-real-page/",
         event_time="2030-01-01T20:00:00-05:00",
         primary_source_leads=["https://www.sec.gov/fixture-lead"]),
    item(statement="SYNTHETIC: Brent fell 1%", claim_type="market_data",
         category="energy_supply", source_url="https://mkt.fixture.invalid/x"),
]


def write(path: Path, rows) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_mapping_is_untrusted_and_preserves_provenance(tmp_path):
    feed = write(tmp_path / "events-2030-01-02.jsonl", FEED)
    L = EvidenceLedger(tmp_path / "staging.jsonl")
    rep = ingest_todd_file(feed, L)
    assert rep["counts"] == {"accepted": 5, "rejected": 1}
    assert rep["rows"][5]["reason"].startswith("market_data_not_an_event")
    for r in L.records:
        assert r.ingested_via == "todd_feed" and not r.retrieved_by_reviewer
        assert r.source_type in ("other", "social_post", "ai_brief")
        assert r.relayed_by == "Todd news brief 2030-01-02"
        assert r.provenance.startswith("events-2030-01-02.jsonl#L") and "sha256=" in r.provenance
        assert r.upstream_source_kind and r.upstream_claim_type
        assert r.sectors == () and r.upstream_sectors          # never auto-mapped
    first = L.records[0]
    assert first.geographies == ("IR",) and first.upstream_geography == ("Iran", "Strait of Hormuz")
    assert set(rep["status_counts"]) <= {"UNCONFIRMED", "ATTRIBUTED_CLAIM"}
    assert "statement_truncated" in rep["rows"][2]["flags"]
    assert "lower_confidence_upstream" in rep["rows"][3]["flags"]


def test_null_timestamps_are_preserved_never_coerced(tmp_path):
    feed = write(tmp_path / "f.jsonl", FEED[:2])
    L = EvidenceLedger(tmp_path / "s.jsonl")
    ingest_todd_file(feed, L)
    law = L.records[1]
    assert law.publication_timestamp is None and law.event_valid_timestamp is None
    assert law.known_at_basis == "first_observed_timestamp"
    stored = [json.loads(l) for l in (tmp_path / "s.jsonl").read_text().splitlines()]
    assert stored[1]["publication_timestamp"] is None and stored[1]["event_valid_timestamp"] is None
    rep = ingest_todd_file(write(tmp_path / "g.jsonl", [item(published_at="2030-01-02T10:00:00")]),
                           EvidenceLedger(tmp_path / "t.jsonl"))
    assert rep["rows"][0]["outcome"] == "rejected" and "bad_timestamp" in rep["rows"][0]["reason"]


def test_missing_optional_fields_are_absent(tmp_path):
    bare = {k: v for k, v in item().items() if k not in ("geography", "sectors", "notes",
                                                         "published_at", "event_time")}
    rec, why, flags = map_item(bare, "x#L1")
    assert why is None
    assert rec.affected_company_ids == () and rec.lead_urls == () and rec.geographies == ()
    assert rec.publication_timestamp is None and "published_at_missing" in flags
    rec, why, _ = map_item({k: v for k, v in item().items() if k != "source_url"}, "x#L1")
    assert rec is None and why == "missing_required_field:source_url"


def test_reingesting_same_file_is_idempotent(tmp_path):
    feed = write(tmp_path / "f.jsonl", FEED)
    path = tmp_path / "s.jsonl"
    ingest_todd_file(feed, EvidenceLedger(path))
    before = path.read_bytes()
    rep = ingest_todd_file(feed, EvidenceLedger(path))
    assert rep["counts"] == {"duplicate": 5, "rejected": 1}
    assert path.read_bytes() == before
    rep = ingest_todd_file(feed, EvidenceLedger(path))      # third time, fresh process view
    assert rep["counts"].get("accepted", 0) == 0


def test_revision_of_truncated_post_appends_update(tmp_path):
    path = tmp_path / "s.jsonl"
    ingest_todd_file(write(tmp_path / "d1.jsonl", [FEED[2]]), EvidenceLedger(path))
    fixed = dict(FEED[2], statement=FEED[2]["statement"] + " — full text recovered")
    L = EvidenceLedger(path)
    rep = ingest_todd_file(write(tmp_path / "d2.jsonl", [fixed]), L)
    assert rep["rows"][0]["outcome"] == "revision"
    orig, upd = L.records
    assert upd.revises_evidence_id == orig.evidence_id and upd.revision_type == "update"
    assert orig.original_statement == FEED[2]["statement"]        # never mutated
    assert len(L.revision_history(orig.evidence_id)) == 2
    assert classify(L.clusters()[orig.event_id]).status == "UNCONFIRMED"
    rep = ingest_todd_file(tmp_path / "d2.jsonl", EvidenceLedger(path))
    assert rep["rows"][0]["outcome"] == "duplicate"


def test_ai_relayed_items_cannot_promote_status(tmp_path):
    L = EvidenceLedger(tmp_path / "s.jsonl")
    official = FEED[4]
    # the same relayed official item arriving in five different daily files
    for i in range(5):
        ingest_todd_file(write(tmp_path / f"d{i}.jsonl",
                               [dict(official, brief_date=f"2030-01-0{i + 2}")]), L)
    for cl in L.clusters().values():
        r = classify(cl)
        assert r.status == "UNCONFIRMED" and r.untrusted_only
    assert L.records[0].lead_urls == ("https://www.sec.gov/fixture-lead",)
    assert research_candidates(L, "2031-01-01")["admitted"] == []
    # trusting the AI item directly is refused by the schema
    d = json.loads(L.records[0].to_json())
    for bad in ({"source_type": "primary_official"}, {"retrieved_by_reviewer": True}):
        with pytest.raises(SchemaError):
            EvidenceRecord.from_dict({**d, **bad}).validate()
    # a status the feed asserts is ignored (flagged as unknown field)
    rec, _, flags = map_item(dict(official, status="VERIFIED_PRIMARY"), "x#L1")
    assert "unknown_field:status" in flags and rec.claimed_status_by_source is None


def _worker(args):
    ledger, feed = args
    ingest_todd_file(Path(feed), EvidenceLedger(Path(ledger)))
    return True


def test_concurrent_writers_produce_one_consistent_ledger(tmp_path):
    shared = write(tmp_path / "shared.jsonl", FEED)
    own = [write(tmp_path / f"own{i}.jsonl",
                 [item(statement=f"SYNTHETIC: writer {i} item {j}",
                       source_url=f"https://w{i}.fixture.invalid/{j}") for j in range(5)])
           for i in range(6)]
    ledger = tmp_path / "s.jsonl"
    jobs = [(str(ledger), str(shared))] * 6 + [(str(ledger), str(p)) for p in own]
    with mp.get_context("fork").Pool(8) as pool:
        assert all(pool.map(_worker, jobs))
    lines = ledger.read_text().splitlines()
    ids = [json.loads(l)["evidence_id"] for l in lines]
    assert len(ids) == len(set(ids)) == 5 + 6 * 5
    assert len(EvidenceLedger(ledger).records) == 35        # every line re-validates
    assert not list(tmp_path.glob(".s.jsonl.*.tmp"))        # no stray temp files


def test_writer_lock_is_exclusive(tmp_path):
    path = tmp_path / "s.jsonl"
    with ledger_lock(path):
        with pytest.raises(LedgerLockTimeout):
            EvidenceLedger(path, lock_timeout_s=0.2).extend(
                [map_item(FEED[0], "x#L1")[0]])
    assert not path.exists()
