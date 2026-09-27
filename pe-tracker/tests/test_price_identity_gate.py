"""Security-identity + reconciliation admission gate for the free price stack.

A ticker's prices enter the canonical manifest (and the >=20-deal readiness
count) only when the ticker is shown to be the SEC target: tickers get reused,
especially across the 2014–2015 corpus. Offline fakes only.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.ingest.equity_prices import (
    NormalizedEquityObservation, PriceProviderOrchestrator, ProviderStatus, SecurityIdentity,
    SecurityIdentityResolver, TiingoEquityPriceProvider)
from src.ingest.equity_prices.yahoo import YahooEquityPriceProvider
from src.ingest.security_identity.name_match import names_agree
from src.ingest.security_identity.openfigi import OpenFIGISecurityIdentityResolver
from scripts.audit_free_price_coverage import _covered
from src.ingest.equity_prices.identity import REVIEWED_SEC_BASIS
from src.ingest.equity_prices.reconciliation import (
    ABS_EPS, RECONCILE_RULE_VERSION, RECONCILE_RULES, REL_EPS, THESIS_RECONCILE_RULE,
    ReconciliationError, classify_close_pair, reconcile_series)
from scripts.run_free_price_coverage import (
    _classify_deal, admit_prints, canonical_status, identity_proofs)

IDENT = SecurityIdentity(deal_id="DEAL-ACME-BIG-2015", ticker="ACME",
                         target_name="Acme Widgets, Inc.",
                         announcement_date="2015-03-02")
META = {"ticker": "ACME", "name": "ACME WIDGETS INC", "exchangeCode": "NYSE",
        "startDate": "1999-01-04", "endDate": "2015-06-30"}
ROWS = [{"date": f"2015-03-0{d}T00:00:00.000Z", "close": 10.0 + d, "adjClose": 10.0 + d}
        for d in (2, 3, 4)]


@pytest.mark.parametrize("a,b,ok", [
    ("ACME WIDGETS INC", "Acme Widgets, Inc.", True),
    ("Acme Widgets Holdings Corp", "ACME WIDGETS", True),
    ("Procter & Gamble Co", "PROCTER AND GAMBLE", True),
    ("Acme Bank", "Acme Widgets, Inc.", False),          # reused-ticker case
    ("American Airlines Group", "American Express Co", False),
    ("Inc.", "Corp", False),                             # nothing significant
    (None, "Acme", False),
])
def test_names_agree_is_strict(a, b, ok):
    assert names_agree(a, b) is ok


def tiingo(meta, calls):
    def fetch(url, headers):
        calls.append(url)
        return (200, ROWS) if "/prices" in url else (200, meta)
    return TiingoEquityPriceProvider(token="tok", fetch_json=fetch, min_interval_s=0)


def test_tiingo_passes_when_name_and_listing_agree():
    calls = []
    r = tiingo(META, calls).fetch_history(IDENT, date(2015, 2, 27), date(2015, 3, 9))
    assert r.status == ProviderStatus.AVAILABLE and len(r.observations) == 3


def test_tiingo_reused_ticker_is_deferred_before_prices_are_fetched():
    calls = []
    r = tiingo({**META, "name": "Acme Bank Corp"}, calls).fetch_history(
        IDENT, date(2015, 2, 27), date(2015, 3, 9))
    assert r.status == ProviderStatus.IDENTITY_AMBIGUOUS and not r.observations
    assert not any("/prices" in u for u in calls)


@pytest.mark.parametrize("start,end", [("2016-01-04", ""), ("1999-01-04", "2014-12-31"),
                                       ("", "")])
def test_tiingo_listing_interval_must_cover_announcement(start, end):
    r = tiingo({**META, "startDate": start, "endDate": end}, []).fetch_history(
        IDENT, date(2015, 2, 27), date(2015, 3, 9))
    assert r.status == ProviderStatus.IDENTITY_AMBIGUOUS


def test_tiingo_without_target_name_cannot_prove_identity():
    ident = SecurityIdentity(deal_id="D", ticker="ACME", announcement_date="2015-03-02")
    r = tiingo(META, []).fetch_history(ident, date(2015, 2, 27), date(2015, 3, 9))
    assert r.status == ProviderStatus.IDENTITY_AMBIGUOUS


def test_orchestrator_does_not_fall_back_to_yahoo_on_identity_ambiguity():
    yahoo_called = []

    def chart(url):
        yahoo_called.append(url)
        return {"chart": {"result": [{"timestamp": [1425306600, 1425393000],
                                      "indicators": {"quote": [{"close": [1.0, 1.1]}]}}]}}

    orch = PriceProviderOrchestrator(
        providers=[tiingo({**META, "name": "Acme Bank Corp"}, []),
                   YahooEquityPriceProvider(fetch_json=chart)],
        resolver=SecurityIdentityResolver(map_path=Path("/nonexistent"),
                                          user_agent="t", fetch_json=lambda u: {}))
    out = orch.fetch_deal({"deal_id": IDENT.deal_id, "target": IDENT.target_name,
                           "announcement_timestamp": "2015-03-02",
                           "resolution_timestamp": "2015-03-06"})
    assert out["status"] == "IDENTITY_AMBIGUOUS" and out["observations"] == []
    assert yahoo_called == []


def figi_post(name):
    def post(url, headers, body):
        return 200, [{"data": [{"figi": "BBG1", "compositeFIGI": "BBG1", "name": name,
                                "ticker": "ACME", "exchCode": "US",
                                "securityType": "Common Stock", "marketSector": "Equity"}]}]
    return post


@pytest.mark.parametrize("name,status", [("ACME WIDGETS INC", "MATCHED"),
                                         ("ACME BANK CORP", "NAME_MISMATCH")])
def test_openfigi_single_candidate_must_be_the_target_issuer(tmp_path, name, status):
    r = OpenFIGISecurityIdentityResolver(api_key="k", cache_dir=tmp_path,
                                         post_json=figi_post(name), min_interval_s=0)
    out = r.resolve_deal({"deal_id": IDENT.deal_id, "target": IDENT.target_name}, ticker="ACME")
    assert out.mapping_status == status
    assert (out.figi is None) == (status != "MATCHED")


BASE = {"openfigi_status": "MATCHED", "tiingo_status": "ok", "tiingo_n": 5,
        "tiingo_identity_verified": True, "yahoo_n": 5, "combined_n": 5,
        "material_conflicts": 0, "identity_basis": "deal_id_convention"}
YAHOO_ONLY = {**BASE, "openfigi_status": "NO_MATCH", "tiingo_status": "SYMBOL_NOT_FOUND",
              "tiingo_n": 0, "tiingo_identity_verified": False}


@pytest.mark.parametrize("patch,admitted,canon,reason,cls", [
    ({}, True, "CANONICALLY_ADMITTED", None, "MULTI_PROVIDER_CONFIRMED"),
    # NO_MATCH is not negative evidence: Tiingo's own verification (B) suffices
    ({"openfigi_status": "NO_MATCH"}, True, "CANONICALLY_ADMITTED", None, "OPENFIGI_NO_MATCH"),
    # OpenFIGI MATCHED alone (A) suffices for Yahoo-only prices
    ({"tiingo_status": "SYMBOL_NOT_FOUND", "tiingo_n": 0, "tiingo_identity_verified": False},
     True, "CANONICALLY_ADMITTED", None, "YAHOO_ONLY"),
    # Tiingo verified identity but has no history in window: Yahoo prints admitted (B)
    ({"openfigi_status": "NO_MATCH", "tiingo_status": "NO_HISTORY", "tiingo_n": 0},
     True, "CANONICALLY_ADMITTED", None, "OPENFIGI_NO_MATCH"),
    ({"openfigi_status": "AMBIGUOUS"}, False, "DEFERRED_IDENTITY", "OPENFIGI_AMBIGUOUS",
     "SECURITY_IDENTITY_AMBIGUOUS"),
    ({"openfigi_status": "NAME_MISMATCH"}, False, "DEFERRED_IDENTITY", "OPENFIGI_NAME_MISMATCH",
     "SECURITY_IDENTITY_NAME_MISMATCH"),
    ({"tiingo_status": "IDENTITY_AMBIGUOUS", "tiingo_n": 0, "tiingo_identity_verified": False},
     False, "DEFERRED_IDENTITY", "TIINGO_IDENTITY_AMBIGUOUS", "SECURITY_IDENTITY_AMBIGUOUS"),
    ({"material_conflicts": 1}, False, "DEFERRED_PRICE_CONFLICT", None, "DEFER_PRICE_CONFLICT"),
    ({"tiingo_n": 0, "yahoo_n": 0, "combined_n": 0}, False, "NO_PRICE_HISTORY", None,
     "TIINGO_NO_HISTORY"),                                  # legacy gap_class label
    ({"combined_n": 2, "tiingo_n": 2, "yahoo_n": 2}, True, "INSUFFICIENT_CANONICAL_PRINTS",
     None, "OTHER"),
])
def test_manifest_admission_rule(patch, admitted, canon, reason, cls):
    row = {**BASE, **patch}
    assert admit_prints(row) is admitted
    assert canonical_status(row) == (canon, reason)
    assert _classify_deal(row) == cls
    row["canonical_status"] = canon
    assert _covered(row) is (canon == "CANONICALLY_ADMITTED")


@pytest.mark.parametrize("tiingo_status", ["SYMBOL_NOT_FOUND", "NO_HISTORY", "CREDENTIALS_REQUIRED",
                                           "TRANSIENT_FAILURE"])
def test_yahoo_only_without_affirmative_proof_is_deferred(tiingo_status):
    """Reused-ticker risk: Yahoo serves whoever holds the symbol *today*."""
    row = {**YAHOO_ONLY, "tiingo_status": tiingo_status}
    assert identity_proofs(row) == []
    assert canonical_status(row) == ("DEFERRED_IDENTITY", "DEFER_IDENTITY_UNCONFIRMED")
    assert admit_prints(row) is False
    assert _classify_deal(row) == "DEFER_IDENTITY_UNCONFIRMED"
    row["canonical_status"] = canonical_status(row)[0]
    assert _covered(row) is False


def test_yahoo_only_admitted_with_reviewed_sec_mapping():
    row = {**YAHOO_ONLY, "identity_basis": REVIEWED_SEC_BASIS}
    assert identity_proofs(row) == ["C_REVIEWED_SEC_MAPPING"]
    assert canonical_status(row) == ("CANONICALLY_ADMITTED", None)


def test_raw_coverage_never_counts_as_canonical():
    row = {**YAHOO_ONLY, "canonical_status": canonical_status(YAHOO_ONLY)[0]}
    assert max(row["tiingo_n"], row["yahoo_n"]) >= 3          # raw-provider covered
    assert _covered(row) is False                              # but not canonical


# ------------------------------------------------ proof C: reviewed SEC mapping
def resolver_with(tmp_path, row):
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"tickers": [{"deal_id": IDENT.deal_id, "ticker": "ACME", **row}]}))
    return SecurityIdentityResolver(map_path=p, fetch_json=lambda u: {})


DEAL = {"deal_id": IDENT.deal_id, "target": IDENT.target_name,
        "announcement_timestamp": "2015-03-02", "resolution_timestamp": "2015-06-30"}


@pytest.mark.parametrize("row,basis", [
    ({"sec_accession": "0001193125-15-012345", "sec_filed_date": "2015-02-20"}, REVIEWED_SEC_BASIS),
    ({"sec_accession": "0001193125-15-012345", "sec_filed_date": "2015-06-30"}, REVIEWED_SEC_BASIS),
    ({"sec_accession": "0001193125-15-012345", "sec_filed_date": "2013-01-02"}, "reviewed_map"),
    ({"sec_accession": "0001193125-15-012345", "sec_filed_date": "2016-01-04"}, "reviewed_map"),
    ({"sec_accession": "not-an-accession", "sec_filed_date": "2015-02-20"}, "reviewed_map"),
    ({"basis": REVIEWED_SEC_BASIS}, "reviewed_map"),          # self-declared basis ignored
])
def test_reviewed_mapping_needs_contemporaneous_sec_evidence(tmp_path, row, basis):
    ident, defer = resolver_with(tmp_path, row).resolve(DEAL)
    assert defer is None and ident.ticker_basis == basis


# --------------------------------------------- provider identity_verified flag
def test_tiingo_sets_identity_verified_only_after_checks_pass():
    ok = tiingo(META, []).fetch_history(IDENT, date(2015, 2, 27), date(2015, 3, 9))
    assert ok.identity_verified is True
    empty = TiingoEquityPriceProvider(token="t", min_interval_s=0,
                                      fetch_json=lambda u, h: (200, []) if "/prices" in u
                                      else (200, META)).fetch_history(
        IDENT, date(2015, 2, 27), date(2015, 3, 9))
    assert empty.status == ProviderStatus.NO_HISTORY and empty.identity_verified is True
    bad = tiingo({**META, "name": "Acme Bank Corp"}, []).fetch_history(
        IDENT, date(2015, 2, 27), date(2015, 3, 9))
    assert bad.identity_verified is False
    missing = TiingoEquityPriceProvider(token="t", min_interval_s=0,
                                        fetch_json=lambda u, h: (404, {})).fetch_history(
        IDENT, date(2015, 2, 27), date(2015, 3, 9))
    assert missing.identity_verified is False


# ------------------------------------------------------ price_reconcile_v2 (frozen)
def test_reconcile_rules_are_frozen():
    assert RECONCILE_RULES == {"price_reconcile_v1": (1e-4, 1e-6),
                               "price_reconcile_v2": (0.01, 1e-4)}
    assert THESIS_RECONCILE_RULE == "price_reconcile_v2"
    assert (RECONCILE_RULE_VERSION, ABS_EPS, REL_EPS) == ("price_reconcile_v1", 1e-4, 1e-6)


@pytest.mark.parametrize("a,b,v1,v2", [
    (10.00, 10.00, "EXACT_MATCH", "EXACT_MATCH"),
    (10.00, 10.00005, "TOLERABLE_MATCH", "TOLERABLE_MATCH"),
    (10.00, 10.01, "MATERIAL_CONFLICT", "TOLERABLE_MATCH"),     # 1 cent (abs)
    (10.00, 10.02, "MATERIAL_CONFLICT", "MATERIAL_CONFLICT"),
    (500.00, 500.05, "MATERIAL_CONFLICT", "TOLERABLE_MATCH"),   # 1 bp (rel)
    (500.00, 500.10, "MATERIAL_CONFLICT", "MATERIAL_CONFLICT"),
])
def test_v1_unchanged_and_v2_thresholds(a, b, v1, v2):
    assert classify_close_pair(a, b) == v1                         # default stays v1
    assert classify_close_pair(a, b, "price_reconcile_v1") == v1
    assert classify_close_pair(a, b, "price_reconcile_v2") == v2


def _o(provider, d, c, field="close"):
    return NormalizedEquityObservation(deal_id="D", session_date=d, close=c, provider=provider,
                                       provider_symbol="X", retrieval_timestamp="t",
                                       close_field_used=field)


def test_v2_series_conflict_defers_and_reports_rule():
    t = [_o("tiingo", "2015-03-02", 10.0), _o("tiingo", "2015-03-03", 10.0)]
    y = [_o("yahoo", "2015-03-02", 10.01), _o("yahoo", "2015-03-03", 10.5)]
    r = reconcile_series(t, y, rule=THESIS_RECONCILE_RULE)
    assert r["rule_version"] == "price_reconcile_v2"
    assert (r["tolerable_match"], r["material_conflict"], r["status"]) == (
        1, 1, "DEFER_PRICE_CONFLICT")


def test_reconciliation_compares_raw_close_only():
    t = [_o("tiingo", "2015-03-02", 10.0)]
    y = [_o("yahoo", "2015-03-02", 10.0, field="adjusted_close")]
    with pytest.raises(ReconciliationError, match="raw close only"):
        reconcile_series(t, y, rule=THESIS_RECONCILE_RULE)


def test_coverage_runner_uses_v2():
    import scripts.run_free_price_coverage as R
    assert R.THESIS_RECONCILE_RULE == "price_reconcile_v2"
    src = Path(R.__file__).read_text()
    assert "reconcile_series(t_obs, y_obs, rule=THESIS_RECONCILE_RULE)" in src
