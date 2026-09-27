"""Yahoo equity target-price provider — mocked HTTP only (no network in CI)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.ingest.equity_prices import (
    SecurityIdentityResolver,
    YahooEquityPriceProvider,
    deal_id_ticker,
)
from src.ingest.equity_prices.normalize import write_normalized_manifest
from src.ingest.equity_prices.schema import NormalizedEquityObservation
from src.ingest.equity_prices.yahoo import session_close_iso
from src.ingest.providers.yahoo_equity import prints_for_deal
from src.ingest.target_prices import TargetPricePrint


def test_deal_id_ticker_convention():
    assert deal_id_ticker("DEAL-ATVI-MSFT-2022") == "ATVI"
    assert deal_id_ticker("DEAL-EA-PIFSLAFF-2025") == "EA"
    assert deal_id_ticker("NOTADEAL") is None


def test_session_close_iso_is_1600():
    from src.ingest.equity_prices.yahoo import session_close_iso as sci
    assert sci(date(2024, 1, 2)) == "2024-01-02T16:00:00"


def test_resolver_prefers_reviewed_map(tmp_path):
    p = tmp_path / "map.json"
    p.write_text('{"schema_version":1,"tickers":[{"deal_id":"DEAL-X-Y-2020",'
                 '"ticker":"ABCD","basis":"reviewed_map"}]}')
    r = SecurityIdentityResolver(map_path=p, fetch_json=lambda url: {})
    ident, defer = r.resolve({
        "deal_id": "DEAL-X-Y-2020", "target_cik": 123,
        "announcement_timestamp": "2020-01-01",
    })
    assert defer is None
    assert ident.ticker == "ABCD"
    assert ident.ticker_basis == "reviewed_map"


def test_resolver_falls_back_to_sec_then_deal_id():
    sec = {"0": {"cik_str": 42, "ticker": "SEC1"}}
    r = SecurityIdentityResolver(
        map_path=Path("/nonexistent"), user_agent="test",
        fetch_json=lambda url: sec)
    ident, _ = r.resolve({
        "deal_id": "DEAL-OTHER-ACQ-2020", "target_cik": 42,
        "announcement_timestamp": "2020-01-01",
    })
    assert ident.ticker == "SEC1"
    assert ident.ticker_basis == "sec_company_tickers"
    ident2, _ = r.resolve({
        "deal_id": "DEAL-FALL-ACQ-2020", "target_cik": 999,
        "announcement_timestamp": "2020-01-01",
    })
    assert ident2.ticker == "FALL"
    assert ident2.ticker_basis == "deal_id_convention"


def test_prints_for_deal_uses_injected_closes_only():
    """Synthetic chart payload exercises plumbing; not a real-data claim."""
    def fake_chart(url: str):
        return {"chart": {"result": [{
            "timestamp": [1704240000, 1704326400, 1704412800],
            "indicators": {"quote": [{"close": [10.0, None, 10.5]}]},
        }]}}

    client = YahooEquityPriceProvider(fetch_json=fake_chart)
    resolver = SecurityIdentityResolver(
        map_path=Path("/nonexistent"), user_agent="test",
        fetch_json=lambda url: {})
    deal = {
        "deal_id": "DEAL-FAKE-ACQ-2024",
        "target_cik": 1,
        "announcement_timestamp": "2024-01-02",
        "resolution_timestamp": "2024-01-10",
    }
    out = prints_for_deal(deal, resolver, client)
    assert out["status"] in ("ok", "no_price_history")
    for p in out["accepted"]:
        assert isinstance(p, TargetPricePrint)
        assert p.source.source_name == "yahoo_finance_chart"
        assert p.target_price > 0


def test_write_price_manifest_roundtrip(tmp_path):
    p = tmp_path / "prices.json"
    obs = [NormalizedEquityObservation(
        deal_id="D1", session_date="2024-01-03", close=12.5,
        provider="yahoo_finance_chart", provider_symbol="ABC",
        retrieval_timestamp="t", ticker="ABC",
        observation_timestamp="2024-01-03T16:00:00",
        known_at="2024-01-03T16:00:00")]
    write_normalized_manifest(obs, p, meta={"n": 1})
    import json
    data = json.loads(p.read_text())
    assert data["prints"][0]["target_price"] == 12.5
    assert data["meta"]["n"] == 1
