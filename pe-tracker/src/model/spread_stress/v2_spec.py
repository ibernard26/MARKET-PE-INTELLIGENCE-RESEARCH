"""spread_stress_v2 — draft specification only.

This module defines feature-time policies, split/weighting rules, and an
execution gate. It does not fit a model, does not run a backtest, and does
not change spread_stress_v1.

Feature dates are computed from the announcement timestamp alone. Resolution
timestamps are not parameters of the feature-time functions.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Iterable, Optional
from zoneinfo import ZoneInfo

from ...config import MIN_SAMPLE_N
from ...ingest.equity_prices.pit_flags import DATE_ONLY, INTRADAY, time_precision
from ..logistic import MIN_CLASS_N
from .features import SPREAD_STRESS_FEATURES, VOL_WINDOW_DEFAULT

SPEC_VERSION = "spread_stress_v2_draft"
SPEC_STATUS = "draft"
MODEL_ID = "spread_stress"
MODEL_VERSION = "spread_stress_v2"
FEATURE_SCHEMA_VERSION = "fs_spread_stress_v2"
PIT_POLICY_STATUS = "draft"
NY = ZoneInfo("America/New_York")
SESSION_CALENDAR = "weekday_placeholder"
FREEZE_SESSION_CALENDAR = "nyse_market_calendar"

# Locked gates, imported rather than copied so they cannot silently diverge.
assert MIN_SAMPLE_N == 20
assert MIN_CLASS_N == 2

BASE_FEATURES = list(SPREAD_STRESS_FEATURES)  # pct_spread, delta_spread, spread_vol, n_delta_obs

IsSession = Callable[[date], bool]


def weekday_session(d: date) -> bool:
    """Placeholder session test (Mon–Fri). Not freeze-ready.

    A later freeze must pass `is_session` bound to the NYSE calendar in the
    store (`FREEZE_SESSION_CALENDAR`). This weekday proxy must not be used
    as the frozen calendar.
    """
    return d.weekday() < 5


def parse_announcement_date(announcement_ts: str) -> date:
    return date.fromisoformat(announcement_ts[:10])


def parse_announcement_datetime(announcement_ts: str) -> Optional[datetime]:
    """Parse an announcement timestamp into America/New_York.

    Naive ISO datetimes are interpreted as ET for this draft only. A freeze
    must require an explicit offset; DATE_ONLY values are not intraday.
    """
    if time_precision(announcement_ts) != INTRADAY:
        return None
    text = announcement_ts.replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=NY)
    return ts.astimezone(NY)


def announcement_session_is_eligible(announcement_ts: str) -> bool:
    """True only when an intraday announcement timestamp is strictly before
    the 16:00 America/New_York session close on that calendar date.

    DATE_ONLY announcements cannot prove that the same-day close is after the
    event, so the announcement session is never eligible.
    """
    ts = parse_announcement_datetime(announcement_ts)
    if ts is None:
        return False
    close = datetime(ts.year, ts.month, ts.day, 16, 0, 0, tzinfo=NY)
    return ts < close


def _as_new_york(ts: str) -> Optional[datetime]:
    """Compare timestamps in America/New_York. DATE_ONLY → that date's 16:00 ET."""
    parsed = parse_announcement_datetime(ts)
    if parsed is not None:
        return parsed
    try:
        d = parse_announcement_date(ts)
    except ValueError:
        return None
    return datetime(d.year, d.month, d.day, 16, 0, 0, tzinfo=NY)


def snapshot_is_active_at_feature_time(
        feature_time: str,
        resolution_known_at: Optional[str],
) -> bool:
    """Label/censor rule. Not a feature-date selector.

    A snapshot stays unlabeled when resolution is already known_at as-of
    feature_time. Resolution time is never used to choose the feature date.
    """
    if not resolution_known_at:
        return True
    ft = _as_new_york(feature_time)
    kn = _as_new_york(resolution_known_at)
    if ft is not None and kn is not None:
        return kn > ft
    return resolution_known_at[:19] > feature_time[:19]


