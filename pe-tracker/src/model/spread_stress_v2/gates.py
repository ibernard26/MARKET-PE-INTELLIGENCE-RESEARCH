"""Execution gates for spread_stress_v2 (deal-level, gates never lowered).

`authorize_execution` is the only entry point a future runner may use. It
returns AUTHORIZED only when the spec is frozen and unmodified, the cohort
passes MIN_SAMPLE_N / MIN_CLASS_N at the deal level, PIT checks pass, and an
explicit, separate execution authorization record is supplied. This module
contains no model-fitting code.
"""
from __future__ import annotations

from .spec import SpecNotFrozenError, assert_frozen

BLOCKED_SPEC = "BLOCKED_SPEC_NOT_FROZEN"
BLOCKED_SAMPLE = "BLOCKED_MIN_SAMPLE_N"
BLOCKED_CLASS = "BLOCKED_MIN_CLASS_N"
BLOCKED_PIT = "BLOCKED_PIT_VALIDATION"
BLOCKED_AUTH = "BLOCKED_NO_EXECUTION_AUTHORIZATION"
AUTHORIZED = "AUTHORIZED"


def cohort_gates(panel: dict, policy: dict) -> dict:
    g = policy["gates"]
    n = panel["n_pos"] + panel["n_neg"]
    return {
        "labelled_deals": n,
        "n_pos": panel["n_pos"],
        "n_neg": panel["n_neg"],
        "MIN_SAMPLE_N": g["MIN_SAMPLE_N"],
        "MIN_CLASS_N": g["MIN_CLASS_N"],
        "min_sample_pass": n >= g["MIN_SAMPLE_N"],
        "min_class_pass": min(panel["n_pos"], panel["n_neg"]) >= g["MIN_CLASS_N"],
    }


def authorize_execution(panel: dict, policy: dict | None = None,
                        pit_validation_passed: bool = False,
                        execution_authorization: dict | None = None) -> dict:
    try:
        policy = assert_frozen(policy)
    except SpecNotFrozenError as exc:
        return {"status": BLOCKED_SPEC, "reason": str(exc)}
    gates = cohort_gates(panel, policy)
    if not gates["min_sample_pass"]:
        return {"status": BLOCKED_SAMPLE, "gates": gates}
    if not gates["min_class_pass"]:
        return {"status": BLOCKED_CLASS, "gates": gates}
    if not pit_validation_passed:
        return {"status": BLOCKED_PIT, "gates": gates}
    auth = execution_authorization or {}
    if not (auth.get("spec_id") == policy["spec_id"]
            and auth.get("spec_sha256") == policy["spec_sha256"]
            and auth.get("approved_by")):
        return {"status": BLOCKED_AUTH, "gates": gates}
    return {"status": AUTHORIZED, "gates": gates}
