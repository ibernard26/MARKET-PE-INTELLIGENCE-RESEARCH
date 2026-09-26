"""SQLite access. Thin on purpose -- no ORM, no magic."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH, ROOT
from .ingest.market_series import ALL_SERIES as SERIES


@contextmanager
def connect():
    """Open the project SQLite DB with foreign keys ON; commits on success, always closes."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


_BITEMPORAL_TABLES = ("deal_market_observations", "deal_events")


def _upgrade_bitemporal_tables(conn):
    """Pre-bitemporal research tables (no known_at) are dropped IF EMPTY so the
    schema script can recreate them with known_at, FK and append-only triggers.
    A non-empty legacy table is never dropped or back-filled: its rows have no
    supported known time, so we refuse and require an explicit migration."""
    for t in _BITEMPORAL_TABLES:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        if cols and "known_at" not in cols:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            if n:
                raise RuntimeError(
                    f"{t} has {n} pre-bitemporal rows without known_at; refusing to "
                    "drop or infer known times — migrate explicitly")
            conn.execute(f"DROP TABLE {t}")
    # model tables from before the normalized-timestamp contract: recreate if empty
    for t in ("model_predictions", "model_registry"):
        r = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                         (t,)).fetchone()
        if r and "GLOB" not in r[0]:
            n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            if n:
                raise RuntimeError(f"{t} has {n} rows under the old temporal contract; "
                                   "refusing to drop — migrate explicitly")
            conn.execute(f"DROP TABLE {t}")


def init_db():
    """Create tables and seed the series registry. Safe to run repeatedly."""
    sql = (ROOT / "schema.sql").read_text()
    with connect() as conn:
        _upgrade_bitemporal_tables(conn)
        conn.executescript(sql)
        _upgrade_model_registry_columns(conn)
        _migrate_model_run_identity(conn)
        conn.executemany(
            "INSERT OR IGNORE INTO series (series_id, label, unit, source) "
            "VALUES (?,?,?,'FRED')",
            [(sid, label, unit) for sid, (label, unit) in SERIES.items()],
        )
    return DB_PATH


