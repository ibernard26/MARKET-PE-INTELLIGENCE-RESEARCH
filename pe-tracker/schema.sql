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
  offer_price     REAL,           -- arb: per-share offer (NULL if n/a)
  current_price   REAL,           -- arb: live quote (NULL = awaiting_quote; illustrative in seed)
  unaffected_price REAL,          -- arb: pre-announcement price
  expected_close_date DATE,       -- arb: expected close (point-in-time horizon)
  model_version   TEXT,
  source_note     TEXT
);
CREATE INDEX IF NOT EXISTS ix_deals_status ON deals(status);
CREATE INDEX IF NOT EXISTS ix_deals_date   ON deals(announce_date);

-- ---------------------------------------------------------------------------
-- Historical point-in-time research spine (feature/historical-arb-research-engine)
-- ---------------------------------------------------------------------------

-- Append-only market/deal observations. One row per (deal, as-of moment, source).
-- Historical observations are NEVER overwritten (enforced in src/research/observations.py).
-- observation_timestamp = the moment the fact was true (business/valid time);
-- ingestion_timestamp    = when we recorded it (system time). Kept distinct so a
-- point-in-time read `as_of D` uses only observation_timestamp <= D.
CREATE TABLE IF NOT EXISTS deal_market_observations (
    deal_id                TEXT NOT NULL,
    observation_timestamp  TEXT NOT NULL,   -- ISO8601 business/valid time
    source                 TEXT NOT NULL,   -- provenance (never NULL)
    target_price           REAL,
    offer_price            REAL,
    unaffected_price       REAL,
    acquirer_price         REAL,
    announce_date          TEXT,
    expected_close_date    TEXT,
    resolution_date        TEXT,
    status                 TEXT,            -- announced|pending|closed|broken|withdrawn|superseded
    deal_type              TEXT,            -- strategic|LBO|take_private|JV|financing
    consideration_type     TEXT,            -- cash|stock|mixed
    exchange_ratio         REAL,            -- shares of acquirer per target share (stock/mixed)
    deal_value_usd_mm      REAL,
    sector                 TEXT,
    geography              TEXT,
    sponsor                TEXT,
    regulatory_attrs       TEXT,            -- JSON blob (antitrust/CFIUS/CMA/EU exposure ...)
    financing_attrs        TEXT,            -- JSON blob (financing condition/secured ...)
    shareholder_vote_state TEXT,            -- none|required_pending|approved|rejected
    regulatory_milestones  TEXT,            -- JSON blob (HSR/second_request/clearance ...)
    source_timestamp       TEXT,            -- when the source published/observed it
    ingestion_timestamp    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (deal_id, observation_timestamp, source)
);
CREATE INDEX IF NOT EXISTS ix_dmo_deal ON deal_market_observations(deal_id);
CREATE INDEX IF NOT EXISTS ix_dmo_ts   ON deal_market_observations(observation_timestamp);

-- Append-only deal lifecycle events. Preserves chronology for reconstructing
-- exactly what was knowable at any historical date.
CREATE TABLE IF NOT EXISTS deal_events (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id             TEXT NOT NULL,
    event_timestamp     TEXT NOT NULL,      -- when the event occurred (valid time)
    event_type          TEXT NOT NULL,      -- see src/research/events.py EVENT_TYPES
    source              TEXT NOT NULL,      -- provenance (never NULL)
    source_timestamp    TEXT,
    ingestion_timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    attributes          TEXT,               -- optional JSON blob
    UNIQUE (deal_id, event_timestamp, event_type, source)
);
CREATE INDEX IF NOT EXISTS ix_devents_deal ON deal_events(deal_id);
CREATE INDEX IF NOT EXISTS ix_devents_ts   ON deal_events(event_timestamp);

-- Signals are recomputed, never hand-entered. Versioned by ruleset.
CREATE TABLE IF NOT EXISTS signals (
    series_id   TEXT NOT NULL REFERENCES series(series_id),
    obs_date    TEXT NOT NULL,
    ruleset     TEXT NOT NULL,             -- e.g. 'ma5_v1'
    signal      TEXT NOT NULL,             -- BUY | HOLD | SELL | NO_DATA
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (series_id, obs_date, ruleset)
);
