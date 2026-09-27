"""Historical-price readiness gates for spread_stress_v1 backtests."""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Optional

from ...ingest.target_prices import deal_print_counts
from .features import VOL_WINDOW_DEFAULT, build_spread_stress_panel

BLOCKED_INSUFFICIENT_PRICE_HISTORY = "BLOCKED_INSUFFICIENT_PRICE_HISTORY"


@dataclass
class PriceReadiness:
    """Audit outcome for longitudinal target-price history."""
    ready: bool
    status: str
    n_deals: int
    n_deals_with_any_print: int
    n_deals_with_min_prints: int
    n_eligible_panel_rows: int
    min_prints_required: int
    vol_window: int
    min_panel_rows_required: int
    missing: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def audit_price_history(conn: sqlite3.Connection, cutoff: str,
                        min_prints: int = 3,
                        vol_window: int = VOL_WINDOW_DEFAULT,
                        min_panel_rows: int = 20,
                        min_class_n: int = 2) -> PriceReadiness:
    """Point-in-time audit: is there enough sourced target history for ΔS/σ?"""
    counts = deal_print_counts(conn)
    n_deals = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
    with_any = sum(1 for n in counts.values() if n > 0)
    with_min = sum(1 for n in counts.values() if n >= min_prints)
    panel = build_spread_stress_panel(cutoff, conn, vol_window=vol_window,
                                      min_prints=min_prints)
    missing = []
    for d, n in sorted(counts.items()):
        if n < min_prints:
            missing.append({"deal_id": d, "n_target_prints": n,
                            "need": min_prints,
                            "gap": "insufficient_longitudinal_target_prints"})
    # deals with zero prints never appear in counts
    zero = conn.execute(
        "SELECT deal_id FROM deals WHERE deal_id NOT IN "
        "(SELECT DISTINCT deal_id FROM deal_market_observations "
        " WHERE target_price IS NOT NULL) ORDER BY deal_id").fetchall()
    for r in zero:
        did = r[0]
        missing.append({"deal_id": did, "n_target_prints": 0, "need": min_prints,
                        "gap": "no_target_price_prints"})

    notes = []
    ready = True
    if with_min < min_panel_rows:
        ready = False
        notes.append(
            f"only {with_min} deals have ≥{min_prints} target prints "
            f"(need ≥{min_panel_rows} for a gradeable panel)")
    if panel["n"] < min_panel_rows:
        ready = False
        notes.append(
            f"spread-stress panel at cutoff={cutoff!r} has n={panel['n']} "
            f"labeled rows (need ≥{min_panel_rows})")
    if panel["n_pos"] < min_class_n or panel["n_neg"] < min_class_n:
        ready = False
        notes.append(
            f"class balance at cutoff insufficient "
            f"(pos={panel['n_pos']}, neg={panel['n_neg']}, min_class_n={min_class_n})")
    if n_deals and with_any == 0:
        ready = False
        notes.append(
            "canonical store has no target_price prints — longitudinal history "
            "required for ΔS and σ_ΔS is missing; populate via "
            "src.ingest.target_prices (reviewed target_price_manifest.json)")

    status = "READY" if ready else BLOCKED_INSUFFICIENT_PRICE_HISTORY
    return PriceReadiness(
        ready=ready, status=status, n_deals=n_deals,
        n_deals_with_any_print=with_any, n_deals_with_min_prints=with_min,
        n_eligible_panel_rows=panel["n"], min_prints_required=min_prints,
        vol_window=vol_window, min_panel_rows_required=min_panel_rows,
        missing=missing, notes=notes,
    )


def authorize_spread_stress_backtest(
        conn: sqlite3.Connection, cutoff: str,
        pit_validation_passed: bool = True,
        **audit_kw) -> dict:
    """Gate: do not run a spread-stress backtest merely because code exists."""
    if not pit_validation_passed:
        return {
            "authorized": False,
            "SPREAD_STRESS_BACKTEST_STATUS": "BLOCKED_PIT_VALIDATION",
            "reason": "point-in-time validation did not pass",
            "price_readiness": None,
        }
    readiness = audit_price_history(conn, cutoff, **audit_kw)
    if not readiness.ready:
        return {
            "authorized": False,
            "SPREAD_STRESS_BACKTEST_STATUS": BLOCKED_INSUFFICIENT_PRICE_HISTORY,
            "reason": "; ".join(readiness.notes) or "insufficient price history",
            "price_readiness": readiness.to_dict(),
            "missing_price_data": readiness.missing,
            "ingestion_unblock": {
                "module": "src.ingest.target_prices",
                "manifest": "pe-tracker/data/target_price_manifest.json",
                "required_fields": [
                    "deal_id", "observation_timestamp", "target_price",
                    "source_name", "source_identifier", "known_at",
                ],
                "instruction": (
                    "Append reviewed target-price prints to the manifest and "
                    "run ingest_target_prices(ManifestTargetPriceProvider()); "
                    "do not fabricate prints."
                ),
            },
        }
    return {
        "authorized": True,
        "SPREAD_STRESS_BACKTEST_STATUS": "AUTHORIZED",
        "reason": "price history and sample gates passed",
        "price_readiness": readiness.to_dict(),
    }
