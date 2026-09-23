"""Stage 5 tests: Monte Carlo simulation.

Reproducibility, deterministic edge cases, unbiased mean loss, ES >= VaR, and
the correlation effect on the tail.
"""
import numpy as np
import pytest

from src.research.simulation import (SimPosition, expected_shortfall,
                                     risk_report, simulate_portfolio,
                                     value_at_risk)


def test_seeded_runs_are_reproducible():
    pos = [SimPosition("A", 0.2, 150_000), SimPosition("B", 0.3, 200_000)]
    a = simulate_portfolio(pos, n_paths=5_000, rho=0.2, seed=7)["pnl"]
    b = simulate_portfolio(pos, n_paths=5_000, rho=0.2, seed=7)["pnl"]
    assert np.array_equal(a, b)                       # identical seed -> identical paths


def test_different_seeds_differ():
    pos = [SimPosition("A", 0.2, 150_000)]
    a = simulate_portfolio(pos, n_paths=5_000, seed=1)["pnl"]
    b = simulate_portfolio(pos, n_paths=5_000, seed=2)["pnl"]
    assert not np.array_equal(a, b)


def test_certain_break_is_deterministic_loss():
    pos = [SimPosition("A", 1.0, 150_000), SimPosition("B", 1.0, 50_000)]
    pnl = simulate_portfolio(pos, n_paths=1_000, seed=3)["pnl"]
    assert np.allclose(pnl, -200_000.0)              # every path: both break

def test_zero_break_never_loses():
    pos = [SimPosition("A", 0.0, 150_000, upside_notional=5_000)]
    pnl = simulate_portfolio(pos, n_paths=1_000, seed=3)["pnl"]
    assert np.allclose(pnl, 5_000.0)                 # always closes, captures spread


def test_mean_loss_is_approximately_unbiased():
    # independent breaks, large N: mean loss ~ sum p_break * downside
    pos = [SimPosition("A", 0.20, 100_000), SimPosition("B", 0.10, 200_000)]
    sim = simulate_portfolio(pos, n_paths=200_000, rho=0.0, seed=11)
    expected = -(0.20 * 100_000 + 0.10 * 200_000)   # -40,000
    assert sim["mean"] == pytest.approx(expected, rel=0.03)


def test_es_at_least_var():
    pos = [SimPosition(f"D{i}", 0.15, 100_000) for i in range(20)]
    pnl = simulate_portfolio(pos, n_paths=50_000, rho=0.2, seed=5)["pnl"]
    assert expected_shortfall(pnl, 0.95) >= value_at_risk(pnl, 0.95)


def test_correlation_fattens_the_tail():
    # identical book; higher rho clusters breaks -> larger tail loss
    pos = [SimPosition(f"D{i}", 0.15, 100_000) for i in range(30)]
    es_indep = expected_shortfall(simulate_portfolio(pos, 60_000, rho=0.0, seed=9)["pnl"], 0.99)
    es_corr = expected_shortfall(simulate_portfolio(pos, 60_000, rho=0.6, seed=9)["pnl"], 0.99)
    assert es_corr > es_indep


def test_risk_report_shape():
    pos = [SimPosition("A", 0.2, 150_000)]
    rep = risk_report(pos, n_paths=10_000, seed=1)
    assert {"VaR", "ES", "mean_pnl", "pnl_percentiles"} <= set(rep)
    assert rep["ES"] >= rep["VaR"]
