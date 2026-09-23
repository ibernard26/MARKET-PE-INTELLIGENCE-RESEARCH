"""Phase B: break-probability model v1 — leakage, fitting, metrics, registry,
backtester integration, decision layer. Synthetic in-memory data only."""
import json
import math
import sqlite3

import numpy as np
import pytest

from src.config import MIN_SAMPLE_N
from src.ingest.historical import UnconfiguredProvider, ingest
from src.model import decision as dc
from src.model.bridge import attach_predictions
from src.model.dataset import build_training_set, label_as_of
from src.model.evaluate import score
from src.model.logistic import BreakModel, InsufficientDataError
from src.model.registry import (load_model, prediction_as_of, record_prediction,
                                register_model)
from src.model.validation import chronological_split, walk_forward
from src.research import events as ev
from src.research.backtest import BacktestConfig, Trade, evaluate_trade

from .model_fixtures import add_deal, mem, synthetic_book


# ------------------------------------------------------------ labels/leakage
def test_pending_is_censored_not_negative():
    c = mem()
    add_deal(c, "P", "2025-01-02", 0.05, None)
    ts = build_training_set("2025-12-31", c)
    assert ts["n"] == 0 and ts["n_censored"] == 1


def test_label_invisible_until_known():
    c = mem()
    # closes 2025-05-02 but the closing is only published 2025-05-20
    add_deal(c, "A", "2025-01-02", 0.05, 0, resolve_days=120, known_lag_days=18)
    assert label_as_of("A", "2025-05-10", c)["label"] is None
    assert build_training_set("2025-05-10", c)["n"] == 0
    assert build_training_set("2025-05-21", c)["rows"][0]["label"] == 0


def test_features_do_not_absorb_future_events():
    c = mem()
    add_deal(c, "A", "2025-01-02", 0.05, 1)
    before = build_training_set("2025-12-31", c)["rows"][0]["x"]
    ev.record_event("A", "2025-02-01", "doj_challenge", "synthetic", conn=c,
                    known_at="2025-02-01")        # after the feature date
    after = build_training_set("2025-12-31", c)["rows"][0]["x"]
    assert before == after
    assert before["under_regulatory_challenge"] == 0.0


def test_feature_date_after_cutoff_excluded():
    c = mem()
    add_deal(c, "A", "2025-06-01", 0.05, 0)
    ts = build_training_set("2025-03-01", c)
    assert ts["n"] == 0 and ts["excluded"][0]["reason"] == "no_known_announcement"


def test_missing_feature_stays_none_in_row():
    c = mem()
    add_deal(c, "A", "2025-01-02", 0.05, 0, deal_value_usd_mm=None)
    x = build_training_set("2025-12-31", c)["rows"][0]["x"]
    assert x["log_deal_value"] is None


# ------------------------------------------------------------------- fitting
def _xy(n=60, seed=1):
    c = synthetic_book(mem(), n=n, seed=seed)
    ts = build_training_set("2030-01-01", c)
    return [r["x"] for r in ts["rows"]], [r["label"] for r in ts["rows"]]


def test_refuses_to_fit_below_min_sample():
    xs, ys = _xy()
    with pytest.raises(InsufficientDataError):
        BreakModel().fit(xs[:MIN_SAMPLE_N - 1], ys[:MIN_SAMPLE_N - 1])
    with pytest.raises(InsufficientDataError):
        BreakModel().fit(xs, [0] * len(xs))       # one class only


def test_probabilities_valid_and_deterministic():
    xs, ys = _xy()
    p1 = BreakModel().fit(xs, ys).predict_proba(xs)
    p2 = BreakModel().fit(xs, ys).predict_proba(xs)
    assert np.array_equal(p1, p2)
    assert ((p1 > 0) & (p1 < 1)).all()


def test_serialization_roundtrip_identical():
    xs, ys = _xy()
    m = BreakModel().fit(xs, ys)
    m2 = BreakModel.from_dict(json.loads(json.dumps(m.to_dict())))
    assert np.allclose(m.predict_proba(xs), m2.predict_proba(xs), atol=0, rtol=0)


def test_missing_values_imputed_from_train_median_with_indicator_not_zero():
    xs, ys = _xy()
    xs = [dict(x) for x in xs]
    for x in xs[:5]:
        x["pct_spread"] = None
    m = BreakModel().fit(xs, ys)
    obs = [x["pct_spread"] for x in xs if x["pct_spread"] is not None]
    assert m.medians["pct_spread"] == pytest.approx(float(np.median(obs)))
    assert "pct_spread" in m.indicators and "pct_spread__missing" in m.columns


def test_model_learns_synthetic_spread_signal():
    xs, ys = _xy(n=200, seed=3)
    m = BreakModel().fit(xs, ys)
    coef = {c["feature"]: c for c in m.coefficients()}
    assert coef["pct_spread"]["coef_per_sd"] > 0
    assert coef["pct_spread"]["odds_ratio_per_sd"] == pytest.approx(
        math.exp(coef["pct_spread"]["coef_per_sd"]))


def test_calibration_skipped_when_sample_small():
    xs, ys = _xy()
    m = BreakModel().fit(xs, ys)
    assert m.calibrate(xs[:10], ys[:10])["method"] == "none"


