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
"""
from ..config import SERIES

RATE_SERIES = {
    "DGS10": ("10-Year Treasury Constant Maturity Rate", "percent"),
}

ALL_SERIES = {**SERIES, **RATE_SERIES}
