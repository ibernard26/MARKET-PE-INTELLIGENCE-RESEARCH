#!/usr/bin/env python3
"""Fetch Tiingo/Yahoo prints for Proof C identities only.

Uses locked price_reconcile_v2 (ABS_EPS=0.01, REL_EPS=0.0001). Does not
refetch already-admitted deals. Does not fit spread_stress_v2.

  cd pe-tracker
  python3 -m scripts.admit_proof_c_prices_v2
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_free_price_coverage import (  # noqa: E402
    CANONICALLY_ADMITTED,
    DEFERRED_IDENTITY,
    DEFERRED_PRICE_CONFLICT,
    HOURLY_RESET_BUFFER_S,
    INSUFFICIENT_CANONICAL_PRINTS,
    NO_PRICE_HISTORY,
    ROW_SCHEMA_VERSION,
    _classify_deal,
    admit_prints,
    canonical_status,
    identity_proofs,
    plan_tiingo_retry,
    reconcile_totals_from_rows,
    seconds_until_hourly_reset,
)
from src.ingest.equity_prices.fetch import CRSP_STATUS, default_providers  # noqa: E402
from src.ingest.equity_prices.identity import (  # noqa: E402
    REVIEWED_SEC_BASIS,
    SecurityIdentityResolver,
)
from src.ingest.equity_prices.normalize import observation_to_print  # noqa: E402
from src.ingest.equity_prices.orchestrator import PriceProviderOrchestrator  # noqa: E402
from src.ingest.equity_prices.pit_flags import annotate_prints, pit_summary  # noqa: E402
from src.ingest.equity_prices.reconciliation import (  # noqa: E402
    RECONCILE_RULES,
    THESIS_RECONCILE_RULE,
    reconcile_series,
)
from src.ingest.equity_prices.schema import NormalizedEquityObservation  # noqa: E402
from src.ingest.equity_prices.tiingo import TiingoEquityPriceProvider  # noqa: E402
from src.ingest.equity_prices.yahoo import YahooEquityPriceProvider  # noqa: E402
from src.ingest.target_prices import DEFAULT_MANIFEST  # noqa: E402
from src.model.logistic import MIN_CLASS_N  # noqa: E402
from src.config import MIN_SAMPLE_N  # noqa: E402
from src.model.spread_stress.v2_spec import authorize_execution  # noqa: E402

MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
DEALS = ROOT / "data" / "sec_deal_manifest.json"
ROUND = ROOT / "data" / "identity_resolution_round_v2.json"
MAP = ROOT / "data" / "target_ticker_map.json"
OUT = ROOT / "data" / "identity_round_v2_admission.json"
IDENTITY = ROOT / "data" / "tiingo_identity_evidence.json"
PIT = ROOT / "data" / "pit_ordering_diagnostics.json"
CHECKPOINT = ROOT / "data" / "cache" / "proof_c_price_v2"
PAD_DAYS = 3
BREAK_LIKE = frozenset({"terminated", "withdrawn", "broken"})
OVERLAP_FIELDS = (
    "overlap_sessions", "exact_matches", "tolerable_matches", "material_conflicts",
)
MIN_PRINTS = 3


def _obs_from_dict(d: dict) -> NormalizedEquityObservation:
    keys = NormalizedEquityObservation.__dataclass_fields__
    return NormalizedEquityObservation(**{k: d[k] for k in keys if k in d})


def _load_cached(deal_id: str) -> dict | None:
    path = CHECKPOINT / f"{deal_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _save_cached(deal_id: str, t_res: dict, y_res: dict) -> None:
    CHECKPOINT.mkdir(parents=True, exist_ok=True)
    payload = {
        "tiingo_status": t_res.get("status"),
        "yahoo_status": y_res.get("status"),
        "tiingo_trace": t_res.get("provider_trace"),
        "yahoo_trace": y_res.get("provider_trace"),
        "tiingo_obs": [asdict(o) for o in (t_res.get("observations") or [])],
        "yahoo_obs": [asdict(o) for o in (y_res.get("observations") or [])],
    }
    (CHECKPOINT / f"{deal_id}.json").write_text(json.dumps(payload) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _print_row(obs) -> dict:
    p = observation_to_print(obs)
    return {
        "deal_id": p.deal_id,
        "observation_timestamp": p.observation_timestamp,
        "target_price": p.target_price,
        "source_name": p.source.source_name,
        "source_identifier": p.source.source_identifier,
        "known_at": p.source.known_at,
        "source_timestamp": p.source.source_timestamp,
        "company_identifier": p.source.company_identifier,
        "session_date": obs.session_date,
        "provider": obs.provider,
        "provider_symbol": obs.provider_symbol,
        "ticker": obs.ticker,
        "exchange": obs.exchange,
        "adjusted_close": obs.adjusted_close,
        "currency": obs.currency,
        "close_field_used": obs.close_field_used,
        "retrieval_timestamp": obs.retrieval_timestamp,
        "corporate_action_note": obs.corporate_action_note,
        "provenance_hash": obs.provenance_hash(),
    }


def _wait_hourly(res: dict, prior: int) -> str:
    decision = plan_tiingo_retry(res, prior)
    if decision == "hourly_wait":
        sleep_s = seconds_until_hourly_reset(time.time(), HOURLY_RESET_BUFFER_S)
        print(json.dumps({"hourly_wait_s": sleep_s, "prior": prior}), flush=True)
        time.sleep(sleep_s)
    return decision


def proof_b_deal_ids(identity_path: Path = IDENTITY) -> set[str]:
    """Deals that already earned reconstructable Proof B in PR #44 evidence."""
    if not identity_path.exists():
        return set()
    doc = json.loads(identity_path.read_text())
    return {r["deal_id"] for r in doc.get("deals") or [] if r.get("proof_B_earned")}


