"""Backward-compatible Yahoo equity entrypoint.

Prefer `src.ingest.equity_prices` for new code. This module re-exports the
Yahoo adapter and corpus fetch helpers so existing import paths keep working.
"""
from __future__ import annotations

from ..equity_prices.fetch import (  # noqa: F401
    DEFAULT_DEAL_MANIFEST,
    fetch_manifest_prints,
    write_price_manifest,
)
from ..equity_prices.identity import (  # noqa: F401
    DEFAULT_TICKER_MAP,
    SecurityIdentityResolver,
    deal_id_ticker,
)
from ..equity_prices.yahoo import (  # noqa: F401
    PROVIDER_NAME,
    YahooEquityPriceProvider,
    session_close_iso,
)

# Legacy names
TickerResolver = SecurityIdentityResolver
YahooChartClient = YahooEquityPriceProvider
YahooEquityError = RuntimeError


def prints_for_deal(deal, resolver, client, pad_days: int = 3):
    """Fetch prints for one deal via orchestrator (legacy test helper)."""
    from ..equity_prices.normalize import observation_to_print
    from ..equity_prices.orchestrator import PriceProviderOrchestrator
    from ..equity_prices.schema import ProviderStatus

    if not isinstance(client, YahooEquityPriceProvider):
        client = YahooEquityPriceProvider(
            fetch_json=getattr(client, "_fetch", None))
    orch = PriceProviderOrchestrator(
        providers=[client], resolver=resolver, pad_days=pad_days)
    r = orch.fetch_deal(deal)
    prints = [observation_to_print(o) for o in r.get("observations") or []]
    status = r["status"]
    if status == "ok":
        legacy = "ok"
    elif status == ProviderStatus.IDENTITY_UNRESOLVED.value:
        legacy = "no_ticker"
    elif status in (ProviderStatus.TRANSIENT_FAILURE.value,
                    ProviderStatus.PROVIDER_ERROR.value):
        legacy = "fetch_error"
    else:
        legacy = "no_price_history"
    return {
        "deal_id": deal["deal_id"],
        "accepted": prints,
        "status": legacy,
        "ticker": r.get("ticker"),
        "n_prints": len(prints),
        "window": r.get("window"),
        "resolved": {
            "ticker": r.get("ticker"),
            "basis": (r["identity"].ticker_basis if r.get("identity") else None),
            "source_identifier": (
                r["identity"].identity_source if r.get("identity") else None),
        },
    }
