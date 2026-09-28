"""spread_stress_v2 panel: features on the frozen session grid + PIT filters.

Feature math follows fs_spread_stress_v1 (pct_spread, delta_spread, spread_vol,
n_delta_obs) but on exchange sessions, with no bridging of gaps:

  close_t        raw provider close whose session_date == t (else snapshot missing)
  pct_spread_t   (offer - close_t) / close_t              cash deals only
  delta_spread_t pct_spread_t - pct_spread_{prev(t)}      both closes required, prev(t) >= S0
  spread_vol_t   sample std of valid deltas over the last `vol_window` sessions
                 ending at t, needing >= `min_valid_deltas` of them (else None)
  n_delta_obs_t  count of valid deltas in that window

Nothing is filled, interpolated or carried forward. Resolution information is
used only by `resolution_eligible` to exclude snapshots that cannot be shown to
precede resolution; it never chooses a snapshot.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from .calendar import previous_session
from .schedule import first_eligible_session, snapshot_schedule, time_precision

NY = ZoneInfo("America/New_York")

POSITIVE_RESOLUTIONS = frozenset({"terminated", "withdrawn"})   # y = 1 (broken)
NEGATIVE_RESOLUTIONS = frozenset({"closed"})                     # y = 0


def label_for(deal: dict) -> Optional[int]:
    """1 broken, 0 closed, None censored (pending/unknown never becomes 0)."""
    rt = (deal.get("resolution_type") or "").lower()
    if not deal.get("resolution_timestamp"):
        return None
    if rt in POSITIVE_RESOLUTIONS:
        return 1
    if rt in NEGATIVE_RESOLUTIONS:
        return 0
    return None


def resolution_eligible(snapshot: date, resolution_ts: Optional[str]) -> bool:
    """True iff the snapshot close is provably before resolution.

    Unresolved deals: every snapshot is (still) active. DATE_ONLY resolution:
    the snapshot session must be a strictly earlier calendar date (the
    resolution-date close is ambiguous). INTRADAY: 16:00 ET close < instant.
    """
    if not resolution_ts:
        return True
    if time_precision(resolution_ts) == "DATE_ONLY":
        return snapshot < date.fromisoformat(resolution_ts[:10])
    inst = datetime.fromisoformat(resolution_ts.replace("Z", "+00:00"))
    close = datetime.combine(snapshot, time(16, 0), tzinfo=NY)
    return close < inst


def _closes(prints: Iterable[dict]) -> dict[date, float]:
    out: dict[date, float] = {}
    for p in prints:
        if (p.get("close_field_used") or "close") != "close":
            raise ValueError("spread_stress_v2 uses raw closes only")
        d = date.fromisoformat(str(p["session_date"])[:10])
        c = float(p["target_price"])
        if d in out and out[d] != c:
            raise ValueError(f"conflicting closes for {p.get('deal_id')} on {d}")
        out[d] = c
    return out


def features_at(t: date, s0: date, closes: dict[date, float], offer: float,
                vol_window: int, min_valid_deltas: int) -> dict:
    def spread(d: date) -> Optional[float]:
        c = closes.get(d)
        return None if c is None or c <= 0 else (offer - c) / c

    def delta(d: date) -> Optional[float]:
        if d <= s0:
            return None
        a, b = spread(d), spread(previous_session(d))
        return None if a is None or b is None else a - b

    window, d = [], t
    for _ in range(vol_window):
        if d < s0:
            break
        window.append(delta(d))
        d = previous_session(d)
    valid = [x for x in window if x is not None]
    vol = None
    if len(valid) >= min_valid_deltas:
        m = sum(valid) / len(valid)
        vol = math.sqrt(sum((x - m) ** 2 for x in valid) / (len(valid) - 1))
    return {"pct_spread": spread(t), "delta_spread": delta(t),
            "spread_vol": vol, "n_delta_obs": float(len(valid))}


def build_deal_snapshots(deal: dict, prints: list[dict], policy: dict) -> dict:
    """All grid snapshots for one deal with feature values and PIT status."""
    grid = policy["snapshot_grid"]
    feat = policy["features"]
    elig = policy["eligibility"]
    base = {"deal_id": deal["deal_id"], "label": label_for(deal), "snapshots": []}
    if (deal.get("consideration_type") or "").lower() not in elig["consideration_types"]:
        return {**base, "excluded": "UNSUPPORTED_CONSIDERATION"}
    offer = deal.get("offer_price")
    if offer is None or offer <= 0:
        return {**base, "excluded": "NO_OFFER_PRICE"}
    s0 = first_eligible_session(deal["announcement_timestamp"])
    closes = _closes(prints)
    for t in snapshot_schedule(deal["announcement_timestamp"], grid["first_offset"],
                               grid["step"], grid["max_snapshots"]):
        row = {"snapshot": t.isoformat(),
               **features_at(t, s0, closes, float(offer), feat["vol_window"],
                             feat["min_valid_deltas_for_vol"])}
        if not resolution_eligible(t, deal.get("resolution_timestamp")):
            row["status"] = "NOT_PROVABLY_BEFORE_RESOLUTION"
        elif t not in closes:
            row["status"] = "NO_PRINT_ON_SNAPSHOT_SESSION"
        elif any(row[k] is None for k in feat["required_complete"]):
            row["status"] = "INCOMPLETE_FEATURES"
        else:
            row["status"] = "ELIGIBLE"
        base["snapshots"].append(row)
    n = sum(1 for s in base["snapshots"] if s["status"] == "ELIGIBLE")
    for s in base["snapshots"]:
        s["weight"] = (1.0 / n) if (n and s["status"] == "ELIGIBLE") else 0.0
    return {**base, "s0": s0.isoformat(), "n_eligible": n,
            "excluded": None if n else "NO_ELIGIBLE_SNAPSHOT"}


def build_panel(deals: list[dict], prints: list[dict], admitted: set[str],
                policy: dict) -> dict:
    """Panel over admitted deals. Censored deals are kept but never labelled."""
    by_deal: dict[str, list[dict]] = {}
    for p in prints:
        by_deal.setdefault(p["deal_id"], []).append(p)
    out = [build_deal_snapshots(d, by_deal.get(d["deal_id"], []), policy)
           for d in sorted(deals, key=lambda d: d["deal_id"]) if d["deal_id"] in admitted]
    usable = [d for d in out if not d["excluded"]]
    return {
        "deals": out,
        "n_deals_admitted": len(out),
        "n_deals_with_eligible_snapshot": len(usable),
        "n_pos": sum(1 for d in usable if d["label"] == 1),
        "n_neg": sum(1 for d in usable if d["label"] == 0),
        "n_censored": sum(1 for d in usable if d["label"] is None),
        "n_eligible_snapshots": sum(d["n_eligible"] for d in usable),
        "exclusions": {k: sum(1 for d in out if d["excluded"] == k)
                       for k in sorted({d["excluded"] for d in out if d["excluded"]})},
    }
