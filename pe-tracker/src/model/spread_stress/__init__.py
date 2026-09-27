"""spread_stress_v1 — challenger feature schema, model, gates, comparison.

Does NOT mutate fs_v1 / break_logit_v1 / first_walkforward_v1.
"""
from __future__ import annotations

from .features import (
    FEATURE_SCHEMA_VERSION,
    SPREAD_STRESS_FEATURES,
    VOL_WINDOW_DEFAULT,
    VOL_WINDOW_SENSITIVITY,
    build_spread_stress_row,
    build_spread_stress_panel,
    delta_spread_series,
)
from .gates import (
    BLOCKED_INSUFFICIENT_PRICE_HISTORY,
    PriceReadiness,
    audit_price_history,
    authorize_spread_stress_backtest,
)
from .model import (
    MODEL_ID,
    MODEL_VERSION,
    SpreadStressModel,
)
from .compare import (
    common_universe,
    incremental_metrics,
    run_gated_comparison,
)

__all__ = [
    "FEATURE_SCHEMA_VERSION",
    "SPREAD_STRESS_FEATURES",
    "VOL_WINDOW_DEFAULT",
    "VOL_WINDOW_SENSITIVITY",
    "build_spread_stress_row",
    "build_spread_stress_panel",
    "delta_spread_series",
    "BLOCKED_INSUFFICIENT_PRICE_HISTORY",
    "PriceReadiness",
    "audit_price_history",
    "authorize_spread_stress_backtest",
    "MODEL_ID",
    "MODEL_VERSION",
    "SpreadStressModel",
    "common_universe",
    "incremental_metrics",
    "run_gated_comparison",
]
