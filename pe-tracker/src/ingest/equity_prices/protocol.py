"""HistoricalEquityPriceProvider protocol — provider-agnostic interface."""
from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, runtime_checkable

from .schema import ProviderFetchResult, SecurityIdentity


@runtime_checkable
class HistoricalEquityPriceProvider(Protocol):
    """Fetch historical daily equity closes for a resolved security identity.

    Implementations must never fabricate, interpolate, or forward-fill prices.
    Yahoo-specific fields must not leak past the adapter boundary.
    """

    name: str

    def fetch_history(
        self,
        identity: SecurityIdentity,
        start: date,
        end: date,
    ) -> ProviderFetchResult:
        """Return AVAILABLE observations in [start, end], or an explicit failure status."""
        ...

    def credentials_required(self) -> bool:
        """True when this adapter cannot run without user-supplied credentials."""
        ...
