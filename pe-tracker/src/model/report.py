"""Run break-model v1 on the REAL research store and report honestly.

    python -m src.model.report [--cutoff YYYY-MM-DD]

Prints dataset counts, class balance and a walk-forward attempt. With too little
resolved, sourced history it reports insufficient data rather than a metric.
"""
from __future__ import annotations

import argparse
import json
from datetime import date

from ..db import connect, migrate_schema
from .dataset import build_training_set
from .validation import walk_forward


def run(cutoff: str) -> dict:
    migrate_schema()
    with connect() as c:
        ts = build_training_set(cutoff, c)
        n_deals = c.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
        n_obs = c.execute("SELECT COUNT(*) FROM deal_market_observations").fetchone()[0]
        n_ev = c.execute("SELECT COUNT(*) FROM deal_events").fetchone()[0]
        wf = walk_forward(c, [cutoff], horizon=cutoff)
    return {"cutoff": cutoff, "deals_in_ledger": n_deals,
            "bitemporal_observations": n_obs, "bitemporal_events": n_ev,
            "labeled_rows": ts["n"], "n_pos": ts["n_pos"], "n_neg": ts["n_neg"],
            "n_censored": ts["n_censored"],
            "excluded": ts["excluded"],
            "prevalence": (ts["n_pos"] / ts["n"]) if ts["n"] else None,
            "walk_forward": wf}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default=date.today().isoformat())
    print(json.dumps(run(ap.parse_args().cutoff), indent=2, default=str))
