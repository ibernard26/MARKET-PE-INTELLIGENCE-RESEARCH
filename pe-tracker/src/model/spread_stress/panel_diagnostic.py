"""Diagnostic for the existing spread_stress_v1 panel rule.

Does not change feature time, does not select a last pre-resolution print,
and does not fit a model. A timestamp collision is not a finding that the
raw price history is missing.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from ...research import events as ev
from ...research.bitemporal import normalize_ts
from ...research.observations import Observation, record_observation
from .features import build_spread_stress_panel

FEATURE_TIME_RESOLUTION_TIMESTAMP_COLLISION = "FEATURE_TIME_RESOLUTION_TIMESTAMP_COLLISION"
SCHEMA = (Path(__file__).resolve().parents[3] / "schema.sql").read_text()

_RESOLUTION_EVENT = {
    "closed": "closing",
    "closing": "closing",
    "completed": "closing",
    "terminated": "termination",
    "broken": "termination",
    "withdrawn": "withdrawal",
    "withdrawal": "withdrawal",
}


def diagnose_v1_panel(
        panel: dict,
        *,
        price_coverage_ready: bool,
        pre_resolution_prints: int,
        deals_with_3plus_pre_resolution_prints: int,
) -> dict:
    """Separate the coverage gate from the v1 feature-time collision."""
    collision = sum(
        1 for row in panel.get("excluded") or []
        if row.get("reason") == "feature_not_before_resolution")
    insufficient = sum(
        1 for row in panel.get("excluded") or []
        if row.get("reason") == "insufficient_price_history")
    if price_coverage_ready and collision > 0:
        reason = FEATURE_TIME_RESOLUTION_TIMESTAMP_COLLISION
        valid = "NO"
    elif not price_coverage_ready:
        reason = "INSUFFICIENT_PRICE_HISTORY" if insufficient else "COVERAGE_GATE_NOT_MET"
        valid = "NO"
    elif panel.get("n_pos", 0) < 2 or panel.get("n_neg", 0) < 2:
        reason = "CLASS_BALANCE_BELOW_MIN_CLASS_N"
        valid = "NO"
    else:
        reason = None
        valid = "YES"
    return {
        "PRICE_COVERAGE_READY": "YES" if price_coverage_ready else "NO",
        "SPREAD_STRESS_V1_PANEL_VALID": valid,
        "SPREAD_STRESS_V1_EXECUTED": "NO",
        "SPREAD_STRESS_V1_MODEL_FIT": "NO",
        "SPREAD_STRESS_V1_BLOCK_REASON": reason,
        "PRE_RESOLUTION_PRINTS_AVAILABLE": pre_resolution_prints,
        "DEALS_WITH_3PLUS_PRE_RESOLUTION_PRINTS": deals_with_3plus_pre_resolution_prints,
        "PANEL_ROWS_EXCLUDED_FEATURE_NOT_BEFORE_RESOLUTION": collision,
        "panel_rows_labeled": panel.get("n"),
        "panel_n_pos": panel.get("n_pos"),
        "panel_n_neg": panel.get("n_neg"),
        "insufficient_price_history_exclusions": insufficient,
        "note": (
            "PRICE_COVERAGE_READY records the historical-price coverage gate. "
            "SPREAD_STRESS_V1_PANEL_VALID records whether the existing v1 "
            "feature-time rule produced a usable panel. A feature-time collision "
            "with date-only resolution timestamps is not evidence that the "
            "dataset lacks longitudinal price history. This diagnostic does not "
            "select the last pre-resolution print and does not fit a model."
        ),
    }


def pre_resolution_print_stats(prints: list[dict], deals_by_id: dict[str, dict],
                               *, min_prints: int = 3) -> tuple[int, int]:
    """Count prints strictly before the stored resolution instant.

    Date-only resolutions normalize to midnight, so a 16:00 close on the
    resolution calendar date is not pre-resolution. This is a count, not a
    feature-time rule.
    """
    by_deal: Counter = Counter()
    total = 0
    for row in prints:
        deal = deals_by_id.get(row["deal_id"]) or {}
        res = deal.get("resolution_timestamp")
        obs = row.get("observation_timestamp")
        if not res or not obs:
            continue
        if normalize_ts(obs) < normalize_ts(res):
            total += 1
            by_deal[row["deal_id"]] += 1
    deals = sum(1 for n in by_deal.values() if n >= min_prints)
    return total, deals


def memory_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def load_manifest_panel(prints: list[dict], deals: list[dict], *,
                        cutoff: str = "2030-01-01", min_prints: int = 3) -> dict:
    """Run the existing v1 panel builder on manifest prints. No model fit."""
    by_id = {d["deal_id"]: d for d in deals}
    conn = memory_connection()
    seen = set()
    for deal_id in sorted({p["deal_id"] for p in prints}):
        deal = by_id.get(deal_id)
        if deal is None:
            continue
        ann = (deal.get("announcement_timestamp") or "")[:10]
        if not ann:
            continue
        conn.execute(
            "INSERT INTO deals (deal_id, announce_date, target, status) VALUES (?,?,?,?)",
            (deal_id, ann, deal.get("target"), "pending"))
        ev.record_event(deal_id, deal.get("announcement_timestamp") or ann,
                        "announcement", "sec_manifest", conn=conn,
                        known_at=deal.get("announcement_timestamp") or ann)
        res = deal.get("resolution_timestamp")
        kind = _RESOLUTION_EVENT.get((deal.get("resolution_type") or "").lower())
        if res and kind:
            ev.record_event(deal_id, res, kind, "sec_manifest", conn=conn, known_at=res)
        seen.add(deal_id)
    for row in prints:
        if row["deal_id"] not in seen:
            continue
        record_observation(Observation(
            row["deal_id"],
            row["observation_timestamp"],
            row.get("source_name") or row.get("provider") or "tiingo",
            target_price=float(row["target_price"]),
            known_at=row.get("known_at") or row["observation_timestamp"],
        ), conn=conn)
    return build_spread_stress_panel(cutoff, conn, min_prints=min_prints)
