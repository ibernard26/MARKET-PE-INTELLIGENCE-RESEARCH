#!/usr/bin/env python3
"""Live connectivity smoke for OpenFIGI, Tiingo, and Yahoo.

This is a provider-reachability check, not a thesis security-resolution
test. OpenFIGISecurityIdentityResolver is unchanged: an ambiguous historical
identity still means DEFER_SECURITY_IDENTITY_AMBIGUOUS for the corpus.

OpenFIGI connectivity PASS means the credential was visible, the API was
reached, authentication succeeded, and the payload was a normal mapping
response. MATCHED, AMBIGUOUS, NO_MATCH, and NAME_MISMATCH are all PASS.
AUTH_FAILURE, NETWORK_BLOCKED, RATE_LIMITED, TRANSIENT_FAILURE,
PROVIDER_ERROR, and INVALID_RESPONSE (including the adapter's
INVALID_REQUEST) are FAIL.

Never prints credential values. Exits 3 on CREDENTIAL_ENVIRONMENT_NOT_VISIBLE.

  cd pe-tracker
  python -m scripts.smoke_free_providers
"""
from __future__ import annotations

import json
import os
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
from src.ingest.equity_prices.yahoo import YahooEquityPriceProvider  # noqa: E402
from src.ingest.security_identity.openfigi import (  # noqa: E402
    OpenFIGISecurityIdentityResolver,
)


# Known currently listed name used only for connectivity — not a thesis claim.
SMOKE_TICKER = "AAPL"
SMOKE_NAME = "APPLE INC"

# Normal mapping outcomes. Unique instrument identity is not required.
OPENFIGI_CONNECTIVITY_OK = frozenset({
    "MATCHED",
    "AMBIGUOUS",
    "NO_MATCH",
    "NAME_MISMATCH",
})

# Infrastructure outcomes. INVALID_REQUEST is the adapter name for a
# non-success HTTP body that is not auth, rate-limit, or transient.
OPENFIGI_CONNECTIVITY_FAIL = frozenset({
    "AUTH_FAILURE",
    "NETWORK_BLOCKED",
    "RATE_LIMITED",
    "TRANSIENT_FAILURE",
    "PROVIDER_ERROR",
    "INVALID_RESPONSE",
    "INVALID_REQUEST",
    "CREDENTIALS_REQUIRED",
})


def openfigi_connectivity_ok(mapping_status: str) -> bool:
    """True when OpenFIGI returned a normal authenticated mapping response."""
    return mapping_status in OPENFIGI_CONNECTIVITY_OK


def _presence_flag(name: str) -> str:
    return "YES" if (os.getenv(name) or "").strip() else "NO"


def _price_pass(status: str, n_observations: int) -> bool:
    return status == "AVAILABLE" and n_observations >= 1


def main() -> int:
    presence = credential_presence()
    presence["SEC_USER_AGENT_PRESENT"] = _presence_flag("SEC_USER_AGENT")
    print(json.dumps({"credential_presence": presence}, indent=2))
    missing = missing_credential_names()
    if missing:
        print("CREDENTIAL_ENVIRONMENT_NOT_VISIBLE", file=sys.stderr)
        for name in missing:
            print(name, file=sys.stderr)
        return 3

    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=14)
    identity = SecurityIdentity(
        deal_id="SMOKE-AAPL", ticker=SMOKE_TICKER, target_name=SMOKE_NAME)

    # --- OpenFIGI (connectivity only; resolver ambiguity rule is untouched) ---
    figi = OpenFIGISecurityIdentityResolver(min_interval_s=0.35)
    of_out = figi.resolve_deal(
        {"deal_id": "SMOKE-AAPL", "target": SMOKE_NAME,
         "announcement_timestamp": "2024-01-02"},
        ticker=SMOKE_TICKER,
    )
    of_pass = openfigi_connectivity_ok(of_out.mapping_status)
    print(json.dumps({
        "OPENFIGI_LIVE_TEST": "PASS" if of_pass else "FAIL",
        "OPENFIGI_RESOLVER_STATUS": of_out.mapping_status,
        "error": of_out.error,
    }, indent=2))

    # --- Tiingo ---
    tiingo = TiingoEquityPriceProvider(min_interval_s=0.25)
    t_res = tiingo.fetch_history(identity, start, end)
    t_pass = _price_pass(t_res.status.value, len(t_res.observations))
    print(json.dumps({
        "TIINGO_LIVE_TEST": "PASS" if t_pass else "FAIL",
        "TIINGO_STATUS": t_res.status.value,
        "n_observations": len(t_res.observations),
        "error": t_res.error,
    }, indent=2))

    # --- Yahoo (public chart API; no API key) ---
    yahoo = YahooEquityPriceProvider()
    y_res = yahoo.fetch_history(identity, start, end)
    y_pass = _price_pass(y_res.status.value, len(y_res.observations))
    print(json.dumps({
        "YAHOO_LIVE_TEST": "PASS" if y_pass else "FAIL",
        "YAHOO_STATUS": y_res.status.value,
        "n_observations": len(y_res.observations),
        "error": y_res.error,
    }, indent=2))

    if of_pass and t_pass and y_pass:
        print("SMOKE_OK")
        return 0
    auth_failed = (
        of_out.mapping_status == "AUTH_FAILURE" or t_res.error == "AUTH_FAILURE")
    if auth_failed:
        print("LIVE_TEST = FAIL (AUTH_FAILURE)", file=sys.stderr)
        return 4
    print("LIVE_TEST = FAIL", file=sys.stderr)
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
