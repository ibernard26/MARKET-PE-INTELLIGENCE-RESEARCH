"""Concrete provider implementations.

  sec_edgar      SEC EDGAR filing-timestamped events + manifest-cited deal terms
  yahoo_equity   Thin re-export of Yahoo equity adapter (prefer
                 src.ingest.equity_prices for new code)
  (future)       commercial / licensed delisted-equity history; regulator providers

Multi-provider historical equity architecture lives in
`src.ingest.equity_prices` (protocol, identity, orchestrator, normalizer).
"""