def iter_sessions_after_announcement(
        announcement_ts: str,
        *,
        is_session: IsSession = weekday_session,
        include_announcement_session: Optional[bool] = None,
) -> Iterable[date]:
    """Yield eligible feature sessions in chronological order.

    Resolution is not consulted. Long or short deals therefore receive the
    same candidate dates; a deal that has already resolved before a given
    session simply has no valid snapshot at that date later, during labeling.
    """
    ann = parse_announcement_date(announcement_ts)
    if include_announcement_session is None:
        include_announcement_session = announcement_session_is_eligible(announcement_ts)
    d = ann if include_announcement_session else ann + timedelta(days=1)
    while True:
        if is_session(d):
            yield d
        d = d + timedelta(days=1)


def feature_session_date(
        announcement_ts: str,
        offset_sessions: int,
        *,
        is_session: IsSession = weekday_session,
) -> date:
    """Nth eligible session after announcement. No resolution argument.

    offset_sessions=1 is the first PIT-safe session (the next session after a
    DATE_ONLY announcement date; announcement-day close is ineligible unless
    intraday evidence proves the close is later).
    """
    if offset_sessions < 1:
        raise ValueError("offset_sessions must be >= 1; T+0 is not a draft default")
    for i, d in enumerate(iter_sessions_after_announcement(
            announcement_ts, is_session=is_session), start=1):
        if i == offset_sessions:
            return d
    raise RuntimeError("session iterator exhausted")  # pragma: no cover


def calendar_offset_session(
        announcement_ts: str,
        offset_days: int,
        *,
        is_session: IsSession = weekday_session,
) -> date:
    """First eligible session on or after announcement_date + offset_days.

    If that calendar date is the DATE_ONLY announcement date, skip to the next
    session. Resolution is not a parameter.
    """
    if offset_days < 1:
        raise ValueError("offset_days must be >= 1")
    ann = parse_announcement_date(announcement_ts)
    target = ann + timedelta(days=offset_days)
    d = target
    while True:
        if is_session(d) and not (
                time_precision(announcement_ts) == DATE_ONLY and d == ann):
            return d
        d = d + timedelta(days=1)


POLICY_CANDIDATES = (
    {
        "policy_id": "ann_tplus_5_session",
        "family": "fixed_trading_day_offset",
        "offset_sessions": 5,
        "snapshots_per_deal": 1,
        "uses_resolution_to_choose_feature_date": False,
    },
    {
        "policy_id": "ann_tplus_10_session",
        "family": "fixed_trading_day_offset",
        "offset_sessions": 10,
        "snapshots_per_deal": 1,
        "uses_resolution_to_choose_feature_date": False,
        "rationale": (
            "Ten post-announcement sessions matches VOL_WINDOW_DEFAULT=10 so "
            "spread_vol can be computed from a PIT-safe window that does not "
            "include a DATE_ONLY announcement-day close. Short deals that "
            "resolve before T+10 are excluded from this snapshot; their "
            "feature date is not pulled forward using the outcome time."
        ),
    },
    {
        "policy_id": "ann_tplus_20_session",
        "family": "fixed_trading_day_offset",
        "offset_sessions": 20,
        "snapshots_per_deal": 1,
        "uses_resolution_to_choose_feature_date": False,
    },
    {
        "policy_id": "weekly_grid_5_60",
        "family": "weekly_grid",
        "offset_sessions": (5, 10, 15, 20, 25, 30, 40, 60),
        "snapshots_per_deal": "variable",
        "uses_resolution_to_choose_feature_date": False,
        "weighting": "deal_equal_snapshot_weight",
    },
    {
        "policy_id": "calendar_7_14_30",
        "family": "calendar_offset",
        "offset_days": (7, 14, 30),
        "snapshots_per_deal": "variable",
        "uses_resolution_to_choose_feature_date": False,
        "weighting": "deal_equal_snapshot_weight",
    },
    {
        "policy_id": "active_deal_weekly_panel",
        "family": "multi_snapshot_active_deal_panel",
        "offset_sessions": (5, 10, 15, 20, 25, 30, 40, 60),
        "snapshots_per_deal": "variable",
        "uses_resolution_to_choose_feature_date": False,
        "split": "grouped_chronological_by_announcement",
        "weighting": "deal_equal_snapshot_weight",
        "note": (
            "Snapshot dates are generated from announcement only. Whether a "
            "deal is still pending at a snapshot is evaluated as-of that "
            "snapshot (label censoring), not by choosing a different feature "
            "date from the resolution timestamp."
        ),
    },
)

