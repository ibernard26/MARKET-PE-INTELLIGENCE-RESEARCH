"""Ordered multi-provider fetch with conflict detection (no blind merges)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Sequence

from .calendar_gate import filter_session_observations
from .identity import SecurityIdentityResolver
from .protocol import HistoricalEquityPriceProvider
from .schema import (
    FALLBACK_STATUSES,
    TRANSIENT_STATUSES,
    NormalizedEquityObservation,
    ProviderFetchResult,
    ProviderStatus,
    SecurityIdentity,
)

# Absolute tolerance for declaring two closes "the same print".
PRICE_MATCH_TOLERANCE = 1e-4  # $0.0001
PRICE_MATCH_REL_TOLERANCE = 1e-6


def _prices_agree(a: float, b: float) -> bool:
    if a == b:
        return True
    diff = abs(a - b)
    return diff <= PRICE_MATCH_TOLERANCE or diff <= PRICE_MATCH_REL_TOLERANCE * max(abs(a), abs(b))


def compare_provider_series(
        primary: list[NormalizedEquityObservation],
        secondary: list[NormalizedEquityObservation],
) -> dict:
    """Compare overlapping session dates. Never silently pick min/max."""
    pmap = {o.session_date: o for o in primary}
    smap = {o.session_date: o for o in secondary}
    overlap = sorted(set(pmap) & set(smap))
    conflicts = []
    agrees = 0
    for sd in overlap:
        if _prices_agree(pmap[sd].close, smap[sd].close):
            agrees += 1
        else:
            conflicts.append({
                "session_date": sd,
                "primary_close": pmap[sd].close,
                "secondary_close": smap[sd].close,
                "primary_provider": pmap[sd].provider,
                "secondary_provider": smap[sd].provider,
            })
    return {
        "n_overlap": len(overlap),
        "n_agree": agrees,
        "n_conflict": len(conflicts),
        "conflicts": conflicts,
        "status": (ProviderStatus.DEFER_PRICE_CONFLICT.value
                   if conflicts else "AGREE"),
    }


class PriceProviderOrchestrator:
    """Try providers in order; do not merge histories blindly."""

    def __init__(self, providers: Sequence[HistoricalEquityPriceProvider],
                 resolver: Optional[SecurityIdentityResolver] = None,
                 calendar_conn=None,
                 pad_days: int = 3):
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = list(providers)
        self.resolver = resolver or SecurityIdentityResolver()
        self.calendar_conn = calendar_conn
        self.pad_days = pad_days

    def fetch_deal(self, deal: dict) -> dict:
        """Fetch announce→resolution prints for one SEC manifest deal."""
        identity, defer = self.resolver.resolve(deal)
        ann = date.fromisoformat(deal["announcement_timestamp"][:10])
        res_s = deal.get("resolution_timestamp") or deal["announcement_timestamp"]
        res = date.fromisoformat(res_s[:10])
        start = ann - timedelta(days=self.pad_days)
        end = res + timedelta(days=self.pad_days)

        if defer is not None:
            return {
                "deal_id": deal["deal_id"],
                "status": defer.value,
                "identity": identity,
                "observations": [],
                "provider_trace": [],
                "window": [start.isoformat(), end.isoformat()],
            }

        trace: list[dict] = []
        chosen: Optional[ProviderFetchResult] = None
        for prov in self.providers:
            if prov.credentials_required():
                # Adapter present but unusable without credentials — record and skip.
                trace.append({"provider": prov.name,
                              "status": ProviderStatus.CREDENTIALS_REQUIRED.value})
                continue
            result = prov.fetch_history(identity, start, end)
            # Restrict to announce..resolution inclusive for spread_stress window
            if result.observations:
                in_window = [o for o in result.observations
                             if ann <= date.fromisoformat(o.session_date) <= res]
                result.observations = in_window
                if not in_window and result.status == ProviderStatus.AVAILABLE:
                    result.status = ProviderStatus.NO_HISTORY
            trace.append({
                "provider": result.provider,
                "status": result.status.value,
                "n_observations": len(result.observations),
                "provider_symbol": result.provider_symbol,
                "error": result.error,
                "identity_verified": result.identity_verified,
            })
            if result.ok:
                chosen = result
                break
            if result.status == ProviderStatus.IDENTITY_AMBIGUOUS:
                # The ticker is not shown to be this target (e.g. reused symbol):
                # a lower-precedence provider keyed on the same ticker must not
                # be tried — defer the deal instead.
                break
            if result.status in TRANSIENT_STATUSES:
                # Already retried inside adapter; try next provider.
                continue
            if result.status not in FALLBACK_STATUSES:
                # Hard provider error — still try next, but keep trace.
                continue

        if chosen is None:
            # Prefer last non-credentials status
            last = next((t for t in reversed(trace)
                         if t["status"] != ProviderStatus.CREDENTIALS_REQUIRED.value),
                        {"status": ProviderStatus.NO_HISTORY.value})
            return {
                "deal_id": deal["deal_id"],
                "status": last["status"],
                "identity": identity,
                "observations": [],
                "provider_trace": trace,
                "window": [start.isoformat(), end.isoformat()],
                "ticker": identity.ticker,
            }

        ok, bad = filter_session_observations(
            chosen.observations, conn=self.calendar_conn)
        return {
            "deal_id": deal["deal_id"],
            "status": "ok" if ok else ProviderStatus.NO_HISTORY.value,
            "identity": identity,
            "observations": ok,
            "rejected_non_session": len(bad),
            "provider": chosen.provider,
            "provider_symbol": chosen.provider_symbol,
            "n_prints": len(ok),
            "provider_trace": trace,
            "window": [start.isoformat(), end.isoformat()],
            "ticker": identity.ticker,
        }
