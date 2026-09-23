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
from src.model.dataset import (FeatureDateError, build_training_set,
                               default_feature_date, label_as_of)
from src.model.evaluate import (evaluate_frozen_threshold, probability_metrics,
                                select_threshold)
from src.model.logistic import BreakModel, InsufficientDataError
from src.model.registry import (load_model, prediction_as_of, record_prediction,
                                register_model)
from src.model.validation import chronological_split, fit_and_score, walk_forward
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
def test_probability_metrics_hand_brier_and_ap_beside_pi():
    s = probability_metrics([0.2, 0.8, 0.1, 0.9], [0, 1, 0, 1], min_n=2)
    assert s["pi"] == 0.5 and s["average_precision_baseline_pi"] == 0.5
    assert s["brier"] == pytest.approx((0.04 + 0.04 + 0.01 + 0.01) / 4)
    assert s["roc_auc"] == 1.0 and s["average_precision"] == 1.0
    assert not any("t_star" in k for k in s)       # no threshold in probability layer


def test_select_threshold_withheld_below_min_sample_and_not_half():
    assert select_threshold([0.1, 0.9], [0, 1])["t_star"] is None
    r = np.random.default_rng(0)
    p = list(r.uniform(0, 1, 100))
    y = [int(r.random() < v) for v in p]
    t = select_threshold(p, y)["t_star"]
    assert t is not None and t != 0.5


def test_frozen_threshold_is_applied_not_reoptimized():
    out = evaluate_frozen_threshold([0.05, 0.2, 0.6], [1, 0, 1], t_star=0.1)
    assert out["t_star_frozen"] == 0.1
    assert (out["tp"], out["fp"], out["fn"], out["tn"]) == (1, 1, 1, 0)
    assert out["realized_cost"] == pytest.approx(1 * 1.0 + 1 * 15.0)


def test_future_test_labels_cannot_change_selected_threshold():
    """LOAD-BEARING: t* is chosen on pre-test data and frozen."""
    c = synthetic_book(mem(), n=120, seed=5)
    train = build_training_set("2025-01-01", c)["rows"]
    test = [r for r in build_training_set("2026-12-31", c)["rows"]
            if r["feature_as_of"] > "2025-01-01T23:59:59.999999"]
    flipped = [{**r, "label": 1 - r["label"]} for r in test]
    a = fit_and_score(train, test)
    b = fit_and_score(train, flipped)
    assert a["status"] == b["status"] == "fitted"
    assert a["t_star_frozen"] is not None
    assert a["t_star_frozen"] == b["t_star_frozen"]
    for k in ("model", "baseline_spread", "baseline_constant"):
        assert a[k]["threshold_selection"] == b[k]["threshold_selection"]
    # ...while test-set outcomes (which DO depend on test labels) differ
    assert a["model"]["frozen_policy"] != b["model"]["frozen_policy"]


# ---------------------------------------------------------------- validation
def test_walk_forward_windows_are_point_in_time():
    c = synthetic_book(mem(), n=120, seed=5)
    wf = walk_forward(c, ["2025-01-01", "2025-07-01"], horizon="2026-12-31")
    assert len(wf["windows"]) == 2
    for w in wf["windows"]:
        assert {"train_start", "train_end", "train_cutoff", "threshold_source_period",
                "calibration_source_period", "test_start", "test_end", "n_train",
                "n_test", "train_prevalence", "test_prevalence", "model_version",
                "feature_schema_version", "t_star_frozen", "calibration"} <= set(w)
        assert w["calibration_source_period"] is None      # v1: uncalibrated
        assert w["train_end"] == w["test_start"]
    w0 = wf["windows"][0]
    tr = build_training_set(w0["train_cutoff"], c)["rows"]
    assert all(r["label_known_at"] <= "2025-01-01T23:59:59.999999" for r in tr)
    assert "2025-01-01" in w0["threshold_source_period"]
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
    assert meta["training_cutoff"] == "2025-06-30T23:59:59.999999"
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
    assert t2.p_break == 0.12 and t2.p_break_as_of == "2025-07-15T23:59:59.999999"
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


