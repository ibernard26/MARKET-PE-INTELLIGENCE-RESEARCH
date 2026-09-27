"""Provider-contract tests for the historical equity price abstraction."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.ingest.equity_prices import (
    NormalizedEquityObservation,
    PriceProviderOrchestrator,
    ProviderFetchResult,
    ProviderStatus,
    SecurityIdentity,
    SecurityIdentityResolver,
    YahooEquityPriceProvider,
    compare_provider_series,
    deal_id_ticker,
    is_valid_session,
    observation_to_print,
)


def test_protocol_runtime_check():
    from src.ingest.equity_prices.protocol import HistoricalEquityPriceProvider
    p = YahooEquityPriceProvider(fetch_json=lambda url: {"chart": {"result": None}})
    assert isinstance(p, HistoricalEquityPriceProvider)


def test_normalized_observation_rejects_non_positive():
    with pytest.raises(ValueError):
        NormalizedEquityObservation(
            deal_id="D", session_date="2024-01-02", close=0.0,
            provider="x", provider_symbol="X", retrieval_timestamp="t")
    with pytest.raises(ValueError):
        NormalizedEquityObservation(
            deal_id="D", session_date="2024-01-02", close=float("nan"),
            provider="x", provider_symbol="X", retrieval_timestamp="t")


def test_weekend_rejected_by_calendar_gate():
    assert is_valid_session("2024-01-06") is False  # Saturday
    assert is_valid_session("2024-01-05") is True   # Friday


def test_identity_resolver_reviewed_map(tmp_path):
    p = tmp_path / "map.json"
    p.write_text('{"schema_version":1,"tickers":[{"deal_id":"DEAL-X-Y-2020",'
                 '"ticker":"ABCD","basis":"reviewed_map"}]}')
    r = SecurityIdentityResolver(map_path=p, fetch_json=lambda url: {})
    ident, defer = r.resolve({
        "deal_id": "DEAL-X-Y-2020", "target_cik": 1, "target": "X",
        "announcement_timestamp": "2020-01-01",
    })
    assert defer is None
    assert ident.ticker == "ABCD"
    assert ident.ticker_basis == "reviewed_map"


def test_identity_resolver_sec_then_deal_id():
    sec = {"0": {"cik_str": 42, "ticker": "SEC1"}}
    r = SecurityIdentityResolver(
        map_path=Path("/nonexistent"),
        user_agent="test", fetch_json=lambda url: sec)
    ident, defer = r.resolve({
        "deal_id": "DEAL-OTHER-ACQ-2020", "target_cik": 42,
        "announcement_timestamp": "2020-01-01",
    })
    assert ident.ticker == "SEC1" and defer is None
    ident2, defer2 = r.resolve({
        "deal_id": "DEAL-FALL-ACQ-2020", "target_cik": 999,
        "announcement_timestamp": "2020-01-01",
    })
    assert ident2.ticker == "FALL"
    assert ident2.ticker_basis == "deal_id_convention"


def test_yahoo_adapter_maps_empty_to_explicit_status():
    p = YahooEquityPriceProvider(
        fetch_json=lambda url: {"chart": {"result": None, "error": {"code": "404"}}})
    ident = SecurityIdentity(deal_id="D", ticker="GONE")
    res = p.fetch_history(ident, date(2020, 1, 1), date(2020, 2, 1))
    assert res.status == ProviderStatus.DELISTED_UNAVAILABLE
    assert res.observations == []


def test_yahoo_adapter_available_with_injected_chart():
    def fake(url: str):
        return {"chart": {"result": [{
            "timestamp": [1704240000, 1704326400],
            "indicators": {
                "quote": [{"close": [10.0, 10.5]}],
                "adjclose": [{"adjclose": [10.0, 10.5]}],
            },
        }]}}
    p = YahooEquityPriceProvider(fetch_json=fake)
    ident = SecurityIdentity(
        deal_id="DEAL-FAKE-ACQ-2024", ticker="FAKE",
        announcement_date="2024-01-02", resolution_date="2024-01-10")
    res = p.fetch_history(ident, date(2024, 1, 2), date(2024, 1, 10))
    assert res.status == ProviderStatus.AVAILABLE
    assert len(res.observations) >= 1
    assert all(o.provider == "yahoo_finance_chart" for o in res.observations)
    assert all(o.close_field_used == "close" for o in res.observations)
    pr = observation_to_print(res.observations[0])
    assert pr.source.source_name == "yahoo_finance_chart"
    assert "synthetic" not in pr.source.source_identifier.lower()


def test_orchestrator_fallback_skips_empty_provider():
    class Empty:
        name = "empty"
        def credentials_required(self): return False
        def fetch_history(self, identity, start, end):
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.NO_HISTORY,
                identity=identity)

    class Hit:
        name = "hit"
        def credentials_required(self): return False
        def fetch_history(self, identity, start, end):
            o = NormalizedEquityObservation(
                deal_id=identity.deal_id, session_date="2024-01-03",
                close=11.0, provider=self.name, provider_symbol="X",
                retrieval_timestamp="t", ticker="X",
                observation_timestamp="2024-01-03T16:00:00",
                known_at="2024-01-03T16:00:00")
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.AVAILABLE,
                identity=identity, observations=[o], provider_symbol="X")

    resolver = SecurityIdentityResolver(
        map_path=Path("/nonexistent"),
        user_agent="test", fetch_json=lambda url: {})
    orch = PriceProviderOrchestrator(
        providers=[Empty(), Hit()], resolver=resolver)
    out = orch.fetch_deal({
        "deal_id": "DEAL-X-ACQ-2024",
        "announcement_timestamp": "2024-01-02",
        "resolution_timestamp": "2024-01-10",
        "target_cik": 1,
    })
    assert out["status"] == "ok"
    assert out["provider"] == "hit"
    assert out["n_prints"] == 1
    assert len(out["provider_trace"]) == 2


def test_compare_provider_series_defers_on_conflict():
    a = [NormalizedEquityObservation(
        deal_id="D", session_date="2024-01-03", close=10.0,
        provider="a", provider_symbol="X", retrieval_timestamp="t")]
    b = [NormalizedEquityObservation(
        deal_id="D", session_date="2024-01-03", close=12.0,
        provider="b", provider_symbol="X", retrieval_timestamp="t")]
    cmp = compare_provider_series(a, b)
    assert cmp["status"] == ProviderStatus.DEFER_PRICE_CONFLICT.value
    assert cmp["n_conflict"] == 1


def test_credentials_required_provider_is_skipped():
    class Paid:
        name = "paid"
        def credentials_required(self): return True
        def fetch_history(self, *a, **k):
            raise AssertionError("must not be called without credentials")

    class Free:
        name = "free"
        def credentials_required(self): return False
        def fetch_history(self, identity, start, end):
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.NO_HISTORY,
                identity=identity)

    orch = PriceProviderOrchestrator(
        providers=[Paid(), Free()],
        resolver=SecurityIdentityResolver(
            map_path=Path("/nonexistent"),
            user_agent="t", fetch_json=lambda u: {}))
    out = orch.fetch_deal({
        "deal_id": "DEAL-Z-ACQ-2024",
        "announcement_timestamp": "2024-01-02",
        "resolution_timestamp": "2024-01-10",
    })
    assert out["provider_trace"][0]["status"] == ProviderStatus.CREDENTIALS_REQUIRED.value
    assert out["status"] == ProviderStatus.NO_HISTORY.value


def test_deal_id_ticker():
    assert deal_id_ticker("DEAL-ATVI-MSFT-2022") == "ATVI"
