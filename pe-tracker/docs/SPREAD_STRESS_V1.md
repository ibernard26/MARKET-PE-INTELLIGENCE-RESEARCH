# Spread-stress challenger (`spread_stress_v1`) — research contract

**Status:** architecture + gated real-data authorization. Replaces any prior
draft that stopped at “No real fitting yet.”

The full copy-paste prompt (sections 1–29) lives at
`outputs/spread_stress_strategy_prompt.md`.

## Locked baselines (must not change)

| Artifact | Version |
|---|---|
| Strategy | `event_driven_v1` |
| Announcement features | `fs_v1` |
| Announcement model | `break_logit_v1` |
| Walk-forward freeze | `first_walkforward_v1` |

Expected invariants: `FS_V1_CHANGED = NO`, `BREAK_LOGIT_V1_CHANGED = NO`,
`FIRST_WALKFORWARD_V1_CHANGED = NO`.

## Challenger identity

| Field | Value |
|---|---|
| `model_id` | `spread_stress` |
| `model_version` | `spread_stress_v1` |
| Feature schema | `fs_spread_stress_v1` |

Features (point-in-time from longitudinal target prints):

- `delta_spread` — \(\Delta S_{i,t}\)
- `spread_vol` — \(\sigma_{\Delta S,i,t}\) over a frozen window \(w\)
- optional levels: `pct_spread` at \(t\) (for diagnostics; not absorbed into `fs_v1`)

## Authorization hierarchy

```
Theory → PIT Data → Model → Walk-Forward Predictions → Trading Rules
      → Backtest → Evidence
```

Real-data walk-forward / backtest is **authorized only after** data audit,
PIT validation, provenance, sample-size, and historical-price readiness gates
pass (`src/model/spread_stress/gates.py`).

If longitudinal target-price history is insufficient:

1. do not fabricate prices;
2. do not claim a spread-stress backtest;
3. set `SPREAD_STRESS_BACKTEST_STATUS = BLOCKED_INSUFFICIENT_PRICE_HISTORY`;
4. list exactly what is missing;
5. use the target-price ingestion architecture
   (`src/ingest/target_prices.py`) to unblock.

## Modules

| Path | Role |
|---|---|
| `src/model/spread_stress/` | features, model, gates, comparison harness |
| `src/ingest/target_prices.py` | longitudinal target-print provider + writer |
| `tests/test_spread_stress_*.py` | readiness, leakage, freeze invariants |

## Combined model

`break_logit_v2` / `fs_v2` is **out of scope until** price history and sample
size support a separately versioned specification. Do not edit
`break_logit_v1` to create a combined model.
