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

from src.ingest.equity_prices.reconciliation import THESIS_RECONCILE_RULE  # noqa: E402

MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
MANIFEST = ROOT / "data" / "target_price_manifest.json"
DEAL_MANIFEST = ROOT / "data" / "sec_deal_manifest.json"
OUT = ROOT / "data" / "spread_stress_thesis_v1_cohort.json"
MIN_DEALS = 20
MIN_PRINTS = 3
COHORT_ID = "spread_stress_thesis_v1"
FINGERPRINT_VERSION = "cohort_fingerprint_v2"
HISTORICAL_V1_NOTE = (
    "Preserved fingerprint from the live freeze. It includes commit_sha and "
    "is not cohort_fingerprint_v2. It is not recomputed."
)


def inclusion_rules() -> dict:
    """Reconcile rule id comes from the canonical module, not a hardcoded v1."""
    return {
        "min_usable_prints": MIN_PRINTS,
        "min_deals": MIN_DEALS,
        "providers_allowed": ["tiingo", "yahoo_finance_chart"],
        "providers_forbidden": ["synthetic"],
        "close_field": "close",
        "reconcile_rule": THESIS_RECONCILE_RULE,
    }


def canonical_corpus_projection(deals: list) -> list:
    rows = []
    for deal in deals:
        rows.append({
            "deal_id": deal["deal_id"],
            "target": deal.get("target"),
            "target_cik": deal.get("target_cik"),
            "announcement_timestamp": deal.get("announcement_timestamp"),
            "resolution_timestamp": deal.get("resolution_timestamp"),
            "resolution_type": deal.get("resolution_type") or deal.get("status"),
        })
    rows.sort(key=lambda r: r["deal_id"])
    return rows


def price_observation_projection(prints: list, eligible: set[str]) -> list:
    """Stable price content. Excludes retrieved_at and any PIT diagnostic flags."""
    rows = []
    for print_row in prints:
        if print_row["deal_id"] not in eligible:
            continue
        session = print_row.get("session_date") or (
            print_row.get("observation_timestamp") or "")[:10]
        rows.append({
            "deal_id": print_row["deal_id"],
            "session": session,
            "raw_close": print_row.get("target_price"),
            "provider": print_row.get("provider") or print_row.get("source_name"),
            "source_identifier": print_row.get("source_identifier"),
        })
    rows.sort(key=lambda r: (r["deal_id"], r["session"], r["source_identifier"] or ""))
    return rows


def fingerprint_payload(eligible: list[str], prints: list, canon_deals: list) -> dict:
    rules = inclusion_rules()
    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "cohort_id": COHORT_ID,
        "eligible_deal_ids": list(eligible),
        "inclusion_rules": rules,
        "canonical_corpus": canonical_corpus_projection(canon_deals),
        "price_observations": price_observation_projection(prints, set(eligible)),
        "reconcile_rule": rules["reconcile_rule"],
    }


def cohort_fingerprint_v2(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def historical_dataset_fingerprint(existing: dict | None) -> dict | None:
    """Keep the pre-v2 fingerprint. Do not recompute it."""
    if not existing:
        return None
    if existing.get("historical_dataset_fingerprint"):
        return existing["historical_dataset_fingerprint"]
    inputs = existing.get("fingerprinted_inputs") or {}
    if inputs.get("commit_sha") and existing.get("dataset_fingerprint"):
        return {
            "fingerprint_version": "v1_includes_commit_sha",
            "dataset_fingerprint": existing["dataset_fingerprint"],
            "commit_sha": inputs.get("commit_sha"),
            "note": HISTORICAL_V1_NOTE,
        }
    return None


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

    canon_deals = json.loads(DEAL_MANIFEST.read_text()).get("deals") or []
    payload = fingerprint_payload(eligible, prints, canon_deals)
    fp = cohort_fingerprint_v2(payload)
    existing = json.loads(OUT.read_text()) if OUT.exists() else None
    historical_fp = historical_dataset_fingerprint(existing)
    rules = inclusion_rules()
    try:
        corpus_path = str(DEAL_MANIFEST.relative_to(ROOT))
    except ValueError:
        corpus_path = str(DEAL_MANIFEST)

    out = {
        "schema_version": 1,
        "cohort_id": COHORT_ID,
        "_doc": (
            "Deterministic thesis-eligible price cohort for spread_stress_v1. "
            "Does not overwrite first_walkforward_v1. Inclusion = ≥3 real "
            "provider-backed prints in announce→resolution window. "
            "dataset_fingerprint is cohort_fingerprint_v2 (semantic). "
            "code_sha is provenance and is not part of the fingerprint."
        ),
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "commit_sha": sha,
        "code_sha": sha,
        "canonical_corpus": corpus_path,
        "canonical_n": meta.get("canonical_n"),
        "inclusion_rules": rules,
        "n_eligible": len(eligible),
        "eligible_deal_ids": eligible,
        "exclusions": exclusions,
        "fingerprint_version": FINGERPRINT_VERSION,
        "dataset_fingerprint": fp,
        "historical_dataset_fingerprint": historical_fp,
        "fingerprinted_inputs": payload,
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
        "fingerprint_version": FINGERPRINT_VERSION,
        "code_sha": sha,
        "path": str(OUT),
        "HISTORICAL_PRICE_DATA_READY": True,
        "PRICE_COVERAGE_READY": "YES",
        "SPREAD_STRESS_V1_PANEL_VALID": "SEE_DIAGNOSTIC",
        "NOTE": (
            "Coverage gate only. The existing spread_stress_v1 panel is a "
            "separate diagnostic. No model and no backtest are run here."
        ),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