RECOMMENDED_POLICY_ID = "ann_tplus_10_session"
RECOMMENDED_POLICY = next(p for p in POLICY_CANDIDATES if p["policy_id"] == RECOMMENDED_POLICY_ID)

WEIGHTING_RULE_ID = "deal_equal_snapshot_weight"
SPLIT_RULE_ID = "grouped_chronological_by_announcement"


def deal_equal_snapshot_weight(n_snapshots_for_deal: int, n_deals: int) -> float:
    """Each deal contributes total weight 1/n_deals regardless of duration.

    Defined before any execution. Snapshot-equal weighting is rejected because
    long-duration deals would dominate the panel.
    """
    if n_snapshots_for_deal < 1 or n_deals < 1:
        raise ValueError("n_snapshots_for_deal and n_deals must be >= 1")
    return (1.0 / n_deals) * (1.0 / n_snapshots_for_deal)


def grouped_chronological_split(
        rows: list[dict],
        *,
        train_announcement_before: str,
) -> dict:
    """Assign every snapshot of a deal to train or test from announcement date.

    A deal never crosses. The split key is announcement_ts, not resolution.
    """
    cutoff = train_announcement_before[:10]
    train, test = [], []
    by_deal: dict[str, set[str]] = {}
    for row in rows:
        deal_id = row["deal_id"]
        ann = row["announcement_ts"][:10]
        bucket = "train" if ann < cutoff else "test"
        by_deal.setdefault(deal_id, set()).add(bucket)
        (train if bucket == "train" else test).append(row)
    crossed = [d for d, sides in by_deal.items() if len(sides) > 1]
    if crossed:
        raise ValueError(f"deal crossed train/test: {sorted(crossed)}")
    return {"train": train, "test": test, "n_train_deals": sum(1 for s in by_deal.values() if s == {"train"}),
            "n_test_deals": sum(1 for s in by_deal.values() if s == {"test"})}


def snapshot_rows_for_policy(
        deals: list[dict],
        policy_id: str = RECOMMENDED_POLICY_ID,
        *,
        is_session: IsSession = weekday_session,
) -> list[dict]:
    """Build unevaluated snapshot descriptors. Does not load prices or labels."""
    policy = next(p for p in POLICY_CANDIDATES if p["policy_id"] == policy_id)
    rows = []
    for deal in deals:
        ann = deal["announcement_ts"]
        deal_id = deal["deal_id"]
        if policy["family"] == "fixed_trading_day_offset":
            offsets = (policy["offset_sessions"],)
            for off in offsets:
                rows.append({
                    "deal_id": deal_id,
                    "announcement_ts": ann,
                    "policy_id": policy_id,
                    "feature_date": feature_session_date(ann, off, is_session=is_session).isoformat(),
                    "offset_sessions": off,
                })
        elif policy["family"] in {"weekly_grid", "multi_snapshot_active_deal_panel"}:
            for off in policy["offset_sessions"]:
                rows.append({
                    "deal_id": deal_id,
                    "announcement_ts": ann,
                    "policy_id": policy_id,
                    "feature_date": feature_session_date(ann, off, is_session=is_session).isoformat(),
                    "offset_sessions": off,
                })
        elif policy["family"] == "calendar_offset":
            for days in policy["offset_days"]:
                rows.append({
                    "deal_id": deal_id,
                    "announcement_ts": ann,
                    "policy_id": policy_id,
                    "feature_date": calendar_offset_session(ann, days, is_session=is_session).isoformat(),
                    "offset_days": days,
                })
        else:  # pragma: no cover
            raise ValueError(policy["family"])
    return rows


def authorize_execution() -> dict:
    """spread_stress_v2 must not run while the specification is draft."""
    return {
        "authorized": False,
        "V2_SPEC_STATUS": SPEC_STATUS,
        "SPEC_VERSION": SPEC_VERSION,
        "reason": "spread_stress_v2 cannot execute while the specification is draft",
        "MODEL_FIT_EXECUTED": "NO",
        "BACKTEST_EXECUTED": "NO",
        "MIN_SAMPLE_N": MIN_SAMPLE_N,
        "MIN_CLASS_N": MIN_CLASS_N,
        "recommended_policy_id": RECOMMENDED_POLICY_ID,
        "SESSION_CALENDAR": SESSION_CALENDAR,
        "freeze_blockers": freeze_blockers(),
    }


