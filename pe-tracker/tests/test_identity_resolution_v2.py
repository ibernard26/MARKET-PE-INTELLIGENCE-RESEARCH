"""Label-blind/outcome-type-blind identity round v2: Proof C, OpenFIGI v2, ordering."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.identity_resolution_round_v2 as R
from src.ingest.security_identity import admission_v2 as A
from src.ingest.security_identity.proof_c import (
    NO_EVIDENCE, RESOLVED, STILL_AMBIGUOUS, Filing, classify, extract)

ROOT = Path(__file__).resolve().parents[1]
CIK = 123456
DEAL = dict(deal_id="DEAL-ACME-BIG-2015", ticker="ACME", target_cik=CIK,
            announcement="2015-03-02", resolution="2015-09-30")


def filing(form="DEFM14A", filed="2015-04-10", cik=CIK, acc="0001-15-000001"):
    return Filing(accession=acc, form=form, filing_date=filed, filer_cik=cik,
                  primary_document="d.htm", url=f"https://www.sec.gov/x/{acc}")


def ev(doc, **kw):
    f = filing(**kw)
    return extract(DEAL["deal_id"], DEAL["ticker"], f, doc, DEAL["target_cik"],
                   DEAL["announcement"], DEAL["resolution"])


# ------------------------------------------------------------ Proof C rules
@pytest.mark.parametrize("doc", [
    "<p>Acme Widgets, Inc. (NASDAQ: ACME) today announced</p>",
    "<p>our common stock is listed on the NYSE under the symbol &ldquo;ACME&rdquo;.</p>",
    "<table><tr><td>Trading Symbol(s)</td></tr><tr><td>Common</td><td>ACME</td>"
    "<td>The Nasdaq Stock Market LLC</td></tr></table>",
])
def test_contemporaneous_target_filing_resolves(doc):
    out = classify([ev(doc)])
    assert out["status"] == RESOLVED and out["sec_accession"] == "0001-15-000001"
    assert out["sec_filed_date"] == "2015-04-10" and "ACME" in out["snippet"]


def test_filer_must_be_the_target():
    e = ev("(NASDAQ: ACME)", cik=999)
    assert e.reject_reason == "FILER_NOT_TARGET" and not e.matched
    assert classify([e])["status"] == NO_EVIDENCE


def test_modern_ticker_reuse_cannot_qualify():
    # A filing from long after the deal window naming ACME is not contemporaneous.
    e = ev("(NASDAQ: ACME)", filed="2024-06-01")
    assert e.reject_reason == "NOT_CONTEMPORANEOUS"
    assert classify([e])["status"] == NO_EVIDENCE
    early = ev("(NASDAQ: ACME)", filed="2013-01-01")
    assert early.reject_reason == "NOT_CONTEMPORANEOUS"


def test_disallowed_form_and_partial_token():
    assert ev("(NASDAQ: ACME)", form="S-4").reject_reason == "FORM_NOT_ALLOWED"
    assert classify([ev("(NASDAQ: ACMEX) and (NYSE: ACMEZ)")])["status"] == STILL_AMBIGUOUS
    assert classify([ev("no symbols here")])["status"] == NO_EVIDENCE
    assert classify([])["status"] == NO_EVIDENCE


def test_evidence_records_document_hash_and_location():
    e = ev("(NASDAQ: ACME)")
    assert len(e.document_sha256) == 64 and e.url.endswith("0001-15-000001")


# -------------------------------- label-blind/outcome-type-blind queue
def _matrix(tmp_path):
    deals = [{"deal_id": d, "target": f"{d} Inc", "target_cik": i,
              "announcement_timestamp": "2015-03-02", "resolution_timestamp": "2015-09-30",
              "resolution_type": rt} for i, (d, rt) in enumerate(
        [("DEAL-ZZZ-A-2015", "terminated"), ("DEAL-AAA-B-2015", "closed"),
         ("DEAL-MMM-C-2015", "withdrawn")], start=1)]
    rows = [{"deal_id": d["deal_id"], "canonical_status": "DEFERRED_IDENTITY",
             "historical_ticker": d["deal_id"].split("-")[1]} for d in deals]
    rows.append({"deal_id": "DEAL-OK-X-2015", "canonical_status": "CANONICALLY_ADMITTED"})
    m, s = tmp_path / "m.json", tmp_path / "s.json"
    m.write_text(json.dumps({"deals": rows}))
    s.write_text(json.dumps({"deals": deals + [{"deal_id": "DEAL-OK-X-2015"}]}))
    return m, s


def test_queue_is_deal_id_ordered_and_carries_no_outcome(tmp_path):
    q = R.review_queue(*_matrix(tmp_path))
    assert [x["deal_id"] for x in q] == sorted(x["deal_id"] for x in q)
    assert len(q) == 3
    for x in q:
        assert set(x) == set(R.QUEUE_FIELDS)
    src = (ROOT / "scripts" / "identity_resolution_round_v2.py").read_text()
    assert "resolution_type" not in src
    assert "outcome_blind" not in src
    assert "label-blind/outcome-type-blind" in src
    assert "resolution_date" in R.QUEUE_FIELDS


def test_plan_filters_and_orders_deterministically(tmp_path):
    q = R.review_queue(*_matrix(tmp_path))[:1]
    sub = {"filings": {"recent": {
        "accessionNumber": ["a1", "a2", "a3", "a4", "a5"],
        "form": ["10-Q", "DEFM14A", "S-4", "8-K", "DEFM14A"],
        "filingDate": ["2015-05-01", "2015-04-01", "2015-04-01", "2015-03-02", "2020-01-01"],
        "primaryDocument": ["q.htm", "p.htm", "s.htm", "k.htm", "late.htm"]}, "files": []}}
    planned = R.plan(q, fetch_json=lambda url: sub)
    forms = [(f["form"], f["accession"]) for f in planned[0]["candidate_filings"]]
    assert forms == [("DEFM14A", "a2"), ("10-Q", "a1"), ("8-K", "a4")]
    assert planned == R.plan(q, fetch_json=lambda url: sub)


def test_fetch_and_classify_with_fake_sec(tmp_path):
    q = R.review_queue(*_matrix(tmp_path))[:1]
    planned = [{**q[0], "status": "PLANNED", "candidate_filings": [
        filing(cik=q[0]["target_cik"], acc="acc-1").__dict__]}]
    out = R.fetch_and_classify(planned, fetch_text=lambda u: f"(NYSE: {q[0]['ticker']})")
    assert out[0]["status"] == RESOLVED
    assert R.summarize(out)["RESOLVED_PROOF_C"] == 1


def test_committed_round_is_fetched_and_not_admitted():
    doc = json.loads((ROOT / "data" / "identity_resolution_round_v2.json").read_text())
    assert doc["selection_blinding"] == "label-blind/outcome-type-blind"
    assert doc["resolution_date_available"] is True
    assert "outcome_blind" not in doc
    assert doc["ordering_rule"] == "deal_id ascending"
    assert doc["step"] == "fetch_and_classify"
    summary = doc["summary"]
    assert summary["queue_size"] == 56 and summary["reviewed"] == 56
    assert summary["not_reviewed"] == 0
    assert summary["RESOLVED_PROOF_C"] + summary["STILL_AMBIGUOUS"] + summary["NO_SUFFICIENT_EVIDENCE"] == 56
    ids = [d["deal_id"] for d in doc["deals"]]
    assert ids == sorted(ids)
    for d in doc["deals"]:
        assert "resolution_type" not in d and "label" not in d
        assert "resolution_date" in d
    from src.ingest.security_identity.admission_v2 import RULE_STATUS
    assert RULE_STATUS == "PROPOSED_PENDING_AUDIT"


# --------------------------------------------------- identity_admission_v2
def row(name, comp, figi):
    return {"name": name, "compositeFIGI": comp, "figi": figi, "marketSector": "Equity"}


def test_openfigi_v2_counts_securities_not_venues():
    venues = [row("ACME WIDGETS INC", "BBG_C1", f"BBG_V{i}") for i in range(4)]
    assert A.openfigi_status_v2(venues, "Acme Widgets, Inc.")["status"] == A.MATCHED
    two = venues + [row("ACME WIDGETS INC", "BBG_C2", "BBG_V9")]
    assert A.openfigi_status_v2(two, "Acme Widgets, Inc.")["status"] == A.AMBIGUOUS
    other = [row("ACME BANK CORP", "BBG_C3", "BBG_V8")]
    assert A.openfigi_status_v2(other, "Acme Widgets, Inc.")["status"] == A.NAME_MISMATCH
    assert A.openfigi_status_v2([], "Acme")["status"] == A.NO_MATCH
    blank = [row("ACME WIDGETS INC", None, None),
             {"name": "ACME WIDGETS INC", "compositeFIGI": "  ", "figi": "",
              "marketSector": "Equity"}]
    refused = A.openfigi_status_v2(blank, "Acme Widgets, Inc.")
    assert refused["status"] == A.NO_MATCH and refused["composite_figis"] == []
    assert refused["status"] != A.MATCHED


def test_admission_v2_is_not_active_until_approved():
    assert A.RULE_STATUS == "PROPOSED_PENDING_AUDIT"
    with pytest.raises(A.RuleNotApprovedError):
        A.canonical_status_v2({}, None)


BASE = {"openfigi_status": "AMBIGUOUS", "tiingo_status": "ok", "tiingo_identity_verified": True,
        "tiingo_n": 50, "yahoo_n": 0, "combined_n": 50, "material_conflicts": 0}


@pytest.mark.parametrize("patch,proof_c,expected", [
    ({}, RESOLVED, ("CANONICALLY_ADMITTED", None)),                     # C + B override
    ({}, None, ("DEFERRED_IDENTITY", "OPENFIGI_AMBIGUOUS")),            # no C
    ({"tiingo_identity_verified": False, "tiingo_n": 0, "yahoo_n": 50},
     RESOLVED, ("DEFERRED_IDENTITY", "OPENFIGI_AMBIGUOUS")),            # Yahoo-only: no override
    ({"tiingo_status": "IDENTITY_AMBIGUOUS", "tiingo_identity_verified": False},
     RESOLVED, ("DEFERRED_IDENTITY", "TIINGO_IDENTITY_AMBIGUOUS")),     # never overridden
    ({"openfigi_status": "NAME_MISMATCH"}, RESOLVED, ("CANONICALLY_ADMITTED", None)),
    ({"material_conflicts": 1}, RESOLVED, ("DEFERRED_PRICE_CONFLICT", None)),
])
def test_admission_v2_rule(patch, proof_c, expected):
    assert A.canonical_status_v2({**BASE, **patch}, proof_c, rule_status=A.APPROVED) == expected
