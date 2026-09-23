"""Stage 3 tests: event-driven backtester.

Hand-worked P&L for a closed and a broken deal, censoring of pending deals, and
rejection of a resolution that precedes entry (no lookahead).
"""
import pytest

from src.research.backtest import (BacktestConfig, Trade, evaluate_trade,
                                   run_backtest)

# No transaction costs makes the arithmetic checkable by hand.
NOCOST = BacktestConfig(tx_cost_bps=0.0, capital_per_deal=1_000_000.0)


def test_closed_deal_pnl_hand_worked():
    # buy at 95, deal closes at offer 100. shares = 1,000,000/95.
    # gross = shares*(100-95) = 1,000,000/95*5 = 52,631.578...
    t = Trade("A", "2026-02-01", entry_price=95.0, offer_price=100.0,
              unaffected_price=80.0, expected_close_date="2026-08-01",
              status="closed", resolution_date="2026-08-01")
    r = evaluate_trade(t, NOCOST)
    assert r["realized_pnl"] == pytest.approx(1_000_000 / 95 * 5)
    assert r["holding_days"] == 181
    assert r["annualized_return"] == pytest.approx((r["realized_pnl"] / 1_000_000) * 365 / 181)
    assert r["is_break_loss"] is False


def test_broken_deal_is_a_loss_to_unaffected():
    # buy at 95, deal breaks -> exit at unaffected 80. gross = shares*(80-95) < 0
    t = Trade("B", "2026-02-01", entry_price=95.0, offer_price=100.0,
              unaffected_price=80.0, expected_close_date="2026-08-01",
              status="broken", resolution_date="2026-05-01")
    r = evaluate_trade(t, NOCOST)
    assert r["realized_pnl"] == pytest.approx(1_000_000 / 95 * (80 - 95))
    assert r["realized_pnl"] < 0
    assert r["is_break_loss"] is True


def test_transaction_costs_reduce_pnl():
    t = Trade("A", "2026-02-01", 95.0, 100.0, 80.0, "2026-08-01",
              status="closed", resolution_date="2026-08-01")
    free = evaluate_trade(t, NOCOST)["realized_pnl"]
    costed = evaluate_trade(t, BacktestConfig(tx_cost_bps=10.0))["realized_pnl"]
    assert costed < free


def test_pending_deal_is_censored():
    t = Trade("C", "2026-02-01", 95.0, 100.0, 80.0, "2026-08-01", status="pending")
    r = evaluate_trade(t, NOCOST)
    assert r["censored"] is True
    assert r["realized_pnl"] is None and r["annualized_return"] is None


def test_resolution_before_entry_is_rejected():
    t = Trade("D", "2026-05-01", 95.0, 100.0, 80.0, "2026-08-01",
              status="closed", resolution_date="2026-01-01")   # before entry
    with pytest.raises(ValueError):
        evaluate_trade(t, NOCOST)


def test_run_backtest_excludes_pending_from_realized_summary():
    trades = [
        Trade("A", "2026-02-01", 95.0, 100.0, 80.0, "2026-08-01",
              status="closed", resolution_date="2026-08-01"),
        Trade("B", "2026-02-01", 95.0, 100.0, 80.0, "2026-08-01",
              status="broken", resolution_date="2026-05-01"),
        Trade("C", "2026-03-01", 50.0, 55.0, 40.0, "2026-09-01", status="pending"),
    ]
    out = run_backtest(trades, NOCOST)
    assert out["summary"]["n_resolved"] == 2
    assert out["summary"]["n_censored_pending"] == 1
    assert out["summary"]["break_rate"] == pytest.approx(0.5)
    # realized P&L reconciles to the sum of resolved positions
    assert out["summary"]["realized_pnl"] == pytest.approx(
        sum(p["realized_pnl"] for p in out["positions"]))
