"""Regularized logistic break model.

Regularization: L2 (ridge), C = 1.0 on standardized inputs. Chosen because
(i) the labeled sample is small and ridge shrinkage keeps coefficients finite
under separation, (ii) spread features are collinear and L2 spreads weight
across them rather than arbitrarily selecting one (as L1 would), and (iii) C is
FIXED, not tuned — with tens of resolved deals, cross-validating C would itself
overfit. Changing C is a versioned change (MODEL_VERSION).

Calibration decision (v1 = option A): break_logit_v1 is an UNCALIBRATED
logistic model. Validation, the registry and stored predictions use raw logistic
probabilities; calibration bins are reported only as a diagnostic. `calibrate()`
exists for a future version and, if used, must be fit on a chronologically
earlier calibration slice — never on the out-of-time test set. At current sample
sizes it is deliberately not applied.

Missing data: never zero-filled. Each feature is imputed with its TRAINING-fold
median and, when any training value was missing, a 0/1 missingness indicator is
added so the model can learn "not reported" separately. Imputation parameters
are frozen at fit time and serialized — prediction never looks at test data.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from ..config import MIN_SAMPLE_N
from .dataset import FEATURE_SCHEMA_VERSION, FEATURES

MODEL_ID = "break_logit"
MODEL_VERSION = "break_logit_v1"
HYPERPARAMETERS = {"penalty": "l2", "C": 1.0, "solver": "lbfgs", "max_iter": 1000,
                   "class_weight": None, "standardize": True,
                   "impute": "train_median+missing_indicator"}
MIN_CLASS_N = 2


class InsufficientDataError(ValueError):
    """Raised when a fit is requested on too little labeled data."""


class BreakModel:
    def __init__(self, features=FEATURES, hyperparameters=None):
        self.features = list(features)
        self.hp = dict(hyperparameters or HYPERPARAMETERS)
        self.medians: dict = {}
        self.indicators: list = []
        self.means = self.stds = None
        self.coef = None
        self.intercept: Optional[float] = None
        self.calibration = {"method": "none", "note": "raw logistic probabilities (v1)"}
        self.columns: list = []

    # ------------------------------------------------------------ design
    def _design(self, xs: list[dict]) -> np.ndarray:
        cols = []
        for f in self.features:
            cols.append([self.medians[f] if x.get(f) is None else x[f] for x in xs])
        for f in self.indicators:
            cols.append([1.0 if x.get(f) is None else 0.0 for x in xs])
        return np.array(cols, dtype=float).T if cols else np.zeros((len(xs), 0))

    def _fit_preprocessing(self, xs):
        for f in self.features:
            vals = [x[f] for x in xs if x.get(f) is not None]
            # all-missing in training: median undefined -> 0 AFTER standardization
            # is the only neutral choice; flagged via indicator below.
            self.medians[f] = float(np.median(vals)) if vals else 0.0
        self.indicators = [f for f in self.features if any(x.get(f) is None for x in xs)]
        self.columns = self.features + [f + "__missing" for f in self.indicators]
        X = self._design(xs)
        self.means = X.mean(axis=0)
        sd = X.std(axis=0)
        self.stds = np.where(sd > 0, sd, 1.0)
        return (X - self.means) / self.stds

    # --------------------------------------------------------------- fit
    def fit(self, xs: list[dict], ys: list[int], min_n: int = MIN_SAMPLE_N):
        n, n_pos = len(ys), int(sum(ys))
        if n < min_n or n_pos < MIN_CLASS_N or (n - n_pos) < MIN_CLASS_N:
            raise InsufficientDataError(
                f"n={n}, pos={n_pos}, neg={n - n_pos}; need n>={min_n} and "
                f">={MIN_CLASS_N} per class")
        from sklearn.linear_model import LogisticRegression
        Z = self._fit_preprocessing(xs)
        clf = LogisticRegression(C=self.hp["C"], solver=self.hp["solver"],
                                 max_iter=self.hp["max_iter"],
                                 class_weight=self.hp["class_weight"])
        clf.fit(Z, np.asarray(ys, dtype=int))
        self.coef = clf.coef_[0].astype(float)
        self.intercept = float(clf.intercept_[0])
        return self

    def decision_function(self, xs: list[dict]) -> np.ndarray:
        if self.coef is None:
            raise RuntimeError("model is not fitted")
        Z = (self._design(xs) - self.means) / self.stds
        return Z @ self.coef + self.intercept

    def predict_raw(self, xs) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-self.decision_function(xs)))

    def predict_proba(self, xs) -> np.ndarray:
        raw = self.predict_raw(xs)
        cal = self.calibration
        if cal["method"] == "platt":
            z = cal["a"] * _logit(raw) + cal["b"]
            return 1.0 / (1.0 + np.exp(-z))
        if cal["method"] == "isotonic":
            return np.interp(raw, cal["x"], cal["y"])
        return raw

    # ------------------------------------------------------- calibration
    def calibrate(self, xs, ys) -> dict:
        """NOT used in v1 validation. Caller must pass a chronologically earlier
        calibration slice (never test data).
        Platt when the held-out set permits (n >= MIN_SAMPLE_N and >= 5 per
        class); isotonic only with >= 200 rows and >= 20 per class; else none."""
        ys = np.asarray(ys, dtype=int)
        n, n_pos = len(ys), int(ys.sum())
        raw = self.predict_raw(xs)
        if n >= 200 and min(n_pos, n - n_pos) >= 20:
            from sklearn.isotonic import IsotonicRegression
            iso = IsotonicRegression(out_of_bounds="clip", y_min=1e-6, y_max=1 - 1e-6)
            iso.fit(raw, ys)
            self.calibration = {"method": "isotonic",
                                "x": [float(v) for v in iso.X_thresholds_],
                                "y": [float(v) for v in iso.y_thresholds_], "n": n}
        elif n >= MIN_SAMPLE_N and min(n_pos, n - n_pos) >= 5:
            from sklearn.linear_model import LogisticRegression
            lr = LogisticRegression(C=1e6, max_iter=1000)
            lr.fit(_logit(raw).reshape(-1, 1), ys)
            self.calibration = {"method": "platt", "a": float(lr.coef_[0][0]),
                                "b": float(lr.intercept_[0]), "n": n}
        else:
            self.calibration = {"method": "none",
                                "reason": f"calibration sample too small (n={n}, pos={n_pos})"}
        return self.calibration

    # ------------------------------------------------------ interpretation
    def coefficients(self) -> list[dict]:
        """Per-1-SD log-odds and odds ratios. ASSOCIATION, not causation."""
        return [{"feature": c, "coef_per_sd": float(b), "odds_ratio_per_sd": math.exp(float(b))}
                for c, b in sorted(zip(self.columns, self.coef), key=lambda t: -abs(t[1]))]

    # ------------------------------------------------------ serialization
    def to_dict(self) -> dict:
        return {"model_id": MODEL_ID, "model_version": MODEL_VERSION,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "features": self.features, "hyperparameters": self.hp,
                "medians": self.medians, "indicators": self.indicators,
                "columns": self.columns,
                "means": [float(v) for v in self.means],
                "stds": [float(v) for v in self.stds],
                "coef": [float(v) for v in self.coef], "intercept": self.intercept,
                "calibration": self.calibration}

    @classmethod
    def from_dict(cls, d: dict) -> "BreakModel":
        if d["feature_schema_version"] != FEATURE_SCHEMA_VERSION:
            raise ValueError(f"feature schema {d['feature_schema_version']} != "
                             f"{FEATURE_SCHEMA_VERSION}")
        m = cls(d["features"], d["hyperparameters"])
        m.medians, m.indicators, m.columns = d["medians"], d["indicators"], d["columns"]
        m.means, m.stds = np.array(d["means"]), np.array(d["stds"])
        m.coef, m.intercept = np.array(d["coef"]), d["intercept"]
        m.calibration = d["calibration"]
        return m


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-9, 1 - 1e-9)
    return np.log(p / (1 - p))
