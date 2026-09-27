"""spread_stress_v1 readiness gates and target-price ingestion architecture."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.ingest.historical import SourceRef
from src.ingest.target_prices import (
    ManifestTargetPriceProvider,
    TargetPricePrint,
    UnconfiguredTargetPriceProvider,
    count_target_prints,
    ingest_target_prices,
    write_print,
)
from src.model.spread_stress import (
    BLOCKED_INSUFFICIENT_PRICE_HISTORY,
    SpreadStressModel,
    audit_price_history,
    authorize_spread_stress_backtest,
    build_spread_stress_panel,
    build_spread_stress_row,
    delta_spread_series,
    run_gated_comparison,
)
from src.model.spread_stress.model import diagnostic_delta
from src.research import events as ev
from src.research.observations import Observation, record_observation

from .model_fixtures import add_deal, mem


def _add_price_path(c, deal_id, ann: str, n_prints: int, base=100.0, step=-0.5):
    """SYNTHETIC longitudinal target prints after announcement (tests only)."""
    d0 = date.fromisoformat(ann)
    for i in range(n_prints):
        day = (d0 + timedelta(days=i + 1)).isoformat()
        record_observation(
            Observation(deal_id, day + "T16:00:00", "synthetic_close",
                        target_price=base + step * i,
                        known_at=day + "T16:05:00"),
            conn=c,
        )


def test_unconfigured_target_price_provider_refuses_to_fabricate():
    with pytest.raises(NotImplementedError):
        list(UnconfiguredTargetPriceProvider().prints())


def test_write_print_requires_known_at_and_positive_price(tmp_path=None):
    c = mem()
    add_deal(c, "D1", "2024-01-02", 0.05, 0)
    bad = TargetPricePrint(
        "D1", "2024-01-03T16:00:00", 10.0,
        SourceRef("nyse", "x", known_at=None))
    r = write_print(bad, c)
    assert r["quarantined"] is True
    assert any("known_at" in p for p in r["problems"])


def test_manifest_ingest_empty_is_noop():
    c = mem()
    add_deal(c, "D1", "2024-01-02", 0.05, 0)
    # empty in-memory provider via empty list: use Manifest on empty file
    p = Path("/workspace/pe-tracker/data/target_price_manifest.json")
    data = json.loads(p.read_text())
    assert data["prints"] == []
    stats = ingest_target_prices(ManifestTargetPriceProvider(p), c)
    assert stats["accepted"] == 0
    assert count_target_prints(c) == 1  # announcement observation has target_price


def test_audit_blocks_without_longitudinal_history():
    c = mem()
    # announcement-only prints (1 per deal) — not enough for ΔS/σ
    for i in range(25):
        add_deal(c, f"D{i}", f"2024-{(i % 12) + 1:02d}-02", 0.05 + 0.01 * (i % 5),
                 int(i % 4 == 0))
    ready = audit_price_history(c, "2030-01-01", min_prints=3, min_panel_rows=20)
    assert ready.ready is False
    assert ready.status == BLOCKED_INSUFFICIENT_PRICE_HISTORY
    assert any(m["gap"] == "insufficient_longitudinal_target_prints" or
               m["n_target_prints"] < 3 for m in ready.missing)


def test_authorize_blocks_backtest_when_price_history_missing():
    c = mem()
    add_deal(c, "D1", "2024-01-02", 0.05, 0)
    gate = authorize_spread_stress_backtest(c, "2030-01-01")
    assert gate["authorized"] is False
    assert gate["SPREAD_STRESS_BACKTEST_STATUS"] == BLOCKED_INSUFFICIENT_PRICE_HISTORY
    assert "ingestion_unblock" in gate
    assert gate["ingestion_unblock"]["module"] == "src.ingest.target_prices"


def test_delta_spread_series_is_point_in_time():
    c = mem()
    add_deal(c, "D1", "2024-01-02", 0.10, 0, resolve_days=200)
    _add_price_path(c, "D1", "2024-01-02", n_prints=5, base=100.0, step=-1.0)
    early = delta_spread_series("D1", "2024-01-04T23:59:59", c)
    late = delta_spread_series("D1", "2024-01-10T23:59:59", c)
    assert len(early) < len(late)
    # a future print must not appear in the early series
    assert all(r["observation_timestamp"] <= "2024-01-04T23:59:59" for r in early)


def test_future_price_cannot_change_earlier_feature_row():
    c = mem()
    add_deal(c, "D1", "2024-01-02", 0.10, 0, resolve_days=200)
    _add_price_path(c, "D1", "2024-01-02", n_prints=4, base=100.0, step=-1.0)
    row_before = build_spread_stress_row("D1", "2024-01-05T16:00:00", "2030-01-01", c)
    # inject a future print
    record_observation(
        Observation("D1", "2024-06-01T16:00:00", "synthetic_close",
                    target_price=50.0, known_at="2024-06-01T16:05:00"), conn=c)
    row_after = build_spread_stress_row("D1", "2024-01-05T16:00:00", "2030-01-01", c)
    assert row_before["x"] == row_after["x"]
    assert row_before["n_target_prints"] == row_after["n_target_prints"]


def test_future_break_cannot_change_earlier_prediction_features():
    c = mem()
    add_deal(c, "D1", "2024-01-02", 0.10, None)  # pending
    _add_price_path(c, "D1", "2024-01-02", n_prints=5)
    row = build_spread_stress_row("D1", "2024-01-06T16:00:00", "2024-01-10", c)
    assert row["label"] is None
    ev.record_event("D1", "2024-03-01", "termination", "synthetic", conn=c,
                    known_at="2024-03-01")
    # features at the earlier as_of must be unchanged; label still censored at early cutoff
    row2 = build_spread_stress_row("D1", "2024-01-06T16:00:00", "2024-01-10", c)
    assert row["x"] == row2["x"]
    assert row2["label"] is None


def test_spread_stress_model_does_not_claim_break_logit_v1_identity():
    c = mem()
    # build a small synthetic stress panel with enough prints
    for i in range(30):
        ann = (date(2024, 1, 2) + timedelta(days=7 * i)).isoformat()
        add_deal(c, f"S{i:03d}", ann, 0.05 + 0.005 * i, int(i % 5 == 0),
                 resolve_days=90)
        _add_price_path(c, f"S{i:03d}", ann, n_prints=6, base=100.0,
                        step=(-0.8 if i % 5 == 0 else -0.2))
    panel = build_spread_stress_panel("2030-01-01", c, min_prints=3)
    assert panel["n"] >= 20
    m = SpreadStressModel().fit([r["x"] for r in panel["rows"]],
                                [r["label"] for r in panel["rows"]], min_n=20)
    d = m.to_dict()
    assert d["model_version"] == "spread_stress_v1"
    assert d["feature_schema_version"] == "fs_spread_stress_v1"
    assert d["model_id"] == "spread_stress"
    m2 = SpreadStressModel.from_dict(d)
    p1 = list(m.predict_proba([panel["rows"][0]["x"]]))
    p2 = list(m2.predict_proba([panel["rows"][0]["x"]]))
    assert p1 == pytest.approx(p2)


def test_diagnostic_delta_is_stress_minus_base():
    assert diagnostic_delta(0.4, 0.25) == pytest.approx(0.15)


def test_gated_comparison_reports_blocked_without_pretending_backtest():
    c = mem()
    for i in range(10):
        add_deal(c, f"D{i}", f"2024-01-{(i % 28) + 1:02d}", 0.05, int(i % 3 == 0))
    out = run_gated_comparison(c, "2024-06-01", "2030-01-01")
    assert out["SPREAD_STRESS_BACKTEST_STATUS"] == BLOCKED_INSUFFICIENT_PRICE_HISTORY
    assert out["BACKTEST_EXECUTED"] is False
    assert out["SPREAD_STRESS_BACKTEST_COMPLETE"] is False
    assert out["INCREMENTAL_OUT_OF_TIME_IMPROVEMENT"] == "INCONCLUSIVE"


def test_panel_excludes_insufficient_prints_with_explicit_reason():
    c = mem()
    add_deal(c, "D1", "2024-01-02", 0.05, 0)
    # only the announcement print
    panel = build_spread_stress_panel("2030-01-01", c, min_prints=3)
    assert panel["n"] == 0
    assert panel["excluded"][0]["reason"] == "insufficient_price_history"
