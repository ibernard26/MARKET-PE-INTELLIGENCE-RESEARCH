"""Multi-provider historical equity price architecture.

Active thesis stack: Tiingo (primary) → Yahoo (reconcile/fallback).
CRSP is retained as a frozen future robustness provider (not in default chain).
Downstream code consumes NormalizedEquityObservation only.
"""
from .calendar_gate import filter_session_observations, is_valid_session
from .credentials import credential_presence, missing_credential_names
from .crsp import CRSPEquityPriceProvider
from .crsp_access import CrspAccessConfig, detect_crsp_access
from .identity import SecurityIdentityResolver, deal_id_ticker
from .normalize import observation_to_print, write_normalized_manifest
from .orchestrator import PriceProviderOrchestrator, compare_provider_series
from .protocol import HistoricalEquityPriceProvider
from .reconciliation import RECONCILE_RULE_VERSION, classify_close_pair, reconcile_series
from .schema import (
    FALLBACK_STATUSES,
    NormalizedEquityObservation,
    ProviderFetchResult,
    ProviderStatus,
    SecurityIdentity,
)
from .tiingo import TiingoEquityPriceProvider, tiingo_api_token_present
from .yahoo import YahooEquityPriceProvider

__all__ = [
    "HistoricalEquityPriceProvider",
    "SecurityIdentity",
    "SecurityIdentityResolver",
    "NormalizedEquityObservation",
    "ProviderFetchResult",
    "ProviderStatus",
    "FALLBACK_STATUSES",
    "TiingoEquityPriceProvider",
    "tiingo_api_token_present",
    "YahooEquityPriceProvider",
    "CRSPEquityPriceProvider",
    "CrspAccessConfig",
    "detect_crsp_access",
    "PriceProviderOrchestrator",
    "compare_provider_series",
    "reconcile_series",
    "classify_close_pair",
    "RECONCILE_RULE_VERSION",
    "credential_presence",
    "missing_credential_names",
    "observation_to_print",
    "write_normalized_manifest",
    "is_valid_session",
    "filter_session_observations",
    "deal_id_ticker",
]
