"""Decision layer — deliberately separate from the probability model.

EV per share = (1 − p)·U − p·D, where U = upside to consideration if the deal
closes and D = downside to the break price. The model only supplies p; U and D
come from point-in-time deal state. A position is taken only if EV > 0 AND
p < t* (the cost-based threshold); t* is never defaulted to 0.5.
"""
from __future__ import annotations

from typing import Optional


def expected_value(p_break: float, upside: float, downside: float) -> float:
    if not 0.0 <= p_break <= 1.0:
        raise ValueError("p_break must be in [0, 1]")
    if upside is None or downside is None:
        raise ValueError("upside and downside are required (no fabrication)")
    return (1.0 - p_break) * upside - p_break * downside


def breakeven_p(upside: float, downside: float) -> Optional[float]:
    """p at which EV = 0: U / (U + D)."""
    return upside / (upside + downside) if (upside + downside) > 0 else None


def decide(p_break: float, upside: float, downside: float,
           t_star: Optional[float]) -> dict:
    ev = expected_value(p_break, upside, downside)
    if t_star is None:
        return {"action": "no_trade", "ev": ev,
                "reason": "no validated cost-based threshold (insufficient sample)"}
    take = ev > 0 and p_break < t_star
    return {"action": "enter" if take else "no_trade", "ev": ev, "t_star": t_star,
            "breakeven_p": breakeven_p(upside, downside)}
