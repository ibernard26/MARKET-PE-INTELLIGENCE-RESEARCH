"""spread_stress_v1 logistic challenger (separate from break_logit_v1)."""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..logistic import BreakModel, InsufficientDataError, HYPERPARAMETERS
from .features import FEATURE_SCHEMA_VERSION, SPREAD_STRESS_FEATURES

MODEL_ID = "spread_stress"
MODEL_VERSION = "spread_stress_v1"


class SpreadStressModel(BreakModel):
    """L2 logistic on fs_spread_stress_v1 features only.

    Reuses BreakModel's preprocessing / serialization mechanics so registry
    storage stays compatible, but pins a distinct model_id / model_version /
    feature schema so break_logit_v1 is never mutated.
    """

    def __init__(self, features=None, hyperparameters=None):
        super().__init__(
            features=list(features or SPREAD_STRESS_FEATURES),
            hyperparameters=hyperparameters or HYPERPARAMETERS,
        )

    def fit(self, xs, ys, min_n: int = 20):
        super().fit(xs, ys, min_n=min_n)
        return self

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["model_id"] = MODEL_ID
        d["model_version"] = MODEL_VERSION
        d["feature_schema_version"] = FEATURE_SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SpreadStressModel":
        if d.get("model_version") != MODEL_VERSION:
            raise ValueError(
                f"SpreadStressModel cannot load model_version={d.get('model_version')!r}")
        if d.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
            raise ValueError(
                f"feature schema {d.get('feature_schema_version')!r} != "
                f"{FEATURE_SCHEMA_VERSION}")
        m = cls(features=d.get("features") or SPREAD_STRESS_FEATURES,
                hyperparameters=d.get("hyperparameters"))
        m.medians = dict(d.get("medians") or {})
        m.indicators = list(d.get("indicators") or [])
        m.columns = list(d.get("columns") or [])
        m.means = np.array(d["means"]) if d.get("means") is not None else None
        m.stds = np.array(d["stds"]) if d.get("stds") is not None else None
        m.coef = np.array(d["coef"]) if d.get("coef") is not None else None
        m.intercept = d.get("intercept")
        m.calibration = dict(d.get("calibration") or m.calibration)
        return m


def diagnostic_delta(p_stress: float, p_base: float) -> float:
    """D^{model} = p^{stress} - p^{base}."""
    return float(p_stress) - float(p_base)
