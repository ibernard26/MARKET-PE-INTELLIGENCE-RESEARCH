"""Tiingo ↔ Yahoo close reconciliation — tolerances fixed before performance use.

Two frozen rule versions; neither may be edited after live data is observed
(a change is a new version, e.g. price_reconcile_v3):

  price_reconcile_v1   ABS_EPS = $0.0001   REL_EPS = 1e-6   (original; kept unchanged)
  price_reconcile_v2   ABS_EPS = $0.01     REL_EPS = 1e-4   (1 bp) — CANONICAL THESIS RULE
                       specified 2026-09-27, before the first live Tiingo/Yahoo run

  EXACT_MATCH:       a == b
  TOLERABLE_MATCH:   abs(diff) <= ABS_EPS  OR  abs(diff)/max(|a|,|b|) <= REL_EPS
  MATERIAL_CONFLICT: otherwise → the deal is DEFER_PRICE_CONFLICT

Comparison is RAW close vs RAW close only (close_field_used == "close" on both
sides); adjusted closes are never compared. Never average or pick by backtest.
"""
from __future__ import annotations

from typing import Iterable

from .schema import NormalizedEquityObservation

RECONCILE_RULES: dict[str, tuple[float, float]] = {
    "price_reconcile_v1": (1e-4, 1e-6),
    "price_reconcile_v2": (0.01, 1e-4),
}
THESIS_RECONCILE_RULE = "price_reconcile_v2"

# v1 names preserved for existing callers.
RECONCILE_RULE_VERSION = "price_reconcile_v1"
ABS_EPS, REL_EPS = RECONCILE_RULES[RECONCILE_RULE_VERSION]


class ReconciliationError(ValueError):
    pass


def classify_close_pair(a: float, b: float,
                        rule: str = RECONCILE_RULE_VERSION) -> str:
    abs_eps, rel_eps = RECONCILE_RULES[rule]
    if a == b:
        return "EXACT_MATCH"
    diff = abs(a - b)
    scale = max(abs(a), abs(b), 1e-12)
    if diff <= abs_eps or diff / scale <= rel_eps:
        return "TOLERABLE_MATCH"
    return "MATERIAL_CONFLICT"


def _require_raw_close(obs: list[NormalizedEquityObservation], side: str) -> None:
    bad = {o.close_field_used for o in obs if o.close_field_used != "close"}
    if bad:
        raise ReconciliationError(
            f"{side} series uses {sorted(bad)}; reconciliation compares raw close only")


def reconcile_series(
        primary: Iterable[NormalizedEquityObservation],
        secondary: Iterable[NormalizedEquityObservation],
        *,
        primary_name: str = "tiingo",
        secondary_name: str = "yahoo_finance_chart",
        rule: str = RECONCILE_RULE_VERSION,
) -> dict:
    """Compare overlapping session dates. Never average or pick by backtest."""
    primary, secondary = list(primary), list(secondary)
    _require_raw_close(primary, primary_name)
    _require_raw_close(secondary, secondary_name)
    abs_eps, rel_eps = RECONCILE_RULES[rule]
    pmap = {o.session_date: o for o in primary}
    smap = {o.session_date: o for o in secondary}
    overlap = sorted(set(pmap) & set(smap))
    exact = tolerable = conflict = 0
    conflicts: list[dict] = []
    for sd in overlap:
        cls = classify_close_pair(pmap[sd].close, smap[sd].close, rule)
        if cls == "EXACT_MATCH":
            exact += 1
        elif cls == "TOLERABLE_MATCH":
            tolerable += 1
        else:
            conflict += 1
            conflicts.append({
                "session_date": sd,
                "primary_provider": pmap[sd].provider,
                "secondary_provider": smap[sd].provider,
                "primary_close": pmap[sd].close,
                "secondary_close": smap[sd].close,
                "classification": cls,
                "primary_splitFactor": (pmap[sd].source_metadata or {}).get("splitFactor"),
                "primary_divCash": (pmap[sd].source_metadata or {}).get("divCash"),
            })
    return {
        "rule_version": rule,
        "abs_eps": abs_eps,
        "rel_eps": rel_eps,
        "n_overlap": len(overlap),
        "exact_match": exact,
        "tolerable_match": tolerable,
        "material_conflict": conflict,
        "tiingo_only": len(set(pmap) - set(smap)),
        "yahoo_only": len(set(smap) - set(pmap)),
        "conflicts": conflicts,
        "status": ("DEFER_PRICE_CONFLICT" if conflict else "AGREE"),
    }
