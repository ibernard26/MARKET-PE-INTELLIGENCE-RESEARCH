"""Mocked CRSP provider-contract tests. No licensed data; no fabricated live pulls."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from src.ingest.equity_prices import (
    CRSPEquityPriceProvider,
    NormalizedEquityObservation,
    PriceProviderOrchestrator,
    ProviderStatus,
    SecurityIdentity,
    SecurityIdentityResolver,
    YahooEquityPriceProvider,
    compare_provider_series,
)
from src.ingest.equity_prices.crsp import (
    CRSP_PRICE_ACCEPTANCE_RULE,
    CrspDailyRow,
    CrspDelistingRow,
    dlyprc_usable_for_spread,
    normalize_crsp_daily_rows,
)
from src.ingest.equity_prices.crsp_access import detect_crsp_access
from src.ingest.equity_prices.crsp_identity import (
    STATUS_AMBIGUOUS,
    STATUS_MATCHED,
    CrspIdentityResolver,
    CrspNameRow,
    CrspSecurityMapping,
    resolve_permno_candidates,
    write_crsp_security_map,
)


def _ident(**kw) -> SecurityIdentity:
    base = dict(
        deal_id="DEAL-FAKE-ACQ-2020",
        target_cik=1,
        target_name="FAKE CORP",
        ticker="FAKE",
        announcement_date="2020-01-02",
        resolution_date="2020-01-31",
    )
    base.update(kw)
    return SecurityIdentity(**base)


def test_detect_crsp_access_none_by_default():
    cfg = detect_crsp_access(env={})
    assert cfg.available is False
    assert cfg.mode == "none"


def test_detect_crsp_access_wrds_requires_username():
    cfg = detect_crsp_access(env={"CRSP_ACCESS_MODE": "wrds"})
    assert cfg.available is False
    assert "WRDS_USERNAME" in cfg.reason


def test_detect_crsp_access_wrds_username_marks_available():
    cfg = detect_crsp_access(env={
        "CRSP_ACCESS_MODE": "wrds",
        "WRDS_USERNAME": "researcher",
    })
    assert cfg.available is True
    assert cfg.mode == "wrds"
    assert cfg.wrds_username == "researcher"


def test_detect_crsp_access_flat_file_missing_dir(tmp_path):
    missing = tmp_path / "nope"
    cfg = detect_crsp_access(env={
        "CRSP_ACCESS_MODE": "flat_file",
        "CRSP_DATA_DIR": str(missing),
    })
    assert cfg.available is False


def test_detect_crsp_access_flat_file_present(tmp_path):
    d = tmp_path / "crsp"
    d.mkdir()
    cfg = detect_crsp_access(env={
        "CRSP_ACCESS_MODE": "flat_file",
        "CRSP_DATA_DIR": str(d),
    })
    assert cfg.available is True
    assert cfg.mode == "flat_file"


def test_credentials_required_without_access():
    p = CRSPEquityPriceProvider(
        access=detect_crsp_access(env={}),
        force_credentials_required=True,
    )
    assert p.credentials_required() is True
    res = p.fetch_history(_ident(), date(2020, 1, 2), date(2020, 1, 10))
    assert res.status == ProviderStatus.CREDENTIALS_REQUIRED
    assert res.observations == []


def test_dlyprc_flg_acceptance_v1():
    assert dlyprc_usable_for_spread(None) is True
    assert dlyprc_usable_for_spread("") is True
    assert dlyprc_usable_for_spread("T") is True
    assert dlyprc_usable_for_spread("A") is False
    assert dlyprc_usable_for_spread("Z") is False


def test_normalize_rejects_bid_ask_average_and_duplicates():
    mapping = CrspSecurityMapping(
        deal_id="DEAL-FAKE-ACQ-2020", permno=12345, permco=1,
        historical_ticker="FAKE", status=STATUS_MATCHED,
        mapping_method="test",
    )
    rows = [
        CrspDailyRow(12345, "2020-01-03", 10.0, None),
        CrspDailyRow(12345, "2020-01-03", 10.5, None),  # duplicate date
        CrspDailyRow(12345, "2020-01-06", 11.0, "A"),   # bid/ask — reject
        CrspDailyRow(12345, "2020-01-04", None, None),  # Saturday + missing
        CrspDailyRow(12345, "2020-01-07", 12.0, None),  # Tuesday OK
    ]
    obs, rejected = normalize_crsp_daily_rows(_ident(), mapping, rows)
    assert all(o.provider == "crsp" for o in obs)
    assert all(o.provider_symbol == "12345" for o in obs)
    assert all(o.source_metadata.get("permno") == 12345 for o in obs)
    assert all(o.close_field_used == "close" for o in obs)
    assert CRSP_PRICE_ACCEPTANCE_RULE in (obs[0].corporate_action_note or "")
    reasons = {r["reason"] for r in rejected}
    assert "duplicate_date" in reasons
    assert any("dly_prc_flg_rejected" in r["reason"] for r in rejected)
    # weekend / missing filtered
    assert all(o.session_date != "2020-01-04" for o in obs)
    assert all(o.session_date != "2020-01-06" for o in obs)


def test_identity_ambiguous_multiple_permnos():
    rows = [
        CrspNameRow(1, 10, "FAKE", "FAKE CORP A", namedt="2019-01-01",
                    nameendt="2021-01-01"),
        CrspNameRow(2, 20, "FAKE", "FAKE CORP B", namedt="2019-01-01",
                    nameendt="2021-01-01"),
    ]
    cands, method = resolve_permno_candidates(_ident(), rows, asof="2020-01-02")
    assert method == STATUS_AMBIGUOUS
    assert len({c.permno for c in cands}) == 2


def test_identity_unique_ticker_name_asof():
    rows = [
        CrspNameRow(99, 9, "FAKE", "FAKE CORP", namedt="2019-01-01",
                    nameendt="2021-01-01"),
        CrspNameRow(98, 8, "FAKE", "OTHER NAME", namedt="2019-01-01",
                    nameendt="2021-01-01"),
    ]
    cands, method = resolve_permno_candidates(_ident(), rows, asof="2020-01-02")
    assert method == "ticker+name+asof"
    assert {c.permno for c in cands} == {99}


def test_crsp_identity_resolver_credentials_without_lookup(tmp_path):
    path = tmp_path / "map.json"
    write_crsp_security_map({
        "schema_version": 1, "meta": {}, "mappings": [],
    }, path)
    r = CrspIdentityResolver(map_path=path, access_available=False)
    mapping, defer = r.resolve(_ident())
    assert defer == ProviderStatus.CREDENTIALS_REQUIRED
    assert mapping.status == "CREDENTIALS_REQUIRED"


def test_crsp_provider_available_with_injected_backend(tmp_path):
    path = tmp_path / "map.json"
    write_crsp_security_map({
        "schema_version": 1,
        "meta": {},
        "mappings": [{
            "deal_id": "DEAL-FAKE-ACQ-2020",
            "target_cik": 1,
            "target_name": "FAKE CORP",
            "historical_ticker": "FAKE",
            "permno": 12345,
            "permco": 7,
            "mapping_method": "reviewed_test",
            "effective_start": "2019-01-01",
            "effective_end": "2021-01-01",
            "evidence": {"test": True},
            "confidence": "high",
            "status": "MATCHED",
        }],
    }, path)

    def daily(permno, start, end):
        assert permno == 12345
        return [
            CrspDailyRow(12345, "2020-01-03", 10.0, None),
            CrspDailyRow(12345, "2020-01-06", 10.5, None),
            CrspDailyRow(12345, "2020-01-07", 11.0, None),
        ]

    def delist(permno):
        return CrspDelistingRow(
            permno=permno, delisting_dt="2020-02-01",
            del_dt_prc=11.5, del_action_type="MERGER",
            delisting_return=0.01,
        )

    p = CRSPEquityPriceProvider(
        map_path=path,
        daily_lookup=daily,
        delist_lookup=delist,
        force_credentials_required=False,
        access=detect_crsp_access(env={
            "CRSP_ACCESS_MODE": "wrds", "WRDS_USERNAME": "test",
        }),
    )
    assert p.credentials_required() is False
    res = p.fetch_history(_ident(), date(2020, 1, 2), date(2020, 1, 10))
    assert res.status == ProviderStatus.AVAILABLE
    assert res.provider_symbol == "12345"
    assert len(res.observations) >= 2
    assert all(o.provider == "crsp" for o in res.observations)
    assert all("synthetic" not in o.provider for o in res.observations)
    assert res.observations[0].source_metadata.get("delisting", {}).get(
        "DelistingDt") == "2020-02-01"
    # Delisting price must not appear as a session close
    assert all(o.session_date != "2020-02-01" for o in res.observations)
    assert all(o.close != 11.5 or o.session_date != "2020-02-01"
               for o in res.observations)


def test_crsp_provider_ambiguous_defers(tmp_path):
    path = tmp_path / "map.json"
    write_crsp_security_map({"schema_version": 1, "meta": {}, "mappings": []}, path)

    def names(identity):
        return [
            CrspNameRow(1, 1, "FAKE", "A", namedt="2019-01-01", nameendt="2021-01-01"),
            CrspNameRow(2, 2, "FAKE", "B", namedt="2019-01-01", nameendt="2021-01-01"),
        ]

    p = CRSPEquityPriceProvider(
        map_path=path,
        name_lookup=names,
        daily_lookup=lambda *a, **k: [],
        force_credentials_required=False,
    )
    res = p.fetch_history(_ident(), date(2020, 1, 2), date(2020, 1, 10))
    assert res.status == ProviderStatus.IDENTITY_AMBIGUOUS


def test_orchestrator_crsp_then_yahoo_fallback(tmp_path):
    """CRSP credentials missing → skip; Yahoo supplies prints."""
    map_path = tmp_path / "crsp_map.json"
    write_crsp_security_map({"schema_version": 1, "meta": {}, "mappings": []},
                            map_path)
    crsp = CRSPEquityPriceProvider(
        map_path=map_path,
        access=detect_crsp_access(env={}),
        force_credentials_required=True,
    )

    def yahoo_chart(url: str):
        return {"chart": {"result": [{
            "timestamp": [1578009600, 1578268800, 1578355200],
            "indicators": {
                "quote": [{"close": [10.0, 10.5, 11.0]}],
                "adjclose": [{"adjclose": [10.0, 10.5, 11.0]}],
            },
        }]}}

    yahoo = YahooEquityPriceProvider(fetch_json=yahoo_chart)
    orch = PriceProviderOrchestrator(
        providers=[crsp, yahoo],
        resolver=SecurityIdentityResolver(
            map_path=Path("/nonexistent"),
            user_agent="t", fetch_json=lambda u: {}),
    )
    out = orch.fetch_deal({
        "deal_id": "DEAL-X-ACQ-2020",
        "announcement_timestamp": "2020-01-02",
        "resolution_timestamp": "2020-01-10",
        "target_cik": 1,
        "target": "X",
    })
    assert out["provider_trace"][0]["status"] == ProviderStatus.CREDENTIALS_REQUIRED.value
    assert out["status"] == "ok"
    assert out["provider"] == "yahoo_finance_chart"


def test_orchestrator_prefers_crsp_when_available(tmp_path):
    path = tmp_path / "map.json"
    write_crsp_security_map({
        "schema_version": 1, "meta": {},
        "mappings": [{
            "deal_id": "DEAL-X-ACQ-2020", "permno": 42, "permco": 1,
            "historical_ticker": "X", "status": "MATCHED",
            "mapping_method": "test", "confidence": "high",
        }],
    }, path)
    crsp = CRSPEquityPriceProvider(
        map_path=path,
        daily_lookup=lambda p, s, e: [
            CrspDailyRow(42, "2020-01-03", 9.0, None),
            CrspDailyRow(42, "2020-01-06", 9.5, None),
            CrspDailyRow(42, "2020-01-07", 9.75, None),
        ],
        force_credentials_required=False,
    )

    class YahooBoom:
        name = "yahoo_finance_chart"
        def credentials_required(self): return False
        def fetch_history(self, *a, **k):
            raise AssertionError("Yahoo must not be called when CRSP succeeds")

    orch = PriceProviderOrchestrator(
        providers=[crsp, YahooBoom()],
        resolver=SecurityIdentityResolver(
            map_path=Path("/nonexistent"),
            user_agent="t", fetch_json=lambda u: {}),
    )
    out = orch.fetch_deal({
        "deal_id": "DEAL-X-ACQ-2020",
        "announcement_timestamp": "2020-01-02",
        "resolution_timestamp": "2020-01-10",
    })
    assert out["status"] == "ok"
    assert out["provider"] == "crsp"
    assert out["n_prints"] >= 2


def test_compare_crsp_yahoo_conflict_defers():
    a = [NormalizedEquityObservation(
        deal_id="D", session_date="2020-01-03", close=10.0,
        provider="crsp", provider_symbol="1", retrieval_timestamp="t")]
    b = [NormalizedEquityObservation(
        deal_id="D", session_date="2020-01-03", close=11.0,
        provider="yahoo_finance_chart", provider_symbol="X",
        retrieval_timestamp="t")]
    cmp = compare_provider_series(a, b)
    assert cmp["status"] == ProviderStatus.DEFER_PRICE_CONFLICT.value


def test_crsp_provider_still_constructible_but_not_in_default_chain():
    """CRSP is frozen for thesis; adapter remains for future robustness."""
    from src.ingest.equity_prices.crsp import CRSPEquityPriceProvider
    from src.ingest.equity_prices.fetch import (
        CRSP_ACTIVE_INGESTION,
        CRSP_STATUS,
        default_providers,
    )
    chain = default_providers()
    assert [p.name for p in chain] == ["tiingo", "yahoo_finance_chart"]
    assert CRSP_STATUS == "FROZEN_FUTURE_ROBUSTNESS_PROVIDER"
    assert CRSP_ACTIVE_INGESTION is False
    p = CRSPEquityPriceProvider(force_credentials_required=True)
    assert p.credentials_required() is True


def test_no_synthetic_provider_in_normalized_obs():
    mapping = CrspSecurityMapping(
        deal_id="D", permno=1, status=STATUS_MATCHED, mapping_method="t")
    obs, _ = normalize_crsp_daily_rows(
        SecurityIdentity(deal_id="D", ticker="X"),
        mapping,
        [CrspDailyRow(1, "2020-01-03", 1.0, None)],
    )
    assert obs[0].provider == "crsp"
    assert "synthetic" not in obs[0].provider.lower()


def test_protocol_runtime_check_crsp():
    from src.ingest.equity_prices.protocol import HistoricalEquityPriceProvider
    p = CRSPEquityPriceProvider(force_credentials_required=True)
    assert isinstance(p, HistoricalEquityPriceProvider)


def test_daily_lookup_must_respect_requested_window(tmp_path):
    """Backends must only return rows in [start, end] (PIT / no future leakage)."""
    path = tmp_path / "map.json"
    write_crsp_security_map({
        "schema_version": 1, "meta": {},
        "mappings": [{
            "deal_id": "DEAL-FAKE-ACQ-2020", "permno": 1, "status": "MATCHED",
            "historical_ticker": "FAKE", "mapping_method": "t",
        }],
    }, path)

    def bounded(permno, start, end):
        all_rows = [
            CrspDailyRow(1, "2020-01-03", 10.0, None),
            CrspDailyRow(1, "2025-01-03", 99.0, None),
        ]
        return [r for r in all_rows
                if start <= date.fromisoformat(r.dly_cal_dt) <= end]

    p = CRSPEquityPriceProvider(
        map_path=path, daily_lookup=bounded, force_credentials_required=False)
    res = p.fetch_history(_ident(), date(2020, 1, 2), date(2020, 1, 10))
    assert res.status == ProviderStatus.AVAILABLE
    assert all(o.session_date <= "2020-01-10" for o in res.observations)
    assert all(o.session_date >= "2020-01-02" for o in res.observations)
    assert all(o.close != 99.0 for o in res.observations)
