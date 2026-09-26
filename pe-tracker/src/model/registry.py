"""Model registry and immutable predictions (append-only, DB-enforced).

Identity layers:
  model_id       — family (e.g. break_logit)
  model_version  — predictive specification (e.g. break_logit_v1)
  model_run_id   — one concrete fitted artifact (SHA-256 of run identity fields)

`prevalence` / `sample_prevalence` are SAMPLE class fractions, never population
break rates. See docs/MODEL_RUN_REGISTRY.md and docs/SAMPLING_FRAME.md.
"""
from __future__ import annotations

import hashlib
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


class RegistryError(ValueError):
    """Raised when registration metadata fails integrity checks."""


class AmbiguousModelRunError(LookupError):
    """Raised when a version+cutoff (or version-level) lookup matches multiple runs."""


def code_commit() -> str:
    """Git commit of the code that fit the model ('unknown' outside a repo)."""
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return "unknown"


def compute_model_run_id(
    *,
    model_id: str,
    model_version: str,
    feature_schema_version: str,
    training_cutoff: str,
    cohort_id: Optional[str],
    cohort_version: Optional[str],
    dataset_fingerprint: str,
    code_commit: str,
    hyperparameters: dict,
    calibration: dict,
    artifact: dict,
) -> str:
    """Deterministic SHA-256 identity of one fitted artifact.

    Timestamps alone are not scientific identity. The digest covers the
    specification, cohort, dataset, code, hyperparameters, calibration policy,
    and serialized artifact so the same logical fit always yields the same
    model_run_id (stdlib hashlib only).
    """
    payload = {
        "model_id": model_id,
        "model_version": model_version,
        "feature_schema_version": feature_schema_version,
        "training_cutoff": training_cutoff,
        "cohort_id": cohort_id,
        "cohort_version": cohort_version,
        "dataset_fingerprint": dataset_fingerprint,
        "code_commit": code_commit,
        "hyperparameters": hyperparameters,
        "calibration": calibration,
        "artifact": artifact,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _derive_counts(rows: list[dict]) -> tuple[int, int, int, float]:
    n = len(rows)
    if n == 0:
        raise RegistryError("refusing to register a model with zero training rows")
    n_pos = sum(1 for r in rows if r["label"] == 1)
    n_neg = sum(1 for r in rows if r["label"] == 0)
    if n_pos + n_neg != n:
        raise RegistryError("training rows must have binary labels 0/1 only")
    return n, n_pos, n_neg, n_pos / n


def _enforce_cohort(cohort: ModelCohort, rows: list[dict],
                    conn: sqlite3.Connection) -> None:
    """Require every training deal_id ∈ cohort (subset OK for chronological cutoffs)."""
    cohort.validate(conn)
    allowed = set(cohort.deal_ids)
    trained = {r["deal_id"] for r in rows}
    outside = sorted(trained - allowed)
    if outside:
        raise RegistryError(
            f"training deal_ids not in claimed cohort {cohort.cohort_id!r}: {outside}")


def _enforce_row_schema(rows: list[dict], cutoff: str) -> None:
    for r in rows:
        schema = r.get("feature_schema_version", FEATURE_SCHEMA_VERSION)
        if schema != FEATURE_SCHEMA_VERSION:
            raise RegistryError(
                f"row {r.get('deal_id')!r} feature_schema_version {schema!r} "
                f"!= registry schema {FEATURE_SCHEMA_VERSION!r}")
        if "cutoff" in r and normalize_as_of(r["cutoff"]) != normalize_as_of(cutoff):
            raise RegistryError(
                f"row {r.get('deal_id')!r} cutoff {r['cutoff']!r} != training_set cutoff")


def register_model(model: BreakModel, training_set: dict,
                   conn: sqlite3.Connection,
                   cohort: Optional[ModelCohort] = None,
                   fingerprint: Optional[str] = None) -> dict:
    """Append a fitted model plus verified training metadata to model_registry.

    Dataset fingerprint is always computed from training rows and is
    authoritative. A caller-supplied fingerprint must match exactly or
    registration fails. Cohort membership (when provided) must contain every
    training deal_id (training ⊆ cohort).
    """
    rows = list(training_set.get("rows") or [])
    n, n_pos, n_neg, sample_pi = _derive_counts(rows)
    if training_set.get("n") not in (None, n):
        raise RegistryError(f"training_set n={training_set.get('n')} != len(rows)={n}")
    if training_set.get("n_pos") not in (None, n_pos):
        raise RegistryError(
            f"training_set n_pos={training_set.get('n_pos')} != derived {n_pos}")
    if training_set.get("n_neg") not in (None, n_neg):
        raise RegistryError(
            f"training_set n_neg={training_set.get('n_neg')} != derived {n_neg}")

    cutoff = normalize_as_of(training_set["cutoff"])
    _enforce_row_schema(rows, training_set["cutoff"])
    computed_fp = dataset_fingerprint(rows)
    if fingerprint is not None and fingerprint != computed_fp:
        raise RegistryError(
            f"supplied dataset_fingerprint {fingerprint!r} != computed {computed_fp!r}")

    if cohort is not None:
        _enforce_cohort(cohort, rows, conn)

    artifact = model.to_dict()
    commit = code_commit()
    hp = model.hp
    cal = model.calibration
    run_id = compute_model_run_id(
        model_id=MODEL_ID, model_version=MODEL_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        training_cutoff=cutoff,
        cohort_id=None if cohort is None else cohort.cohort_id,
        cohort_version=None if cohort is None else cohort.cohort_version,
        dataset_fingerprint=computed_fp, code_commit=commit,
        hyperparameters=hp, calibration=cal, artifact=artifact)

    meta = {
        "model_run_id": run_id,
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "training_cutoff": cutoff,
        "n_train": n,
        "n_pos": n_pos,
        "n_neg": n_neg,
        "prevalence": sample_pi,
        "sample_prevalence": sample_pi,
        "hyperparameters": hp,
        "calibration": cal,
        "fit_timestamp": now_iso(),
        "code_commit": commit,
        "cohort_id": None if cohort is None else cohort.cohort_id,
        "cohort_version": None if cohort is None else cohort.cohort_version,
        "dataset_fingerprint": computed_fp,
    }
    conn.execute(
        """INSERT INTO model_registry (
             model_run_id, model_id, model_version, feature_schema_version,
             training_cutoff, n_train, n_pos, n_neg, prevalence, hyperparameters,
             calibration, artifact, fit_timestamp, code_commit,
             cohort_id, cohort_version, dataset_fingerprint, sample_prevalence)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (meta["model_run_id"], meta["model_id"], meta["model_version"],
         meta["feature_schema_version"], meta["training_cutoff"], n, n_pos, n_neg,
         meta["prevalence"], json.dumps(hp, sort_keys=True),
         json.dumps(cal, sort_keys=True), json.dumps(artifact, sort_keys=True),
         meta["fit_timestamp"], meta["code_commit"],
         meta["cohort_id"], meta["cohort_version"], meta["dataset_fingerprint"],
         meta["sample_prevalence"]))
    return meta


def load_model_run(model_run_id: str, conn: sqlite3.Connection) -> BreakModel:
    """Reload the exact fitted artifact identified by model_run_id."""
    r = conn.execute(
        "SELECT artifact FROM model_registry WHERE model_run_id = ?",
        (model_run_id,)).fetchone()
    if r is None:
        raise KeyError(model_run_id)
    return BreakModel.from_dict(json.loads(r[0]))


def load_model(model_version: str, training_cutoff: str,
               conn: sqlite3.Connection) -> BreakModel:
    """Legacy lookup by (version, cutoff).

    Succeeds only when exactly one registered run matches. Multiple matches
    raise AmbiguousModelRunError — never silently LIMIT 1.
    """
    rows = conn.execute(
        "SELECT model_run_id, artifact FROM model_registry "
        "WHERE model_version = ? AND training_cutoff = ? "
        "ORDER BY model_run_id",
        (model_version, normalize_as_of(training_cutoff))).fetchall()
    if not rows:
        raise KeyError((model_version, training_cutoff))
    if len(rows) > 1:
        ids = [r["model_run_id"] for r in rows]
        raise AmbiguousModelRunError(
            f"multiple model_run_id values for "
            f"({model_version!r}, {normalize_as_of(training_cutoff)!r}): {ids}; "
            f"use load_model_run(model_run_id)")
    return BreakModel.from_dict(json.loads(rows[0]["artifact"]))


def _resolve_run(conn: sqlite3.Connection, *, model_run_id: Optional[str],
                 model_version: str, training_cutoff: str) -> dict:
    if model_run_id is not None:
        r = conn.execute(
            "SELECT * FROM model_registry WHERE model_run_id = ?",
            (model_run_id,)).fetchone()
        if r is None:
            raise KeyError(model_run_id)
        return dict(r)
    rows = conn.execute(
        "SELECT * FROM model_registry WHERE model_version = ? AND training_cutoff = ? "
        "ORDER BY model_run_id",
        (model_version, normalize_as_of(training_cutoff))).fetchall()
    if not rows:
        raise KeyError((model_version, training_cutoff))
    if len(rows) > 1:
        ids = [r["model_run_id"] for r in rows]
        raise AmbiguousModelRunError(
            f"multiple model_run_id values for "
            f"({model_version!r}, {normalize_as_of(training_cutoff)!r}): {ids}; "
            f"pass model_run_id explicitly")
    return dict(rows[0])


def record_prediction(deal_id: str, as_of: str, p_break: float, training_cutoff: str,
                      conn: sqlite3.Connection, model_version: str = MODEL_VERSION,
                      model_run_id: Optional[str] = None) -> dict:
    """Immutable prediction referencing an exact model_run_id.

    If model_run_id is omitted, resolves the unique run for
    (model_version, training_cutoff) or raises AmbiguousModelRunError.
    Denormalized version/cutoff/schema are copied from the registered run;
    the DB rejects training_cutoff > as_of (lookahead).
    """
    run = _resolve_run(conn, model_run_id=model_run_id, model_version=model_version,
                       training_cutoff=training_cutoff)
    # Prefer the run's authoritative cutoff for the lookahead contract.
    row = {
        "deal_id": deal_id,
        "as_of": normalize_as_of(as_of),
        "p_break": float(p_break),
        "model_run_id": run["model_run_id"],
        "model_version": run["model_version"],
        "training_cutoff": run["training_cutoff"],
        "feature_schema_version": run["feature_schema_version"],
        "prediction_timestamp": now_iso(),
    }
    conn.execute(
        "INSERT INTO model_predictions (deal_id, as_of, p_break, model_run_id, "
        "model_version, training_cutoff, feature_schema_version, prediction_timestamp) "
        "VALUES (:deal_id, :as_of, :p_break, :model_run_id, :model_version, "
        ":training_cutoff, :feature_schema_version, :prediction_timestamp)", row)
    return row


def prediction_as_of(deal_id: str, as_of: str, conn: sqlite3.Connection,
                     model_version: str = MODEL_VERSION,
                     model_run_id: Optional[str] = None) -> Optional[dict]:
    """Latest stored prediction knowable at `as_of` for a specific run.

    Prefer `model_run_id`. If only `model_version` is given and more than one
    run has admissible predictions for the deal, raise AmbiguousModelRunError
    rather than mixing experimental fits.
    """
    t = normalize_as_of(as_of)
    if model_run_id is not None:
        r = conn.execute(
            "SELECT * FROM model_predictions WHERE deal_id = ? AND model_run_id = ? "
            "AND as_of <= ? ORDER BY as_of DESC LIMIT 1",
            (deal_id, model_run_id, t)).fetchone()
        return dict(r) if r else None

    runs = [row[0] for row in conn.execute(
        "SELECT DISTINCT model_run_id FROM model_predictions "
        "WHERE deal_id = ? AND model_version = ? AND as_of <= ?",
        (deal_id, model_version, t)).fetchall()]
    if not runs:
        return None
    if len(runs) > 1:
        raise AmbiguousModelRunError(
            f"multiple model_run_id values have predictions for deal {deal_id!r} "
            f"under model_version {model_version!r}: {sorted(runs)}; "
            f"pass model_run_id explicitly")
    r = conn.execute(
        "SELECT * FROM model_predictions WHERE deal_id = ? AND model_run_id = ? "
        "AND as_of <= ? ORDER BY as_of DESC LIMIT 1",
        (deal_id, runs[0], t)).fetchone()
    return dict(r) if r else None
