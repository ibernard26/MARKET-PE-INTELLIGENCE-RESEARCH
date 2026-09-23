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

-- Bitemporal research spine. Every fact carries THREE times:
--   valid time      (observation_timestamp / event_timestamp): when the fact was true
--                   or the event occurred;
--   known_at        : when the information became publicly knowable. Set from an
--                   explicit, reliable source publication timestamp; otherwise from
--                   source_timestamp; otherwise the ingestion time (live capture).
--                   A historical known time is NEVER inferred without support —
--                   an unsupported backfill is therefore invisible to past as-of reads.
--   ingestion_timestamp: when this system recorded it.
-- A point-in-time read as_of T admits a row only if valid_time <= T AND known_at <= T.
-- known_at_basis records which rule produced known_at (explicit|source_timestamp|ingestion).
--
-- Integrity is enforced at the DB layer, not only in application code:
--   * deal_id must reference deals(deal_id)  (FK + BEFORE INSERT trigger, so orphans
--     are rejected even when PRAGMA foreign_keys is off);
--   * rows are append-only: BEFORE UPDATE / BEFORE DELETE triggers abort.

-- Append-only market/deal observations. One row per (deal, valid moment, source).
CREATE TABLE IF NOT EXISTS deal_market_observations (
    deal_id                TEXT NOT NULL REFERENCES deals(deal_id),
    observation_timestamp  TEXT NOT NULL,   -- ISO8601 valid time
    source                 TEXT NOT NULL,   -- provenance (never NULL)
    target_price           REAL,            -- market print (never forward-filled)
    offer_price            REAL,            -- cash consideration per share (state term)
    unaffected_price       REAL,
    acquirer_price         REAL,            -- market print (never forward-filled)
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
    source_timestamp       TEXT,            -- when the source published it (if stated)
    known_at               TEXT NOT NULL,   -- when it became publicly knowable
    known_at_basis         TEXT NOT NULL CHECK (known_at_basis IN
                               ('explicit','source_timestamp','ingestion')),
    ingestion_timestamp    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    PRIMARY KEY (deal_id, observation_timestamp, source)
);
CREATE INDEX IF NOT EXISTS ix_dmo_deal  ON deal_market_observations(deal_id);
CREATE INDEX IF NOT EXISTS ix_dmo_ts    ON deal_market_observations(observation_timestamp);
CREATE INDEX IF NOT EXISTS ix_dmo_known ON deal_market_observations(known_at);

