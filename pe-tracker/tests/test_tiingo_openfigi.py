"""Mocked OpenFIGI + Tiingo thesis-stack tests. Never use live credentials in CI."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from src.ingest.equity_prices import (
    NormalizedEquityObservation,
    PriceProviderOrchestrator,
    ProviderStatus,
    SecurityIdentity,
    SecurityIdentityResolver,
    TiingoEquityPriceProvider,
    classify_close_pair,
    credential_presence,
    missing_credential_names,
    reconcile_series,
)
from src.ingest.equity_prices.fetch import (
    CRSP_ACTIVE_INGESTION,
    CRSP_STATUS,
    default_providers,
)
from src.ingest.security_identity.openfigi import (
    OpenFIGIMappingStatus,
    OpenFIGISecurityIdentityResolver,
)


def test_credential_presence_no_values():
    flags = credential_presence(env={})
    assert flags["OPENFIGI_API_KEY_PRESENT"] == "NO"
    assert flags["TIINGO_API_TOKEN_PRESENT"] == "NO"
    assert missing_credential_names(env={}) == [
        "OPENFIGI_API_KEY", "TIINGO_API_TOKEN"]
    # Presence YES when non-empty — values never returned by helper
    flags2 = credential_presence(env={
        "OPENFIGI_API_KEY": "x",
        "TIINGO_API_TOKEN": "y",
    })
    assert flags2["OPENFIGI_API_KEY_PRESENT"] == "YES"
    assert flags2["TIINGO_API_TOKEN_PRESENT"] == "YES"
    assert "x" not in str(flags2) and "y" not in str(flags2)


def test_default_providers_tiingo_then_yahoo_crsp_frozen():
    chain = default_providers()
    assert [p.name for p in chain] == ["tiingo", "yahoo_finance_chart"]
    assert CRSP_STATUS == "FROZEN_FUTURE_ROBUSTNESS_PROVIDER"
    assert CRSP_ACTIVE_INGESTION is False


def test_openfigi_credentials_required():
    r = OpenFIGISecurityIdentityResolver(api_key="", env={})
    out = r.resolve_deal({"deal_id": "DEAL-X-Y-2020", "target": "X"}, ticker="X")
    assert out.mapping_status == OpenFIGIMappingStatus.CREDENTIALS_REQUIRED.value


def test_openfigi_matched_and_cache(tmp_path):
    calls = {"n": 0}

    def post(url, headers, body):
        calls["n"] += 1
        assert "X-OPENFIGI-APIKEY" in headers
        assert headers["X-OPENFIGI-APIKEY"] == "test-key"
        return 200, [{
            "data": [{
                "figi": "BBG000B9XRY4",
                "compositeFIGI": "BBG000B9XRY4",
                "shareClassFIGI": "BBG001S5N8V8",
                "name": "APPLE INC",
                "ticker": "AAPL",
                "exchCode": "US",
                "securityType": "Common Stock",
                "marketSector": "Equity",
            }]
        }]

    r = OpenFIGISecurityIdentityResolver(
        api_key="test-key", cache_dir=tmp_path, post_json=post, min_interval_s=0)
    deal = {"deal_id": "DEAL-AAPL-X-2020", "target": "Apple Inc",
            "announcement_timestamp": "2020-01-01"}
    a = r.resolve_deal(deal, ticker="AAPL")
    b = r.resolve_deal(deal, ticker="AAPL")  # cache hit
    assert a.mapping_status == "MATCHED"
    assert a.figi == "BBG000B9XRY4"
    assert calls["n"] == 1
    assert b.figi == a.figi


def test_openfigi_ambiguous_multiple_figis(tmp_path):
    def post(url, headers, body):
        return 200, [{
            "data": [
                {"figi": "F1", "name": "FOO A", "ticker": "FOO",
                 "marketSector": "Equity", "securityType": "Common Stock"},
                {"figi": "F2", "name": "FOO B", "ticker": "FOO",
                 "marketSector": "Equity", "securityType": "Common Stock"},
            ]
        }]

    r = OpenFIGISecurityIdentityResolver(
        api_key="k", cache_dir=tmp_path, post_json=post, min_interval_s=0)
    out = r.resolve_deal(
        {"deal_id": "DEAL-FOO-X-2020", "target": "Unrelated"}, ticker="FOO")
    assert out.mapping_status == "AMBIGUOUS"
    assert out.error == "DEFER_SECURITY_IDENTITY_AMBIGUOUS"


def test_openfigi_auth_failure(tmp_path):
    def post(url, headers, body):
        return 401, {"error": "unauthorized"}

    r = OpenFIGISecurityIdentityResolver(
        api_key="bad", cache_dir=tmp_path, post_json=post, min_interval_s=0)
    out = r.resolve_deal({"deal_id": "D", "target": "X"}, ticker="X")
    assert out.mapping_status == "AUTH_FAILURE"


def test_tiingo_credentials_required():
    p = TiingoEquityPriceProvider(token="", env={})
    assert p.credentials_required() is True
    res = p.fetch_history(
        SecurityIdentity(deal_id="D", ticker="X"),
        date(2020, 1, 2), date(2020, 1, 10))
    assert res.status == ProviderStatus.CREDENTIALS_REQUIRED


def test_tiingo_eod_normalization_raw_vs_adj():
    def fetch(url, headers):
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Token ")
        if "/prices" in url:
            return 200, [{
                "date": "2020-01-03T00:00:00.000Z",
                "open": 10, "high": 11, "low": 9, "close": 10.5,
                "volume": 1000,
                "adjOpen": 5, "adjHigh": 5.5, "adjLow": 4.5, "adjClose": 5.25,
                "adjVolume": 2000, "divCash": 0.0, "splitFactor": 2.0,
            }, {
                "date": "2020-01-06T00:00:00.000Z",
                "close": 10.75, "adjClose": 5.375,
                "divCash": 0.1, "splitFactor": 1.0,
                "open": 10.5, "high": 11, "low": 10, "volume": 900,
            }]
        return 200, {
            "ticker": "FAKE", "name": "FAKE CORP", "exchangeCode": "NASDAQ",
            "startDate": "2010-01-01", "endDate": "2020-12-31",
        }

    p = TiingoEquityPriceProvider(token="tok", fetch_json=fetch, min_interval_s=0)
    res = p.fetch_history(
        SecurityIdentity(deal_id="DEAL-FAKE-ACQ-2020", ticker="FAKE",
                         target_name="FAKE CORP"),
        date(2020, 1, 2), date(2020, 1, 10))
    assert res.status == ProviderStatus.AVAILABLE
    assert len(res.observations) >= 1
    o = res.observations[0]
    assert o.provider == "tiingo"
    assert o.close == 10.5
    assert o.adjusted_close == 5.25
    assert o.close_field_used == "close"
    assert o.close != o.adjusted_close
    assert o.source_metadata.get("splitFactor") == 2.0
    assert "synthetic" not in o.provider


def test_tiingo_symbol_not_found():
    def fetch(url, headers):
        return 404, {"detail": "Not found"}

    p = TiingoEquityPriceProvider(token="tok", fetch_json=fetch, min_interval_s=0)
    res = p.fetch_history(
        SecurityIdentity(deal_id="D", ticker="GONE"),
        date(2020, 1, 2), date(2020, 1, 10))
    assert res.status == ProviderStatus.SYMBOL_NOT_FOUND


def test_reconcile_tolerance_and_conflict():
    assert classify_close_pair(10.0, 10.0) == "EXACT_MATCH"
    assert classify_close_pair(10.0, 10.00005) == "TOLERABLE_MATCH"
    assert classify_close_pair(10.0, 11.0) == "MATERIAL_CONFLICT"
    a = [NormalizedEquityObservation(
        deal_id="D", session_date="2020-01-03", close=10.0,
        provider="tiingo", provider_symbol="X", retrieval_timestamp="t")]
    b = [NormalizedEquityObservation(
        deal_id="D", session_date="2020-01-03", close=11.0,
        provider="yahoo_finance_chart", provider_symbol="X",
        retrieval_timestamp="t")]
    r = reconcile_series(a, b)
    assert r["material_conflict"] == 1
    assert r["status"] == "DEFER_PRICE_CONFLICT"


def test_orchestrator_tiingo_credentials_skip_to_yahoo():
    tiingo = TiingoEquityPriceProvider(token="", env={})

    def yahoo_chart(url: str):
        return {"chart": {"result": [{
            "timestamp": [1578009600, 1578268800, 1578355200],
            "indicators": {
                "quote": [{"close": [10.0, 10.5, 11.0]}],
                "adjclose": [{"adjclose": [10.0, 10.5, 11.0]}],
            },
        }]}}

    from src.ingest.equity_prices.yahoo import YahooEquityPriceProvider
    yahoo = YahooEquityPriceProvider(fetch_json=yahoo_chart)
    orch = PriceProviderOrchestrator(
        providers=[tiingo, yahoo],
        resolver=SecurityIdentityResolver(
            map_path=Path("/nonexistent"),
            user_agent="t", fetch_json=lambda u: {}),
    )
    out = orch.fetch_deal({
        "deal_id": "DEAL-X-ACQ-2020",
        "announcement_timestamp": "2020-01-02",
        "resolution_timestamp": "2020-01-10",
    })
    assert out["provider_trace"][0]["status"] == "CREDENTIALS_REQUIRED"
    assert out["status"] == "ok"
    assert out["provider"] == "yahoo_finance_chart"


def test_no_future_leakage_in_tiingo_window():
    def fetch(url, headers):
        if "/prices" in url:
            return 200, [
                {"date": "2020-01-03T00:00:00.000Z", "close": 10.0,
                 "adjClose": 10.0, "open": 10, "high": 10, "low": 10,
                 "volume": 1, "divCash": 0, "splitFactor": 1},
                {"date": "2025-06-01T00:00:00.000Z", "close": 99.0,
                 "adjClose": 99.0, "open": 99, "high": 99, "low": 99,
                 "volume": 1, "divCash": 0, "splitFactor": 1},
            ]
        return 200, {"ticker": "X", "name": "X CORP", "exchangeCode": "NYSE",
                     "startDate": "2010-01-01", "endDate": ""}

    p = TiingoEquityPriceProvider(token="t", fetch_json=fetch, min_interval_s=0)
    res = p.fetch_history(
        SecurityIdentity(deal_id="D", ticker="X", target_name="X Corp"),
        date(2020, 1, 2), date(2020, 1, 10))
    assert res.status == ProviderStatus.AVAILABLE and res.observations
    assert all(o.session_date <= "2020-01-10" for o in res.observations)
    assert all(o.close != 99.0 for o in res.observations)
