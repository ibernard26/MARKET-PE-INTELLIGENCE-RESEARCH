"""OPTIONAL live FRED integration test. Skipped unless FRED_LIVE=1 and
FRED_API_KEY are set, so ordinary CI never depends on FRED uptime."""
import os

import pytest

from src.ingest import fred
from src.ingest.market_series import ALL_SERIES

pytestmark = pytest.mark.skipif(
    not (os.getenv("FRED_LIVE") == "1" and os.getenv("FRED_API_KEY")),
    reason="live FRED test: set FRED_LIVE=1 and FRED_API_KEY")


@pytest.mark.parametrize("series_id", sorted(ALL_SERIES))
def test_live_series_resolves(series_id):
    obs = fred.fetch_series(series_id, start="2026-01-01")
    assert obs, f"{series_id} returned no observations"
    assert all(o["value"] is None or isinstance(o["value"], float) for o in obs)
