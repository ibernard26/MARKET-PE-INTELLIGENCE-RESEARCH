"""Corpus-level fetch using the multi-provider orchestrator."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

from .crsp import CRSPEquityPriceProvider
from .identity import DEFAULT_TICKER_MAP, SecurityIdentityResolver
from .normalize import observation_to_print, write_normalized_manifest
from .orchestrator import PriceProviderOrchestrator
from .protocol import HistoricalEquityPriceProvider
from .yahoo import YahooEquityPriceProvider

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEAL_MANIFEST = ROOT / "data" / "sec_deal_manifest.json"


def default_providers() -> list[HistoricalEquityPriceProvider]:
    """Ordered fallback: CRSP (authoritative when licensed) → Yahoo → NO_HISTORY."""
    return [CRSPEquityPriceProvider(), YahooEquityPriceProvider()]


def fetch_manifest_prints(
        deal_manifest: Path = DEFAULT_DEAL_MANIFEST,
        ticker_map: Path = DEFAULT_TICKER_MAP,
        user_agent: Optional[str] = None,
        providers: Optional[Sequence[HistoricalEquityPriceProvider]] = None,
) -> dict:
    """Fetch real target prints for every SEC manifest deal via orchestrator."""
    deals = json.loads(Path(deal_manifest).read_text())["deals"]
    resolver = SecurityIdentityResolver(map_path=ticker_map, user_agent=user_agent)
    orch = PriceProviderOrchestrator(
        providers=list(providers or default_providers()),
        resolver=resolver,
    )
    all_obs = []
    audit = []
    for d in deals:
        r = orch.fetch_deal(d)
        audit.append({
            "deal_id": r["deal_id"],
            "status": r["status"],
            "ticker": r.get("ticker"),
            "n_prints": r.get("n_prints", len(r.get("observations") or [])),
            "provider": r.get("provider"),
            "provider_symbol": r.get("provider_symbol"),
            "provider_trace": r.get("provider_trace"),
            "window": r.get("window"),
            "identity_basis": (
                r["identity"].ticker_basis if r.get("identity") else None),
        })
        all_obs.extend(r.get("observations") or [])
    n_ok = sum(1 for a in audit if a.get("status") == "ok" and a.get("n_prints", 0) >= 3)
    prints = [observation_to_print(o) for o in all_obs]
    return {
        "provider_chain": [p.name for p in (providers or default_providers())],
        "provider": (providers or default_providers())[0].name,
        "n_deals": len(deals),
        "n_prints": len(prints),
        "n_deals_with_ge3_prints": n_ok,
        "audit": audit,
        "prints": prints,
        "observations": all_obs,
    }


# Re-export write helper under the old name used by scripts/tests.
write_price_manifest = write_normalized_manifest