# ------------------------------------------------------------------- metrics
def test_score_reports_pi_beside_pr_auc_and_hand_brier():
    s = score([0.2, 0.8, 0.1, 0.9], [0, 1, 0, 1], min_n=2)
    assert s["pi"] == 0.5 and s["pr_baseline_pi"] == 0.5
    assert s["brier"] == pytest.approx((0.04 + 0.04 + 0.01 + 0.01) / 4)
    assert s["roc_auc"] == 1.0


def test_t_star_withheld_below_min_sample_and_not_half():
    small = score([0.1, 0.9], [0, 1])
    assert small["t_star"] is None
    r = np.random.default_rng(0)
    p = list(r.uniform(0, 1, 100))
    y = [int(r.random() < v) for v in p]
    s = score(p, y)
    assert s["t_star"] is not None and s["t_star"] != 0.5


# ---------------------------------------------------------------- validation
def test_walk_forward_windows_are_point_in_time():
    c = synthetic_book(mem(), n=120, seed=5)
    wf = walk_forward(c, ["2025-01-01", "2025-07-01"], horizon="2026-12-31")
    assert len(wf["windows"]) == 2
    for w in wf["windows"]:
        assert {"train_cutoff", "test_start", "test_end", "n_train", "train_pos",
                "train_neg", "n_test", "model_version", "feature_schema_version"} <= set(w)
    w0 = wf["windows"][0]
    tr = build_training_set(w0["train_cutoff"], c)["rows"]
    assert all(r["label_known_at"] <= "2025-01-01T23:59:59.999999" for r in tr)
    assert w0["status"] == "fitted"
    assert {"baseline_constant", "baseline_spread", "model"} <= set(w0)


def test_split_reports_insufficient_data_honestly():
    c = synthetic_book(mem(), n=10, seed=5)
    out = chronological_split(c, "2024-02-01", "2026-12-31")
    assert out["status"] in ("insufficient_data", "no_test_rows")


# ------------------------------------------------------------------ registry
def _fitted_registry():
    c = synthetic_book(mem(), n=60, seed=1)
    ts = build_training_set("2025-06-30", c)
    m = BreakModel().fit([r["x"] for r in ts["rows"]], [r["label"] for r in ts["rows"]])
    meta = register_model(m, ts, c)
    return c, m, meta


def test_registry_metadata_complete_and_append_only():
    c, m, meta = _fitted_registry()
    for k in ("model_id", "model_version", "feature_schema_version", "training_cutoff",
              "n_train", "n_pos", "n_neg", "prevalence", "hyperparameters",
              "fit_timestamp", "code_commit"):
        assert meta[k] is not None
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE model_registry SET n_train = 0")
    assert load_model(meta["model_version"], "2025-06-30", c).to_dict() == m.to_dict()


def test_predictions_immutable_and_no_lookahead():
    c, m, meta = _fitted_registry()
    record_prediction("S050", "2025-07-15", 0.12, "2025-06-30", c)
    with pytest.raises(sqlite3.IntegrityError):
        record_prediction("S050", "2025-07-15", 0.50, "2025-06-30", c)   # no overwrite
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("DELETE FROM model_predictions")
    with pytest.raises(sqlite3.IntegrityError):   # model trained after as_of
        record_prediction("S001", "2025-01-15", 0.1, "2025-06-30", c)
    with pytest.raises(sqlite3.IntegrityError):   # unregistered model
        record_prediction("S050", "2025-08-01", 0.1, "2099-01-01", c)


# --------------------------------------------------------------- backtester
def test_backtester_uses_contemporaneous_prediction():
    c, m, meta = _fitted_registry()
    record_prediction("S050", "2025-07-15", 0.12, "2025-06-30", c)
    record_prediction("S050", "2025-09-01", 0.40, "2025-06-30", c)
    t = Trade("S050", "2025-08-01", 95.0, 100.0, 80.0, "2026-01-01",
              status="closed", resolution_date="2025-12-01")
    [t2] = attach_predictions([t], c)
    assert t2.p_break == 0.12 and t2.p_break_as_of == "2025-07-15"
    r = evaluate_trade(t2, BacktestConfig())
    assert r["p_break"] == 0.12


def test_backtester_rejects_future_prediction():
    t = Trade("X", "2025-08-01", 95.0, 100.0, 80.0, "2026-01-01", status="closed",
              resolution_date="2025-12-01", p_break=0.1, p_break_as_of="2025-09-01")
    with pytest.raises(ValueError):
        evaluate_trade(t)


# ------------------------------------------------------------------ decision
def test_expected_value_formula():
    assert dc.expected_value(0.1, 5.0, 20.0) == pytest.approx(0.9 * 5 - 0.1 * 20)
    assert dc.breakeven_p(5.0, 20.0) == pytest.approx(0.2)
    assert dc.decide(0.1, 5.0, 20.0, t_star=None)["action"] == "no_trade"
    assert dc.decide(0.1, 5.0, 20.0, t_star=0.15)["action"] == "enter"
    assert dc.decide(0.3, 5.0, 20.0, t_star=0.5)["action"] == "no_trade"   # EV<0
    with pytest.raises(ValueError):
        dc.expected_value(1.2, 1, 1)


# ------------------------------------------------------------------- ingest
def test_unconfigured_provider_never_fabricates():
    with pytest.raises(NotImplementedError):
        ingest(UnconfiguredProvider(), mem())
