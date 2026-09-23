"""Registry of FRED series ingested into the canonical market store.

`config.SERIES` holds the four original market series and is left untouched
(config.py also carries the locked strategy contract). Rate context lives here
so it can be added without touching that file.

DGS10 = 10-Year Treasury Constant Maturity Rate (percent, daily). Chosen over
alternatives because it is the standard long-rate benchmark, is published daily
by the Board of Governors (H.15) on FRED with the same observation format as the
existing series ("." = missing), and needs no new provider or key.

Calendar note: DGS10 follows the U.S. government-bond calendar (SIFMA), not the
NYSE calendar. On days the bond market is closed but NYSE is open (e.g. Columbus
Day, Veterans Day) FRED reports "." and the value stays NULL — it is never filled.

DFF = Effective Federal Funds Rate (percent, daily; Board of Governors H.15 via
FRED). Short-rate / policy-stance context beside DGS10's long rate, same provider
and observation format. FRED publishes DFF for EVERY calendar day, weekends and
holidays included, so it has rows on non-NYSE days; the NYSE calendar gate
applies wherever signal code joins against market_calendar.

DFF is RESEARCH CONTEXT ONLY: it is ingested and queryable point-in-time via
research/market_data (series_as_of / level / change), but it is NOT in the break
model's feature schema fs_v1, nor in RESEARCH_FEATURES / PointInTimeMarketContext.
Promoting it requires an empirical case and a new feature_schema_version.
"""
from ..config import SERIES

RATE_SERIES = {
    "DGS10": ("10-Year Treasury Constant Maturity Rate", "percent"),
    "DFF": ("Effective Federal Funds Rate", "percent"),
}

ALL_SERIES = {**SERIES, **RATE_SERIES}
