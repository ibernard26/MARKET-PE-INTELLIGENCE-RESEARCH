#!/usr/bin/env python3
"""Controlled live smoke tests for OpenFIGI + Tiingo.

Never prints credential values. Exits 3 on CREDENTIAL_ENVIRONMENT_NOT_VISIBLE.

  cd pe-tracker
  python -m scripts.smoke_free_providers
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.equity_prices.credentials import (  # noqa: E402
    credential_presence,
    missing_credential_names,
)
from src.ingest.equity_prices.schema import SecurityIdentity  # noqa: E402
from src.ingest.equity_prices.tiingo import TiingoEquityPriceProvider  # noqa: E402
from src.ingest.security_identity.openfigi import (  # noqa: E402
    OpenFIGISecurityIdentityResolver,
)


# Known currently listed name used only for connectivity — not a thesis claim.
SMOKE_TICKER = "AAPL"
SMOKE_NAME = "APPLE INC"


def main() -> int:
    presence = credential_presence()
    print(json.dumps({"credential_presence": presence}, indent=2))
    missing = missing_credential_names()
    if missing:
        print("CREDENTIAL_ENVIRONMENT_NOT_VISIBLE", file=sys.stderr)
        for name in missing:
            print(name, file=sys.stderr)
        return 3

    # --- OpenFIGI ---
    figi = OpenFIGISecurityIdentityResolver(min_interval_s=0.35)
    of_out = figi.resolve_deal(
        {"deal_id": "SMOKE-AAPL", "target": SMOKE_NAME,
         "announcement_timestamp": "2024-01-02"},
        ticker=SMOKE_TICKER,
    )
    of_pass = of_out.mapping_status == "MATCHED" and bool(of_out.figi)
    print(json.dumps({
        "OPENFIGI_LIVE_TEST": "PASS" if of_pass else "FAIL",
        "openfigi_status": of_out.mapping_status,
        "figi_present": bool(of_out.figi),
        "mapped_ticker": of_out.historical_ticker,
        "error": of_out.error,
    }, indent=2))
    if of_out.mapping_status == "AUTH_FAILURE":
        print("OPENFIGI_LIVE_TEST = FAIL (AUTH_FAILURE)", file=sys.stderr)
        return 4

    # --- Tiingo ---
    tiingo = TiingoEquityPriceProvider(min_interval_s=0.25)
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=14)
    t_res = tiingo.fetch_history(
        SecurityIdentity(deal_id="SMOKE-AAPL", ticker=SMOKE_TICKER,
                         target_name=SMOKE_NAME),
        start, end,
    )
    t_pass = t_res.status.value == "AVAILABLE" and len(t_res.observations) >= 1
    print(json.dumps({
        "TIINGO_LIVE_TEST": "PASS" if t_pass else "FAIL",
        "tiingo_status": t_res.status.value,
        "n_observations": len(t_res.observations),
        "error": t_res.error,
        "close_field_used": (
            t_res.observations[0].close_field_used if t_res.observations else None),
    }, indent=2))
    if t_res.error == "AUTH_FAILURE":
        print("TIINGO_LIVE_TEST = FAIL (AUTH_FAILURE)", file=sys.stderr)
        return 4

    if not (of_pass and t_pass):
        return 5
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
