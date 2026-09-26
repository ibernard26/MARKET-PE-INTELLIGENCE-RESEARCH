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

-- Append-only, bitemporal market observations (FRED). The legacy `prices` table
-- keeps the current value per (series, date) for the existing signal code; this
-- table keeps EVERY distinct value we ever saw, with when it was knowable.
--   obs_date       valid time (the session / observation date)
--   value          NULL = FRED reported "." (missing) — never filled
--   realtime_start FRED/ALFRED vintage start date, when requested
--   known_at       when the value was knowable:
--                    'fred_first_release' -> ALFRED initial-release vintage date,
--                                            stored as END of that day (time of day
--                                            is not published, so we are conservative)
--                    'ingestion'           -> the moment we fetched it (live capture)
--   A historical publication time is never inferred beyond these two rules.
CREATE TABLE IF NOT EXISTS market_observations (
    series_id           TEXT NOT NULL,
    obs_date            TEXT NOT NULL,
    value               REAL,
    source              TEXT NOT NULL,          -- 'FRED'
    source_identifier   TEXT NOT NULL,          -- e.g. 'FRED:SP500'
    realtime_start      TEXT,
    realtime_end        TEXT,
    known_at            TEXT NOT NULL,
    known_at_basis      TEXT NOT NULL CHECK (known_at_basis IN ('fred_first_release','ingestion')),
    ingestion_timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    PRIMARY KEY (series_id, obs_date, known_at)
);
CREATE INDEX IF NOT EXISTS ix_mobs_series_date ON market_observations(series_id, obs_date);
CREATE TRIGGER IF NOT EXISTS trg_mobs_no_update BEFORE UPDATE ON market_observations
BEGIN SELECT RAISE(ABORT, 'market_observations is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_mobs_no_delete BEFORE DELETE ON market_observations
BEGIN SELECT RAISE(ABORT, 'market_observations is append-only'); END;

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
    training_cutoff        TEXT NOT NULL CHECK (training_cutoff GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*'),
    n_train                INTEGER NOT NULL,
    n_pos                  INTEGER NOT NULL,
    n_neg                  INTEGER NOT NULL,
    -- Legacy column name. Value is SAMPLE prevalence (n_pos/n_train), never a
    -- population break rate. Prefer sample_prevalence for new readers.
    prevalence             REAL NOT NULL,
    hyperparameters        TEXT NOT NULL,   -- JSON
    calibration            TEXT NOT NULL,   -- JSON
    artifact               TEXT NOT NULL,   -- JSON (serialized model)
    fit_timestamp          TEXT NOT NULL,
    code_commit            TEXT NOT NULL,
    cohort_id              TEXT,            -- optional; NULL = unspecified cohort
    cohort_version         TEXT,
    dataset_fingerprint    TEXT,            -- SHA-256 of canonical training rows
    sample_prevalence      REAL,            -- n_pos/n_train; not a population rate
    PRIMARY KEY (model_version, training_cutoff)
);
CREATE TRIGGER IF NOT EXISTS trg_mreg_no_update BEFORE UPDATE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_mreg_no_delete BEFORE DELETE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry is append-only'); END;

CREATE TABLE IF NOT EXISTS model_predictions (
    deal_id                TEXT NOT NULL REFERENCES deals(deal_id),
    -- Temporal contract: as_of and training_cutoff are normalized ISO timestamps
    -- (a bare date is stored as end-of-day by src/model/registry.py), so the
    -- lookahead check is a plain comparison valid for date AND timestamp inputs.
    as_of                  TEXT NOT NULL CHECK (as_of GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*'),  -- information time
    p_break                REAL NOT NULL CHECK (p_break >= 0 AND p_break <= 1),
    model_version          TEXT NOT NULL,
    training_cutoff        TEXT NOT NULL CHECK (training_cutoff GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*'),
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
WHEN NEW.training_cutoff > NEW.as_of
BEGIN SELECT RAISE(ABORT, 'model trained after prediction as_of (lookahead)'); END;
CREATE TRIGGER IF NOT EXISTS trg_mpred_no_update BEFORE UPDATE ON model_predictions
BEGIN SELECT RAISE(ABORT, 'model_predictions is immutable'); END;
CREATE TRIGGER IF NOT EXISTS trg_mpred_no_delete BEFORE DELETE ON model_predictions
BEGIN SELECT RAISE(ABORT, 'model_predictions is immutable'); END;

-- ---------------------------------------------------------------------------
-- Record-level provenance for historical ingestion. Answers "where did this exact
-- label or feature value come from?" One row per written fact (append-only).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS record_provenance (
    provenance_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type         TEXT NOT NULL CHECK (record_type IN ('deal','observation','event')),
    deal_id             TEXT NOT NULL REFERENCES deals(deal_id),
    record_key          TEXT NOT NULL,     -- e.g. 'event:closing:2025-05-01T16:02:11'
    field               TEXT,              -- optional: the specific field sourced
    source_name         TEXT NOT NULL,     -- e.g. 'SEC EDGAR'
    source_identifier   TEXT NOT NULL,     -- URL or URI of the exact document
    accession_number    TEXT,              -- SEC accession, when applicable
    docket_reference    TEXT,              -- regulator docket / case number
    company_identifier  TEXT,              -- e.g. CIK
    source_timestamp    TEXT,
    known_at            TEXT NOT NULL,
    ingestion_timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
CREATE INDEX IF NOT EXISTS ix_prov_deal ON record_provenance(deal_id);
CREATE TRIGGER IF NOT EXISTS trg_prov_no_update BEFORE UPDATE ON record_provenance
BEGIN SELECT RAISE(ABORT, 'record_provenance is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trg_prov_no_delete BEFORE DELETE ON record_provenance
BEGIN SELECT RAISE(ABORT, 'record_provenance is append-only'); END;

-- Signals are recomputed, never hand-entered. Versioned by ruleset.
CREATE TABLE IF NOT EXISTS signals (
    series_id   TEXT NOT NULL REFERENCES series(series_id),
    obs_date    TEXT NOT NULL,
    ruleset     TEXT NOT NULL,             -- e.g. 'ma5_v1'
    signal      TEXT NOT NULL,             -- BUY | HOLD | SELL | NO_DATA
    computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (series_id, obs_date, ruleset)
);
