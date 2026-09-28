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


# Session-evidence labels. classify_close_pair keeps EXACT_MATCH / TOLERABLE_MATCH
# so existing callers do not change; the persisted artifact uses these names.
EVIDENCE_CLASSIFICATION = {
    "EXACT_MATCH": "EXACT",
    "TOLERABLE_MATCH": "TOLERABLE",
    "MATERIAL_CONFLICT": "MATERIAL_CONFLICT",
}


def session_differences(a: float, b: float) -> tuple[float, float]:
    """Absolute and relative raw-close gaps used by classify_close_pair."""
    diff = abs(a - b)
    scale = max(abs(a), abs(b), 1e-12)
    return diff, diff / scale


def reconcile_session_evidence(
        primary: Iterable[NormalizedEquityObservation],
        secondary: Iterable[NormalizedEquityObservation],
        *,
        deal_id: str,
        rule: str = THESIS_RECONCILE_RULE,
) -> list[dict]:
    """One record per overlapping session. Raw close vs raw close; no average."""
    primary, secondary = list(primary), list(secondary)
    _require_raw_close(primary, "tiingo")
    _require_raw_close(secondary, "yahoo")
    pmap = {o.session_date: o for o in primary}
    smap = {o.session_date: o for o in secondary}
    records = []
    for sd in sorted(set(pmap) & set(smap)):
        a, b = pmap[sd].close, smap[sd].close
        cls = classify_close_pair(a, b, rule)
        abs_diff, rel_diff = session_differences(a, b)
        records.append({
            "deal_id": deal_id,
            "session_date": sd,
            "tiingo_raw_close": a,
            "yahoo_raw_close": b,
            "absolute_difference": abs_diff,
            "relative_difference": rel_diff,
            "classification": EVIDENCE_CLASSIFICATION[cls],
            "rule_version": rule,
        })
    return records


def summarize_session_evidence(sessions: Iterable[dict]) -> tuple[list[dict], dict]:
    """Per-deal counts and grand totals derived only from session rows."""
    by: dict[str, dict] = {}
    for row in sessions:
        slot = by.setdefault(row["deal_id"], {
            "deal_id": row["deal_id"],
            "overlap_sessions": 0,
            "exact_matches": 0,
            "tolerable_matches": 0,
            "material_conflicts": 0,
            "rule_version": row["rule_version"],
        })
        slot["overlap_sessions"] += 1
        label = row["classification"]
        if label == "EXACT":
            slot["exact_matches"] += 1
        elif label == "TOLERABLE":
            slot["tolerable_matches"] += 1
        elif label == "MATERIAL_CONFLICT":
            slot["material_conflicts"] += 1
        else:
            raise ReconciliationError(f"unknown classification {label!r}")
        if slot["rule_version"] != row["rule_version"]:
            raise ReconciliationError("mixed reconcile rule versions in one artifact")
    per_deal = [by[k] for k in sorted(by)]
    totals = {
        "overlap_sessions": sum(r["overlap_sessions"] for r in per_deal),
        "exact": sum(r["exact_matches"] for r in per_deal),
        "tolerable": sum(r["tolerable_matches"] for r in per_deal),
        "conflict": sum(r["material_conflicts"] for r in per_deal),
    }
    if totals["overlap_sessions"] != totals["exact"] + totals["tolerable"] + totals["conflict"]:
        raise ReconciliationError("session evidence does not partition the overlap")
    return per_deal, totals