def freeze_blockers() -> list[str]:
    """Conditions that must be cleared in a later freeze commit. Not cleared here."""
    return [
        "SPEC_STATUS_DRAFT",
        "NYSE_SESSION_CALENDAR_REQUIRED",
        "TIMEZONE_AWARE_INTRADAY_REQUIRED",
        "ACTIVE_AT_FEATURE_TIME_MUST_USE_PIT_KNOWN_AT",
        "RESOLUTION_MUST_NOT_CHOOSE_FEATURE_DATES",
    ]


def fit(*_a, **_k):
    """Blocked while draft. Do not call."""
    raise RuntimeError(authorize_execution()["reason"])


def pit_policy_document() -> dict:
    return {
        "schema_version": 1,
        "spec_version": SPEC_VERSION,
        "V2_SPEC_STATUS": SPEC_STATUS,
        "PIT_POLICY_STATUS": PIT_POLICY_STATUS,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "does_not_modify": [
            "first_walkforward_v1",
            "EVENT_RULES",
            "fs_v1",
            "break_logit_v1",
            "spread_stress_v1",
            "price_reconcile_v2",
        ],
        "MIN_SAMPLE_N": MIN_SAMPLE_N,
        "MIN_CLASS_N": MIN_CLASS_N,
        "VOL_WINDOW_DEFAULT": VOL_WINDOW_DEFAULT,
        "base_features": [
            {
                "name": "pct_spread",
                "economic_rationale": (
                    "Gross arb spread (offer − target)/target. Levels show how "
                    "much compensation the market is offering for remaining deal risk."
                ),
                "pit_definition": (
                    "Computed from the last known raw close at feature_time and "
                    "the offer known_at <= feature_time. DATE_ONLY announcement-day "
                    "closes are not used as the feature print."
                ),
            },
            {
                "name": "delta_spread",
                "economic_rationale": (
                    "First difference of pct_spread. Widening into the deal is "
                    "the stress signal the challenger is built to measure."
                ),
                "pit_definition": (
                    "ΔS at feature_time uses only prints with observation_timestamp "
                    "<= feature_time and known_at <= feature_time. No forward-fill."
                ),
            },
            {
                "name": "spread_vol",
                "economic_rationale": (
                    "Rolling volatility of ΔS. Elevated vol is the path through "
                    "which financing, antitrust, or financing-stress news usually "
                    "appears before a binary break."
                ),
                "pit_definition": (
                    f"Sample stdev of the last {VOL_WINDOW_DEFAULT} PIT ΔS values "
                    "ending at feature_time. Missing history stays missing."
                ),
            },
            {
                "name": "n_delta_obs",
                "economic_rationale": (
                    "Count of realized ΔS observations. Sparse paths are less "
                    "informative; the count is a transparency feature, not a "
                    "fabricated vol input."
                ),
                "pit_definition": "Count of non-null ΔS with timestamps <= feature_time.",
            },
        ],
        "new_features": [],
        "feature_time_policy_candidates": list(POLICY_CANDIDATES),
        "recommended_policy_id": RECOMMENDED_POLICY_ID,
        "recommended_policy": RECOMMENDED_POLICY,
        "date_only_announcement_rule": (
            "Same-day close on a DATE_ONLY announcement is "
            "ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS and is not a feature print "
            "unless an intraday announcement timestamp proves the close is later."
        ),
        "split_rule_id": SPLIT_RULE_ID,
        "weighting_rule_id": WEIGHTING_RULE_ID,
        "grouped_split": (
            "Train/test assignment is by deal announcement date. Every snapshot "
            "of a deal stays on one side. Resolution is not the split key."
        ),
        "weighting": (
            "deal_equal_snapshot_weight = (1/n_deals)*(1/n_snapshots_deal). "
            "Defined before execution so long-duration deals cannot dominate."
        ),
        "SESSION_CALENDAR": SESSION_CALENDAR,
        "FREEZE_SESSION_CALENDAR": FREEZE_SESSION_CALENDAR,
        "freeze_blockers": freeze_blockers(),
        "active_at_feature_time": (
            "Pending vs resolved at a snapshot uses resolution known_at <= "
            "feature_time (label censoring). It does not choose the feature date."
        ),
        "intraday_timezone": "America/New_York",
        "execution": authorize_execution(),
    }
