"""SQLite access. Thin on purpose -- no ORM, no magic."""
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
        conn.executemany(
            "INSERT OR IGNORE INTO series (series_id, label, unit, source) "
            "VALUES (?,?,?,'FRED')",
            [(sid, label, unit) for sid, (label, unit) in SERIES.items()],
        )
    return DB_PATH


def migrate_schema():
    """Bring an existing database up to the current schema. Idempotent.

    - prices.is_derived (fabrication ban support)
    - deals table replaced with the current ledger IF the old empty
      stub is present (refuses to drop a table containing rows).
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
