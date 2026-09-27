"""Multi-provider historical equity price architecture.

Yahoo is one adapter. Downstream code consumes NormalizedEquityObservation
only — never Yahoo-specific payloads.
"""
from .calendar_gate import filter_session_observations, is_valid_session
from .identity import SecurityIdentityResolver, deal_id_ticker
from .normalize import observation_to_print, write_normalized_manifest
from .orchestrator import PriceProviderOrchestrator, compare_provider_series
from .protocol import HistoricalEquityPriceProvider
from .schema import (
    FALLBACK_STATUSES,
    NormalizedEquityObservation,
    ProviderFetchResult,
    ProviderStatus,
    SecurityIdentity,
)
from .yahoo import YahooEquityPriceProvider

__all__ = [
    "HistoricalEquityPriceProvider",
    "SecurityIdentity",
    "SecurityIdentityResolver",
    "NormalizedEquityObservation",
    "ProviderFetchResult",
    "ProviderStatus",
    "FALLBACK_STATUSES",
    "YahooEquityPriceProvider",
    "PriceProviderOrchestrator",
    "compare_provider_series",
    "observation_to_print",
    "write_normalized_manifest",
    "is_valid_session",
    "filter_session_observations",
    "deal_id_ticker",
]
