"""Experiment-identity / model_run_id registry hardening (synthetic only)."""
import json
import sqlite3

import pytest

from src.db import _migrate_model_run_identity, _upgrade_model_registry_columns
from src.model.cohort import ModelCohort
from src.model.dataset import build_training_set
from src.model.fingerprint import dataset_fingerprint
from src.model.logistic import BreakModel, MODEL_VERSION
from src.model.registry import (
    AmbiguousModelRunError,
    RegistryError,
    load_model,
    load_model_run,
    prediction_as_of,
    record_prediction,
    register_model,
)
from tests.model_fixtures import mem, synthetic_book


def _fit(conn, cutoff="2025-06-30"):
    ts = build_training_set(cutoff, conn)
    m = BreakModel().fit([r["x"] for r in ts["rows"]], [r["label"] for r in ts["rows"]])
    return m, ts


def test_two_runs_same_version_cutoff_coexist():
    c = synthetic_book(mem(), n=60, seed=1)
    m, ts = _fit(c)
    ids = sorted({r["deal_id"] for r in ts["rows"]})
    cohort_a = ModelCohort.from_ids(
        "cohort_a", "v1", "A", "unit_test_fixture", False, False, ids, "deadbeef")
    cohort_b = ModelCohort.from_ids(
        "cohort_b", "v1", "B", "unit_test_fixture", False, False, ids[:-1], "deadbeef")
    # Restrict training rows for B so fingerprints differ
    ts_b = {**ts, "rows": [r for r in ts["rows"] if r["deal_id"] in set(ids[:-1])],
            "n": len(ids) - 1,
            "n_pos": sum(r["label"] for r in ts["rows"] if r["deal_id"] in set(ids[:-1])),
            "n_neg": 0}
    ts_b["n_neg"] = ts_b["n"] - ts_b["n_pos"]
    meta_a = register_model(m, ts, c, cohort=cohort_a)
    m_b = BreakModel().fit([r["x"] for r in ts_b["rows"]], [r["label"] for r in ts_b["rows"]])
    meta_b = register_model(m_b, ts_b, c, cohort=cohort_b)
    assert meta_a["model_version"] == meta_b["model_version"] == MODEL_VERSION
    assert meta_a["training_cutoff"] == meta_b["training_cutoff"]
    assert meta_a["model_run_id"] != meta_b["model_run_id"]
    assert meta_a["dataset_fingerprint"] != meta_b["dataset_fingerprint"]
    assert load_model_run(meta_a["model_run_id"], c).to_dict() == m.to_dict()
    assert load_model_run(meta_b["model_run_id"], c).to_dict() == m_b.to_dict()


def test_legacy_load_model_ambiguous_when_multiple_runs():
    c = synthetic_book(mem(), n=60, seed=2)
    m, ts = _fit(c)
    ids = sorted({r["deal_id"] for r in ts["rows"]})
    ca = ModelCohort.from_ids("ca", "v1", "", "unit_test_fixture", False, False, ids, "x")
    cb = ModelCohort.from_ids("cb", "v1", "", "unit_test_fixture", False, False, ids, "x")
    register_model(m, ts, c, cohort=ca)
    register_model(m, ts, c, cohort=cb)
    with pytest.raises(AmbiguousModelRunError):
        load_model(MODEL_VERSION, "2025-06-30", c)


def test_cohort_mismatch_rejected():
    c = synthetic_book(mem(), n=40, seed=3)
    m, ts = _fit(c)
    # Cohort missing one of the training deals
    ids = sorted({r["deal_id"] for r in ts["rows"]})
    bad = ModelCohort.from_ids(
        "bad", "v1", "", "unit_test_fixture", False, False, ids[1:], "x")
    with pytest.raises(RegistryError, match="not in claimed cohort"):
        register_model(m, ts, c, cohort=bad)


def test_fingerprint_mismatch_rejected_match_accepted():
    c = synthetic_book(mem(), n=40, seed=4)
    m, ts = _fit(c)
    with pytest.raises(RegistryError, match="dataset_fingerprint"):
        register_model(m, ts, c, fingerprint="0" * 64)
    fp = dataset_fingerprint(ts["rows"])
    meta = register_model(m, ts, c, fingerprint=fp)
    assert meta["dataset_fingerprint"] == fp


def test_prediction_fk_and_immutability_and_lookahead():
    c = synthetic_book(mem(), n=60, seed=5)
    m, ts = _fit(c)
    meta = register_model(m, ts, c)
    record_prediction("S050", "2025-07-15", 0.12, "2025-06-30", c,
                      model_run_id=meta["model_run_id"])
    with pytest.raises(sqlite3.IntegrityError):
        record_prediction("S050", "2025-07-15", 0.50, "2025-06-30", c,
                          model_run_id=meta["model_run_id"])
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("DELETE FROM model_predictions")
    with pytest.raises(sqlite3.IntegrityError):
        record_prediction("S001", "2025-01-15", 0.1, "2025-06-30", c,
                          model_run_id=meta["model_run_id"])
    with pytest.raises(KeyError):
        record_prediction("S050", "2025-08-01", 0.1, "2099-01-01", c)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute(
            "INSERT INTO model_predictions (deal_id, as_of, p_break, model_run_id, "
            "model_version, training_cutoff, feature_schema_version, prediction_timestamp) "
            "VALUES ('S050','2025-08-01T23:59:59.999999',0.1,?,?,?,?,?)",
            ("no_such_run", MODEL_VERSION, meta["training_cutoff"], "fs_v1", "t"))


