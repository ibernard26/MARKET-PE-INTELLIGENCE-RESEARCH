"""Historical event-driven merger-arb backtester.

Sequence per deal:
    entry date -> information available at entry -> p_break -> trade decision
    -> position -> later events -> resolution -> P&L

No lookahead: a position is opened using only what was knowable at the entry
date, and a resolution dated before entry is rejected as impossible. Pending
(unresolved) deals are CENSORED — carried as open positions, never counted in
realized performance (Invariant 4). Costs are explicit; assumptions are held in
a versioned config object so a backtest is reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class BacktestConfig:
    """Explicit, versioned research assumptions."""
    version: str = "bt_v1"
    tx_cost_bps: float = 10.0          # per side, in basis points of notional
    capital_per_deal: float = 1_000_000.0


@dataclass
class Trade:
    """One deal put through the backtester.

    entry_price / offer_price / unaffected_price are per-share. status is the
    REALIZED outcome ('closed'/'broken') or 'pending' (censored). resolution_date
    is None while pending.
    """
    deal_id: str
    entry_date: str
    entry_price: float
    offer_price: float
    unaffected_price: float
    expected_close_date: str
    status: str = "pending"
    resolution_date: Optional[str] = None
    capital: Optional[float] = None


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days


def evaluate_trade(t: Trade, cfg: BacktestConfig = BacktestConfig()) -> dict:
    """Realized P&L for one trade. Pending trades return a censored position with
    no realized figures. Raises on a resolution that precedes entry (lookahead /
    impossible lifecycle)."""
    capital = t.capital if t.capital is not None else cfg.capital_per_deal
    shares = capital / t.entry_price
    bps = cfg.tx_cost_bps / 1e4

    base = {
        "deal_id": t.deal_id, "entry_date": t.entry_date,
        "entry_price": t.entry_price, "shares": shares, "capital": capital,
        "expected_close_date": t.expected_close_date,
    }

    if t.status == "pending" or t.resolution_date is None:
        return {**base, "status": "pending", "censored": True,
                "realized_pnl": None, "annualized_return": None}

    if t.status not in ("closed", "broken"):
        raise ValueError(f"unknown realized status {t.status!r}")
    if _days(t.resolution_date, t.entry_date) < 0:
        raise ValueError(
            f"resolution {t.resolution_date} precedes entry {t.entry_date} "
            f"for {t.deal_id} — impossible / lookahead")

    exit_price = t.offer_price if t.status == "closed" else t.unaffected_price
    gross_pnl = shares * (exit_price - t.entry_price)
    entry_cost = capital * bps
    exit_cost = shares * exit_price * bps
    realized_pnl = gross_pnl - entry_cost - exit_cost
    hold_days = max(_days(t.resolution_date, t.entry_date), 1)
    ann = (realized_pnl / capital) * (365.0 / hold_days)

    return {
        **base, "status": t.status, "censored": False,
        "resolution_date": t.resolution_date, "exit_price": exit_price,
        "holding_days": hold_days,
        "gross_pnl": gross_pnl,
        "transaction_costs": entry_cost + exit_cost,
        "realized_pnl": realized_pnl,
        "return_on_capital": realized_pnl / capital,
        "annualized_return": ann,
        "is_break_loss": t.status == "broken",
    }


def run_backtest(trades: list[Trade], cfg: BacktestConfig = BacktestConfig()) -> dict:
    """Backtest a book of trades. Returns resolved positions, censored (pending)
    positions, and a realized-only summary."""
    resolved, censored = [], []
    for t in trades:
        r = evaluate_trade(t, cfg)
        (censored if r["censored"] else resolved).append(r)

    realized_pnl = sum(p["realized_pnl"] for p in resolved)
    capital_resolved = sum(p["capital"] for p in resolved)
    n_break = sum(1 for p in resolved if p["status"] == "broken")
    summary = {
        "config_version": cfg.version,
        "n_resolved": len(resolved),
        "n_censored_pending": len(censored),
        "realized_pnl": realized_pnl,
        "capital_deployed_resolved": capital_resolved,
        "return_on_capital": (realized_pnl / capital_resolved) if capital_resolved else None,
        "n_breaks": n_break,
        "break_rate": (n_break / len(resolved)) if resolved else None,
    }
    return {"positions": resolved, "censored": censored, "summary": summary}
