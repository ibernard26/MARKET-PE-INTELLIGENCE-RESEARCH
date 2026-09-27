"""Point-in-time ΔS / σ_ΔS feature construction for spread_stress_v1.

Uses only deal_market_observations prints with valid_time ≤ t and known_at ≤ t.
Missing history stays None — never fabricated or forward-filled beyond the
observation layer's print-staleness rules (we read raw prints here, not the
stale-tolerant state_as_of target_price alone).
"""
from __future__ import annotations

import math
import sqlite3
from typing import Optional

from ...research.bitemporal import normalize_as_of
from ...research import events as ev
from ...research import observations as obs
from ...research.features import offer_value
from ..dataset import label_as_of

FEATURE_SCHEMA_VERSION = "fs_spread_stress_v1"
VOL_WINDOW_DEFAULT = 10
VOL_WINDOW_SENSITIVITY = (5, 10, 20)

SPREAD_STRESS_FEATURES = [
    "pct_spread",
    "delta_spread",
    "spread_vol",
    "n_delta_obs",
]


def _num(v) -> Optional[float]:
    if v is None or isinstance(v, str):
        return None
    return float(v)


def _target_prints_as_of(deal_id: str, as_of: str,
                         conn: sqlite3.Connection) -> list[dict]:
    """Ordered target-price prints knowable at `as_of` (bitemporal)."""
    t = normalize_as_of(as_of)
    rows = conn.execute(
        "SELECT observation_timestamp, target_price, known_at, source "
        "FROM deal_market_observations "
        "WHERE deal_id = ? AND target_price IS NOT NULL "
        "  AND observation_timestamp <= ? AND known_at <= ? "
        "ORDER BY observation_timestamp ASC, known_at ASC",
        (deal_id, t, t),
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "observation_timestamp": r["observation_timestamp"] if isinstance(r, sqlite3.Row) else r[0],
            "target_price": float(r["target_price"] if isinstance(r, sqlite3.Row) else r[1]),
            "known_at": r["known_at"] if isinstance(r, sqlite3.Row) else r[2],
            "source": r["source"] if isinstance(r, sqlite3.Row) else r[3],
        })
    return out


def _pct_spread_at(offer: Optional[float], price: Optional[float]) -> Optional[float]:
    if offer is None or price is None or not price:
        return None
    return (offer - price) / price


def delta_spread_series(deal_id: str, as_of: str, conn: sqlite3.Connection,
                        offer_price: Optional[float] = None) -> list[dict]:
    """Build the point-in-time series of S and ΔS up to `as_of`.

    If `offer_price` is None, reconstruct the offer from state_as_of at each
    print timestamp (terms persist; prints do not forward-fill).
    """
    prints = _target_prints_as_of(deal_id, as_of, conn)
    series = []
    prev_s = None
    for p in prints:
        ts = p["observation_timestamp"]
        if offer_price is None:
            st = obs.state_as_of(deal_id, ts, conn=conn)
            offer, _ = offer_value(st or {})
        else:
            offer = offer_price
        s = _pct_spread_at(offer, p["target_price"])
        d = (s - prev_s) if (s is not None and prev_s is not None) else None
        series.append({
            "observation_timestamp": ts,
            "target_price": p["target_price"],
            "offer_price": offer,
            "pct_spread": s,
            "delta_spread": d,
            "known_at": p["known_at"],
            "source": p["source"],
            "deal_id": deal_id,
        })
        if s is not None:
            prev_s = s
    return series


def _rolling_vol(deltas: list[Optional[float]], w: int) -> Optional[float]:
    vals = [d for d in deltas[-w:] if d is not None]
    if len(vals) < max(2, min(3, w)):  # need at least 2 changes; prefer 3
        return None
    mean = sum(vals) / len(vals)
    var = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
    return math.sqrt(var)


def build_spread_stress_row(deal_id: str, feature_as_of: str, cutoff: str,
                            conn: sqlite3.Connection,
                            vol_window: int = VOL_WINDOW_DEFAULT) -> dict:
    """One challenger row: features at `feature_as_of`, label known by `cutoff`."""
    series = delta_spread_series(deal_id, feature_as_of, conn)
    deltas = [r["delta_spread"] for r in series]
    last = series[-1] if series else None
    x = {
        "pct_spread": last["pct_spread"] if last else None,
        "delta_spread": last["delta_spread"] if last else None,
        "spread_vol": _rolling_vol(deltas, vol_window),
        "n_delta_obs": float(sum(1 for d in deltas if d is not None)),
    }
    lab = label_as_of(deal_id, cutoff, conn)
    return {
        "deal_id": deal_id,
        "feature_as_of": feature_as_of,
        "cutoff": cutoff,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "vol_window": vol_window,
        "n_target_prints": len(series),
        "x": x,
        **lab,
    }


def build_spread_stress_panel(cutoff: str, conn: sqlite3.Connection,
                              feature_dates: dict | None = None,
                              vol_window: int = VOL_WINDOW_DEFAULT,
                              min_prints: int = 3) -> dict:
    """Labeled panel at `cutoff` for deals with enough target prints.

    Unlike fs_v1 (one announcement snapshot), this panel uses an explicit
    feature time (default: last knowable target print on/before cutoff, else
    announcement knowable time). Rows lacking min_prints are excluded with
    reason `insufficient_price_history`.
    """
    from ..dataset import default_feature_date

    c_norm = normalize_as_of(cutoff)
    ids = [r[0] for r in conn.execute("SELECT deal_id FROM deals ORDER BY deal_id")]
    rows, censored, excluded = [], [], []
    for d in ids:
        if feature_dates and d in feature_dates:
            fa = feature_dates[d]
        else:
            prints = _target_prints_as_of(d, cutoff, conn)
            if prints:
                fa = prints[-1]["observation_timestamp"]
            else:
                fa = default_feature_date(d, cutoff, conn)
        if fa is None:
            excluded.append({"deal_id": d, "reason": "no_known_announcement"})
            continue
        if normalize_as_of(fa) > c_norm:
            excluded.append({"deal_id": d, "reason": "feature_after_cutoff"})
            continue
        row = build_spread_stress_row(d, fa, cutoff, conn, vol_window=vol_window)
        if row["n_target_prints"] < min_prints:
            excluded.append({"deal_id": d, "reason": "insufficient_price_history",
                             "n_target_prints": row["n_target_prints"],
                             "min_prints": min_prints})
            continue
        if row["label"] is None:
            censored.append(d)
            continue
        # feature must predate resolution valid time
        if row["resolution_timestamp"] and normalize_as_of(fa) >= normalize_as_of(
                row["resolution_timestamp"]):
            excluded.append({"deal_id": d, "reason": "feature_not_before_resolution"})
            continue
        rows.append(row)
    n_pos = sum(1 for r in rows if r["label"] == 1)
    return {
        "cutoff": cutoff,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "vol_window": vol_window,
        "min_prints": min_prints,
        "n": len(rows),
        "n_pos": n_pos,
        "n_neg": len(rows) - n_pos,
        "n_censored": len(censored),
        "n_excluded": len(excluded),
        "censored": censored,
        "excluded": excluded,
        "rows": rows,
    }