def test_prediction_as_of_requires_run_when_multiple():
    c = synthetic_book(mem(), n=60, seed=6)
    m, ts = _fit(c)
    ids = sorted({r["deal_id"] for r in ts["rows"]})
    ca = ModelCohort.from_ids("p_a", "v1", "", "unit_test_fixture", False, False, ids, "x")
    cb = ModelCohort.from_ids("p_b", "v1", "", "unit_test_fixture", False, False, ids, "x")
    a = register_model(m, ts, c, cohort=ca)
    b = register_model(m, ts, c, cohort=cb)
    record_prediction("S050", "2025-07-15", 0.1, "2025-06-30", c, model_run_id=a["model_run_id"])
    record_prediction("S050", "2025-07-15", 0.2, "2025-06-30", c, model_run_id=b["model_run_id"])
    with pytest.raises(AmbiguousModelRunError):
        prediction_as_of("S050", "2025-08-01", c, model_version=MODEL_VERSION)
    pr = prediction_as_of("S050", "2025-08-01", c, model_run_id=a["model_run_id"])
    assert pr["p_break"] == 0.1


_PR18_REGISTRY_DDL = """
CREATE TABLE model_registry (
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
    dataset_fingerprint    TEXT,
    sample_prevalence      REAL,
    PRIMARY KEY (model_version, training_cutoff)
);
CREATE TRIGGER trg_mreg_no_update BEFORE UPDATE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry is append-only'); END;
CREATE TRIGGER trg_mreg_no_delete BEFORE DELETE ON model_registry
BEGIN SELECT RAISE(ABORT, 'model_registry is append-only'); END;
"""


def test_pr18_populated_registry_migrates_to_model_run_id():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    # Minimal deals table for prediction FK in rebuilt schema
    c.execute("CREATE TABLE deals (deal_id TEXT PRIMARY KEY)")
    c.execute("INSERT INTO deals (deal_id) VALUES ('S050')")
    c.executescript(_PR18_REGISTRY_DDL)
    # Build a real fitted artifact so load_model_run works after migration.
    live = synthetic_book(mem(), n=40, seed=99)
    m, ts = _fit(live)
    art = m.to_dict()
    c.execute(
        """INSERT INTO model_registry
           (model_id, model_version, feature_schema_version, training_cutoff,
            n_train, n_pos, n_neg, prevalence, hyperparameters, calibration,
            artifact, fit_timestamp, code_commit, cohort_id, cohort_version,
            dataset_fingerprint, sample_prevalence)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("break_logit", "break_logit_v1", "fs_v1", "2025-01-01T23:59:59.999999",
         ts["n"], ts["n_pos"], ts["n_neg"], ts["n_pos"] / ts["n"],
         json.dumps(m.hp, sort_keys=True),
         json.dumps(m.calibration, sort_keys=True),
         json.dumps(art, sort_keys=True), "2025-01-02T00:00:00", "legacycommit",
         "cohort_x", "v1", "a" * 64, ts["n_pos"] / ts["n"]))
    before = dict(c.execute("SELECT * FROM model_registry").fetchone())
    assert "model_run_id" not in before

    _upgrade_model_registry_columns(c)
    _migrate_model_run_identity(c)
    after = dict(c.execute("SELECT * FROM model_registry").fetchone())
    assert after["model_run_id"]
    assert len(after["model_run_id"]) == 64
    assert after["artifact"] == before["artifact"]
    assert after["n_train"] == before["n_train"]
    assert after["dataset_fingerprint"] == before["dataset_fingerprint"]
    assert after["sample_prevalence"] == before["sample_prevalence"]
    assert load_model_run(after["model_run_id"], c)  # loadable

    # idempotent
    snap = [dict(r) for r in c.execute("SELECT * FROM model_registry")]
    _migrate_model_run_identity(c)
    snap2 = [dict(r) for r in c.execute("SELECT * FROM model_registry")]
    assert snap2 == snap
    assert c.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 1

    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE model_registry SET n_train = 0")
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("DELETE FROM model_registry")


def test_register_rejects_empty_training_rows():
    c = mem()
    m = BreakModel()
    # Unfitted model + empty rows
    with pytest.raises(RegistryError, match="zero training rows"):
        register_model(m, {"cutoff": "2025-06-30", "rows": [], "n": 0, "n_pos": 0, "n_neg": 0}, c)
