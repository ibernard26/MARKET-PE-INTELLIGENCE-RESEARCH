"""SYNTHETIC in-memory fixtures for model-infrastructure tests.

These deals are generated, not real transactions. They never touch the real
database and exist only to exercise the pipeline mechanics.
"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from src.research import events as ev
from src.research.observations import Observation, record_observation

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()


def mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def add_deal(c, deal_id, ann: str, pct_spread: float, outcome, resolve_days=120,
             known_lag_days=0, **obs_kw):
    c.execute("INSERT INTO deals (deal_id, announce_date, status) VALUES (?,?,'pending')",
              (deal_id, ann))
    target = 100.0
    kw = dict(offer_price=target * (1 + pct_spread), target_price=target,
              unaffected_price=target * 0.75, consideration_type="cash",
              expected_close_date=(date.fromisoformat(ann) + timedelta(days=180)).isoformat(),
              deal_type="strategic", deal_value_usd_mm=1000.0)
    kw.update(obs_kw)
    record_observation(Observation(deal_id, ann + "T16:00:00", "synthetic",
                                   known_at=ann + "T16:05:00", **kw), conn=c)
    ev.record_event(deal_id, ann + "T16:00:00", "announcement", "synthetic", conn=c,
                    known_at=ann + "T16:05:00")
    if outcome is not None:
        rd = (date.fromisoformat(ann) + timedelta(days=resolve_days)).isoformat()
        kd = (date.fromisoformat(rd) + timedelta(days=known_lag_days)).isoformat()
        ev.record_event(deal_id, rd, "termination" if outcome else "closing",
                        "synthetic", conn=c, known_at=kd)


def synthetic_book(c, n=80, seed=0, start="2024-01-02"):
    """Breaks are more likely at wide spreads (a learnable synthetic signal)."""
    r = np.random.default_rng(seed)
    d0 = date.fromisoformat(start)
    for i in range(n):
        spread = float(r.uniform(0.01, 0.30))
        p = 1 / (1 + np.exp(-(-3.0 + 14.0 * spread)))
        add_deal(c, f"S{i:03d}", (d0 + timedelta(days=7 * i)).isoformat(), spread,
                 int(r.random() < p))
    return c
