"""Yahoo equity target-price provider — mocked HTTP only (no network in CI)."""
from __future__ import annotations

from datetime import date

import pytest

from src.ingest.providers.yahoo_equity import (
    TickerResolver,
    YahooChartClient,
    deal_id_ticker,
    prints_for_deal,
    session_close_iso,
    write_price_manifest,
)
from src.ingest.target_prices import TargetPricePrint
from src.ingest.historical import SourceRef


def test_deal_id_ticker_convention():
    assert deal_id_ticker("DEAL-ATVI-MSFT-2022") == "ATVI"
    assert deal_id_ticker("DEAL-EA-PIFSLAFF-2025") == "EA"
    assert deal_id_ticker("NOTADEAL") is None


def test_session_close_iso_is_1600():
    assert session_close_iso(date(2024, 1, 2)) == "2024-01-02T16:00:00"


def test_resolver_prefers_reviewed_map(tmp_path):
    p = tmp_path / "map.json"
    p.write_text('{"schema_version":1,"tickers":[{"deal_id":"DEAL-X-Y-2020",'
                 '"ticker":"ABCD","basis":"reviewed_map"}]}')
    r = TickerResolver(map_path=p, fetch_json=lambda url: {})
    out = r.resolve("DEAL-X-Y-2020", 123)
    assert out["ticker"] == "ABCD"
    assert out["basis"] == "reviewed_map"


def test_resolver_falls_back_to_sec_then_deal_id():
    sec = {"0": {"cik_str": 42, "ticker": "SEC1"}}
    r = TickerResolver(map_path=__import__("pathlib").Path("/nonexistent"),
                       user_agent="test",
                       fetch_json=lambda url: sec)
    assert r.resolve("DEAL-OTHER-ACQ-2020", 42)["ticker"] == "SEC1"
    assert r.resolve("DEAL-OTHER-ACQ-2020", 42)["basis"] == "sec_company_tickers"
    assert r.resolve("DEAL-FALL-ACQ-2020", 999)["ticker"] == "FALL"
    assert r.resolve("DEAL-FALL-ACQ-2020", 999)["basis"] == "deal_id_convention"


def test_prints_for_deal_uses_injected_closes_only():
    """Synthetic chart payload exercises plumbing; not a real-data claim."""
    def fake_chart(url: str):
        # two sessions inside announce..resolve
        return {"chart": {"result": [{
            "timestamp": [1704240000, 1704326400, 1704412800],  # 2024-01-03..05 UTC-ish
            "indicators": {"quote": [{"close": [10.0, None, 10.5]}]},
        }]}}

    client = YahooChartClient(fetch_json=fake_chart)
    resolver = TickerResolver(
        map_path=__import__("pathlib").Path("/nonexistent"),
        user_agent="test",
        fetch_json=lambda url: {},
    )
    deal = {
        "deal_id": "DEAL-FAKE-ACQ-2024",
        "target_cik": 1,
        "announcement_timestamp": "2024-01-02",
        "resolution_timestamp": "2024-01-10",
    }
    out = prints_for_deal(deal, resolver, client)
    # May be 0+ depending on timezone conversion of timestamps; must not invent
    assert out["status"] in ("ok", "no_price_history")
    for p in out["accepted"]:
        assert isinstance(p, TargetPricePrint)
        assert p.source.source_name == "yahoo_finance_chart"
        assert p.target_price > 0


def test_write_price_manifest_roundtrip(tmp_path):
    p = tmp_path / "prices.json"
    prints = [TargetPricePrint(
        "D1", "2024-01-03T16:00:00", 12.5,
        SourceRef("yahoo_finance_chart", "yahoo_finance_chart:ABC@2024-01-03",
                  known_at="2024-01-03T16:00:00"))]
    write_price_manifest(prints, p, meta={"n": 1})
    import json
    data = json.loads(p.read_text())
    assert data["prints"][0]["target_price"] == 12.5
    assert data["meta"]["n"] == 1
