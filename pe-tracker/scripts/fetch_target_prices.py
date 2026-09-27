#!/usr/bin/env python3
"""Fetch real target-price prints into data/target_price_manifest.json.

Requires network + SEC_USER_AGENT (for CIK→ticker via company_tickers.json).

  cd pe-tracker
  SEC_USER_AGENT='…' python -m scripts.fetch_target_prices

Does not fabricate prices. Deals with no Yahoo history are listed in the
coverage audit and omitted from the manifest.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.providers.yahoo_equity import (  # noqa: E402
    DEFAULT_DEAL_MANIFEST,
    DEFAULT_TICKER_MAP,
    fetch_manifest_prints,
    write_price_manifest,
)
from src.ingest.target_prices import DEFAULT_MANIFEST  # noqa: E402


def main() -> int:
    if not os.getenv("SEC_USER_AGENT"):
        print("SEC_USER_AGENT is not set", file=sys.stderr)
        return 2
    result = fetch_manifest_prints(
        deal_manifest=DEFAULT_DEAL_MANIFEST,
        ticker_map=DEFAULT_TICKER_MAP,
        user_agent=os.environ["SEC_USER_AGENT"],
    )
    meta = {
        "provider": result["provider"],
        "n_deals": result["n_deals"],
        "n_prints": result["n_prints"],
        "n_deals_with_ge3_prints": result["n_deals_with_ge3_prints"],
        "sec_deal_manifest": str(DEFAULT_DEAL_MANIFEST.relative_to(ROOT)),
    }
    write_price_manifest(result["prints"], DEFAULT_MANIFEST, meta=meta)
    audit_path = ROOT / "data" / "target_price_fetch_audit.json"
    audit_path.write_text(json.dumps({
        "meta": meta,
        "audit": result["audit"],
    }, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    print(f"wrote {DEFAULT_MANIFEST} ({result['n_prints']} prints)")
    print(f"wrote {audit_path}")
    if result["n_deals_with_ge3_prints"] < 20:
        print(
            "NOTE: n_deals_with_ge3_prints < 20 — "
            "SPREAD_STRESS_BACKTEST remains BLOCKED_INSUFFICIENT_PRICE_HISTORY "
            "(delisted targets typically have no Yahoo history).",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
