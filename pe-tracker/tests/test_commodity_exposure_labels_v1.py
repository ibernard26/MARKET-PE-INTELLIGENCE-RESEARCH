"""Schema/chronology checks for the research-only commodity-exposure labels
(docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v1.md). Offline; reads committed files."""
import csv
import json
import random
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "data" / "research" / "commodity_exposure_labels_v1.csv"
PASSB = ROOT / "data" / "research" / "commodity_exposure_passB_v1.csv"
SUMMARY = ROOT / "data" / "research" / "commodity_exposure_coverage_v1.json"
MANIFEST = ROOT / "data" / "sec_deal_manifest.json"
FLAGS = ("producer", "consumer", "shipping_dependent", "hedged")
ALLOWED_FORMS = {"10-K", "10-K405", "10-KT", "10-KSB", "20-F", "40-F", "10-Q", "10-QSB"}
REASONS = {"no_qualifying_disclosure_in_reviewed_filings",
           "no_preannouncement_annual_report_in_window", "acquirer_identity_unresolved",
           "fetch_error"}


@pytest.fixture(scope="module")
def rows():
    return list(csv.DictReader(LABELS.open()))


@pytest.fixture(scope="module")
def manifest():
    return {d["deal_id"]: d for d in json.loads(MANIFEST.read_text())["deals"]}


def test_one_row_per_deal_party(rows, manifest):
    keys = [(r["deal_id"], r["party"]) for r in rows]
    assert len(keys) == len(set(keys))
    assert set(keys) == {(d, p) for d in manifest for p in ("target", "acquirer")}


def test_every_row_labeled_or_explicit_unknown(rows):
    for r in rows:
        assert r["exposure_status"] in {"labeled", "unknown", "not_yet_reviewed"}
        if r["exposure_status"] == "labeled":
            assert any(r[f] == "yes" for f in ("producer", "consumer", "shipping_dependent"))
            assert r["unknown_reason"] == ""
        elif r["exposure_status"] == "unknown":
            assert r["unknown_reason"] in REASONS


def test_no_silent_zero(rows):
    for r in rows:
        for f in ("producer", "consumer", "shipping_dependent"):
            assert r[f] in {"yes", "unknown"}, (r["deal_id"], f, r[f])
        assert r["hedged"] in {"yes", "no_disclosed", "unknown"}


def test_every_label_cites_a_pre_announcement_filing(rows, manifest):
    for r in rows:
        assert r["announce_date"] == manifest[r["deal_id"]]["announcement_timestamp"][:10]
        for f in FLAGS:
            if r[f] in ("yes", "no_disclosed"):
                assert r[f"{f}_accession"] and r[f"{f}_quote"], (r["deal_id"], f)
                assert r[f"{f}_form"] in ALLOWED_FORMS
                assert r[f"{f}_filing_date"] < r["announce_date"], (r["deal_id"], f)
                assert r[f"{f}_accession"] in r["filings_reviewed"]
            else:
                assert r[f"{f}_accession"] == ""


def test_pass_b_covers_the_preregistered_sample():
    ids = sorted(d["deal_id"] for d in json.loads(MANIFEST.read_text())["deals"])
    sample = sorted(random.Random(20261009).sample(ids, 20))
    b = list(csv.DictReader(PASSB.open()))
    assert sorted({r["deal_id"] for r in b}) == sample
    assert len(b) == 40
    for r in b:
        for f in ("producer", "consumer", "shipping_dependent"):
            assert r[f] in {"yes", "unknown"}
        assert r["hedged"] in {"yes", "no_disclosed", "unknown"}


def test_summary_is_research_only():
    s = json.loads(SUMMARY.read_text())
    assert s["research_only"] is True
    assert s["model_fit_executed"] is False and s["backtest_executed"] is False
    assert s["canonical_store_written"] is False
