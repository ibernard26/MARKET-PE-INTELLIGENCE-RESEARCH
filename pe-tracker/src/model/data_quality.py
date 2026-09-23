"""Dataset-quality report and training-readiness gate.

    python -m src.model.data_quality [--cutoff YYYY-MM-DD]

Ingestion never triggers a fit. The intended flow is:

    ingestion -> validation -> THIS REPORT -> readiness gate -> reviewed model run

MODEL_DATA_STATUS (checked in this order):
  NO_REAL_LABELS                     no resolved deal with a known label
  INSUFFICIENT_SAMPLE                labeled rows < MIN_SAMPLE_N
  INSUFFICIENT_POSITIVE_CLASS        breaks (or closes) < MIN_CLASS_N
  READY_FOR_EXPERIMENTAL_WALK_FORWARD enough rows to RUN an experiment

READY means only that an out-of-time experiment can be run. It is not
evidence that the model works — that requires the walk-forward to beat the
baselines on real data.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import date

from ..config import MIN_SAMPLE_N
from .dataset import build_training_set
from .logistic import MIN_CLASS_N

STATUSES = ("NO_REAL_LABELS", "INSUFFICIENT_SAMPLE", "INSUFFICIENT_POSITIVE_CLASS",
            "READY_FOR_EXPERIMENTAL_WALK_FORWARD")


def readiness(n: int, n_pos: int, min_n: int = MIN_SAMPLE_N,
              min_class: int = MIN_CLASS_N) -> str:
    n_neg = n - n_pos
    if n == 0:
        return "NO_REAL_LABELS"
    if n < min_n:
        return "INSUFFICIENT_SAMPLE"
    if n_pos < min_class or n_neg < min_class:
        return "INSUFFICIENT_POSITIVE_CLASS"
    return "READY_FOR_EXPERIMENTAL_WALK_FORWARD"


def _count(conn, sql, args=()):
    return conn.execute(sql, args).fetchone()[0]


def quality_report(conn: sqlite3.Connection, cutoff: str) -> dict:
    deals = [dict(r) for r in conn.execute("SELECT * FROM deals")]
    ids = [d["deal_id"] for d in deals]
    ev_types = {}
    for r in conn.execute("SELECT deal_id, event_type FROM deal_events"):
        ev_types.setdefault(r[0], set()).add(r[1])
    with_obs = {r[0] for r in conn.execute("SELECT DISTINCT deal_id FROM deal_market_observations")}
    terms = {r[0] for r in conn.execute(
        "SELECT DISTINCT deal_id FROM deal_market_observations "
        "WHERE offer_price IS NOT NULL OR exchange_ratio IS NOT NULL")}
    unaff = {r[0] for r in conn.execute(
        "SELECT DISTINCT deal_id FROM deal_market_observations WHERE unaffected_price IS NOT NULL")}
    prints = {r[0] for r in conn.execute(
        "SELECT DISTINCT deal_id FROM deal_market_observations "
        "WHERE target_price IS NOT NULL OR acquirer_price IS NOT NULL")}
    closed = sum(1 for i in ids if "closing" in ev_types.get(i, set()))
    broken = sum(1 for i in ids if ev_types.get(i, set()) & {"termination", "withdrawal"})
    ts = build_training_set(cutoff, conn)
    fields = ["announce_date", "acquirer", "target", "sponsor", "value_usd_mm", "sector",
              "geography", "deal_type", "offer_price", "unaffected_price",
              "expected_close_date"]
    status = readiness(ts["n"], ts["n_pos"])
    prov_sources = Counter(r[0] for r in conn.execute("SELECT source_name FROM record_provenance"))
    dates = sorted(d["announce_date"] for d in deals if d["announce_date"])
    return {
        "cutoff": cutoff,
        "total_deals": len(ids),
        "deals_with_lifecycle_events": len(ev_types),
        "resolved_deals_by_events": closed + broken,
        "pending_deals": len(ids) - (closed + broken),
        "closed": closed, "broken_terminated_withdrawn": broken,
        "class_prevalence_pi": (broken / (closed + broken)) if (closed + broken) else None,
        "deals_with_announcement_event": sum(1 for i in ids if "announcement" in ev_types.get(i, set())),
        "deals_with_known_at": _count(conn, "SELECT COUNT(DISTINCT deal_id) FROM deal_events WHERE known_at IS NOT NULL"),
        "deals_with_offer_terms": len(terms),
        "deals_with_unaffected_price": len(unaff),
        "deals_with_resolution_event": closed + broken,
        "deals_with_sourced_market_observations": len(prints),
        "deals_with_any_observation": len(with_obs),
        "announce_date_coverage": [dates[0], dates[-1]] if dates else None,
        "sector_coverage": dict(Counter(d["sector"] or "unknown" for d in deals)),
        "geography_coverage": dict(Counter(d["geography"] or "unknown" for d in deals)),
        "ledger_missingness": {f: sum(1 for d in deals if d.get(f) is None) for f in fields},
        "source_coverage": dict(prov_sources) or {"record_provenance": 0},
        "ledger_rows_without_bitemporal_history": sum(1 for i in ids if i not in ev_types),
        "break_logit_v1_eligible_rows": ts["n"],
        "eligible_pos": ts["n_pos"], "eligible_neg": ts["n_neg"],
        "censored_pending_rows": ts["n_censored"],
        "excluded_rows": Counter(e["reason"] for e in ts["excluded"]),
        "MODEL_DATA_STATUS": status,
        "status_note": ("READY means an experiment can be run, not that the model is "
                        "validated" if status.startswith("READY") else
                        "do not fit; collect sourced resolved deals first"),
        "min_sample_n": MIN_SAMPLE_N, "min_class_n": MIN_CLASS_N,
    }


if __name__ == "__main__":
    from ..db import connect, migrate_schema
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default=date.today().isoformat())
    migrate_schema()
    with connect() as c:
        print(json.dumps(quality_report(c, ap.parse_args().cutoff), indent=2, default=dict))