def restore_frozen_overlap(row: dict, origin_row: dict, new_conflicts: int) -> None:
    """Keep PR #44 session-evidence overlap unless a new material conflict appears."""
    if new_conflicts > 0:
        return
    for key in OVERLAP_FIELDS:
        row[key] = origin_row.get(key, 0)


def recompute_row_admission(row: dict, *, proof_b_ids: set[str]) -> dict:
    """Recompute proofs/status. Proof B is only claimed when reconstructable."""
    if row.get("deal_id") not in proof_b_ids:
        row["tiingo_identity_verified"] = False
    row["identity_proofs"] = identity_proofs(row)
    row["canonical_status"], row["identity_deferral"] = canonical_status(row)
    row["prints_admitted"] = admit_prints(row)
    row["final_coverage_status"] = _classify_deal(row)
    return row


def class_counts(admitted: list[dict]) -> tuple[int, int]:
    closed = break_like = 0
    for r in admitted:
        kind = (r.get("resolution_type") or "").lower()
        if kind in BREAK_LIKE:
            break_like += 1
        elif kind == "closed":
            closed += 1
    return closed, break_like


def rebuild_matrix_meta(rows: list[dict], prints: list[dict], *,
                        origin_meta: dict, n_proof_c: int,
                        closed: int, break_like: int) -> dict:
    recon_stats = reconcile_totals_from_rows(rows)
    by_deal_prints = Counter(p["deal_id"] for p in prints)
    n_3plus = sum(1 for n in by_deal_prints.values() if n >= MIN_PRINTS)
    meta = {
        "canonical_n": len(rows),
        "total_real_price_prints": len(prints),
        "deals_with_3plus_prints": n_3plus,
        "tiingo_deals_covered": sum(1 for r in rows if r.get("tiingo_n", 0) >= 3),
        "yahoo_deals_covered": sum(1 for r in rows if r.get("yahoo_n", 0) >= 3),
        "multi_provider_confirmed": sum(
            1 for r in rows if r.get("final_coverage_status") == "MULTI_PROVIDER_CONFIRMED"),
        "raw_provider_covered": sum(1 for r in rows if r.get("raw_provider_covered")),
        "canonically_admitted": sum(
            1 for r in rows if r.get("canonical_status") == CANONICALLY_ADMITTED),
        "deferred_identity": sum(
            1 for r in rows if r.get("canonical_status") == DEFERRED_IDENTITY),
        "deferred_price_conflict": sum(
            1 for r in rows if r.get("canonical_status") == DEFERRED_PRICE_CONFLICT),
        "no_price_history": sum(
            1 for r in rows if r.get("canonical_status") == NO_PRICE_HISTORY),
        "insufficient_canonical_prints": sum(
            1 for r in rows if r.get("canonical_status") == INSUFFICIENT_CANONICAL_PRINTS),
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
        "reconcile": dict(recon_stats),
        "RUN_COMPLETE": "YES",
        "tiingo_hourly_limited_remaining": sum(
            1 for r in rows if r.get("tiingo_status") == "TRANSIENT_FAILURE"),
        "identity_round_v2": {
            "admitted_closed": closed,
            "admitted_break_like": break_like,
            "new_proof_c": n_proof_c,
        },
    }
    if origin_meta.get("historical_debug"):
        meta["historical_debug"] = origin_meta["historical_debug"]
    return meta


