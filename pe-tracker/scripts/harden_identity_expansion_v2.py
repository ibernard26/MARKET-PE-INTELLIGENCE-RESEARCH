#!/usr/bin/env python3
"""Recompute derived coverage fields after the Yahoo-reuse / WLTW provenance fix.

Does not fit spread_stress_v2. Does not invent prices.

  cd pe-tracker
  python3 -m scripts.harden_identity_expansion_v2
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit_free_price_coverage import write_bias, write_recon  # noqa: E402
from scripts.run_free_price_coverage import (  # noqa: E402
    CANONICALLY_ADMITTED,
    DEFERRED_IDENTITY,
    MIN_PRINTS,
    overlap_population_counts,
    raw_provider_covered_count,
    recompute_row_derived,
    reconcile_totals_from_rows,
)
from src.ingest.equity_prices.fetch import CRSP_STATUS, default_providers  # noqa: E402
from src.ingest.equity_prices.identity import REVIEWED_SEC_BASIS  # noqa: E402
from src.ingest.equity_prices.pit_flags import annotate_prints, pit_summary  # noqa: E402
from src.ingest.equity_prices.reconciliation import THESIS_RECONCILE_RULE  # noqa: E402
from src.ingest.target_prices import DEFAULT_MANIFEST  # noqa: E402
from src.config import MIN_SAMPLE_N  # noqa: E402
from src.model.logistic import MIN_CLASS_N  # noqa: E402
from src.model.spread_stress.v2_spec import authorize_execution, pit_policy_document  # noqa: E402

MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
DEALS = ROOT / "data" / "sec_deal_manifest.json"
PIT = ROOT / "data" / "pit_ordering_diagnostics.json"
ROUND = ROOT / "data" / "identity_resolution_round_v2.json"
ADMISSION = ROOT / "data" / "identity_round_v2_admission.json"
POLICY = ROOT / "data" / "spread_stress_v2_pit_policy_draft.json"
WLTW = "DEAL-WLTW-AON-2020"
COR = "DEAL-COR-AMT-2021"
BREAK_LIKE = frozenset({"terminated", "withdrawn", "broken"})
OVERLAP_FIELDS = (
    "overlap_sessions", "exact_matches", "tolerable_matches", "material_conflicts",
)


def _origin_matrix() -> dict:
    raw = subprocess.check_output(
        ["git", "show", "origin/main:pe-tracker/data/free_price_coverage_matrix.json"],
        cwd=str(ROOT.parent),
    )
    return json.loads(raw)


def main() -> int:
    origin = _origin_matrix()
    origin_by = {r["deal_id"]: r for r in origin["deals"]}
    matrix = json.loads(MATRIX.read_text())
    sec = json.loads(DEALS.read_text())
    round_doc = json.loads(ROUND.read_text())
    proof_c = {d["deal_id"] for d in round_doc["deals"] if d["status"] == "RESOLVED_PROOF_C"}

    rows = []
    for row in matrix["deals"]:
        row = dict(row)
        deal_id = row["deal_id"]
        orig = origin_by[deal_id]
        t_n = int(row.get("tiingo_n") or 0)
        y_n = int(row.get("yahoo_n") or 0)
        row["current_fetch_tiingo_n"] = t_n
        row["current_fetch_yahoo_n"] = y_n
        hist_ov = int(orig.get("overlap_sessions") or 0)
        row["historical_reconciliation_sessions"] = hist_ov
        row["historical_exact_matches"] = int(orig.get("exact_matches") or 0)
        row["historical_tolerable_matches"] = int(orig.get("tolerable_matches") or 0)
        row["historical_material_conflicts"] = int(orig.get("material_conflicts") or 0)
        current_dual = t_n > 0 and y_n > 0
        if not current_dual:
            # Current fetch cannot produce overlap. Frozen sessions stay
            # historical; they are not copied into overlap_sessions.
            if int(row.get("overlap_sessions") or 0) > 0:
                row["overlap_sessions"] = 0
                row["exact_matches"] = 0
                row["tolerable_matches"] = 0
                row["material_conflicts"] = 0
            if hist_ov > 0:
                row["historical_reconciliation_provenance"] = {
                    "source": "price_reconcile_v2_evidence.json",
                    "era": "PR44",
                    "historical_ticker": orig.get("historical_ticker"),
                    "current_ticker": row.get("historical_ticker"),
                    "note": (
                        "Frozen dual-provider session evidence is not current "
                        "coverage. Current fetch has no overlapping Tiingo/Yahoo "
                        "prints. Historical sessions are not used as prices."
                    ),
                }
            else:
                row["historical_reconciliation_provenance"] = {
                    "source": "price_reconcile_v2_evidence.json",
                    "era": "no_current_overlap",
                }
        else:
            row["historical_reconciliation_provenance"] = {
                "source": "price_reconcile_v2_evidence.json",
                "era": "current_dual_provider",
                "note": "Current fetch has both providers; overlap is current.",
            }
        if deal_id == COR:
            row["yahoo_identity_verified"] = False
            row["yahoo_identity_note"] = (
                "Yahoo COR is Cencora (ticker reuse 2023). Proof C mapped "
                "historical CoreSite COR. Yahoo-only prints are not admitted."
            )
        recompute_row_derived(row)
        rows.append(row)

    overlap_pop = overlap_population_counts(rows)
    recon = reconcile_totals_from_rows(rows)
    admitted = [r for r in rows if r.get("canonical_status") == CANONICALLY_ADMITTED]
    closed = sum(1 for r in admitted if (r.get("resolution_type") or "").lower() == "closed")
    break_like = sum(1 for r in admitted if (r.get("resolution_type") or "").lower() in BREAK_LIKE)
    by_prints = Counter()
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    admitted_ids = {r["deal_id"] for r in rows if r.get("prints_admitted")}
    prints = annotate_prints(
        [p for p in manifest.get("prints") or [] if p["deal_id"] in admitted_ids],
        {d["deal_id"]: d for d in sec["deals"]},
    )
    by_prints = Counter(p["deal_id"] for p in prints)
    n_3plus = sum(1 for n in by_prints.values() if n >= MIN_PRINTS)
    origin_meta = origin.get("meta") or {}
    meta = {
        "canonical_n": len(rows),
        "total_real_price_prints": len(prints),
        "deals_with_3plus_prints": n_3plus,
        "tiingo_deals_covered": sum(1 for r in rows if int(r.get("tiingo_n") or 0) >= 3),
        "yahoo_deals_covered": sum(1 for r in rows if int(r.get("yahoo_n") or 0) >= 3),
        "multi_provider_confirmed": sum(
            1 for r in rows if r.get("final_coverage_status") == "MULTI_PROVIDER_CONFIRMED"),
        "raw_provider_covered": raw_provider_covered_count(rows),
        "canonically_admitted": len(admitted),
        "deferred_identity": sum(1 for r in rows if r.get("canonical_status") == DEFERRED_IDENTITY),
        "deferred_price_conflict": sum(
            1 for r in rows if r.get("canonical_status") == "DEFERRED_PRICE_CONFLICT"),
        "no_price_history": sum(1 for r in rows if r.get("canonical_status") == "NO_PRICE_HISTORY"),
        "insufficient_canonical_prints": sum(
            1 for r in rows if r.get("canonical_status") == "INSUFFICIENT_CANONICAL_PRINTS"),
        "identity_deferral_reasons": dict(Counter(
            r["identity_deferral"] for r in rows if r.get("identity_deferral"))),
        "uncovered_deals": sum(
            1 for r in rows if r.get("canonical_status") != CANONICALLY_ADMITTED),
        "deals_not_admitted": sum(1 for r in rows if not r.get("prints_admitted")),
        "reconcile_rule": THESIS_RECONCILE_RULE,
        "historical_price_data_ready": n_3plus >= 20,
        "crsp_status": origin_meta.get("crsp_status") or CRSP_STATUS,
        "provider_chain": origin_meta.get("provider_chain") or [p.name for p in default_providers()],
        "openfigi_matched": sum(1 for r in rows if r.get("openfigi_status") == "MATCHED"),
        "openfigi_ambiguous": sum(1 for r in rows if r.get("openfigi_status") == "AMBIGUOUS"),
        "openfigi_no_match": sum(1 for r in rows if r.get("openfigi_status") == "NO_MATCH"),
        "openfigi_name_mismatch": sum(
            1 for r in rows if r.get("openfigi_status") == "NAME_MISMATCH"),
        "tiingo_identity_verified": sum(
            1 for r in rows if r.get("tiingo_identity_verified")),
        "gap_class_counts": dict(Counter(r.get("final_coverage_status") for r in rows)),
        "reconcile": dict(recon),
        "RUN_COMPLETE": "YES",
        "tiingo_hourly_limited_remaining": sum(
            1 for r in rows if r.get("tiingo_status") == "TRANSIENT_FAILURE"),
        "identity_round_v2": {
            "admitted_closed": closed,
            "admitted_break_like": break_like,
            "new_proof_c": len(proof_c),
            "COR_AMT_DISPOSITION": next(
                r["canonical_status"] for r in rows if r["deal_id"] == COR),
            "WLTW_DISPOSITION": next(
                r["canonical_status"] for r in rows if r["deal_id"] == WLTW),
        },
        **overlap_pop,
    }
    if origin_meta.get("historical_debug"):
        meta["historical_debug"] = origin_meta["historical_debug"]
        meta["historical_debug"]["wltw_mixed_era"] = {
            "deal_id": WLTW,
            "historical_reconciliation_sessions": next(
                r["historical_reconciliation_sessions"] for r in rows if r["deal_id"] == WLTW),
            "current_fetch_tiingo_n": 0,
            "current_fetch_yahoo_n": 0,
            "current_overlap_sessions": 0,
            "note": (
                "PR44 overlap under ticker WTW is retained as "
                "historical_reconciliation_sessions only."
            ),
        }
    assert meta["raw_provider_covered"] == raw_provider_covered_count(rows)
    assert meta["gap_class_counts"] == dict(Counter(r.get("final_coverage_status") for r in rows))
    matrix["deals"] = rows
    matrix["meta"] = meta
    MATRIX.write_text(json.dumps(matrix, indent=2) + "\n")
    manifest["prints"] = prints
    DEFAULT_MANIFEST.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    pit = pit_summary(sec["deals"], prints)
    pit["schema_version"] = 1
    PIT.write_text(json.dumps(pit, indent=2) + "\n")
    POLICY.write_text(json.dumps(pit_policy_document(), indent=2) + "\n")

    v2 = authorize_execution()
    per_deal = []
    for rec in round_doc["deals"]:
        row = next(r for r in rows if r["deal_id"] == rec["deal_id"])
        per_deal.append({
            "deal_id": rec["deal_id"],
            "canonical_status": row["canonical_status"],
            "tiingo_n": row.get("tiingo_n", 0),
            "yahoo_n": row.get("yahoo_n", 0),
            "combined_n": row.get("combined_n", 0),
        })
    summary = {
        "reconcile_rule": THESIS_RECONCILE_RULE,
        "ABS_EPS": 0.01,
        "REL_EPS": 0.0001,
        "NEW_PROOF_C": len(proof_c),
        "CANONICALLY_ADMITTED": len(admitted),
        "DEFERRED_IDENTITY": meta["deferred_identity"],
        "NO_PRICE_HISTORY": meta["no_price_history"],
        "ADMITTED_CLOSED": closed,
        "ADMITTED_BREAK_LIKE": break_like,
        "MIN_SAMPLE_GATE": MIN_SAMPLE_N,
        "MIN_CLASS_GATE": MIN_CLASS_N,
        "TOTAL_REAL_PRICE_PRINTS": len(prints),
        "RAW_PROVIDER_COVERED": meta["raw_provider_covered"],
        "COR_AMT_DISPOSITION": meta["identity_round_v2"]["COR_AMT_DISPOSITION"],
        "WLTW_DISPOSITION": meta["identity_round_v2"]["WLTW_DISPOSITION"],
        **overlap_pop,
        "STOP_BELOW_MIN_CLASS": break_like < MIN_CLASS_N,
        "MODEL_FIT_EXECUTED": "NO",
        "BACKTEST_EXECUTED": "NO",
        "v2_execution": v2,
        "per_deal": per_deal,
    }
    ADMISSION.write_text(json.dumps(summary, indent=2) + "\n")
    write_recon(matrix)
    write_bias(matrix)
    print(json.dumps({k: summary[k] for k in (
        "CANONICALLY_ADMITTED", "ADMITTED_CLOSED", "ADMITTED_BREAK_LIKE",
        "RAW_PROVIDER_COVERED", "COR_AMT_DISPOSITION", "WLTW_DISPOSITION",
        "OVERLAP_DEALS_CANONICALLY_ADMITTED", "OVERLAP_DEALS_NO_PRICE_HISTORY",
        "MODEL_FIT_EXECUTED")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
