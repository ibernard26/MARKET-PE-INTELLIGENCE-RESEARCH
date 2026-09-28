"""Proof C identity review: lex order, contemporaneous SEC, no ticker reuse."""
from __future__ import annotations

import json
from datetime import date
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
from scripts.run_free_price_coverage import (
    _classify_deal,
    canonical_status,
    identity_proofs,
    overlap_population_counts,
    raw_provider_covered_count,
    recompute_row_derived,
    reconcile_totals_from_rows,
)
from src.ingest.equity_prices.schema import SecurityIdentity
from src.ingest.equity_prices.yahoo import (
    YahooEquityPriceProvider,
    yahoo_identity_problems,
)
from src.ingest.security_identity.name_match import names_agree


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


CORESITE = SecurityIdentity(
    deal_id="DEAL-COR-AMT-2021",
    ticker="COR",
    target_name="CoreSite Realty Corporation",
    announcement_date="2021-11-14",
)
CENCORA_COR_META = {
    "symbol": "COR",
    "shortName": "Cencora, Inc.",
    "longName": "Cencora, Inc.",
    "firstTradeDate": 631152000,  # 1990-01-01 — listing window is not the discriminator
}


def test_coresite_cor_versus_cencora_cor_is_ticker_reuse():
    assert names_agree("Cencora, Inc.", "CoreSite Realty Corporation") is False
    problems = yahoo_identity_problems(CENCORA_COR_META, CORESITE, date(2021, 11, 14))
    assert problems
    assert any("does not agree" in p for p in problems)
    # Closes are not an input to the identity rule.
    assert all("close" not in p.lower() and "price" not in p.lower() for p in problems)

    def fake_chart(url: str):
        return {"chart": {"result": [{
            "meta": CENCORA_COR_META,
            "timestamp": [1636934400, 1637020800, 1637107200],
            "indicators": {"quote": [{"close": [150.0, 151.0, 152.0]}]},
        }]}}

    res = YahooEquityPriceProvider(fetch_json=fake_chart).fetch_history(
        CORESITE, date(2021, 11, 15), date(2021, 12, 28))
    assert res.status.value == "IDENTITY_AMBIGUOUS"
    assert res.observations == []
    assert res.identity_verified is False


def test_yahoo_only_proof_c_cannot_admit_without_yahoo_identity():
    row = {
        "deal_id": "DEAL-COR-AMT-2021",
        "openfigi_status": "AMBIGUOUS",
        "tiingo_status": "IDENTITY_AMBIGUOUS",
        "tiingo_n": 0,
        "yahoo_n": 30,
        "combined_n": 30,
        "tiingo_identity_verified": False,
        "yahoo_identity_verified": False,
        "material_conflicts": 0,
        "identity_basis": REVIEWED_SEC_BASIS,
    }
    assert canonical_status(row) == ("DEFERRED_IDENTITY", "YAHOO_TICKER_REUSE_UNVALIDATED")
    assert _classify_deal(row) == "YAHOO_TICKER_REUSE_UNVALIDATED"


def test_committed_matrix_derived_fields_match_recompute():
    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "free_price_coverage_matrix.json").read_text())
    rows = matrix["deals"]
    meta = matrix["meta"]
    assert meta["raw_provider_covered"] == raw_provider_covered_count(rows)
    assert meta["gap_class_counts"] == {
        k: sum(1 for r in rows if r.get("final_coverage_status") == k)
        for k in meta["gap_class_counts"]
    }
    assert sum(meta["gap_class_counts"].values()) == len(rows)
    overlap = overlap_population_counts(rows)
    for key, val in overlap.items():
        assert meta[key] == val
    totals = reconcile_totals_from_rows(rows)
    assert totals == meta["reconcile"]
    for row in rows:
        fresh = recompute_row_derived(dict(row))
        assert fresh["raw_provider_covered"] == (
            max(int(row["tiingo_n"] or 0), int(row["yahoo_n"] or 0)) >= 3)
        assert fresh["identity_proofs"] == row["identity_proofs"]
        assert fresh["canonical_status"] == row["canonical_status"]
        assert fresh["identity_deferral"] == row["identity_deferral"]
        assert fresh["prints_admitted"] == row["prints_admitted"]
        assert fresh["final_coverage_status"] == row["final_coverage_status"]
        if row["canonical_status"] == "CANONICALLY_ADMITTED":
            assert row["final_coverage_status"] not in {
                "SECURITY_IDENTITY_AMBIGUOUS", "SECURITY_IDENTITY_NAME_MISMATCH",
                "OPENFIGI_NO_MATCH", "YAHOO_TICKER_REUSE_UNVALIDATED"}
            if "C_REVIEWED_SEC_MAPPING" in (row.get("identity_proofs") or []):
                assert row["final_coverage_status"] not in {
                    "SECURITY_IDENTITY_AMBIGUOUS", "SECURITY_IDENTITY_NAME_MISMATCH"}
        if row["canonical_status"] == "NO_PRICE_HISTORY":
            assert row["final_coverage_status"] not in {
                "SECURITY_IDENTITY_AMBIGUOUS", "SECURITY_IDENTITY_NAME_MISMATCH"}
        if int(row.get("tiingo_n") or 0) == 0 or int(row.get("yahoo_n") or 0) == 0:
            assert int(row.get("overlap_sessions") or 0) == 0


def test_cor_amt_and_wltw_dispositions():
    matrix = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "free_price_coverage_matrix.json").read_text())
    by = {r["deal_id"]: r for r in matrix["deals"]}
    cor = by["DEAL-COR-AMT-2021"]
    assert cor["canonical_status"] == "DEFERRED_IDENTITY"
    assert cor["identity_deferral"] == "YAHOO_TICKER_REUSE_UNVALIDATED"
    assert cor["prints_admitted"] is False
    wltw = by["DEAL-WLTW-AON-2020"]
    assert wltw["canonical_status"] == "NO_PRICE_HISTORY"
    assert wltw["final_coverage_status"] in {
        "NO_PUBLIC_PRICE_HISTORY", "TIINGO_NO_HISTORY", "TIINGO_NO_SYMBOL"}
    assert int(wltw["overlap_sessions"] or 0) == 0
    assert int(wltw["current_fetch_tiingo_n"] or 0) == 0
    assert int(wltw["current_fetch_yahoo_n"] or 0) == 0
    assert int(wltw["historical_reconciliation_sessions"] or 0) == 349
    assert wltw["historical_reconciliation_provenance"]["era"] == "PR44"
    assert wltw["historical_reconciliation_provenance"].get("historical_ticker") == "WTW"
    prints = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "target_price_manifest.json").read_text())["prints"]
    assert "DEAL-COR-AMT-2021" not in {p["deal_id"] for p in prints}
