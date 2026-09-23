"""Historical point-in-time research layer.

Every read here answers "what was knowable at time T?" and nothing more.

  bitemporal      the three-times rule (valid / known_at / ingestion) + helpers
  observations    append-only deal snapshots; sparse state reconstruction
  events          append-only lifecycle events with ordering validation
  market_context  timestamped, sourced market prints (no raw dicts)
  features        pure point-in-time feature builder (spread, structure, regulatory)
  backtest        cash-deal merger-arb backtester; pending deals censored
  portfolio       exposure, concentration, expected loss, stress scenarios
  simulation      correlated Monte Carlo of deal breaks (VaR / ES)

See docs/ARCHITECTURE.md for how these fit together with src/model.
"""
