-- PE Tracker — canonical store. One row per fact. No derived values persisted.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS series (
    series_id   TEXT PRIMARY KEY,          -- FRED series id, e.g. 'SP500'
    label       TEXT NOT NULL,             -- human name, e.g. 'S&P 500'
    unit        TEXT NOT NULL,             -- 'index' | 'usd_per_bbl'
    source      TEXT NOT NULL              -- 'FRED'
);

CREATE TABLE IF NOT EXISTS prices (
    series_id   TEXT NOT NULL REFERENCES series(series_id),
    obs_date    TEXT NOT NULL,             -- ISO yyyy-mm-dd
    close       REAL,                      -- NULL = genuinely no observation
    provenance  TEXT NOT NULL,             -- 'FRED' | 'workbook_v3' | 'manual'
    is_derived  INTEGER NOT NULL DEFAULT 0, -- 1 = computed, never a market print
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (series_id, obs_date)
);
CREATE INDEX IF NOT EXISTS ix_prices_date ON prices(obs_date);

CREATE TABLE IF NOT EXISTS market_calendar (
    obs_date    TEXT PRIMARY KEY,
    is_trading  INTEGER NOT NULL,          -- 1 = NYSE session
    reason      TEXT                       -- 'weekend' | holiday name | NULL
);

-- Deal ledger: the gradeable transaction spine (Part C1).
-- Pending deals are censored, never negatives. y=1 <=> status='broken'.
CREATE TABLE IF NOT EXISTS deals (
  deal_id         TEXT PRIMARY KEY,
  announce_date   DATE NOT NULL,
  acquirer        TEXT, target TEXT, sponsor TEXT,
  value_usd_mm    REAL,
  sector          TEXT, geography TEXT,
  offer_premium   REAL,           -- observable at announce
  deal_type       TEXT,           -- strategic / LBO / take_private / JV / financing
  resolution_date DATE,           -- NULL while pending
  status          TEXT CHECK (status IN ('pending','closed','broken')),
  p_break         REAL,           -- model score set AT announce (point-in-time)
  model_version   TEXT,
  source_note     TEXT
);
CREATE INDEX IF NOT EXISTS ix_deals_status ON deals(status);
CREATE INDEX IF NOT EXISTS ix_deals_date   ON deals(announce_date);

-- Signals are recomputed, never hand-entered. Versioned by ruleset.
CREATE TABLE IF NOT EXISTS signals (
    series_id   TEXT NOT NULL REFERENCES series(series_id),
    obs_date    TEXT NOT NULL,
    ruleset     TEXT NOT NULL,             -- e.g. 'ma5_v1'
    signal      TEXT NOT NULL,             -- BUY | HOLD | SELL | NO_DATA
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (series_id, obs_date, ruleset)
);
