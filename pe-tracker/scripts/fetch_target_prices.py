#!/usr/bin/env python3
"""Fetch real target-price prints into data/target_price_manifest.json.

Uses the multi-provider orchestrator (CRSP first when licensed, else Yahoo).
Requires SEC_USER_AGENT. Optional: WRDS_USERNAME / CRSP_DATA_DIR (see docs/CRSP_ACCESS.md).

  cd pe-tracker
  SEC_USER_AGENT='…' python -m scripts.fetch_target_prices

Does not fabricate prices. Deals with no provider history are listed in the
coverage audit and omitted from the manifest.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.equity_prices.fetch import (  # noqa: E402
    DEFAULT_DEAL_MANIFEST,
    fetch_manifest_prints,
)
from src.ingest.equity_prices.identity import DEFAULT_TICKER_MAP  # noqa: E402
from src.ingest.equity_prices.normalize import write_normalized_manifest  # noqa: E402
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
        "provider_chain": result["provider_chain"],
        "provider": result["provider"],
        "n_deals": result["n_deals"],
        "n_prints": result["n_prints"],
        "n_deals_with_ge3_prints": result["n_deals_with_ge3_prints"],
        "sec_deal_manifest": str(DEFAULT_DEAL_MANIFEST.relative_to(ROOT)),
    }
    write_normalized_manifest(
        result["observations"], DEFAULT_MANIFEST, meta=meta)
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
            "SPREAD_STRESS_BACKTEST remains BLOCKED_INSUFFICIENT_PRICE_HISTORY.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