def annotate_manifest_prints(prints: list[dict], deals: list[dict]) -> list[dict]:
    by_id = {d["deal_id"]: d for d in deals}
    return annotate_prints(prints, by_id)


def main() -> int:
    abs_eps, rel_eps = RECONCILE_RULES[THESIS_RECONCILE_RULE]
    assert THESIS_RECONCILE_RULE == "price_reconcile_v2"
    assert (abs_eps, rel_eps) == (0.01, 1e-4)

    round_doc = json.loads(ROUND.read_text())
    resolved = [d for d in round_doc["deals"] if d["status"] == "RESOLVED_PROOF_C"]
    if not resolved:
        summary = {
            "NEW_PROOF_C": 0,
            "CANONICALLY_ADMITTED": json.loads(MATRIX.read_text())["meta"]["canonically_admitted"],
            "ADMITTED_BREAK_LIKE": None,
            "MODEL_FIT_EXECUTED": "NO",
            "BACKTEST_EXECUTED": "NO",
            "v2_execution": authorize_execution(),
        }
        OUT.write_text(json.dumps(summary, indent=2) + "\n")
        return 0

    matrix = json.loads(MATRIX.read_text())
    origin_overlap = {r["deal_id"]: {k: r.get(k, 0) for k in OVERLAP_FIELDS}
                      for r in matrix["deals"]}
    origin_meta = dict(matrix.get("meta") or {})
    sec = json.loads(DEALS.read_text())
    deals_by_id = {d["deal_id"]: d for d in sec["deals"]}
    by_cov = {r["deal_id"]: r for r in matrix["deals"]}
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    proof_b_ids = proof_b_deal_ids()

    resolver = SecurityIdentityResolver(map_path=MAP, user_agent=os.getenv("SEC_USER_AGENT") or "x",
                                        fetch_json=lambda u: {})
    tiingo = TiingoEquityPriceProvider()
    yahoo = YahooEquityPriceProvider()
    orch_t = PriceProviderOrchestrator(providers=[tiingo], resolver=resolver, pad_days=PAD_DAYS)
    orch_y = PriceProviderOrchestrator(providers=[yahoo], resolver=resolver, pad_days=PAD_DAYS)

    new_prints = []
    per_deal = []
    for rec in resolved:
        deal_id = rec["deal_id"]
        deal = deals_by_id[deal_id]
        cached = _load_cached(deal_id)
        if cached:
            t_res = {
                "status": cached["tiingo_status"],
                "provider_trace": cached.get("tiingo_trace") or [],
                "observations": [_obs_from_dict(o) for o in cached.get("tiingo_obs") or []],
            }
            y_res = {
                "status": cached["yahoo_status"],
                "provider_trace": cached.get("yahoo_trace") or [],
                "observations": [_obs_from_dict(o) for o in cached.get("yahoo_obs") or []],
            }
        else:
            t_attempts = 0
            while True:
                t_res = orch_t.fetch_deal(deal)
                decision = _wait_hourly(t_res, t_attempts)
                if decision == "hourly_wait":
                    t_attempts += 1
                    continue
                break
            y_res = orch_y.fetch_deal(deal)
            _save_cached(deal_id, t_res, y_res)
        t_obs = t_res.get("observations") or []
        y_obs = y_res.get("observations") or []
        ident, _ = resolver.resolve(deal)
        recon = reconcile_series(t_obs, y_obs, rule=THESIS_RECONCILE_RULE) if t_obs or y_obs else {
            "n_overlap": 0, "exact_match": 0, "tolerable_match": 0,
            "material_conflict": 0, "status": "N/A",
        }
        if t_obs and t_res.get("status") == "ok":
            chosen = t_obs
        elif y_obs and y_res.get("status") == "ok":
            chosen = y_obs
        else:
            chosen = []

        row = dict(by_cov[deal_id])
        row["historical_ticker"] = ident.ticker or rec.get("historical_ticker")
        row["identity_basis"] = REVIEWED_SEC_BASIS
        row["historical_exchange"] = ident.exchange or rec.get("exchange")
        row["tiingo_status"] = t_res.get("status")
        row["tiingo_n"] = len(t_obs)
        row["yahoo_status"] = y_res.get("status")
        row["yahoo_n"] = len(y_obs)
        row["overlap_sessions"] = recon.get("n_overlap", 0)
        row["exact_matches"] = recon.get("exact_match", 0)
        row["tolerable_matches"] = recon.get("tolerable_match", 0)
        row["material_conflicts"] = recon.get("material_conflict", 0)
        restore_frozen_overlap(row, origin_overlap[deal_id],
                               int(recon.get("material_conflict") or 0))
        row["reconcile_rule"] = THESIS_RECONCILE_RULE
        row["combined_n"] = len(chosen)
        row["row_schema_version"] = ROW_SCHEMA_VERSION
        recompute_row_admission(row, proof_b_ids=proof_b_ids)
        by_cov[deal_id] = row
        if row["prints_admitted"]:
            for o in chosen:
                new_prints.append(_print_row(o))
        per_deal.append({
            "deal_id": deal_id,
            "canonical_status": row["canonical_status"],
            "tiingo_n": row["tiingo_n"],
            "yahoo_n": row["yahoo_n"],
            "combined_n": row["combined_n"],
        })
        print(json.dumps(per_deal[-1] | {"ticker": ident.ticker}), flush=True)

    return write_round_artifacts(
        matrix=matrix,
        by_cov=by_cov,
        origin_meta=origin_meta,
        sec_deals=sec["deals"],
        manifest=manifest,
        new_prints=new_prints,
        per_deal=per_deal,
        n_proof_c=len(resolved),
        abs_eps=abs_eps,
        rel_eps=rel_eps,
    )


