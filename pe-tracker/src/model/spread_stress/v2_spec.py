"""spread_stress_v2 — frozen methodology, execution still disabled.

This module freezes the v2 feature-time, PIT, model, and chronological
validation policy. It does not fit a model, walk-forward, calibrate, or
backtest. Execution requires a separate post-freeze cohort/panel review and
explicit authorization.

Feature dates are generated only from the announcement clock and the XNYS
calendar. Resolution timestamps and resolution known_at never choose or pull a
feature date; resolution known_at can only censor an already-generated snapshot.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from ...config import COST_FN, COST_FP, COST_RATIO_GRID, MIN_SAMPLE_N
from ...ingest.equity_prices.pit_flags import DATE_ONLY, INTRADAY, time_precision
from ..logistic import HYPERPARAMETERS, MIN_CLASS_N
from .features import SPREAD_STRESS_FEATURES, VOL_WINDOW_DEFAULT

SPEC_VERSION = "spread_stress_v2_frozen_1"
SPEC_STATUS = "frozen"
MODEL_ID = "spread_stress"
MODEL_VERSION = "spread_stress_v2"
FEATURE_SCHEMA_VERSION = "fs_spread_stress_v2"
PIT_POLICY_STATUS = "frozen"
EXECUTION_AUTHORIZED = False

NY = ZoneInfo("America/New_York")
SESSION_CALENDAR = "XNYS_exchange_calendars"
CALENDAR_START = "2010-01-01"
CALENDAR_END = "2031-12-31"
FROZEN_POLICY_ID = "ann_tplus_10_session"
RECOMMENDED_POLICY_ID = FROZEN_POLICY_ID  # compatibility alias from draft
FREEZE_SESSION_CALENDAR = SESSION_CALENDAR  # compatibility alias from draft
VOL_MIN_DELTAS = 3
FROZEN_TRAIN_FRACTION = 0.60
CALIBRATION_METHOD = "none"
MODEL_HYPERPARAMETERS = dict(HYPERPARAMETERS)
BASELINES = ("constant_train_prevalence", "pct_spread_only_logit")
THRESHOLD_SELECTION_RULE = "train_only_cost_min"

# Methodology is frozen; these are *execution* blockers, not freeze blockers.
EXECUTION_BLOCKERS = (
    "V2_PANEL_COHORT_FREEZE_REQUIRED",
    "V2_MODEL_IMPLEMENTATION_REQUIRED",
    "EXPLICIT_EXECUTION_AUTHORIZATION_REQUIRED",
)

assert MIN_SAMPLE_N == 20
assert MIN_CLASS_N == 2
assert COST_FP == 1.0
assert COST_FN == 15.0
assert tuple(COST_RATIO_GRID) == (5, 10, 15, 20)

BASE_FEATURES = list(SPREAD_STRESS_FEATURES)

ACTIVE = "ACTIVE"
RESOLVED_KNOWN = "RESOLVED_KNOWN"
ORDERING_AMBIGUOUS = "ORDERING_AMBIGUOUS"


@lru_cache(maxsize=1)
def xnys_calendar():
    """Frozen NYSE calendar, including holidays and early closes."""
    return xcals.get_calendar("XNYS", start=CALENDAR_START, end=CALENDAR_END)


def nyse_session(d: date) -> bool:
    return bool(xnys_calendar().is_session(d.isoformat()))


def nyse_session_close(d: date) -> datetime:
    """Actual XNYS close for `d`, returned as aware America/New_York time."""
    if not nyse_session(d):
        raise ValueError(f"{d.isoformat()} is not an XNYS session")
    close = xnys_calendar().session_close(d.isoformat())
    if close.tzinfo is None:
        close = close.tz_localize("UTC")
    return close.tz_convert("America/New_York").to_pydatetime()


def parse_announcement_date(announcement_ts: str) -> date:
    return date.fromisoformat(announcement_ts[:10])


def parse_announcement_datetime(announcement_ts: str) -> Optional[datetime]:
    """Parse intraday announcement time and require an explicit UTC offset.

    DATE_ONLY returns None. A naive intraday timestamp is rejected rather than
    guessed as Eastern Time.
    """
    if time_precision(announcement_ts) != INTRADAY:
        return None
    text = announcement_ts.replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid announcement timestamp {announcement_ts!r}") from exc
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("intraday announcement timestamp requires explicit timezone offset")
    return ts.astimezone(NY)


def announcement_market_date(announcement_ts: str) -> date:
    """Announcement date in the NYSE timezone (DATE_ONLY keeps its literal date)."""
    intraday = parse_announcement_datetime(announcement_ts)
    return intraday.date() if intraday is not None else parse_announcement_date(announcement_ts)


def announcement_session_is_eligible(announcement_ts: str) -> bool:
    """True only if an aware intraday announcement precedes that XNYS close."""
    ts = parse_announcement_datetime(announcement_ts)
    if ts is None:
        return False
    if not nyse_session(ts.date()):
        return False
    return ts < nyse_session_close(ts.date())


def iter_sessions_after_announcement(announcement_ts: str) -> Iterable[date]:
    """Yield PIT-safe XNYS sessions from announcement information only."""
    ann = announcement_market_date(announcement_ts)
    include_ann = announcement_session_is_eligible(announcement_ts)
    sessions = xnys_calendar().sessions_in_range(ann.isoformat(), CALENDAR_END)
    for session in sessions:
        d = session.date()
        if d == ann and not include_ann:
            continue
        yield d


def feature_session_date(announcement_ts: str, offset_sessions: int) -> date:
    """Nth PIT-safe XNYS session. Resolution is intentionally not an input."""
    if offset_sessions < 1:
        raise ValueError("offset_sessions must be >= 1")
    for i, d in enumerate(iter_sessions_after_announcement(announcement_ts), start=1):
        if i == offset_sessions:
            return d
    raise ValueError("feature session outside frozen XNYS calendar bounds")


def feature_session_time(announcement_ts: str, offset_sessions: int) -> datetime:
    """Aware actual market close of the frozen candidate feature session."""
    return nyse_session_close(feature_session_date(announcement_ts, offset_sessions))


def calendar_offset_session(announcement_ts: str, offset_days: int) -> date:
    """First XNYS session on/after announcement market date + N calendar days."""
    if offset_days < 1:
        raise ValueError("offset_days must be >= 1")
    target = announcement_market_date(announcement_ts) + timedelta(days=offset_days)
    return xnys_calendar().date_to_session(target.isoformat(), direction="next").date()


POLICY_CANDIDATES = (
    {
        "policy_id": "ann_tplus_5_session",
        "family": "fixed_trading_day_offset",
        "offset_sessions": 5,
        "snapshots_per_deal": 1,
        "uses_resolution_to_choose_feature_date": False,
    },
    {
        "policy_id": FROZEN_POLICY_ID,
        "family": "fixed_trading_day_offset",
        "offset_sessions": 10,
        "snapshots_per_deal": 1,
        "uses_resolution_to_choose_feature_date": False,
        "rationale": (
            "Ten PIT-safe XNYS sessions after announcement balances early stress capture "
            "with enough path history. VOL_WINDOW_DEFAULT=10 is a maximum delta window, "
            "not a requirement for 10 deltas: ten closes can produce at most nine "
            "post-announcement deltas. spread_vol uses up to the last 10 non-null "
            f"deltas and requires at least {VOL_MIN_DELTAS}. Short deals are censored "
            "at T+10; their feature date is never pulled toward resolution."
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
        "offset_sessions": [5, 10, 15, 20, 25, 30, 40, 60],
        "snapshots_per_deal": "variable",
        "uses_resolution_to_choose_feature_date": False,
        "weighting": "deal_equal_snapshot_weight",
    },
    {
        "policy_id": "calendar_7_14_30",
        "family": "calendar_offset",
        "offset_days": [7, 14, 30],
        "snapshots_per_deal": "variable",
        "uses_resolution_to_choose_feature_date": False,
        "weighting": "deal_equal_snapshot_weight",
    },
    {
        "policy_id": "active_deal_weekly_panel",
        "family": "multi_snapshot_active_deal_panel",
        "offset_sessions": [5, 10, 15, 20, 25, 30, 40, 60],
        "snapshots_per_deal": "variable",
        "uses_resolution_to_choose_feature_date": False,
        "split": "grouped_chronological_by_announcement",
        "weighting": "deal_equal_snapshot_weight",
    },
)
FROZEN_POLICY = next(p for p in POLICY_CANDIDATES if p["policy_id"] == FROZEN_POLICY_ID)
RECOMMENDED_POLICY = FROZEN_POLICY  # compatibility alias from draft
WEIGHTING_RULE_ID = "deal_equal_snapshot_weight"
SPLIT_RULE_ID = "grouped_chronological_60_40_by_announcement"

FEATURE_DEFINITIONS = (
    {
        "name": "pct_spread",
        "economic_rationale": "Gross merger-arb spread remaining in the market.",
        "pit_definition": (
            "(offer-known-at-feature-time - raw target close) / raw target close. "
            "Both offer valid_time/known_at and price observation/known_at must be <= feature_time."
        ),
    },
    {
        "name": "delta_spread",
        "economic_rationale": "Stress as widening or tightening of the merger-arb spread.",
        "pit_definition": "First difference of PIT pct_spread using only observations knowable by feature_time.",
    },
    {
        "name": "spread_vol",
        "economic_rationale": "Realized instability of the spread path before the frozen snapshot.",
        "pit_definition": (
            f"Sample stdev of up to the last {VOL_WINDOW_DEFAULT} non-null PIT delta_spread values; "
            f"requires at least {VOL_MIN_DELTAS}, otherwise missing."
        ),
    },
    {
        "name": "n_delta_obs",
        "economic_rationale": "Transparency measure for how much realized spread path is available.",
        "pit_definition": "Count of non-null delta_spread observations knowable by feature_time.",
    },
)


def deal_equal_snapshot_weight(n_snapshots_for_deal: int, n_deals: int) -> float:
    if n_snapshots_for_deal < 1 or n_deals < 1:
        raise ValueError("n_snapshots_for_deal and n_deals must be >= 1")
    return (1.0 / n_deals) * (1.0 / n_snapshots_for_deal)


def grouped_chronological_split(
        rows: list[dict], *, train_announcement_before: str) -> dict:
    """Compatibility helper for an explicit chronological cutoff."""
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
    return {
        "train": train,
        "test": test,
        "n_train_deals": sum(1 for s in by_deal.values() if s == {"train"}),
        "n_test_deals": sum(1 for s in by_deal.values() if s == {"test"}),
    }


def chronological_group_split_by_fraction(
        rows: list[dict], train_fraction: float = FROZEN_TRAIN_FRACTION) -> dict:
    """Frozen outcome-blind 60/40 split by deal announcement chronology.

    Unique deals are ordered by (announcement timestamp, deal_id). All rows for
    a deal remain on one side. Labels and resolution fields are not inputs.
    """
    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction must be between 0 and 1")
    ann_by_deal: dict[str, str] = {}
    for row in rows:
        deal_id, ann = row["deal_id"], row["announcement_ts"]
        prior = ann_by_deal.setdefault(deal_id, ann)
        if prior != ann:
            raise ValueError(f"{deal_id}: inconsistent announcement timestamps")
    ordered = sorted(ann_by_deal, key=lambda d: (ann_by_deal[d], d))
    if len(ordered) < 2:
        return {"train": list(rows), "test": [], "n_train_deals": len(ordered), "n_test_deals": 0}
    n_train = int(len(ordered) * train_fraction)
    n_train = max(1, min(n_train, len(ordered) - 1))
    train_ids = set(ordered[:n_train])
    train = [r for r in rows if r["deal_id"] in train_ids]
    test = [r for r in rows if r["deal_id"] not in train_ids]
    return {
        "train": train,
        "test": test,
        "n_train_deals": n_train,
        "n_test_deals": len(ordered) - n_train,
        "train_fraction": train_fraction,
        "split_basis": "announcement_chronology_then_deal_id",
    }


def _aware_timestamp(ts: str) -> Optional[datetime]:
    if time_precision(ts) != INTRADAY:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(NY)


def snapshot_activity_state(feature_time: str, resolution_known_at: Optional[str]) -> str:
    """PIT activity state using resolution `known_at` only after date generation.

    Same-day DATE_ONLY or naive intraday known_at cannot be ordered relative to
    the session close and is censored as ORDERING_AMBIGUOUS. A known_at on an
    earlier date is RESOLVED_KNOWN; a later date remains ACTIVE.
    """
    ft = _aware_timestamp(feature_time)
    if ft is None:
        raise ValueError("feature_time must be an offset-aware intraday timestamp")
    if not resolution_known_at:
        return ACTIVE
    rk = _aware_timestamp(resolution_known_at)
    if rk is not None:
        return RESOLVED_KNOWN if rk <= ft else ACTIVE
    try:
        r_date = date.fromisoformat(resolution_known_at[:10])
    except (TypeError, ValueError):
        return ORDERING_AMBIGUOUS
    if r_date < ft.date():
        return RESOLVED_KNOWN
    if r_date > ft.date():
        return ACTIVE
    return ORDERING_AMBIGUOUS


def snapshot_is_active_at_feature_time(
        feature_time: str, resolution_known_at: Optional[str]) -> bool:
    return snapshot_activity_state(feature_time, resolution_known_at) == ACTIVE


def partition_snapshots_by_known_at(
        rows: list[dict], resolution_known_at_by_deal: dict[str, Optional[str]]) -> dict:
    """Censor frozen snapshots after generation; never substitute another date."""
    active, censored = [], []
    for row in rows:
        state = snapshot_activity_state(
            row["feature_time"], resolution_known_at_by_deal.get(row["deal_id"]))
        tagged = {**row, "activity_state": state}
        (active if state == ACTIVE else censored).append(tagged)
    return {"active": active, "censored": censored}


def snapshot_rows_for_policy(
        deals: list[dict], policy_id: str = FROZEN_POLICY_ID) -> list[dict]:
    """Generate the frozen v2 snapshot without inspecting outcome fields."""
    if policy_id != FROZEN_POLICY_ID:
        raise ValueError(f"spread_stress_v2 is frozen to {FROZEN_POLICY_ID}")
    rows = []
    offset = int(FROZEN_POLICY["offset_sessions"])
    for deal in deals:
        ann = deal.get("announcement_ts") or deal.get("announcement_timestamp")
        if not ann:
            raise ValueError(f"{deal.get('deal_id')}: announcement timestamp required")
        d = feature_session_date(ann, offset)
        close = nyse_session_close(d)
        rows.append({
            "deal_id": deal["deal_id"],
            "announcement_ts": ann,
            "policy_id": FROZEN_POLICY_ID,
            "feature_date": d.isoformat(),
            "feature_time": close.isoformat(),
            "offset_sessions": offset,
        })
    return rows


def freeze_blockers() -> list[str]:
    """All methodology-freeze blockers are cleared in frozen_1."""
    return []


def execution_blockers() -> list[str]:
    return list(EXECUTION_BLOCKERS)


def authorize_execution() -> dict:
    """Frozen does not mean executable. A later PR must clear execution blockers."""
    return {
        "authorized": EXECUTION_AUTHORIZED,
        "V2_SPEC_STATUS": SPEC_STATUS,
        "SPEC_VERSION": SPEC_VERSION,
        "reason": "methodology frozen; execution requires panel/cohort freeze, v2 implementation, and explicit authorization",
        "MODEL_FIT_EXECUTED": "NO",
        "WALK_FORWARD_EXECUTED": "NO",
        "CALIBRATION_EXECUTED": "NO",
        "BACKTEST_EXECUTED": "NO",
        "MIN_SAMPLE_N": MIN_SAMPLE_N,
        "MIN_CLASS_N": MIN_CLASS_N,
        "frozen_policy_id": FROZEN_POLICY_ID,
        "SESSION_CALENDAR": SESSION_CALENDAR,
        "freeze_blockers": freeze_blockers(),
        "execution_blockers": execution_blockers(),
    }


def fit(*_a, **_k):
    raise RuntimeError(authorize_execution()["reason"])


def pit_policy_document() -> dict:
    return {
        "schema_version": 2,
        "spec_version": SPEC_VERSION,
        "V2_SPEC_STATUS": SPEC_STATUS,
        "PIT_POLICY_STATUS": PIT_POLICY_STATUS,
        "execution_authorized": EXECUTION_AUTHORIZED,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "does_not_modify": [
            "first_walkforward_v1", "EVENT_RULES", "fs_v1", "break_logit_v1",
            "spread_stress_v1", "price_reconcile_v2",
        ],
        "MIN_SAMPLE_N": MIN_SAMPLE_N,
        "MIN_CLASS_N": MIN_CLASS_N,
        "MODEL_HYPERPARAMETERS": MODEL_HYPERPARAMETERS,
        "CALIBRATION_METHOD": CALIBRATION_METHOD,
        "BASELINES": list(BASELINES),
        "threshold_selection": {
            "rule": THRESHOLD_SELECTION_RULE,
            "COST_FP": COST_FP,
            "COST_FN": COST_FN,
            "COST_RATIO_GRID": list(COST_RATIO_GRID),
            "source": "training predictions only; frozen before out-of-time scoring",
        },
        "VOL_WINDOW_DEFAULT": VOL_WINDOW_DEFAULT,
        "VOL_MIN_DELTAS": VOL_MIN_DELTAS,
        "base_features": list(FEATURE_DEFINITIONS),
        "feature_time_policy_candidates": list(POLICY_CANDIDATES),
        "frozen_policy_id": FROZEN_POLICY_ID,
        "frozen_policy": FROZEN_POLICY,
        "date_only_announcement_rule": (
            "DATE_ONLY announcement-day close is never a v2 feature print."
        ),
        "intraday_announcement_rule": (
            "Intraday announcements require an explicit UTC offset and are compared "
            "with the actual XNYS close, including early closes."
        ),
        "session_calendar": SESSION_CALENDAR,
        "calendar_bounds": {"start": CALENDAR_START, "end": CALENDAR_END},
        "active_at_feature_time": (
            "Feature dates are generated first. Resolution known_at can only censor "
            "the frozen snapshot. Same-day DATE_ONLY or naive known_at is "
            "ORDERING_AMBIGUOUS and censored."
        ),
        "resolution_feature_date_rule": (
            "Resolution timestamp and resolution known_at are forbidden inputs to feature-date generation."
        ),
        "validation": {
            "split_rule_id": SPLIT_RULE_ID,
            "train_fraction": FROZEN_TRAIN_FRACTION,
            "ordering": "announcement timestamp then deal_id",
            "grouping": "all rows for one deal stay on one side",
            "test_labels": "never used to fit preprocessing, coefficients, or threshold",
            "minimum gates": "MIN_SAMPLE_N and MIN_CLASS_N are rechecked after T+10 censoring",
        },
        "weighting_rule_id": WEIGHTING_RULE_ID,
        "freeze_blockers": freeze_blockers(),
        "execution_blockers": execution_blockers(),
        "execution": authorize_execution(),
    }
