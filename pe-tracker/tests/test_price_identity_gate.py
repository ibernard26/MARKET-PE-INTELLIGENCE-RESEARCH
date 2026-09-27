"""Security-identity + reconciliation admission gate for the free price stack.

A ticker's prices enter the canonical manifest (and the >=20-deal readiness
count) only when the ticker is shown to be the SEC target: tickers get reused,
especially across the 2014–2015 corpus. Offline fakes only.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.ingest.equity_prices import (
    PriceProviderOrchestrator, ProviderStatus, SecurityIdentity,
    SecurityIdentityResolver, TiingoEquityPriceProvider)
from src.ingest.equity_prices.yahoo import YahooEquityPriceProvider
from src.ingest.security_identity.name_match import names_agree
from src.ingest.security_identity.openfigi import OpenFIGISecurityIdentityResolver
from scripts.audit_free_price_coverage import _covered
from scripts.run_free_price_coverage import _classify_deal, admit_prints

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
        "yahoo_n": 5, "combined_n": 5, "material_conflicts": 0}


@pytest.mark.parametrize("patch,admitted,cls", [
    ({}, True, "MULTI_PROVIDER_CONFIRMED"),
    ({"openfigi_status": "NO_MATCH"}, True, "OPENFIGI_NO_MATCH"),       # not negative evidence
    ({"openfigi_status": "AMBIGUOUS"}, False, "SECURITY_IDENTITY_AMBIGUOUS"),
    ({"openfigi_status": "NAME_MISMATCH"}, False, "SECURITY_IDENTITY_NAME_MISMATCH"),
    ({"tiingo_status": "IDENTITY_AMBIGUOUS", "tiingo_n": 0}, False,
     "SECURITY_IDENTITY_AMBIGUOUS"),
    ({"material_conflicts": 1}, False, "DEFER_PRICE_CONFLICT"),
])
def test_manifest_admission_rule(patch, admitted, cls):
    row = {**BASE, **patch}
    assert admit_prints(row) is admitted
    assert _classify_deal(row) == cls
    row["prints_admitted"] = admitted
    assert _covered(row) is admitted
