"""spread_stress_v2 — frozen, deal-grouped, session-grid successor to v1.

Does not modify spread_stress_v1, fs_v1, break_logit_v1 or
first_walkforward_v1. Contains no model-fitting code: execution is gated by
gates.authorize_execution against the frozen spec (spec.py).
"""
from .gates import authorize_execution, cohort_gates
from .panel import build_panel, label_for, resolution_eligible
from .schedule import first_eligible_session, snapshot_schedule
from .spec import FEATURE_SCHEMA_VERSION, SPEC_ID, SpecNotFrozenError, assert_frozen
from .splits import SplitLeakError, annual_cutoffs, walk_forward

__all__ = [
    "SPEC_ID", "FEATURE_SCHEMA_VERSION", "SpecNotFrozenError", "assert_frozen",
    "first_eligible_session", "snapshot_schedule", "build_panel", "label_for",
    "resolution_eligible", "walk_forward", "annual_cutoffs", "SplitLeakError",
    "cohort_gates", "authorize_execution",
]
