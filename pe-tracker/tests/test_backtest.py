"""Stage 3 tests: event-driven backtester.

Hand-worked P&L for a closed and a broken deal, censoring of pending deals, and
rejection of a resolution that precedes entry (no lookahead).
"""
import pytest

from src.research.backtest import (BacktestConfig, Trade,
                                   UnsupportedConsiderationError,
                                   evaluate_trade, run_backtest)

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


def test_broken_deal_without_sourced_exit_is_modeled_not_realized():
    # buy at 95, deal breaks, no sourced post-break print -> modeled exit at
    # unaffected 80. Reported as modeled_break_pnl, NEVER as realized_pnl.
    t = Trade("B", "2026-02-01", entry_price=95.0, offer_price=100.0,
              unaffected_price=80.0, expected_close_date="2026-08-01",
              status="broken", resolution_date="2026-05-01")
    r = evaluate_trade(t, NOCOST)
    assert r["pnl_type"] == "modeled_break"
    assert r["realized_pnl"] is None
    assert r["modeled_break_pnl"] == pytest.approx(1_000_000 / 95 * (80 - 95))
    assert r["exit_source"] == "modeled:unaffected_price"
    assert r["is_break_loss"] is True


def test_broken_deal_with_sourced_exit_is_realized():
    t = Trade("B", "2026-02-01", 95.0, 100.0, 80.0, "2026-08-01",
              status="broken", resolution_date="2026-05-01",
              break_exit_price=83.0, break_exit_source="nyse_close",
              break_exit_timestamp="2026-05-02T16:00:00")
    r = evaluate_trade(t, NOCOST)
    assert r["pnl_type"] == "realized"
    assert r["realized_pnl"] == pytest.approx(1_000_000 / 95 * (83 - 95))
    assert r["modeled_break_pnl"] is None
    assert (r["exit_source"], r["exit_timestamp"]) == ("nyse_close", "2026-05-02T16:00:00")


def test_sourced_exit_requires_provenance_and_post_break_timestamp():
    base = dict(status="broken", resolution_date="2026-05-01", break_exit_price=83.0)
    with pytest.raises(ValueError):
        evaluate_trade(Trade("B", "2026-02-01", 95.0, 100.0, 80.0, "2026-08-01", **base), NOCOST)
    with pytest.raises(ValueError):   # exit before the break is lookahead-impossible
        evaluate_trade(Trade("B", "2026-02-01", 95.0, 100.0, 80.0, "2026-08-01", **base,
                             break_exit_source="s", break_exit_timestamp="2026-04-01"), NOCOST)


def test_break_without_exit_or_fallback_is_unresolved():
    t = Trade("B", "2026-02-01", 95.0, 100.0, None, "2026-08-01",
              status="broken", resolution_date="2026-05-01")
    r = evaluate_trade(t, NOCOST)
    assert r["pnl_type"] == "unresolved_exit"
    assert r["realized_pnl"] is None and r["modeled_break_pnl"] is None
    t2 = Trade("B", "2026-02-01", 95.0, 100.0, 80.0, "2026-08-01",
               status="broken", resolution_date="2026-05-01")
    r2 = evaluate_trade(t2, BacktestConfig(tx_cost_bps=0.0, allow_modeled_break_fallback=False))
    assert r2["pnl_type"] == "unresolved_exit"


@pytest.mark.parametrize("ct", ["stock", "mixed"])
def test_non_cash_deals_are_rejected_not_run_through_cash_formulas(ct):
    t = Trade("S", "2026-02-01", 95.0, 100.0, 80.0, "2026-08-01",
              status="closed", resolution_date="2026-08-01", consideration_type=ct)
    with pytest.raises(UnsupportedConsiderationError):
        evaluate_trade(t, NOCOST)


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
    # realized P&L reconciles to realized positions only; the modeled break is separate
    assert out["summary"]["n_realized"] == 1 and out["summary"]["n_modeled_break"] == 1
    assert out["summary"]["realized_pnl"] == pytest.approx(
        sum(p["realized_pnl"] for p in out["positions"] if p["pnl_type"] == "realized"))
    assert out["summary"]["modeled_break_pnl"] == pytest.approx(1_000_000 / 95 * (80 - 95))
