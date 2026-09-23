"""Backtester integration: attach the contemporaneous stored p_break to trades.

A trade entered on date E receives the latest immutable prediction whose
information date is on/before E, produced by a model whose training cutoff is
on/before that date (DB-enforced). Trades with no admissible prediction keep
p_break = None — nothing is back-filled.
"""
from __future__ import annotations

import sqlite3
from dataclasses import replace

from ..research.backtest import Trade
from .logistic import MODEL_VERSION
from .registry import prediction_as_of


def attach_predictions(trades: list[Trade], conn: sqlite3.Connection,
                       model_version: str = MODEL_VERSION) -> list[Trade]:
    out = []
    for t in trades:
        pr = prediction_as_of(t.deal_id, t.entry_date, conn, model_version)
        out.append(replace(t, p_break=pr["p_break"], p_break_as_of=pr["as_of"],
                           p_break_model_version=pr["model_version"]) if pr else t)
    return out
