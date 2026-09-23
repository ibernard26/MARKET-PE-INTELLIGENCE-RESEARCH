"""Point-in-time training-data builder.

One row per deal. Features are built as of the deal's FEATURE DATE (the day its
announcement became knowable, or an explicit date), via the bitemporal readers,
so nothing after that date can enter X. The label is taken from resolution
events KNOWN on/before the training cutoff:

    termination / withdrawal  -> y = 1 (broken, the positive class)
    closing                   -> y = 0
    otherwise                 -> censored (pending), EXCLUDED — never a negative

A row is admissible for a cutoff C only if feature_as_of <= C, the label was
known by C, and feature_as_of is strictly before the resolution's valid time.
"""
from __future__ import annotations

import math
import sqlite3
from typing import Optional

from ..research import events as ev
from ..research import features as ft
from ..research.bitemporal import normalize_as_of

FEATURE_SCHEMA_VERSION = "fs_v1"

# Economically motivated, point-in-time features (see features.build_features).
NUMERIC_FEATURES = [
    "pct_spread",
    "annualized_spread",
    "days_to_expected_close",
    "premium_to_unaffected",
    "log_deal_value",
]
BINARY_FEATURES = [
    "is_sponsor",
    "is_all_cash",
    "cfius_exposure",
    "antitrust_exposure",
    "cma_eu_exposure",
    "second_request_open",
    "under_regulatory_challenge",
    "financing_condition",
    "shareholder_approval_required",
]
FEATURES = NUMERIC_FEATURES + BINARY_FEATURES

BREAK_EVENTS = {"termination", "withdrawal"}
CLOSE_EVENTS = {"closing"}


def _num(v) -> Optional[float]:
    if v is None or isinstance(v, str):
        return None
    return float(v)


def feature_vector(f: dict) -> dict:
    """Project a feature dict onto the model schema. Missing stays None."""
    out = {k: _num(f.get(k)) for k in NUMERIC_FEATURES if k != "log_deal_value"}
    dv = _num(f.get("deal_value_usd_mm"))
    out["log_deal_value"] = math.log(dv) if dv and dv > 0 else None
    for k in BINARY_FEATURES:
        v = f.get(k)
        out[k] = None if v is None else float(bool(v))
    return out


def label_as_of(deal_id: str, cutoff: str, conn: sqlite3.Connection) -> dict:
    """Outcome knowable at `cutoff` (bitemporal). First resolution event wins."""
    for e in ev.events_as_of(deal_id, cutoff, conn=conn):
        if e["event_type"] in BREAK_EVENTS:
            return {"label": 1, "resolution_timestamp": e["event_timestamp"],
                    "label_known_at": e["known_at"]}
        if e["event_type"] in CLOSE_EVENTS:
            return {"label": 0, "resolution_timestamp": e["event_timestamp"],
                    "label_known_at": e["known_at"]}
    return {"label": None, "resolution_timestamp": None, "label_known_at": None}


def default_feature_date(deal_id: str, cutoff: str, conn: sqlite3.Connection
                         ) -> Optional[str]:
    """EXACT instant the announcement became knowable (as known by `cutoff`):
    the later of its valid timestamp and its known_at. Never truncated to a
    calendar date — a bare date would mean end-of-day and admit later same-day
    information into the announcement-time feature vector."""
    anns = [e for e in ev.events_as_of(deal_id, cutoff, conn=conn)
            if e["event_type"] == "announcement"]
    if not anns:
        return None
    return max(anns[0]["event_timestamp"], anns[0]["known_at"])


class FeatureDateError(ValueError):
    """Raised when an explicit feature time predates the knowable announcement."""


def build_row(deal_id: str, feature_as_of: str, cutoff: str,
              conn: sqlite3.Connection, market_ctx=None) -> dict:
    feats = ft.build_features_for_deal(deal_id, feature_as_of,
                                       market_ctx=market_ctx, conn=conn)
    lab = label_as_of(deal_id, cutoff, conn)
    row = {"deal_id": deal_id, "feature_as_of": feature_as_of, "cutoff": cutoff,
           "feature_schema_version": FEATURE_SCHEMA_VERSION,
           "x": feature_vector(feats), **lab}
    return row


def build_training_set(cutoff: str, conn: sqlite3.Connection,
                       feature_dates: dict = None, market_ctx=None) -> dict:
    """Admissible labeled rows at `cutoff`, plus censored/excluded accounting."""
    c_norm = normalize_as_of(cutoff)
    ids = [r[0] for r in conn.execute("SELECT deal_id FROM deals ORDER BY deal_id")]
    rows, censored, excluded = [], [], []
    for d in ids:
        ann_known = default_feature_date(d, cutoff, conn)
        explicit = (feature_dates or {}).get(d)
        if explicit is not None and ann_known is not None and \
                normalize_as_of(explicit) < ann_known:
            raise FeatureDateError(
                f"{d}: feature time {explicit} predates the knowable announcement "
                f"{ann_known} — would create a pre-announcement row")
        fdate = explicit or ann_known
        if ann_known is None:   # explicit time or not: no row before an announcement
            excluded.append({"deal_id": d, "reason": "no_known_announcement"})
            continue
        if normalize_as_of(fdate) > c_norm:
            excluded.append({"deal_id": d, "reason": "feature_date_after_cutoff"})
            continue
        row = build_row(d, fdate, cutoff, conn, market_ctx=market_ctx)
        if row["label"] is None:
            censored.append(row)
            continue
        if normalize_as_of(fdate) >= row["resolution_timestamp"]:
            excluded.append({"deal_id": d, "reason": "feature_date_not_before_resolution"})
            continue
        rows.append(row)
    return {"cutoff": cutoff, "rows": rows, "censored": censored, "excluded": excluded,
            "n": len(rows), "n_pos": sum(r["label"] for r in rows),
            "n_neg": sum(1 - r["label"] for r in rows), "n_censored": len(censored)}