def write_round_artifacts(*, matrix, by_cov, origin_meta, sec_deals, manifest,
                          new_prints, per_deal, n_proof_c, abs_eps, rel_eps) -> int:
    """Persist coverage/manifest/admission. Does not fit v2."""
    for row in by_cov.values():
        recompute_row_admission(row, proof_b_ids=proof_b_deal_ids())
    matrix["deals"] = [by_cov[r["deal_id"]] for r in matrix["deals"]]
    rows = matrix["deals"]
    admitted_ids = {r["deal_id"] for r in rows if r.get("prints_admitted")}
    if new_prints:
        still = [p for p in (manifest.get("prints") or [])
                 if p["deal_id"] not in {n["deal_id"] for n in new_prints}]
        prints = still + new_prints
    else:
        prints = list(manifest.get("prints") or [])
    prints = [p for p in prints if p["deal_id"] in admitted_ids]
    prints = annotate_manifest_prints(prints, sec_deals)
    manifest["prints"] = prints
    admitted = [r for r in rows if r.get("canonical_status") == CANONICALLY_ADMITTED]
    closed, break_like = class_counts(admitted)
    matrix["meta"] = rebuild_matrix_meta(
        rows, prints, origin_meta=origin_meta, n_proof_c=n_proof_c,
        closed=closed, break_like=break_like)
    MATRIX.write_text(json.dumps(matrix, indent=2) + "\n")
    DEFAULT_MANIFEST.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    pit = pit_summary(sec_deals, prints)
    pit["schema_version"] = 1
    PIT.write_text(json.dumps(pit, indent=2) + "\n")
    stop = break_like < MIN_CLASS_N
    v2 = authorize_execution()
    summary = {
        "created_at": _now(),
        "reconcile_rule": THESIS_RECONCILE_RULE,
        "ABS_EPS": abs_eps,
        "REL_EPS": rel_eps,
        "NEW_PROOF_C": n_proof_c,
        "CANONICALLY_ADMITTED": len(admitted),
        "DEFERRED_IDENTITY": matrix["meta"]["deferred_identity"],
        "NO_PRICE_HISTORY": matrix["meta"]["no_price_history"],
        "ADMITTED_CLOSED": closed,
        "ADMITTED_BREAK_LIKE": break_like,
        "MIN_SAMPLE_GATE": MIN_SAMPLE_N,
        "MIN_CLASS_GATE": MIN_CLASS_N,
        "STOP_BELOW_MIN_CLASS": stop,
        "MODEL_FIT_EXECUTED": "NO",
        "BACKTEST_EXECUTED": "NO",
        "v2_execution": v2,
        "per_deal": per_deal,
    }
    OUT.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in (
        "CANONICALLY_ADMITTED", "ADMITTED_CLOSED", "ADMITTED_BREAK_LIKE",
        "STOP_BELOW_MIN_CLASS", "MODEL_FIT_EXECUTED")}), flush=True)
    if stop:
        print("ADMITTED_BREAK_LIKE < MIN_CLASS_N; not fitting spread_stress_v2",
              file=sys.stderr)
    return 0


