"""Central config. Every constant the pipeline needs lives here."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / os.getenv("PE_TRACKER_DB", "data/pe_tracker.db")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# One provider covers all four series -- one key, one client, one failure mode.
SERIES = {
    "SP500":        ("S&P 500",           "index"),
    "NASDAQCOM":    ("NASDAQ Composite",  "index"),
    "DCOILWTICO":   ("WTI Cushing Spot",  "usd_per_bbl"),
    "DCOILBRENTEU": ("Brent Europe Spot", "usd_per_bbl"),
}

START_DATE = "2026-04-20"   # matches the workbook's first logged session

# NYSE closures 2026. Half-days are still sessions and are NOT listed here.
MARKET_HOLIDAYS = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-06-19": "Juneteenth",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving",
    "2026-12-25": "Christmas Day",
}

RULESET = "ma5_v1"
BUY_THRESHOLD = 0.0025
SELL_THRESHOLD = -0.0025
MA_WINDOW = 5

# ---------------------------------------------------------------------------
# STRATEGY CONTRACT (locked). These constants ARE the strategy. Every loop
# cycle and every session reads them from here — never re-derives or re-tunes
# them ad hoc. Changing one is a deliberate, versioned act: bump
# STRATEGY_VERSION, document it in STRATEGY.md, and expect the contract test
# (tests/test_strategy_contract.py) to require an update in the same commit.
# This is the mechanism that stops the strategy from differentiating between
# runs.
# ---------------------------------------------------------------------------
STRATEGY_VERSION = "event_driven_v1"

# The live thesis is event-driven / merger-arb deal-break scoring.
# The rare POSITIVE class is the deal BREAKING.
POSITIVE_CLASS = "broken"          # y = 1  <=>  status == 'broken'
CENSOR_STATUS = "pending"          # pending deals are censored, never negatives

# Cost-based operating point. FN (unhedged break -> full drawdown) is set an
# order of magnitude above FP (spread forgone hedging a deal that closes).
COST_FP = 1.0
COST_FN = 15.0                     # default FN:FP ratio = 15:1
COST_RATIO_GRID = (5, 10, 15, 20)  # sensitivity sweep reported every cycle

# Overfitting guard shared by the threshold sweep and any cohort read.
MIN_SAMPLE_N = 20

# The index momentum rule (ma5_v1) is RETIRED as a trade signal — it scored
# no edge (p = 0.44). It is retained, versioned, only as a gradeable baseline.
MOMENTUM_RULESET_STATUS = "retired_baseline"
