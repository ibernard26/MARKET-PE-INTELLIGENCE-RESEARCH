"""Model registry and immutable predictions (append-only, DB-enforced)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from typing import Optional

from ..config import ROOT
from ..research.bitemporal import normalize_as_of, now_iso
from .cohort import ModelCohort
from .dataset import FEATURE_SCHEMA_VERSION
from .fingerprint import dataset_fingerprint
from .logistic import MODEL_ID, MODEL_VERSION, BreakModel


def code_commit() -> str:
    """Git commit of the code that fit the model ('unknown' outside a repo)."""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def register_model(model: BreakModel, training_set: dict,
                   conn: sqlite3.Connection,
                   cohort: Optional[ModelCohort] = None,
                   fingerprint: Optional[str] = None) -> dict:
    """Append a fitted model plus its training metadata to model_registry.

    `prevalence` / `sample_prevalence` record SAMPLE class prevalence
    (n_pos / n_train). They are never a population break rate.
    """
    n, n_pos = training_set["n"], training_set["n_pos"]
    sample_pi = n_pos / n
    rows = training_set.get("rows") or []
    fp = fingerprint if fingerprint is not None else (
        dataset_fingerprint(rows) if rows else None)
    if cohort is not None:
        cohort.validate(conn)
    meta = {"model_id": MODEL_ID, "model_version": MODEL_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "training_cutoff": normalize_as_of(training_set["cutoff"]), "n_train": n,
            "n_pos": n_pos, "n_neg": n - n_pos,
            "prevalence": sample_pi,
            "sample_prevalence": sample_pi,
            "hyperparameters": model.hp, "calibration": model.calibration,
            "fit_timestamp": now_iso(), "code_commit": code_commit(),
            "cohort_id": None if cohort is None else cohort.cohort_id,
            "cohort_version": None if cohort is None else cohort.cohort_version,
            "dataset_fingerprint": fp}
    conn.execute(
        """INSERT INTO model_registry (model_id, model_version, feature_schema_version,
           training_cutoff, n_train, n_pos, n_neg, prevalence, hyperparameters,
           calibration, artifact, fit_timestamp, code_commit,
           cohort_id, cohort_version, dataset_fingerprint, sample_prevalence)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (meta["model_id"], meta["model_version"], meta["feature_schema_version"],
         meta["training_cutoff"], n, n_pos, n - n_pos, meta["prevalence"],
         json.dumps(model.hp, sort_keys=True), json.dumps(model.calibration, sort_keys=True),
         json.dumps(model.to_dict(), sort_keys=True), meta["fit_timestamp"],
         meta["code_commit"],
         meta["cohort_id"], meta["cohort_version"], meta["dataset_fingerprint"],
         meta["sample_prevalence"]))
    return meta


def load_model(model_version: str, training_cutoff: str,
               conn: sqlite3.Connection) -> BreakModel:
    """Reload a registered model by (version, training cutoff)."""
    r = conn.execute("SELECT artifact FROM model_registry WHERE model_version = ? "
                     "AND training_cutoff = ?",
                     (model_version, normalize_as_of(training_cutoff))).fetchone()
    if r is None:
        raise KeyError((model_version, training_cutoff))
    return BreakModel.from_dict(json.loads(r[0]))


def record_prediction(deal_id: str, as_of: str, p_break: float, training_cutoff: str,
                      conn: sqlite3.Connection, model_version: str = MODEL_VERSION) -> dict:
    """Immutable prediction. `as_of` (information time) and `training_cutoff` are
    normalized to ISO timestamps; a bare date means end of that day. The DB
    rejects training_cutoff > as_of (lookahead) for either input form."""
    row = {"deal_id": deal_id, "as_of": normalize_as_of(as_of), "p_break": float(p_break),
           "model_version": model_version,
           "training_cutoff": normalize_as_of(training_cutoff),
           "feature_schema_version": FEATURE_SCHEMA_VERSION,
           "prediction_timestamp": now_iso()}
    conn.execute(
        "INSERT INTO model_predictions (deal_id, as_of, p_break, model_version, "
        "training_cutoff, feature_schema_version, prediction_timestamp) "
        "VALUES (:deal_id, :as_of, :p_break, :model_version, :training_cutoff, "
        ":feature_schema_version, :prediction_timestamp)", row)
    return row


def prediction_as_of(deal_id: str, as_of: str, conn: sqlite3.Connection,
                     model_version: str = MODEL_VERSION) -> Optional[dict]:
    """Latest stored prediction whose information date is on/before `as_of`
    (contemporaneous p_break for the backtester)."""
    r = conn.execute(
        "SELECT * FROM model_predictions WHERE deal_id = ? AND model_version = ? "
        "AND as_of <= ? ORDER BY as_of DESC, training_cutoff DESC LIMIT 1",
        (deal_id, model_version, normalize_as_of(as_of))).fetchone()
    return dict(r) if r else None