# ------------------------------------------------ remediation: timestamps
def test_same_day_intraday_event_not_in_announcement_features():
    c = mem()
    c.execute("INSERT INTO deals (deal_id, announce_date, status) VALUES ('A','2025-01-02','pending')")
    from src.research.observations import Observation, record_observation
    record_observation(Observation("A", "2025-01-02T08:00:00", "s", offer_price=105.0,
                                   target_price=100.0, consideration_type="cash",
                                   known_at="2025-01-02T08:00:00"), conn=c)
    ev.record_event("A", "2025-01-02T07:30:00", "announcement", "s", conn=c,
                    known_at="2025-01-02T08:00:00")
    ev.record_event("A", "2025-01-02T15:00:00", "doj_challenge", "s", conn=c,
                    known_at="2025-01-02T16:00:00")
    ev.record_event("A", "2025-06-01", "termination", "s", conn=c, known_at="2025-06-01")
    assert default_feature_date("A", "2025-12-31", c) == "2025-01-02T08:00:00"
    row = build_training_set("2025-12-31", c)["rows"][0]
    assert row["feature_as_of"] == "2025-01-02T08:00:00"
    assert row["x"]["under_regulatory_challenge"] == 0.0     # 16:00 event unseen
    assert row["x"]["pct_spread"] == pytest.approx(0.05)


def test_explicit_feature_time_before_announcement_rejected():
    c = mem()
    add_deal(c, "A", "2025-01-02", 0.05, 0)       # announcement known 16:05
    with pytest.raises(FeatureDateError):
        build_training_set("2025-12-31", c, feature_dates={"A": "2025-01-02T09:00:00"})
    with pytest.raises(FeatureDateError):
        build_training_set("2025-12-31", c, feature_dates={"A": "2024-12-31"})
    ok = build_training_set("2025-12-31", c, feature_dates={"A": "2025-01-03T10:00:00"})
    assert ok["rows"][0]["x"]["pct_spread"] is not None


def test_explicit_feature_time_without_announcement_is_excluded():
    c = mem()
    c.execute("INSERT INTO deals (deal_id, announce_date, status) VALUES ('Z','2025-01-02','pending')")
    ts = build_training_set("2025-12-31", c, feature_dates={"Z": "2025-03-01"})
    assert ts["n"] == 0 and ts["n_censored"] == 0
    assert ts["excluded"][0]["reason"] == "no_known_announcement"


@pytest.mark.parametrize("as_of,cutoff,ok", [
    ("2025-07-15", "2025-06-30", True),
    ("2025-06-30", "2025-06-30", True),                           # same day, EOD both
    ("2025-06-30T12:00:00", "2025-06-30T09:00:00", True),
    ("2025-06-30T08:00:00", "2025-06-30T09:00:00", False),        # intraday lookahead
    ("2025-06-30T12:00:00", "2025-06-30", False),                 # cutoff = end of day
    ("2025-06-29", "2025-06-30", False),
])
def test_prediction_time_contract_date_and_timestamp(as_of, cutoff, ok):
    c = synthetic_book(mem(), n=60, seed=1)
    ts = build_training_set(cutoff, c)            # 2025-06-30 cutoff: labeled rows exist
    m = BreakModel().fit([r["x"] for r in ts["rows"]], [r["label"] for r in ts["rows"]])
    register_model(m, ts, c)
    if ok:
        row = record_prediction("S050", as_of, 0.1, cutoff, c)
        assert row["as_of"] >= row["training_cutoff"]
    else:
        with pytest.raises(sqlite3.IntegrityError):
            record_prediction("S050", as_of, 0.1, cutoff, c)


def test_raw_non_normalized_prediction_time_rejected_by_db():
    c, m, meta = _fitted_registry()
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO model_predictions (deal_id, as_of, p_break, model_version, "
                  "training_cutoff, feature_schema_version, prediction_timestamp) "
                  "VALUES ('S050','2025-07-15',0.1,?,?,'fs_v1','x')",
                  (meta["model_version"], meta["training_cutoff"]))


def test_registry_records_uncalibrated_v1():
    c, m, meta = _fitted_registry()
    assert meta["calibration"]["method"] == "none"
