"""Point-in-time feature generation.

A feature vector X[i, t] for deal i as-of date t contains ONLY information
knowable on/before t. Features are regenerated on demand from the append-only
observations and events (nothing derived is stored), so a feature set is exactly
reproducible and can never absorb a future event.

Features are economically defensible, not "everything available." Where an input
is missing the feature is None — never fabricated or zero-filled.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

from . import events as ev
from . import observations as obs
from .market_context import MARKET_FIELDS, PointInTimeMarketContext

SUPPORTED_CONSIDERATION = ("cash", "stock", "mixed")


def offer_value(o: dict) -> tuple[Optional[float], str]:
    """Per-share value of the consideration knowable in state `o`.

    cash  : offer_price
    stock : exchange_ratio * acquirer_price (needs a fresh acquirer print)
    mixed : offer_price (cash component) + exchange_ratio * acquirer_price
    unknown consideration -> None (a cash formula is never applied silently).
    Returns (value, basis).
    """
    ct = o.get("consideration_type")
    cash, ratio, acq = o.get("offer_price"), o.get("exchange_ratio"), o.get("acquirer_price")
    if ct == "cash":
        return cash, "cash"
    if ct == "stock":
        return ((ratio * acq), "stock") if (ratio is not None and acq is not None) else (None, "stock")
    if ct == "mixed":
        if cash is not None and ratio is not None and acq is not None:
            return cash + ratio * acq, "mixed"
        return None, "mixed"
    return None, "unknown_consideration"


def _days(a: str, b: str) -> Optional[int]:
    try:
        return (date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days
    except Exception:
        return None


def _annualize(period_ret: Optional[float], days: Optional[int]) -> Optional[float]:
    if period_ret is None or not days or days <= 0:
        return None
    return period_ret * (365.0 / days)


def build_features(as_of: str, observation: Optional[dict],
                   events: list[dict],
                   market_ctx: Optional[PointInTimeMarketContext] = None) -> dict:
    """Pure feature builder: given the reconstructed deal state knowable at
    `as_of` (see observations.state_as_of), the events knowable at `as_of`, and
    an optional point-in-time market provider, return the feature dict.

    `market_ctx` must be a PointInTimeMarketContext — a raw dict carries no
    timestamps or known-at times and is rejected."""
    if market_ctx is not None and not isinstance(market_ctx, PointInTimeMarketContext):
        raise TypeError("market_ctx must be a PointInTimeMarketContext "
                        "(timestamped, sourced, known-at); raw dicts are rejected")
    f: dict = {"as_of": as_of}
    o = observation or {}

    offer, f["offer_value_basis"] = offer_value(o)
    current = o.get("target_price")
    unaffected = o.get("unaffected_price")
    exp_close = o.get("expected_close_date")

    # --- deal economics ---
    raw_spread = (offer - current) if (offer is not None and current is not None) else None
    pct_spread = (raw_spread / current) if (raw_spread is not None and current) else None
    dtc = _days(exp_close, as_of) if exp_close else None
    f["raw_spread"] = raw_spread
    f["pct_spread"] = pct_spread
    f["days_to_expected_close"] = dtc
    f["annualized_spread"] = _annualize(pct_spread, dtc)
    f["downside_to_unaffected"] = (
        (current - unaffected) if (current is not None and unaffected is not None) else None)

    # --- deal structure ---
    f["is_sponsor"] = (o.get("deal_type") in ("LBO", "take_private")) if o.get("deal_type") else None
    f["consideration_type"] = o.get("consideration_type")
    f["is_all_cash"] = (o.get("consideration_type") == "cash") if o.get("consideration_type") else None
    f["deal_value_usd_mm"] = o.get("deal_value_usd_mm")
    f["premium_to_unaffected"] = (
        ((offer - unaffected) / unaffected)
        if (offer is not None and unaffected) else None)
    fin = o.get("financing_attrs") or {}
    f["financing_condition"] = fin.get("condition")            # e.g. True/False/None
    f["shareholder_approval_required"] = (
        o.get("shareholder_vote_state") not in (None, "none"))

    # --- regulatory (derived from events + attrs knowable as_of) ---
    etypes = {e["event_type"] for e in events}
    reg = o.get("regulatory_attrs") or {}
    f["antitrust_exposure"] = bool(reg.get("antitrust")) if "antitrust" in reg else None
    f["cfius_exposure"] = bool(reg.get("cfius")) if "cfius" in reg else None
    f["cma_eu_exposure"] = (
        bool(reg.get("cma") or reg.get("eu")) if ("cma" in reg or "eu" in reg) else None)
    f["second_request_open"] = "second_request" in etypes and not (
        {"hsr_clearance", "termination", "closing"} & etypes)
    f["under_regulatory_challenge"] = bool(
        {"doj_challenge", "ftc_challenge"} & etypes) and "termination" not in etypes

    # --- market environment (point-in-time; None when not knowable) ---
    snap = market_ctx.snapshot(as_of) if market_ctx is not None else {}
    for k in MARKET_FIELDS:
        f[k] = snap.get(k)
    return f


def build_features_for_deal(deal_id: str, as_of: str,
                            market_ctx: Optional[PointInTimeMarketContext] = None,
                            conn: sqlite3.Connection = None) -> dict:
    """DB-backed wrapper: bitemporal state reconstruction + events + market."""
    o = obs.state_as_of(deal_id, as_of, conn=conn)
    es = ev.events_as_of(deal_id, as_of, conn=conn)
    feats = build_features(as_of, o, es, market_ctx=market_ctx)
    feats["deal_id"] = deal_id
    return feats
