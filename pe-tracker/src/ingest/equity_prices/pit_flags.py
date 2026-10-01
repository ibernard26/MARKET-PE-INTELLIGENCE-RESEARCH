"""Point-in-time ordering flags for date-only event timestamps.

A market close stamped 16:00 on the same calendar date as a date-only
announcement (or resolution) cannot be shown to fall after that event.
Flags mark the ambiguity. They do not drop raw observations and they are
not a feature-time policy.
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

DATE_ONLY = "DATE_ONLY"
INTRADAY = "INTRADAY"
ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS = "ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS"
RESOLUTION_DAY_ORDERING_AMBIGUOUS = "RESOLUTION_DAY_ORDERING_AMBIGUOUS"


def time_precision(ts: Optional[str]) -> str:
    """DATE_ONLY for a bare YYYY-MM-DD; INTRADAY when a clock time is present."""
    text = (ts or "").strip()
    if not text:
        return "MISSING"
    return DATE_ONLY if len(text) == 10 else INTRADAY


def pit_flags_for_print(print_row: dict, announcement_ts: Optional[str],
                        resolution_ts: Optional[str]) -> dict:
    """Flags for one raw print. Does not alter the close."""
    ann_p = time_precision(announcement_ts)
    res_p = time_precision(resolution_ts)
    session = print_row.get("session_date") or (print_row.get("observation_timestamp") or "")[:10]
    flags: list[str] = []
    if ann_p == DATE_ONLY and announcement_ts and session == announcement_ts[:10]:
        flags.append(ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS)
    if res_p == DATE_ONLY and resolution_ts and session == resolution_ts[:10]:
        flags.append(RESOLUTION_DAY_ORDERING_AMBIGUOUS)
    return {
        "announcement_time_precision": ann_p,
        "resolution_time_precision": res_p,
        "pit_ordering_flags": flags,
    }


def annotate_prints(prints: list[dict], deals_by_id: dict[str, dict]) -> list[dict]:
    """Return prints with PIT fields added. Prices and provenance are unchanged."""
    out = []
    for row in prints:
        deal = deals_by_id.get(row["deal_id"]) or {}
        flagged = dict(row)
        flagged.update(pit_flags_for_print(
            row,
            deal.get("announcement_timestamp"),
            deal.get("resolution_timestamp"),
        ))
        out.append(flagged)
    return out


def pit_summary(deals: list[dict], prints: list[dict]) -> dict:
    """Corpus timestamp precision plus same-day close counts on the manifest."""
    ann = Counter(time_precision(d.get("announcement_timestamp")) for d in deals)
    res = Counter(time_precision(d.get("resolution_timestamp")) for d in deals)
    ann_flags = 0
    res_flags = 0
    for row in prints:
        flags = row.get("pit_ordering_flags") or []
        if ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS in flags:
            ann_flags += 1
        if RESOLUTION_DAY_ORDERING_AMBIGUOUS in flags:
            res_flags += 1
    return {
        "DATE_ONLY_ANNOUNCEMENTS": ann.get(DATE_ONLY, 0),
        "INTRADAY_ANNOUNCEMENTS": ann.get(INTRADAY, 0),
        "DATE_ONLY_RESOLUTIONS": res.get(DATE_ONLY, 0),
        "INTRADAY_RESOLUTIONS": res.get(INTRADAY, 0),
        "ANNOUNCEMENT_DAY_AMBIGUOUS_PRINTS": ann_flags,
        "RESOLUTION_DAY_AMBIGUOUS_PRINTS": res_flags,
        "policy": (
            "Same-day closes on DATE_ONLY events are ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS "
            "or RESOLUTION_DAY_ORDERING_AMBIGUOUS. Raw prints stay in the manifest. "
            "This remediation does not define a PIT-safe feature policy."
        ),
    }
