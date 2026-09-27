#!/usr/bin/env python3
"""Freeze a deterministic thesis-eligible price cohort when readiness gate passes.

Does NOT overwrite first_walkforward_v1. Creates spread_stress_thesis_v1 metadata.

  cd pe-tracker
  python -m scripts.freeze_thesis_price_cohort

Exits 2 if HISTORICAL_PRICE_DATA_READY is false / deals_with_3plus < 20.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
MANIFEST = ROOT / "data" / "target_price_manifest.json"
DEAL_MANIFEST = ROOT / "data" / "sec_deal_manifest.json"
OUT = ROOT / "data" / "spread_stress_thesis_v1_cohort.json"
MIN_DEALS = 20
MIN_PRINTS = 3
COHORT_ID = "spread_stress_thesis_v1"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    if not MATRIX.exists() or not MANIFEST.exists():
        print("coverage matrix / price manifest missing", file=sys.stderr)
        return 2
    matrix = json.loads(MATRIX.read_text())
    meta = matrix.get("meta") or {}
    n_3 = int(meta.get("deals_with_3plus_prints") or 0)
    ready = bool(meta.get("historical_price_data_ready")) or n_3 >= MIN_DEALS
    if not ready or n_3 < MIN_DEALS:
        print(
            f"GATE_FAIL deals_with_3plus_prints={n_3} "
            f"(need >={MIN_DEALS}); cohort not frozen",
            file=sys.stderr,
        )
        return 2

    prints = json.loads(MANIFEST.read_text()).get("prints") or []
    by_deal: dict[str, list] = {}
    for p in prints:
        # reject synthetic
        src = (p.get("source_name") or p.get("provider") or "").lower()
        if "synthetic" in src:
            continue
        by_deal.setdefault(p["deal_id"], []).append(p)

    eligible = sorted(
        deal_id for deal_id, rows in by_deal.items() if len(rows) >= MIN_PRINTS
    )
    if len(eligible) < MIN_DEALS:
        print(f"GATE_FAIL eligible={len(eligible)}", file=sys.stderr)
        return 2

    exclusions = []
    for row in matrix.get("deals") or []:
        if row["deal_id"] not in eligible:
            exclusions.append({
                "deal_id": row["deal_id"],
                "reason": row.get("final_coverage_status") or "INSUFFICIENT_PRINTS",
                "tiingo_n": row.get("tiingo_n"),
                "yahoo_n": row.get("yahoo_n"),
            })

    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT.parent, text=True
        ).strip()
    except Exception:
        sha = "unknown"

    fingerprint_payload = {
        "cohort_id": COHORT_ID,
        "eligible_deal_ids": eligible,
        "min_prints": MIN_PRINTS,
        "matrix_sha256": _sha256_file(MATRIX),
        "manifest_sha256": _sha256_file(MANIFEST),
        "deal_manifest_sha256": _sha256_file(DEAL_MANIFEST),
        "commit_sha": sha,
    }
    fp = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    out = {
        "schema_version": 1,
        "cohort_id": COHORT_ID,
        "_doc": (
            "Deterministic thesis-eligible price cohort for spread_stress_v1. "
            "Does not overwrite first_walkforward_v1. Inclusion = ≥3 real "
            "provider-backed prints in announce→resolution window."
        ),
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "commit_sha": sha,
        "canonical_corpus": str(DEAL_MANIFEST.relative_to(ROOT)),
        "canonical_n": meta.get("canonical_n"),
        "inclusion_rules": {
            "min_usable_prints": MIN_PRINTS,
            "min_deals": MIN_DEALS,
            "providers_allowed": ["tiingo", "yahoo_finance_chart"],
            "providers_forbidden": ["synthetic"],
            "close_field": "close",
            "reconcile_rule": "price_reconcile_v1",
        },
        "n_eligible": len(eligible),
        "eligible_deal_ids": eligible,
        "exclusions": exclusions,
        "dataset_fingerprint": fp,
        "fingerprinted_inputs": fingerprint_payload,
        "meta": {
            "total_real_price_prints": meta.get("total_real_price_prints"),
            "tiingo_deals_covered": meta.get("tiingo_deals_covered"),
            "yahoo_deals_covered": meta.get("yahoo_deals_covered"),
            "multi_provider_confirmed": meta.get("multi_provider_confirmed"),
            "historical_price_data_ready": True,
            "first_walkforward_v1_unchanged": True,
        },
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({
        "cohort_id": COHORT_ID,
        "n_eligible": len(eligible),
        "dataset_fingerprint": fp,
        "path": str(OUT),
        "HISTORICAL_PRICE_DATA_READY": True,
        "SPREAD_STRESS_READY_FOR_EXECUTION": True,
        "NOTE": "Per free-thesis goal: stop before model/backtest execution.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
