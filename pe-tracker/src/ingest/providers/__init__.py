"""Concrete HistoricalDealProvider implementations.

  sec_edgar      SEC EDGAR filing-timestamped events + manifest-cited deal terms
  yahoo_equity   Yahoo Finance daily target closes for spread_stress_v1
                 (gaps for delisted names stay gaps — see docs/TARGET_PRICE_HISTORY.md)
  (future)       commercial / licensed delisted-equity history; regulator providers
"""
