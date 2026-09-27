"""Tiingo ↔ Yahoo close reconciliation — tolerance fixed before performance use.

Rule version: price_reconcile_v1
  EXACT_MATCH: abs(diff) == 0
  TOLERABLE_MATCH: abs(diff) <= ABS_EPS or abs(diff)/max(|a|,|b|) <= REL_EPS
  MATERIAL_CONFLICT: otherwise (when both present)
Tolerance chosen for float/vendor representation — not model performance.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .schema import NormalizedEquityObservation

RECONCILE_RULE_VERSION = "price_reconcile_v1"
ABS_EPS = 1e-4          # $0.0001
REL_EPS = 1e-6          # 0.0001%


def classify_close_pair(a: float, b: float) -> str:
    if a == b:
        return "EXACT_MATCH"
    diff = abs(a - b)
    scale = max(abs(a), abs(b), 1e-12)
    if diff <= ABS_EPS or diff / scale <= REL_EPS:
        return "TOLERABLE_MATCH"
    return "MATERIAL_CONFLICT"


def reconcile_series(
        primary: Iterable[NormalizedEquityObservation],
        secondary: Iterable[NormalizedEquityObservation],
        *,
        primary_name: str = "tiingo",
        secondary_name: str = "yahoo_finance_chart",
) -> dict:
    """Compare overlapping session dates. Never average or pick by backtest."""
    pmap = {o.session_date: o for o in primary}
    smap = {o.session_date: o for o in secondary}
    overlap = sorted(set(pmap) & set(smap))
    exact = tolerable = conflict = 0
    conflicts: list[dict] = []
    for sd in overlap:
        cls = classify_close_pair(pmap[sd].close, smap[sd].close)
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
        "rule_version": RECONCILE_RULE_VERSION,
        "abs_eps": ABS_EPS,
        "rel_eps": REL_EPS,
        "n_overlap": len(overlap),
        "exact_match": exact,
        "tolerable_match": tolerable,
        "material_conflict": conflict,
        "tiingo_only": len(set(pmap) - set(smap)),
        "yahoo_only": len(set(smap) - set(pmap)),
        "conflicts": conflicts,
        "status": ("DEFER_PRICE_CONFLICT" if conflict else "AGREE"),
    }