def _upgrade_model_registry_columns(conn):
    """PR #18 metadata columns (nullable ADD COLUMN; no history rewrite)."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(model_registry)")]
    if not cols:
        return
    for col, typ in (
        ("cohort_id", "TEXT"),
        ("cohort_version", "TEXT"),
        ("dataset_fingerprint", "TEXT"),
        ("sample_prevalence", "REAL"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE model_registry ADD COLUMN {col} {typ}")


def _registry_pk_is_model_run_id(conn) -> bool:
    rows = list(conn.execute("PRAGMA table_info(model_registry)"))
    if not rows:
        return False
    # r[5] is the PK ordinal (1-based); only model_run_id should be PK.
    pk = sorted(((r[5], r[1]) for r in rows if r[5]), key=lambda x: x[0])
    return [name for _, name in pk] == ["model_run_id"]


def _migrate_model_run_identity(conn):
    """Upgrade PR #18 (version,cutoff)-keyed registry to model_run_id PK.

    Preserves all historical registry and prediction rows. Assigns deterministic
    model_run_id values from existing metadata + artifact. Idempotent: a second
    call is a no-op when the PK is already model_run_id.
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(model_registry)")]
    if not cols:
        return
    if _registry_pk_is_model_run_id(conn):
        return

    from .model.registry import compute_model_run_id

    _upgrade_model_registry_columns(conn)
    old_reg = [dict(r) for r in conn.execute("SELECT * FROM model_registry")]
    pred_cols = [r[1] for r in conn.execute("PRAGMA table_info(model_predictions)")]
    old_pred = [dict(r) for r in conn.execute("SELECT * FROM model_predictions")] \
        if pred_cols else []

    # Map legacy (model_version, training_cutoff) -> model_run_id
    key_to_run = {}
    new_reg_rows = []
    for row in old_reg:
        artifact = json.loads(row["artifact"])
        hp = json.loads(row["hyperparameters"])
        cal = json.loads(row["calibration"])
        fp = row.get("dataset_fingerprint")
        if not fp:
            # Pre-fingerprint legacy row: stable stand-in from artifact bytes.
            fp = hashlib.sha256(
                ("legacy-missing-fp:" + row["artifact"]).encode("utf-8")
            ).hexdigest()
        sample_pi = row.get("sample_prevalence")
        if sample_pi is None:
            sample_pi = row["prevalence"]
        run_id = compute_model_run_id(
            model_id=row["model_id"],
            model_version=row["model_version"],
            feature_schema_version=row["feature_schema_version"],
            training_cutoff=row["training_cutoff"],
            cohort_id=row.get("cohort_id"),
            cohort_version=row.get("cohort_version"),
            dataset_fingerprint=fp,
            code_commit=row["code_commit"],
            hyperparameters=hp,
            calibration=cal,
            artifact=artifact,
        )
        key_to_run[(row["model_version"], row["training_cutoff"])] = run_id
        new_reg_rows.append({
            **row,
            "model_run_id": run_id,
            "dataset_fingerprint": fp,
            "sample_prevalence": sample_pi,
        })

    # Rebuild: SQLite cannot alter PRIMARY KEY in place. Data is copied fully;
    # this is not a destructive wipe of history.
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DROP TABLE IF EXISTS model_predictions")
    conn.execute("DROP TABLE IF EXISTS model_registry")
    conn.executescript("""
    CREATE TABLE model_registry (
        model_run_id           TEXT PRIMARY KEY,
        model_id               TEXT NOT NULL,
        model_version          TEXT NOT NULL,
        feature_schema_version TEXT NOT NULL,
        training_cutoff        TEXT NOT NULL CHECK (training_cutoff GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*'),
        n_train                INTEGER NOT NULL,
        n_pos                  INTEGER NOT NULL,
        n_neg                  INTEGER NOT NULL,
        prevalence             REAL NOT NULL,
        hyperparameters        TEXT NOT NULL,
        calibration            TEXT NOT NULL,
        artifact               TEXT NOT NULL,
        fit_timestamp          TEXT NOT NULL,
        code_commit            TEXT NOT NULL,
        cohort_id              TEXT,
        cohort_version         TEXT,
        dataset_fingerprint    TEXT NOT NULL,
        sample_prevalence      REAL NOT NULL
    );
    CREATE TRIGGER trg_mreg_no_update BEFORE UPDATE ON model_registry
    BEGIN SELECT RAISE(ABORT, 'model_registry is append-only'); END;
    CREATE TRIGGER trg_mreg_no_delete BEFORE DELETE ON model_registry
    BEGIN SELECT RAISE(ABORT, 'model_registry is append-only'); END;
    CREATE TABLE model_predictions (
        deal_id                TEXT NOT NULL REFERENCES deals(deal_id),
        as_of                  TEXT NOT NULL CHECK (as_of GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*'),
        p_break                REAL NOT NULL CHECK (p_break >= 0 AND p_break <= 1),
        model_run_id           TEXT NOT NULL REFERENCES model_registry(model_run_id),
        model_version          TEXT NOT NULL,
        training_cutoff        TEXT NOT NULL CHECK (training_cutoff GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]*'),
        feature_schema_version TEXT NOT NULL,
        prediction_timestamp   TEXT NOT NULL,
        PRIMARY KEY (deal_id, as_of, model_run_id)
    );
    CREATE TRIGGER trg_mpred_model BEFORE INSERT ON model_predictions
    WHEN NOT EXISTS (SELECT 1 FROM model_registry WHERE model_run_id = NEW.model_run_id)
    BEGIN SELECT RAISE(ABORT, 'prediction references unregistered model_run_id'); END;
    CREATE TRIGGER trg_mpred_lookahead BEFORE INSERT ON model_predictions
    WHEN NEW.training_cutoff > NEW.as_of
    BEGIN SELECT RAISE(ABORT, 'model trained after prediction as_of (lookahead)'); END;
    CREATE TRIGGER trg_mpred_no_update BEFORE UPDATE ON model_predictions
    BEGIN SELECT RAISE(ABORT, 'model_predictions is immutable'); END;
    CREATE TRIGGER trg_mpred_no_delete BEFORE DELETE ON model_predictions
    BEGIN SELECT RAISE(ABORT, 'model_predictions is immutable'); END;
    """)
    for row in new_reg_rows:
        conn.execute(
            """INSERT INTO model_registry (
                 model_run_id, model_id, model_version, feature_schema_version,
                 training_cutoff, n_train, n_pos, n_neg, prevalence, hyperparameters,
                 calibration, artifact, fit_timestamp, code_commit,
                 cohort_id, cohort_version, dataset_fingerprint, sample_prevalence)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row["model_run_id"], row["model_id"], row["model_version"],
             row["feature_schema_version"], row["training_cutoff"],
             row["n_train"], row["n_pos"], row["n_neg"], row["prevalence"],
             row["hyperparameters"], row["calibration"], row["artifact"],
             row["fit_timestamp"], row["code_commit"],
             row.get("cohort_id"), row.get("cohort_version"),
             row["dataset_fingerprint"], row["sample_prevalence"]))
    for p in old_pred:
        run_id = p.get("model_run_id") or key_to_run[(p["model_version"], p["training_cutoff"])]
        conn.execute(
            """INSERT INTO model_predictions (
                 deal_id, as_of, p_break, model_run_id, model_version,
                 training_cutoff, feature_schema_version, prediction_timestamp)
               VALUES (?,?,?,?,?,?,?,?)""",
            (p["deal_id"], p["as_of"], p["p_break"], run_id, p["model_version"],
             p["training_cutoff"], p["feature_schema_version"], p["prediction_timestamp"]))
    conn.execute("PRAGMA foreign_keys = ON")


def migrate_schema():
    """Bring an existing database up to the current schema. Idempotent.

    - prices.is_derived (fabrication ban support)
    - deals table replaced with the current ledger IF the old empty
      stub is present (refuses to drop a table containing rows).
    - model_registry PR #18 metadata columns
    - model_run_id primary identity (preserves populated history)
    """
    with connect() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(prices)")]
        if "is_derived" not in cols:
            conn.execute("ALTER TABLE prices ADD COLUMN is_derived INTEGER NOT NULL DEFAULT 0")
        dealcols = [r["name"] for r in conn.execute("PRAGMA table_info(deals)")]
        for coldef in ("offer_price REAL", "current_price REAL",
                       "unaffected_price REAL", "expected_close_date DATE"):
            name = coldef.split()[0]
            if dealcols and name not in dealcols:
                conn.execute(f"ALTER TABLE deals ADD COLUMN {coldef}")
        dcols = [r["name"] for r in conn.execute("PRAGMA table_info(deals)")]
        if dcols and "p_break" not in dcols:
            n = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
            if n:
                raise RuntimeError(f"deals has {n} rows in the old shape; refusing to drop")
            conn.execute("DROP TABLE deals")
    with connect() as conn:
        _upgrade_bitemporal_tables(conn)
        conn.executescript((ROOT / "schema.sql").read_text())
        _upgrade_model_registry_columns(conn)
        _migrate_model_run_identity(conn)


def upsert_prices(rows):
    """rows: iterable of (series_id, obs_date, close, provenance).

    Never overwrites a real observation with NULL -- a later run that returns
    no data must not erase what an earlier run captured.
    """
    rows = list(rows)
    with connect() as conn:
        conn.executemany(
            """INSERT INTO prices (series_id, obs_date, close, provenance)
               VALUES (?,?,?,?)
               ON CONFLICT(series_id, obs_date) DO UPDATE SET
                   close      = COALESCE(excluded.close, prices.close),
                   provenance = CASE WHEN excluded.close IS NOT NULL
                                     THEN excluded.provenance
                                     ELSE prices.provenance END,
                   ingested_at = datetime('now')""",
            rows,
        )
    return len(rows)


def coverage_report():
    """Trading days with no close, by series. This is the gap list."""
    sql = """
        SELECT s.series_id,
               COUNT(*) AS trading_days,
               SUM(CASE WHEN p.close IS NULL THEN 1 ELSE 0 END) AS missing
        FROM market_calendar c
        CROSS JOIN series s
        LEFT JOIN prices p
               ON p.series_id = s.series_id AND p.obs_date = c.obs_date
        WHERE c.is_trading = 1
        GROUP BY s.series_id
        ORDER BY missing DESC
    """
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def missing_dates(series_id):
    """Trading days on which `series_id` has no stored close (the gap list for one series)."""
    sql = """
        SELECT c.obs_date
        FROM market_calendar c
        LEFT JOIN prices p
               ON p.series_id = ? AND p.obs_date = c.obs_date
        WHERE c.is_trading = 1 AND p.close IS NULL
        ORDER BY c.obs_date
    """
    with connect() as conn:
        return [r["obs_date"] for r in conn.execute(sql, (series_id,))]
