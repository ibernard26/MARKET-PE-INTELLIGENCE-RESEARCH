"""Deterministic dataset fingerprinting for reconstructible model results.

A model result must be reconstructible from code + model version + feature
schema + training cutoff + the exact training dataset. This module hashes a
canonical serialization of training rows with SHA-256 (stdlib only).
"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable, Optional, Sequence

from .dataset import FEATURE_SCHEMA_VERSION, FEATURES

# Sentinel string for missing feature values — must be stable across runs.
_NULL = "__NULL__"


def _canon_value(v) -> object:
    """Deterministic JSON-serializable representation of one feature value."""
    if v is None:
        return _NULL
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, float):
        # Use shortest round-trip repr; avoids locale / binary float churn in JSON.
        return float(format(v, ".17g"))
    return v


def canonicalize_training_rows(
    rows: Iterable[dict],
    feature_names: Optional[Sequence[str]] = None,
    feature_schema_version: str = FEATURE_SCHEMA_VERSION,
) -> list[dict]:
    """Return a deterministically ordered canonical row list for hashing."""
    names = list(feature_names) if feature_names is not None else list(FEATURES)
    canon = []
    for r in rows:
        x = r.get("x") or {}
        canon.append({
            "deal_id": r["deal_id"],
            "feature_as_of": r["feature_as_of"],
            "label": r["label"],
            "label_known_at": r.get("label_known_at"),
            "feature_schema_version": r.get("feature_schema_version", feature_schema_version),
            "feature_names": names,
            "feature_values": [_canon_value(x.get(n)) for n in names],
        })
    canon.sort(key=lambda row: (row["deal_id"], row["feature_as_of"], row["label"]))
    return canon


def dataset_fingerprint(
    rows: Iterable[dict],
    feature_names: Optional[Sequence[str]] = None,
    feature_schema_version: str = FEATURE_SCHEMA_VERSION,
) -> str:
    """SHA-256 hex digest of the canonical training-row serialization.

    Order of input rows does not affect the fingerprint. Changing any material
    field (deal_id, feature_as_of, label, label_known_at, schema, feature
    names, or feature values) changes the digest.
    """
    payload = canonicalize_training_rows(
        rows, feature_names=feature_names,
        feature_schema_version=feature_schema_version)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
