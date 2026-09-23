"""Performance benchmark harness — SYNTHETIC DATA ONLY.

Everything this module generates is random synthetic data for measuring compute
performance. It is NEVER research evidence and must never be mixed with the real
observation/deal store. Its only purpose is to show where time goes as the
workload grows, so the C++ decision (docs/CPP_QUANT_CORE_CRITERIA.md) rests on
measurements rather than intuition.

Run:  python -m benchmarks.bench          # default scales
      python -m benchmarks.bench --quick  # tiny scales (smoke)
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from src.research import portfolio as pf
from src.research.backtest import Trade, run_backtest
from src.research.features import build_features
from src.research.portfolio import OpenPosition
from src.research.simulation import SimPosition, risk_report

SYNTHETIC = True  # marker: nothing here is real data
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _rng(seed=0):
    return np.random.default_rng(seed)


# ---------------------------------------------------- synthetic generators
def synth_observations(n, seed=0):
    """n synthetic (observation, events) pairs for feature-gen timing."""
    r = _rng(seed)
    out = []
    for i in range(n):
        offer = float(r.uniform(20, 200))
        cur = offer * float(r.uniform(0.90, 0.99))
        unaff = cur * float(r.uniform(0.6, 0.85))
        obs = {"offer_price": offer, "target_price": cur, "unaffected_price": unaff,
               "expected_close_date": "2027-01-01", "deal_type": "take_private",
               "consideration_type": "cash", "deal_value_usd_mm": float(r.uniform(500, 50000)),
               "shareholder_vote_state": "required_pending",
               "regulatory_attrs": {"cfius": bool(i % 3 == 0), "antitrust": True}}
        out.append((obs, [{"event_type": "announcement"}]))
    return out


def synth_trades(n, seed=1):
    r = _rng(seed)
    trades = []
    for i in range(n):
        entry = float(r.uniform(20, 200))
        offer = entry * float(r.uniform(1.01, 1.12))
        unaff = entry * float(r.uniform(0.6, 0.85))
        broke = r.random() < 0.10
        trades.append(Trade(f"S{i}", "2026-01-05", entry, offer, unaff, "2026-09-01",
                            status="broken" if broke else "closed",
                            resolution_date="2026-06-01"))
    return trades


def synth_open_positions(n, seed=2):
    r = _rng(seed)
    sectors = ["Tech", "Health", "Energy", "Industrials", "Airlines"]
    vecs = ["antitrust", "cfius", "financing", "regulatory"]
    return [OpenPosition(f"S{i}", capital=1e6, p_break=float(r.uniform(0.05, 0.5)),
                         downside_notional=float(r.uniform(50_000, 400_000)),
                         sector=sectors[i % len(sectors)],
                         sponsor=("PE" if i % 2 else None),
                         break_vector=vecs[i % len(vecs)]) for i in range(n)]


def synth_sim_positions(n, seed=3):
    r = _rng(seed)
    return [SimPosition(f"S{i}", p_break=float(r.uniform(0.05, 0.5)),
                        downside_notional=float(r.uniform(50_000, 400_000)))
            for i in range(n)]


# ------------------------------------------------------------------ timing
def _time(fn) -> float:
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def run_all(scales=(100, 1_000, 10_000), mc_paths=50_000) -> list[dict]:
    rows = []
    for n in scales:
        obs = synth_observations(n)
        trades = synth_trades(n)
        opens = synth_open_positions(n)
        sims = synth_sim_positions(n)
        rets = _rng(4).standard_normal((n, min(n, 50)))  # returns matrix for covariance

        rows.append({
            "workload_size": n,
            "synthetic": SYNTHETIC,
            "feature_generation_s": _time(
                lambda: [build_features("2026-03-01", o, e) for o, e in obs]),
            "backtest_s": _time(lambda: run_backtest(trades)),
            "portfolio_aggregation_s": _time(
                lambda: (pf.concentration(
                    [{"capital": p.capital, "sector": p.sector} for p in opens], "sector"),
                    pf.expected_loss(opens))),
            "covariance_s": _time(lambda: np.cov(rets, rowvar=False)),
            "monte_carlo_s": _time(
                lambda: risk_report(sims, n_paths=mc_paths, seed=1)),
            "mc_paths": mc_paths,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="tiny scales (smoke)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    scales = (25, 100) if args.quick else (100, 1_000, 10_000)
    paths = 5_000 if args.quick else 50_000
    rows = run_all(scales=scales, mc_paths=paths)
    print(json.dumps({"synthetic_data": True, "results": rows}, indent=2))
    out = Path(args.out) if args.out else (RESULTS_DIR / "latest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"synthetic_data": True, "results": rows}, indent=2))
    print(f"\nwrote {out}  (SYNTHETIC — performance only, not research evidence)")


if __name__ == "__main__":
    main()
