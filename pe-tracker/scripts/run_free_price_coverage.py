#!/usr/bin/env python3
"""Full-corpus OpenFIGI + Tiingo + Yahoo coverage pass.

Requires OPENFIGI_API_KEY and TIINGO_API_TOKEN in the environment.
Never prints credential values. Stops with CREDENTIAL_ENVIRONMENT_NOT_VISIBLE
when either variable is missing.

  cd pe-tracker
  python -m scripts.run_free_price_coverage
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.equity_prices.credentials import (  # noqa: E402
    credential_presence,
    missing_credential_names,
)
from src.ingest.equity_prices.fetch import (  # noqa: E402
    CRSP_STATUS,
    DEFAULT_DEAL_MANIFEST,
    default_providers,
)
from src.ingest.equity_prices.identity import (  # noqa: E402
    DEFAULT_TICKER_MAP,
    SecurityIdentityResolver,
)
from src.ingest.equity_prices.normalize import write_normalized_manifest  # noqa: E402
from src.ingest.equity_prices.orchestrator import PriceProviderOrchestrator  # noqa: E402
from src.ingest.equity_prices.reconciliation import reconcile_series  # noqa: E402
from src.ingest.equity_prices.tiingo import TiingoEquityPriceProvider  # noqa: E402
from src.ingest.equity_prices.yahoo import YahooEquityPriceProvider  # noqa: E402
from src.ingest.security_identity.openfigi import (  # noqa: E402
    OpenFIGISecurityIdentityResolver,
)
from src.ingest.target_prices import DEFAULT_MANIFEST  # noqa: E402

OUT_MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
OUT_AUDIT = ROOT / "data" / "free_price_fetch_audit.json"
PAD_DAYS = 3


def _classify_deal(row: dict) -> str:
    if row.get("openfigi_status") == "AMBIGUOUS":
        return "SECURITY_IDENTITY_AMBIGUOUS"
    if row.get("openfigi_status") == "NO_MATCH":
        return "OPENFIGI_NO_MATCH"
    if row.get("material_conflicts", 0) > 0 and row.get("tiingo_n", 0) >= 3 and row.get("yahoo_n", 0) >= 3:
        # conflicts recorded; do not enter as MULTI_PROVIDER_CONFIRMED
        pass
    if row.get("tiingo_n", 0) >= 3 and row.get("yahoo_n", 0) >= 3 and row.get("material_conflicts", 0) == 0:
        return "MULTI_PROVIDER_CONFIRMED"
    if row.get("tiingo_n", 0) >= 3:
        return "TIINGO_COVERED" if row.get("yahoo_n", 0) == 0 else "TIINGO_COVERED"
    if row.get("yahoo_n", 0) >= 3 and row.get("tiingo_n", 0) == 0:
        return "YAHOO_ONLY"
    if row.get("tiingo_status") == "SYMBOL_NOT_FOUND":
        return "TIINGO_NO_SYMBOL"
    if row.get("tiingo_status") in ("NO_HISTORY", "ok") and row.get("tiingo_n", 0) == 0:
        return "TIINGO_NO_HISTORY"
    if row.get("tiingo_status") == "TRANSIENT_FAILURE":
        return "PROVIDER_TRANSIENT_FAILURE"
    if row.get("tiingo_n", 0) == 0 and row.get("yahoo_n", 0) == 0:
        return "NO_PUBLIC_PRICE_HISTORY"
    return "OTHER"


def main() -> int:
    presence = credential_presence()
    print(json.dumps({"credential_presence": presence}, indent=2))
    missing = missing_credential_names()
    if missing:
        print("CREDENTIAL_ENVIRONMENT_NOT_VISIBLE", file=sys.stderr)
        for name in missing:
            print(name, file=sys.stderr)
        return 3

    if not os.getenv("SEC_USER_AGENT"):
        print("SEC_USER_AGENT is not set", file=sys.stderr)
        return 2

    deals = json.loads(DEFAULT_DEAL_MANIFEST.read_text())["deals"]
    ticker_resolver = SecurityIdentityResolver(
        map_path=DEFAULT_TICKER_MAP, user_agent=os.environ["SEC_USER_AGENT"])
    figi = OpenFIGISecurityIdentityResolver()
    tiingo = TiingoEquityPriceProvider()
    yahoo = YahooEquityPriceProvider()
    # Dual fetch for reconciliation: run each provider independently
    orch_tiingo = PriceProviderOrchestrator(
        providers=[tiingo], resolver=ticker_resolver, pad_days=PAD_DAYS)
    orch_yahoo = PriceProviderOrchestrator(
        providers=[yahoo], resolver=ticker_resolver, pad_days=PAD_DAYS)
    orch_combined = PriceProviderOrchestrator(
        providers=default_providers(), resolver=ticker_resolver, pad_days=PAD_DAYS)

    rows = []
    all_obs = []
    recon_stats = Counter()
    conflict_samples = []

    for d in deals:
        ident, defer = ticker_resolver.resolve(d)
        figi_id = figi.resolve_deal(
            d, ticker=ident.ticker, exchange=ident.exchange)
        # Do not fetch prices when identity ambiguous at FIGI layer with multiple
        # FIGIs — still allow ticker-based Tiingo/Yahoo but flag ambiguity.
        t_res = orch_tiingo.fetch_deal(d)
        y_res = orch_yahoo.fetch_deal(d)
        c_res = orch_combined.fetch_deal(d)

        t_obs = t_res.get("observations") or []
        y_obs = y_res.get("observations") or []
        recon = reconcile_series(t_obs, y_obs) if t_obs or y_obs else {
            "n_overlap": 0, "exact_match": 0, "tolerable_match": 0,
            "material_conflict": 0, "tiingo_only": 0, "yahoo_only": 0,
            "conflicts": [], "status": "N/A",
        }
        recon_stats["overlap_sessions"] += recon.get("n_overlap", 0)
        recon_stats["exact"] += recon.get("exact_match", 0)
        recon_stats["tolerable"] += recon.get("tolerable_match", 0)
        recon_stats["conflict"] += recon.get("material_conflict", 0)
        if recon.get("material_conflict", 0):
            for c in recon.get("conflicts", [])[:3]:
                conflict_samples.append({"deal_id": d["deal_id"], **c})

        # Canonical observations: combined orchestrator (Tiingo preferred)
        # Skip committing conflicted multi-provider pairs as "confirmed";
        # still keep Tiingo-preferred series from combined fetch.
        all_obs.extend(c_res.get("observations") or [])

        row = {
            "deal_id": d["deal_id"],
            "target_cik": d.get("target_cik"),
            "target_name": d.get("target"),
            "announcement_date": (d.get("announcement_timestamp") or "")[:10],
            "resolution_date": (d.get("resolution_timestamp") or "")[:10],
            "resolution_type": d.get("resolution_type") or d.get("status"),
            "historical_ticker": ident.ticker,
            "historical_exchange": ident.exchange,
            "openfigi_status": figi_id.mapping_status,
            "figi": figi_id.figi,
            "composite_figi": figi_id.composite_figi,
            "share_class_figi": figi_id.share_class_figi,
            "tiingo_status": t_res.get("status"),
            "tiingo_n": len(t_obs),
            "yahoo_status": y_res.get("status"),
            "yahoo_n": len(y_obs),
            "overlap_sessions": recon.get("n_overlap", 0),
            "material_conflicts": recon.get("material_conflict", 0),
            "combined_provider": c_res.get("provider"),
            "combined_n": c_res.get("n_prints", len(c_res.get("observations") or [])),
        }
        row["final_coverage_status"] = _classify_deal(row)
        rows.append(row)

    by_deal_prints = Counter(o.deal_id for o in all_obs)
    n_3plus = sum(1 for _, n in by_deal_prints.items() if n >= 3)
    meta = {
        "canonical_n": len(deals),
        "total_real_price_prints": len(all_obs),
        "deals_with_3plus_prints": n_3plus,
        "tiingo_deals_covered": sum(1 for r in rows if r["tiingo_n"] >= 3),
        "yahoo_deals_covered": sum(1 for r in rows if r["yahoo_n"] >= 3),
        "multi_provider_confirmed": sum(
            1 for r in rows if r["final_coverage_status"] == "MULTI_PROVIDER_CONFIRMED"),
        "uncovered_deals": sum(1 for r in rows if r["combined_n"] < 3),
        "historical_price_data_ready": n_3plus >= 20,
        "crsp_status": CRSP_STATUS,
        "provider_chain": [p.name for p in default_providers()],
        "openfigi_matched": sum(1 for r in rows if r["openfigi_status"] == "MATCHED"),
        "openfigi_ambiguous": sum(1 for r in rows if r["openfigi_status"] == "AMBIGUOUS"),
        "openfigi_no_match": sum(1 for r in rows if r["openfigi_status"] == "NO_MATCH"),
        "gap_class_counts": dict(Counter(r["final_coverage_status"] for r in rows)),
        "reconcile": dict(recon_stats),
    }
    doc = {
        "schema_version": 1,
        "_doc": "Free thesis stack coverage matrix (OpenFIGI + Tiingo + Yahoo).",
        "meta": meta,
        "deals": rows,
        "conflict_samples": conflict_samples[:50],
    }
    OUT_MATRIX.write_text(json.dumps(doc, indent=2) + "\n")
    write_normalized_manifest(all_obs, DEFAULT_MANIFEST, meta=meta)
    OUT_AUDIT.write_text(json.dumps({"meta": meta, "deals": rows}, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    print(f"wrote {OUT_MATRIX}")
    print(f"wrote {DEFAULT_MANIFEST} ({len(all_obs)} prints)")

    # Offline audit docs (no credentials required once matrix exists)
    from scripts.audit_free_price_coverage import main as audit_main
    audit_rc = audit_main()
    if audit_rc != 0:
        print("audit_free_price_coverage failed", file=sys.stderr)
        return audit_rc

    if n_3plus < 20:
        print("HISTORICAL_PRICE_DATA_READY = NO", file=sys.stderr)
        print("SPREAD_STRESS_BACKTEST_STATUS = BLOCKED_INSUFFICIENT_PRICE_HISTORY",
              file=sys.stderr)
        return 0

    print("HISTORICAL_PRICE_DATA_READY = YES", file=sys.stderr)
    print("SPREAD_STRESS_READY_FOR_EXECUTION = YES", file=sys.stderr)
    print("THESIS_PRICE_DATA_READY_FOR_REVIEW = YES", file=sys.stderr)
    from scripts.freeze_thesis_price_cohort import main as freeze_main
    freeze_rc = freeze_main()
    if freeze_rc != 0:
        print("cohort freeze failed after readiness", file=sys.stderr)
        return freeze_rc
    # Free-thesis goal: stop before model / spread_stress execution.
    print("STOP — cohort frozen; do not execute backtest in this goal.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
