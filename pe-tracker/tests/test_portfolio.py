"""Stage 4 tests: portfolio accounting, concentration, expected loss, scenarios."""
import pytest

from src.research import portfolio as pf
from src.research.portfolio import OpenPosition


def test_position_pnl_reconciles_to_portfolio():
    positions = [
        {"deal_id": "A", "capital": 1_000_000, "realized_pnl": 52_631.0, "censored": False, "sector": "Tech"},
        {"deal_id": "B", "capital": 1_000_000, "realized_pnl": -157_894.0, "censored": False, "sector": "Energy"},
        {"deal_id": "C", "capital": 1_000_000, "realized_pnl": None, "censored": True, "sector": "Tech"},
    ]
    agg = pf.realized_portfolio(positions)
    assert agg["n"] == 2                                   # censored excluded
    assert agg["realized_pnl"] == pytest.approx(52_631.0 - 157_894.0)
    assert agg["capital"] == 2_000_000


def test_concentration_hhi_and_max_name():
    positions = [
        {"deal_id": "A", "capital": 3_000_000, "sector": "Tech"},
        {"deal_id": "B", "capital": 1_000_000, "sector": "Energy"},
    ]
    c = pf.concentration(positions, key="sector")
    assert c["groups"]["Tech"] == pytest.approx(0.75)
    assert c["max_name"] == "Tech" and c["max_weight"] == pytest.approx(0.75)
    assert c["hhi"] == pytest.approx(0.75 ** 2 + 0.25 ** 2)


def test_expected_loss_and_contributions():
    opens = [
        OpenPosition("A", capital=1e6, p_break=0.10, downside_notional=150_000, break_vector="cfius"),
        OpenPosition("B", capital=1e6, p_break=0.40, downside_notional=200_000, break_vector="antitrust"),
    ]
    el = pf.expected_loss(opens)
    # 0.10*150k + 0.40*200k = 15k + 80k = 95k
    assert el["expected_loss_total"] == pytest.approx(95_000)
    assert el["contributions"][0]["deal_id"] == "B"        # largest EL first
    assert el["contributions"][0]["share_of_el"] == pytest.approx(80_000 / 95_000)


def test_drawdown_curve():
    dd = pf.drawdown([("2026-03-01", 100.0), ("2026-04-01", -250.0), ("2026-05-01", 50.0)])
    # cum: 100, -150, -100 ; peak 100 ; trough drawdown at -150 -> -250
    assert dd["max_drawdown"] == pytest.approx(-250.0)


def test_scenario_stress_raises_expected_loss():
    opens = [
        OpenPosition("A", capital=1e6, p_break=0.10, downside_notional=150_000, break_vector="cfius"),
        OpenPosition("B", capital=1e6, p_break=0.20, downside_notional=200_000, break_vector="antitrust"),
    ]
    base = pf.expected_loss(opens)["expected_loss_total"]
    # antitrust shock forces B (antitrust) to break; A untouched
    sc = pf.scenario_loss(opens, "antitrust_shock")
    assert sc["positions_stressed"] == 1
    assert sc["scenario_expected_loss"] == pytest.approx(0.10 * 150_000 + 1.0 * 200_000)
    assert sc["incremental_loss"] == pytest.approx(sc["scenario_expected_loss"] - base)


def test_unknown_scenario_rejected():
    with pytest.raises(ValueError):
        pf.scenario_loss([], "meteor_strike")


def test_stress_table_covers_all_scenarios():
    opens = [OpenPosition("A", 1e6, 0.15, 150_000, sponsor="PE", break_vector="financing")]
    table = pf.stress_table(opens)
    assert {r["scenario"] for r in table} == set(pf.SCENARIOS)
