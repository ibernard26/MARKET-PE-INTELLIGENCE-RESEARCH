"""Frozen specification for spread_stress_v2.

The policy file pins every design choice and the sha256 of
docs/SPREAD_STRESS_V2_SPEC.md. Nothing in spread_stress_v2 may build a panel
for scoring, fit, or evaluate unless the policy is FROZEN and the spec document
on disk still hashes to the frozen value. Changing either requires a new
version (spread_stress_v3), never an edit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = ROOT / "docs" / "SPREAD_STRESS_V2_SPEC.md"
POLICY_PATH = ROOT / "data" / "spread_stress_v2_pit_policy.json"

SPEC_ID = "spread_stress_v2"
FEATURE_SCHEMA_VERSION = "fs_spread_stress_v2"
FROZEN = "FROZEN"


class SpecNotFrozenError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(Path(path).read_text())


def assert_frozen(policy: dict | None = None, spec_path: Path = SPEC_PATH) -> dict:
    """Return the policy if frozen and consistent with the spec doc; else raise."""
    policy = policy if policy is not None else load_policy()
    if policy.get("spec_id") != SPEC_ID:
        raise SpecNotFrozenError(f"policy is for {policy.get('spec_id')!r}, not {SPEC_ID}")
    if policy.get("status") != FROZEN:
        raise SpecNotFrozenError(f"{SPEC_ID} policy status is {policy.get('status')!r}")
    if not policy.get("frozen_before_any_v2_execution"):
        raise SpecNotFrozenError("policy was not frozen before execution")
    actual = sha256_file(spec_path)
    if policy.get("spec_sha256") != actual:
        raise SpecNotFrozenError(
            f"{spec_path.name} changed after freeze (sha256 {actual[:12]} != "
            f"{str(policy.get('spec_sha256'))[:12]}); create spread_stress_v3")
    return policy
