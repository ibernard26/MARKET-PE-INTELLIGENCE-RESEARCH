"""Normalized historical equity-price schema + failure taxonomy.

Downstream consumers must not depend on Yahoo-specific fields. Every
canonical observation is provider-backed, session-dated, and non-synthetic.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


class ProviderStatus(str, Enum):
    """Explicit provider outcomes — do not collapse into a single 'missing'."""
    AVAILABLE = "AVAILABLE"
    NO_HISTORY = "NO_HISTORY"
    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    DELISTED_UNAVAILABLE = "DELISTED_UNAVAILABLE"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"
    IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"
    NON_SESSION_DATE = "NON_SESSION_DATE"
    DEFER_PRICE_CONFLICT = "DEFER_PRICE_CONFLICT"
    CREDENTIALS_REQUIRED = "CREDENTIALS_REQUIRED"


# Terminal "no data" outcomes that should trigger the next provider in fallback.
FALLBACK_STATUSES = frozenset({
    ProviderStatus.NO_HISTORY,
    ProviderStatus.SYMBOL_NOT_FOUND,
    ProviderStatus.DELISTED_UNAVAILABLE,
    ProviderStatus.IDENTITY_UNRESOLVED,
    ProviderStatus.CREDENTIALS_REQUIRED,
})

# Retryable once (then escalate / fall through).
TRANSIENT_STATUSES = frozenset({
    ProviderStatus.TRANSIENT_FAILURE,
})


@dataclass(frozen=True)
class SecurityIdentity:
    """Point-in-time security identity for a deal target (separate from prices)."""
    deal_id: str
    target_cik: Optional[int] = None
    target_name: Optional[str] = None
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    ticker_basis: Optional[str] = None  # reviewed_map | sec_company_tickers | …
    announcement_date: Optional[str] = None
    resolution_date: Optional[str] = None
    identity_source: Optional[str] = None
    notes: tuple[str, ...] = ()

    def resolved(self) -> bool:
        return bool(self.ticker)


@dataclass(frozen=True)
class NormalizedEquityObservation:
    """Provider-agnostic daily close observation."""
    deal_id: str
    session_date: str                     # YYYY-MM-DD
    close: float
    provider: str
    provider_symbol: str
    retrieval_timestamp: str              # ISO when we fetched it
    target_cik: Optional[int] = None
    target_name: Optional[str] = None
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    adjusted_close: Optional[float] = None
    currency: str = "USD"
    close_field_used: str = "close"       # close | adjusted_close
    corporate_action_note: Optional[str] = None
    source_metadata: dict = field(default_factory=dict)
    observation_timestamp: Optional[str] = None  # session close instant
    known_at: Optional[str] = None

    def __post_init__(self):
        if not (isinstance(self.close, (int, float)) and self.close > 0
                and self.close == self.close):  # NaN check
            raise ValueError(f"close must be a positive finite float, got {self.close!r}")
        if self.adjusted_close is not None:
            if not (self.adjusted_close > 0 and self.adjusted_close == self.adjusted_close):
                raise ValueError("adjusted_close must be positive finite when set")
        # Normalize empty metadata
        if self.source_metadata is None:
            object.__setattr__(self, "source_metadata", {})

    def provenance_hash(self) -> str:
        payload = {
            "deal_id": self.deal_id,
            "session_date": self.session_date,
            "close": self.close,
            "adjusted_close": self.adjusted_close,
            "provider": self.provider,
            "provider_symbol": self.provider_symbol,
            "ticker": self.ticker,
            "exchange": self.exchange,
            "currency": self.currency,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["provenance_hash"] = self.provenance_hash()
        return d


@dataclass
class ProviderFetchResult:
    """Outcome of one provider fetch for one security/window."""
    provider: str
    status: ProviderStatus
    identity: Optional[SecurityIdentity] = None
    observations: list[NormalizedEquityObservation] = field(default_factory=list)
    error: Optional[str] = None
    provider_symbol: Optional[str] = None
    window: Optional[tuple[str, str]] = None

    @property
    def ok(self) -> bool:
        return self.status == ProviderStatus.AVAILABLE and bool(self.observations)