CREATE TRIGGER IF NOT EXISTS trg_dmo_fk BEFORE INSERT ON deal_market_observations
WHEN NOT EXISTS (SELECT 1 FROM deals WHERE deal_id = NEW.deal_id)
BEGIN SELECT RAISE(ABORT, 'orphan observation: deal_id not in deals'); END;
CREATE TRIGGER IF NOT EXISTS trg_dmo_no_update BEFORE UPDATE ON deal_market_observations
BEGIN SELECT RAISE(ABORT, 'deal_market_observations is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_dmo_no_delete BEFORE DELETE ON deal_market_observations
BEGIN SELECT RAISE(ABORT, 'deal_market_observations is append-only'); END;

-- Append-only deal lifecycle events.
CREATE TABLE IF NOT EXISTS deal_events (
    event_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    deal_id             TEXT NOT NULL REFERENCES deals(deal_id),
    event_timestamp     TEXT NOT NULL,      -- when the event occurred (valid time)
    event_type          TEXT NOT NULL,      -- see src/research/events.py EVENT_TYPES
    source              TEXT NOT NULL,      -- provenance (never NULL)
    source_timestamp    TEXT,
    known_at            TEXT NOT NULL,      -- when it became publicly knowable
    known_at_basis      TEXT NOT NULL CHECK (known_at_basis IN
                            ('explicit','source_timestamp','ingestion')),
    ingestion_timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    attributes          TEXT,               -- optional JSON blob
    UNIQUE (deal_id, event_timestamp, event_type, source)
);
CREATE INDEX IF NOT EXISTS ix_devents_deal  ON deal_events(deal_id);
CREATE INDEX IF NOT EXISTS ix_devents_ts    ON deal_events(event_timestamp);
CREATE INDEX IF NOT EXISTS ix_devents_known ON deal_events(known_at);

CREATE TRIGGER IF NOT EXISTS trg_dev_fk BEFORE INSERT ON deal_events
WHEN NOT EXISTS (SELECT 1 FROM deals WHERE deal_id = NEW.deal_id)
BEGIN SELECT RAISE(ABORT, 'orphan event: deal_id not in deals'); END;
CREATE TRIGGER IF NOT EXISTS trg_dev_no_update BEFORE UPDATE ON deal_events
BEGIN SELECT RAISE(ABORT, 'deal_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_dev_no_delete BEFORE DELETE ON deal_events
BEGIN SELECT RAISE(ABORT, 'deal_events is append-only'); END;

-- ---------------------------------------------------------------------------
-- Break-probability model registry + immutable predictions (break_logit_v1)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_registry (
    model_id               TEXT NOT NULL,
    model_version          TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    training_cutoff        TEXT NOT NULL,
    n_train                INTEGER NOT NULL,
    n_pos                  INTEGER NOT NULL,
    n_neg                  INTEGER NOT NULL,
    prevalence             REAL NOT NULL,
    hyperparameters        TEXT NOT NULL,   -- JSON
    calibration            TEXT NOT NULL,   -- JSON
    artifact               TEXT NOT NULL,   -- JSON (serialized model)
    fit_timestamp          TEXT NOT NULL,
    code_commit            TEXT NOT NULL,
    PRIMARY KEY (model_version, training_cutoff)
);
CREATE TRIGGER IF NOT EXISTS trg_mreg_no_update BEFORE UPDATE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_mreg_no_delete BEFORE DELETE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry is append-only'); END;

CREATE TABLE IF NOT EXISTS model_predictions (
    deal_id                TEXT NOT NULL REFERENCES deals(deal_id),
    as_of                  TEXT NOT NULL,   -- information date of the features
    p_break                REAL NOT NULL CHECK (p_break >= 0 AND p_break <= 1),
    model_version          TEXT NOT NULL,
    training_cutoff        TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    prediction_timestamp   TEXT NOT NULL,
    PRIMARY KEY (deal_id, as_of, model_version, training_cutoff),
    FOREIGN KEY (model_version, training_cutoff)
        REFERENCES model_registry(model_version, training_cutoff)
);
CREATE TRIGGER IF NOT EXISTS trg_mpred_model BEFORE INSERT ON model_predictions
WHEN NOT EXISTS (SELECT 1 FROM model_registry WHERE model_version = NEW.model_version
                 AND training_cutoff = NEW.training_cutoff)
BEGIN SELECT RAISE(ABORT, 'prediction references unregistered model'); END;
CREATE TRIGGER IF NOT EXISTS trg_mpred_lookahead BEFORE INSERT ON model_predictions
WHEN NEW.training_cutoff > NEW.as_of || 'T23:59:59.999999'
BEGIN SELECT RAISE(ABORT, 'model trained after prediction as_of (lookahead)'); END;
CREATE TRIGGER IF NOT EXISTS trg_mpred_no_update BEFORE UPDATE ON model_predictions
BEGIN SELECT RAISE(ABORT, 'model_predictions is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_mpred_no_delete BEFORE DELETE ON model_predictions
BEGIN SELECT RAISE(ABORT, 'model_predictions is immutable'); END;

-- Signals are recomputed, never hand-entered. Versioned by ruleset.
CREATE TABLE IF NOT EXISTS signals (
    series_id   TEXT NOT NULL REFERENCES series(series_id),
    obs_date    TEXT NOT NULL,
    ruleset     TEXT NOT NULL,             -- e.g. 'ma5_v1'
    signal      TEXT NOT NULL,             -- BUY | HOLD | SELL | NO_DATA
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (series_id, obs_date, ruleset)
);
