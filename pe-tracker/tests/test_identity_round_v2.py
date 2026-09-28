"""Proof C identity review: lex order, contemporaneous SEC, no ticker reuse."""
from __future__ import annotations

import json
from pathlib import Path

from src.ingest.equity_prices.identity import REVIEWED_SEC_BASIS, SEC_ACCESSION
from src.ingest.equity_prices.identity_review_v2 import (
    NO_SUFFICIENT_EVIDENCE,
    RESOLVED_PROOF_C,
    STILL_AMBIGUOUS,
    assert_outcome_blind_order,
    classify_extracted,
    deferred_rows_in_review_order,
    extract_identity_from_filing,
    identity_review_order,
    qualifies_as_proof_c,
    ticker_reuse_or_convention_is_not_proof,
)
from scripts.run_free_price_coverage import canonical_status, identity_proofs


def test_committed_round_is_lexicographic_and_outcome_blind():
    path = Path(__file__).resolve().parents[1] / "data" / "identity_resolution_round_v2.json"
    doc = json.loads(path.read_text())
    ids = [d["deal_id"] for d in doc["deals"]]
    assert ids == sorted(ids)
    assert len(ids) == 56 == doc["IDENTITIES_REVIEWED"]
    assert doc["outcome_fields_used_for_prioritization"] == []
    assert doc["NEW_PROOF_C"] + doc["STILL_AMBIGUOUS"] + doc["NO_SUFFICIENT_EVIDENCE"] == 56
    for row in doc["deals"]:
        assert "resolution_type" not in row
        assert row["status"] in {RESOLVED_PROOF_C, STILL_AMBIGUOUS, NO_SUFFICIENT_EVIDENCE}
        if row["status"] == RESOLVED_PROOF_C:
            assert SEC_ACCESSION.match(row["sec_accession"])
            assert row["filing_date"]
            assert row["form"]
            assert row["historical_ticker"]
            assert row["evidence_location"]

    ids = ["DEAL-ZEN-ZORO-2022", "DEAL-ADVENT-SSCTEC-2015", "DEAL-CI-ANTM-2015"]
    assert identity_review_order(ids) == [
        "DEAL-ADVENT-SSCTEC-2015",
        "DEAL-CI-ANTM-2015",
        "DEAL-ZEN-ZORO-2022",
    ]


def test_review_order_ignores_outcome_labels():
    rows = [
        {"deal_id": "DEAL-B", "canonical_status": "DEFERRED_IDENTITY",
         "resolution_type": "closed", "status": "closed"},
        {"deal_id": "DEAL-A", "canonical_status": "DEFERRED_IDENTITY",
         "resolution_type": "terminated", "y": 1},
        {"deal_id": "DEAL-C", "canonical_status": "CANONICALLY_ADMITTED",
         "resolution_type": "terminated"},
    ]
    order = assert_outcome_blind_order(rows)
    assert order == ["DEAL-A", "DEAL-B"]
    assert [r["deal_id"] for r in deferred_rows_in_review_order(rows)] == order


def test_proof_c_requires_contemporaneous_sec_accession():
    ann, res = "2015-03-02", "2015-06-30"
    good = {"sec_accession": "0001193125-15-012345", "sec_filed_date": "2015-02-20",
            "ticker": "ACME"}
    assert qualifies_as_proof_c(good, ann, res) is True
    too_old = {**good, "sec_filed_date": "2013-01-02"}
    assert qualifies_as_proof_c(too_old, ann, res) is False
    too_new = {**good, "sec_filed_date": "2016-01-04"}
    assert qualifies_as_proof_c(too_new, ann, res) is False
    bad_acc = {**good, "sec_accession": "not-an-accession"}
    assert qualifies_as_proof_c(bad_acc, ann, res) is False
    self_declared = {"basis": REVIEWED_SEC_BASIS, "ticker": "ACME"}
    assert qualifies_as_proof_c(self_declared, ann, res) is False


def test_ticker_reuse_and_deal_id_convention_cannot_qualify():
    assert ticker_reuse_or_convention_is_not_proof(
        ticker="UPBD", source="sec_company_tickers") is True
    assert ticker_reuse_or_convention_is_not_proof(
        ticker="RCII", source="deal_id_convention", deal_id="DEAL-RCII-VINTAGE-2018") is True
    # contemporaneous accession is what would qualify — convention alone does not
    assert qualifies_as_proof_c(
        {"deal_id": "DEAL-RCII-VINTAGE-2018", "ticker": "RCII",
         "source": "deal_id_convention"},
        "2018-06-17", "2018-12-31") is False