def overlay_existing_round(origin_matrix: dict) -> int:
    """Restore frozen overlap from origin/main; overlay Proof C identity only."""
    abs_eps, rel_eps = RECONCILE_RULES[THESIS_RECONCILE_RULE]
    matrix = json.loads(MATRIX.read_text())
    origin_by = {r["deal_id"]: r for r in origin_matrix["deals"]}
    proof_b_ids = proof_b_deal_ids()
    round_doc = json.loads(ROUND.read_text())
    resolved = {d["deal_id"]: d for d in round_doc["deals"] if d["status"] == "RESOLVED_PROOF_C"}
    by_cov = {r["deal_id"]: dict(r) for r in matrix["deals"]}
    for deal_id, row in by_cov.items():
        restore_frozen_overlap(row, origin_by[deal_id], 0)
        rec = resolved.get(deal_id)
        if rec:
            row["historical_ticker"] = rec.get("historical_ticker") or row.get("historical_ticker")
            row["historical_exchange"] = rec.get("exchange") or row.get("historical_exchange")
            row["identity_basis"] = REVIEWED_SEC_BASIS
        recompute_row_admission(row, proof_b_ids=proof_b_ids)
    sec = json.loads(DEALS.read_text())
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    per_deal = [{
        "deal_id": rec["deal_id"],
        "canonical_status": by_cov[rec["deal_id"]]["canonical_status"],
        "tiingo_n": by_cov[rec["deal_id"]].get("tiingo_n", 0),
        "yahoo_n": by_cov[rec["deal_id"]].get("yahoo_n", 0),
        "combined_n": by_cov[rec["deal_id"]].get("combined_n", 0),
    } for rec in round_doc["deals"] if rec["status"] == "RESOLVED_PROOF_C"]
    return write_round_artifacts(
        matrix=matrix,
        by_cov=by_cov,
        origin_meta=origin_matrix.get("meta") or {},
        sec_deals=sec["deals"],
        manifest=manifest,
        new_prints=[],
        per_deal=per_deal,
        n_proof_c=len(resolved),
        abs_eps=abs_eps,
        rel_eps=rel_eps,
    )


if __name__ == "__main__":
    raise SystemExit(main())
