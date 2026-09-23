"""Portfolio-level research: exposure, concentration, expected loss, drawdown,
and event-driven stress scenarios.

Merger-arb payoffs are asymmetric (small spread captured on close, large loss on
break) and breaks cluster on common shocks, so ordinary covariance understates
tail risk. This layer therefore leads with expected-loss accounting and named
scenario stresses rather than a Gaussian vol number. Where a Sharpe-like ratio is
offered it is explicitly caveated for small samples.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


# --------------------------------------------------------------- exposures
@dataclass
class OpenPosition:
    """An unresolved (censored) position, for forward-looking risk only."""
    deal_id: str
    capital: float
    p_break: float
    downside_notional: float          # $ lost if it breaks (shares * (entry - unaffected))
    sector: Optional[str] = None
    sponsor: Optional[str] = None
    geography: Optional[str] = None
    break_vector: Optional[str] = None   # antitrust|cfius|financing|regulatory|...


def concentration(positions: list, key: str, weight_field: str = "capital") -> dict:
    """Weight by group for `key`, plus HHI and the largest single name.

    HHI (sum of squared weights) runs 1/n (perfectly diversified) to 1 (single
    name) — a scale-free concentration read that a raw max-weight misses.
    """
    total = sum(_get(p, weight_field) or 0.0 for p in positions)
    if total <= 0:
        return {"groups": {}, "hhi": None, "max_weight": None, "max_name": None}
    groups: dict = {}
    for p in positions:
        g = _get(p, key) or "?"
        groups[g] = groups.get(g, 0.0) + (_get(p, weight_field) or 0.0) / total
    hhi = sum(w * w for w in groups.values())
    max_name = max(groups, key=groups.get)
    return {"groups": groups, "hhi": hhi,
            "max_weight": groups[max_name], "max_name": max_name}


def gross_exposure(positions: list, weight_field: str = "capital") -> float:
    return sum(_get(p, weight_field) or 0.0 for p in positions)


# ------------------------------------------------------------ realized P&L
def realized_portfolio(positions: list) -> dict:
    """Aggregate realized (resolved) positions. Reconciles to the position sum."""
    resolved = [p for p in positions if not _get(p, "censored")]
    pnl = sum(_get(p, "realized_pnl") or 0.0 for p in resolved)
    cap = sum(_get(p, "capital") or 0.0 for p in resolved)
    return {"n": len(resolved), "realized_pnl": pnl,
            "capital": cap, "return_on_capital": (pnl / cap) if cap else None}


# --------------------------------------------------------- expected loss
def expected_loss(open_positions: list[OpenPosition]) -> dict:
    """Forward EL = Σ p_break · downside_notional, with per-position contribution.

    This is the number that matters on a rare-break book — a portfolio can look
    calm on realized vol while carrying large expected-loss concentration.
    """
    contribs = [{"deal_id": p.deal_id,
                 "expected_loss": p.p_break * p.downside_notional}
                for p in open_positions]
    total = sum(c["expected_loss"] for c in contribs)
    for c in contribs:
        c["share_of_el"] = (c["expected_loss"] / total) if total else None
    contribs.sort(key=lambda c: c["expected_loss"], reverse=True)
    return {"expected_loss_total": total, "contributions": contribs}


# --------------------------------------------------------------- drawdown
def drawdown(pnl_by_date: list[tuple]) -> dict:
    """Max drawdown of the cumulative realized-P&L curve.

    pnl_by_date: list of (date_str, realized_pnl) — resolution events in time.
    """
    ordered = sorted(pnl_by_date, key=lambda x: x[0])
    cum, peak, max_dd, curve = 0.0, 0.0, 0.0, []
    for d, pnl in ordered:
        cum += pnl
        peak = max(peak, cum)
        dd = cum - peak
        max_dd = min(max_dd, dd)
        curve.append((d, cum, dd))
    return {"max_drawdown": max_dd, "curve": curve}


# ---------------------------------------------------------- stress scenarios
# Each scenario names an event-driven shock: which deals are stressed and how the
# break probability is raised. These are asymmetric / common-cause by design.
SCENARIOS = {
    "broad_risk_off":     {"applies": lambda p: True,                         "p_break_floor": 0.35},
    "financing_shock":    {"applies": lambda p: p.break_vector == "financing" or p.sponsor is not None, "p_break_floor": 0.60},
    "regulatory_tightening": {"applies": lambda p: p.break_vector in ("antitrust", "regulatory"), "p_break_floor": 0.55},
    "antitrust_shock":    {"applies": lambda p: p.break_vector == "antitrust", "force_break": True},
    "cfius_shock":        {"applies": lambda p: p.break_vector == "cfius",     "force_break": True},
    "sponsor_financing_stress": {"applies": lambda p: p.sponsor is not None,   "p_break_floor": 0.50},
}


def scenario_loss(open_positions: list[OpenPosition], scenario: str) -> dict:
    """Expected loss under a named stress scenario.

    Positions the scenario 'applies' to have their break probability raised to
    the scenario floor (or forced to 1.0). Untouched positions keep their own
    p_break. Returns scenario EL and the delta versus the base expected loss.
    """
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; allowed: {sorted(SCENARIOS)}")
    spec = SCENARIOS[scenario]
    base = expected_loss(open_positions)["expected_loss_total"]
    stressed = 0.0
    hit = 0
    for p in open_positions:
        pb = p.p_break
        if spec["applies"](p):
            hit += 1
            pb = 1.0 if spec.get("force_break") else max(pb, spec.get("p_break_floor", pb))
        stressed += pb * p.downside_notional
    return {"scenario": scenario, "positions_stressed": hit,
            "base_expected_loss": base, "scenario_expected_loss": stressed,
            "incremental_loss": stressed - base}


def stress_table(open_positions: list[OpenPosition]) -> list[dict]:
    """Run every scenario — the tail-risk view a reviewer asks for."""
    return [scenario_loss(open_positions, s) for s in SCENARIOS]


# --------------------------------------------------------------- helpers
def _get(obj, k):
    if isinstance(obj, dict):
        return obj.get(k)
    return getattr(obj, k, None)
