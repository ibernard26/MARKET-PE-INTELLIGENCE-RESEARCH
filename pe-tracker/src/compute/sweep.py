"""Threshold sweep — Phase 2 groundwork.

Grid-search the ma5 rule's three free parameters (MA window, BUY threshold,
SELL threshold) and report how each combination's BUY and SELL days performed
against the all-days baseline.

Overfitting guard: every cell reports its sample size, and any cell with
n < MIN_N is flagged `thin`. A thin cell is never evidence — 37 days of data
will happily produce an 80% hit rate by luck.

Nothing here persists to the database. The sweep is exploratory; only a
deliberately chosen ruleset (a new RULESET version in config) writes signals.
"""
import itertools

import pandas as pd

from ..config import MIN_SAMPLE_N
from .signals import add_metrics, classify, load_series

MIN_N = MIN_SAMPLE_N

BUY_GRID = (0.0, 0.0025, 0.005, 0.0075)
SELL_GRID = (0.0, -0.0025, -0.005, -0.0075)
WINDOW_GRID = (3, 5, 7, 10)


def _stats(fwd: pd.Series) -> dict:
    r = fwd.dropna()
    return {
        "n": int(len(r)),
        "mean_fwd_1d": float(r.mean()) if len(r) else None,
        "hit_rate": float((r > 0).mean()) if len(r) else None,
    }


def sweep(series_id: str = "SP500",
          buy_grid=BUY_GRID, sell_grid=SELL_GRID, window_grid=WINDOW_GRID,
          min_n: int = MIN_N, base_df: pd.DataFrame = None) -> pd.DataFrame:
    """One row per (window, buy, sell) x {BUY, SELL} signal.

    Columns: window, buy_thr, sell_thr, signal, n, mean_fwd_1d, hit_rate,
    edge_vs_baseline, thin. `base_df` lets tests inject a frame instead of
    reading the database.
    """
    raw = base_df if base_df is not None else load_series(series_id)

    rows = []
    for window in window_grid:
        with_metrics = add_metrics(raw, ma_window=window)
        fwd = with_metrics["close"].pct_change().shift(-1)
        baseline = _stats(fwd)

        for buy, sell in itertools.product(buy_grid, sell_grid):
            df = classify(with_metrics, buy=buy, sell=sell)
            for label in ("BUY", "SELL"):
                cell = _stats(fwd[df["signal"] == label])
                rows.append({
                    "window": window,
                    "buy_thr": buy,
                    "sell_thr": sell,
                    "signal": label,
                    "n": cell["n"],
                    "mean_fwd_1d": cell["mean_fwd_1d"],
                    "hit_rate": cell["hit_rate"],
                    "baseline_mean": baseline["mean_fwd_1d"],
                    "edge_vs_baseline": (
                        cell["mean_fwd_1d"] - baseline["mean_fwd_1d"]
                        if cell["mean_fwd_1d"] is not None
                           and baseline["mean_fwd_1d"] is not None else None
                    ),
                    "thin": cell["n"] < min_n,
                })
    return pd.DataFrame(rows)


def report(df: pd.DataFrame, top: int = 10) -> str:
    """Human-readable summary: the strongest non-thin cells per signal,
    then a count of how much of the grid was too thin to judge."""
    lines = []
    solid = df[~df["thin"]]
    for label in ("BUY", "SELL"):
        sub = solid[solid["signal"] == label]
        lines.append(f"\n== {label}: top {top} by edge vs baseline "
                     f"({len(sub)}/{len(df[df['signal'] == label])} cells have n >= {MIN_N}) ==")
        if sub.empty:
            lines.append("  (no cell reaches the minimum sample size — "
                         "every result below the line is noise)")
            sub = df[df["signal"] == label]
        show = sub.sort_values("edge_vs_baseline", ascending=False).head(top)
        lines.append(show.to_string(index=False,
                     float_format=lambda x: f"{x:+.4f}"))
    thin = int(df["thin"].sum())
    lines.append(f"\nthin cells (n < {MIN_N}): {thin}/{len(df)} — never cite these")
    return "\n".join(lines)
