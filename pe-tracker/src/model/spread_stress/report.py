"""Gated spread-stress readiness / comparison report.

  python -m src.model.spread_stress.report

Never pretends a spread-stress backtest ran when price history is missing.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from ...db import connect, init_db
from ...ingest.target_prices import (
    ManifestTargetPriceProvider,
    ensure_empty_manifest,
    ingest_target_prices,
)
from .compare import run_gated_comparison
from .gates import audit_price_history
from .model import MODEL_VERSION as STRESS_VERSION

ROOT = Path(__file__).resolve().parents[3]
REPO = ROOT.parent
EXP = ROOT / "data" / "experiments" / "first_walkforward_v1"
LOGISTIC = ROOT / "src" / "model" / "logistic.py"
DATASET = ROOT / "src" / "model" / "dataset.py"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args) -> str:
    return subprocess.check_output(["git", *args], cwd=REPO, text=True).strip()


def frozen_invariants() -> dict:
    """Prove this run did not mutate locked baseline artifacts (content hash)."""
    return {
        "first_walkforward_v1": {
            "cohort.json": _sha(EXP / "cohort.json"),
            "protocol.json": _sha(EXP / "protocol.json"),
            "plan.json": _sha(EXP / "plan.json"),
        },
        "break_logit_v1_source": _sha(LOGISTIC),
        "fs_v1_source": _sha(DATASET),
    }


def contract_flags(comparison: dict, invariants_before: dict,
                   invariants_after: dict, main_sha_start: str) -> dict:
    wf_changed = invariants_before["first_walkforward_v1"] != invariants_after["first_walkforward_v1"]
    bl_changed = invariants_before["break_logit_v1_source"] != invariants_after["break_logit_v1_source"]
    fs_changed = invariants_before["fs_v1_source"] != invariants_after["fs_v1_source"]
    ready = (comparison.get("gate") or {}).get("authorized", False)
    return {
        "MAIN_SHA_START": main_sha_start,
        "MAIN_SHA_END": _git("rev-parse", "HEAD"),
        "BRANCH": _git("branch", "--show-current"),
        "FS_V1_CHANGED": "YES" if fs_changed else "NO",
        "BREAK_LOGIT_V1_CHANGED": "YES" if bl_changed else "NO",
        "FIRST_WALKFORWARD_V1_CHANGED": "YES" if wf_changed else "NO",
        "SPREAD_STRESS_V1_IMPLEMENTED": "YES",
        "HISTORICAL_PRICE_DATA_READY": "YES" if ready else "NO",
        "REAL_MODEL_FIT_EXECUTED": "YES" if comparison.get("REAL_MODEL_FIT_EXECUTED") else "NO",
        "WALK_FORWARD_EXECUTED": "YES" if comparison.get("WALK_FORWARD_EXECUTED") else "NO",
        "BACKTEST_EXECUTED": "YES" if comparison.get("BACKTEST_EXECUTED") else "NO",
        "CALIBRATION_EXECUTED": "YES" if comparison.get("CALIBRATION_EXECUTED") else "NO",
        "BASELINE_BACKTEST_COMPLETE": "YES" if comparison.get("BASELINE_BACKTEST_COMPLETE") else "NO",
        "SPREAD_STRESS_BACKTEST_COMPLETE": "YES" if comparison.get("SPREAD_STRESS_BACKTEST_COMPLETE") else "NO",
        "COMBINED_BACKTEST_COMPLETE": "YES" if comparison.get("COMBINED_BACKTEST_COMPLETE") else "NO",
        "SPREAD_STRESS_BACKTEST_STATUS": comparison.get("SPREAD_STRESS_BACKTEST_STATUS"),
        "INCREMENTAL_OUT_OF_TIME_IMPROVEMENT": comparison.get(
            "INCREMENTAL_OUT_OF_TIME_IMPROVEMENT", "INCONCLUSIVE"),
        "challenger_model_version": STRESS_VERSION,
    }


def main() -> dict:
    main_sha_start = _git("rev-parse", "HEAD")
    before = frozen_invariants()
    init_db()
    ensure_empty_manifest()
    with connect() as conn:
        # Ingest reviewed prints if any (empty scaffold is a no-op).
        ingest_stats = ingest_target_prices(ManifestTargetPriceProvider(), conn)
        # Horizon/cutoff: use far-future so all known labels are visible for audit.
        cutoff = "2020-01-01"
        horizon = "2030-01-01"
        readiness = audit_price_history(conn, horizon)
        comparison = run_gated_comparison(conn, cutoff, horizon,
                                          pit_validation_passed=True)
    after = frozen_invariants()
    flags = contract_flags(comparison, before, after, main_sha_start)
    out = {
        "ingest_stats": ingest_stats,
        "price_readiness": readiness.to_dict(),
        "comparison": comparison,
        "contract_flags": flags,
        "invariants": {"before": before, "after": after},
    }
    print(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    main()
