"""Historical event-driven merger-arb backtester.

Sequence per deal:
    entry date -> information available at entry -> p_break -> trade decision
    -> position -> later events -> resolution -> P&L

No lookahead: a position is opened using only what was knowable at the entry
date, and a resolution dated before entry is rejected as impossible. Pending
(unresolved) deals are CENSORED — carried as open positions, never counted in
realized performance (Invariant 4). Costs are explicit; assumptions are held in
a versioned config object so a backtest is reproducible.

Scope: CASH consideration only. Stock/mixed deals need an acquirer-price path
and hedge accounting that this backtester does not model, so they are rejected
(UnsupportedConsiderationError) rather than silently run through cash formulas.

Break exits follow an explicit hierarchy:
  1. actual sourced post-break price (break_exit_price + source + timestamp)
     -> pnl_type 'realized', counted in realized_pnl;
  2. modeled fallback to the unaffected price (only if cfg allows)
     -> pnl_type 'modeled_break', reported as modeled_break_pnl, NEVER realized;
  3. otherwise 'unresolved_exit' -> no P&L figure at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .bitemporal import normalize_as_of


@dataclass(frozen=True)
class BacktestConfig:
    """Explicit, versioned research assumptions."""
    version: str = "bt_v2"
    tx_cost_bps: float = 10.0          # per side, in basis points of notional
    capital_per_deal: float = 1_000_000.0
    allow_modeled_break_fallback: bool = True   # unaffected-price model, labeled


class UnsupportedConsiderationError(ValueError):
    """Raised for non-cash deals: the backtester is scoped to cash consideration."""


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
    consideration_type: str = "cash"
    break_exit_price: Optional[float] = None      # actual sourced post-break print
    break_exit_source: Optional[str] = None
    break_exit_timestamp: Optional[str] = None
    # contemporaneous model score (see src/model/bridge.py); never later than entry
    p_break: Optional[float] = None
    p_break_as_of: Optional[str] = None
    p_break_model_version: Optional[str] = None


def _days(a: str, b: str) -> int:
    """Whole calendar days from date `b` to date `a`."""
    return (date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days


def evaluate_trade(t: Trade, cfg: BacktestConfig = BacktestConfig()) -> dict:
    """Realized P&L for one trade. Pending trades return a censored position with
    no realized figures. Raises on a resolution that precedes entry (lookahead /
    impossible lifecycle)."""
    if t.consideration_type != "cash":
        raise UnsupportedConsiderationError(
            f"{t.deal_id}: consideration {t.consideration_type!r} not supported — "
            "backtester is scoped to cash deals")
    if t.p_break is not None and (t.p_break_as_of is None
                                  or normalize_as_of(t.p_break_as_of)
                                  > normalize_as_of(t.entry_date)):
        raise ValueError(f"{t.deal_id}: p_break as_of {t.p_break_as_of} is not on/before "
                         f"entry {t.entry_date} — lookahead")
    capital = t.capital if t.capital is not None else cfg.capital_per_deal
    shares = capital / t.entry_price
    bps = cfg.tx_cost_bps / 1e4

    base = {
        "deal_id": t.deal_id, "entry_date": t.entry_date,
        "entry_price": t.entry_price, "shares": shares, "capital": capital,
        "expected_close_date": t.expected_close_date,
        "p_break": t.p_break, "p_break_as_of": t.p_break_as_of,
        "p_break_model_version": t.p_break_model_version,
    }

    if t.status == "pending" or t.resolution_date is None:
        return {**base, "status": "pending", "censored": True, "pnl_type": None,
                "realized_pnl": None, "modeled_break_pnl": None,
                "annualized_return": None}

    if t.status not in ("closed", "broken"):
        raise ValueError(f"unknown realized status {t.status!r}")
    if _days(t.resolution_date, t.entry_date) < 0:
        raise ValueError(
            f"resolution {t.resolution_date} precedes entry {t.entry_date} "
            f"for {t.deal_id} — impossible / lookahead")

    if t.status == "closed":
        exit_price, exit_source, exit_ts, pnl_type = (
            t.offer_price, "deal_consideration", t.resolution_date, "realized")
    elif t.break_exit_price is not None:
        if not t.break_exit_source or not t.break_exit_timestamp:
            raise ValueError(f"{t.deal_id}: break_exit_price requires source and timestamp")
        if t.break_exit_timestamp[:10] < t.resolution_date[:10]:
            raise ValueError(f"{t.deal_id}: break exit {t.break_exit_timestamp} precedes "
                             f"break resolution {t.resolution_date}")
        exit_price, exit_source, exit_ts, pnl_type = (
            t.break_exit_price, t.break_exit_source, t.break_exit_timestamp, "realized")
    elif cfg.allow_modeled_break_fallback and t.unaffected_price is not None:
        exit_price, exit_source, exit_ts, pnl_type = (
            t.unaffected_price, "modeled:unaffected_price", None, "modeled_break")
    else:
        return {**base, "status": t.status, "censored": False,
                "resolution_date": t.resolution_date, "pnl_type": "unresolved_exit",
                "exit_price": None, "exit_source": None, "exit_timestamp": None,
                "realized_pnl": None, "modeled_break_pnl": None,
                "annualized_return": None, "is_break_loss": True}

    gross_pnl = shares * (exit_price - t.entry_price)
    entry_cost = capital * bps
    exit_cost = shares * exit_price * bps
    pnl = gross_pnl - entry_cost - exit_cost
    hold_days = max(_days(t.resolution_date, t.entry_date), 1)
    ann = (pnl / capital) * (365.0 / hold_days)
    realized = pnl_type == "realized"

    return {
        **base, "status": t.status, "censored": False,
        "resolution_date": t.resolution_date, "exit_price": exit_price,
        "exit_source": exit_source, "exit_timestamp": exit_ts,
        "pnl_type": pnl_type,
        "holding_days": hold_days,
        "gross_pnl": gross_pnl,
        "transaction_costs": entry_cost + exit_cost,
        "realized_pnl": pnl if realized else None,
        "modeled_break_pnl": None if realized else pnl,
        "return_on_capital": pnl / capital,
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

    realized = [p for p in resolved if p["pnl_type"] == "realized"]
    modeled = [p for p in resolved if p["pnl_type"] == "modeled_break"]
    realized_pnl = sum(p["realized_pnl"] for p in realized)
    capital_resolved = sum(p["capital"] for p in realized)
    n_break = sum(1 for p in resolved if p["status"] == "broken")
    summary = {
        "config_version": cfg.version,
        "n_resolved": len(resolved),
        "n_censored_pending": len(censored),
        "n_realized": len(realized),
        "n_modeled_break": len(modeled),
        "n_unresolved_exit": sum(1 for p in resolved if p["pnl_type"] == "unresolved_exit"),
        "realized_pnl": realized_pnl,
        "modeled_break_pnl": sum(p["modeled_break_pnl"] for p in modeled),
        "capital_deployed_resolved": capital_resolved,
        "return_on_capital": (realized_pnl / capital_resolved) if capital_resolved else None,
        "n_breaks": n_break,
        "break_rate": (n_break / len(resolved)) if resolved else None,
    }
    return {"positions": resolved, "censored": censored, "summary": summary}