def test_cover_and_press_extract_target_ticker_not_acquirer():
    html = """
    <ix:nonNumeric name="dei:TradingSymbol">HCP</ix:nonNumeric>
    Trading Symbol(s) Name of each exchange on which registered
    Class A Common Stock HCP The NASDAQ Stock Market
    """
    out = extract_identity_from_filing(html, target_name="HashiCorp, Inc.", filer_is_target=True)
    assert out["historical_ticker"] == "HCP"
    assert out["evidence_location"] in {"dei:TradingSymbol", "8-K_cover_trading_symbol"}

    press = """
    SANTA CLARA and SAN JOSE, June 1, 2015 Intel Corporation (NASDAQ: INTC)
    and Altera Corporation (NASDAQ: ALTR) today announced a definitive agreement
    """
    out = extract_identity_from_filing(
        press, target_name="Altera Corporation", filer_is_target=True)
    assert out["historical_ticker"] == "ALTR"
    assert out["name_adjacent_ticker"] == "ALTR"
    assert "INTC" in out["parenthetical_tickers"]


def test_sgml_header_ticker():
    raw = "<SEC-HEADER>\n<TICKER>CI\n<EXCHANGE>NYSE\n</SEC-HEADER>"
    out = extract_identity_from_filing(
        raw, target_name="Cigna Corporation", filer_is_target=True)
    assert out["historical_ticker"] == "CI"
    assert out["evidence_location"] == "SEC_HEADER_TICKER"
    assert classify_extracted(out, deal_id="DEAL-CI-ANTM-2015") == RESOLVED_PROOF_C


def test_nyse_mkt_parenthetical_is_target_not_acquirer():
    press = (
        "LKQ Corporation (Nasdaq: LKQ) and The Coast Distribution System, Inc. "
        "(NYSE MKT: CRV) today announced that they have signed a definitive agreement"
    )
    out = extract_identity_from_filing(
        press, target_name="COAST DISTRIBUTION SYSTEM INC", filer_is_target=True)
    assert out["historical_ticker"] == "CRV"
    assert out["name_adjacent_ticker"] == "CRV"


def test_cover_fragments_are_not_tickers():
    bogus = "Trading Symbol(s) Name of each exchange NEW YORK STOCK EXCHANGE indicated"
    out = extract_identity_from_filing(
        bogus, target_name="Red Hat, Inc.", filer_is_target=True)
    assert out["cover_ticker"] is None or out["cover_ticker"] not in {"YORK", "EXCHA", "INDIC"}
    if out["historical_ticker"] in {"YORK", "EXCHA", "INDIC"}:
        raise AssertionError(out)

    out = extract_identity_from_filing(
        "Item 1.01 Entry into a Material Definitive Agreement",
        target_name="Bolt Technology Corp", filer_is_target=True)
    assert out["historical_ticker"] is None
    assert classify_extracted(out, deal_id="DEAL-BOLT-TELEDY-2014") == NO_SUFFICIENT_EVIDENCE


def test_proof_c_overrides_openfigi_ambiguous_veto():
    row = {
        "openfigi_status": "AMBIGUOUS",
        "tiingo_status": "ok",
        "tiingo_n": 5,
        "yahoo_n": 5,
        "combined_n": 5,
        "tiingo_identity_verified": True,
        "material_conflicts": 0,
        "identity_basis": REVIEWED_SEC_BASIS,
    }
    assert "C_REVIEWED_SEC_MAPPING" in identity_proofs(row)
    assert canonical_status(row) == ("CANONICALLY_ADMITTED", None)


def test_openfigi_ambiguous_without_proof_c_still_deferred():
    row = {
        "openfigi_status": "AMBIGUOUS",
        "tiingo_status": "ok",
        "tiingo_n": 5,
        "yahoo_n": 0,
        "combined_n": 5,
        "tiingo_identity_verified": True,
        "material_conflicts": 0,
        "identity_basis": "deal_id_convention",
    }
    assert canonical_status(row) == ("DEFERRED_IDENTITY", "OPENFIGI_AMBIGUOUS")


def test_committed_proof_c_does_not_claim_unverified_proof_b():
    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "free_price_coverage_matrix.json").read_text())
    identity = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "tiingo_identity_evidence.json").read_text())
    evidence_ids = {r["deal_id"] for r in identity["deals"] if r.get("proof_B_earned")}
    for row in matrix["deals"]:
        proofs = row.get("identity_proofs") or []
        if "B_TIINGO_NAME_AND_LISTING_WINDOW" in proofs:
            assert row["deal_id"] in evidence_ids
        if row.get("canonical_status") == "CANONICALLY_ADMITTED" and "C_REVIEWED_SEC_MAPPING" in proofs:
            assert row.get("identity_basis") == REVIEWED_SEC_BASIS


def test_ambiguous_parentheticals_without_name_link_stay_ambiguous():
    text = "Acquirer (NASDAQ: BIGA) also mentioned TargetHoldCo (NYSE: BIGB) without the issuer name."
    out = extract_identity_from_filing(
        text, target_name="Unrelated Issuer LLC", filer_is_target=False)
    assert classify_extracted(out, deal_id="DEAL-X-Y-2015") in {
        STILL_AMBIGUOUS, NO_SUFFICIENT_EVIDENCE}
    assert out["historical_ticker"] is None
