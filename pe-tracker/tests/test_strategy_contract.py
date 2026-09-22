"""The strategy must not differentiate between runs.

These tests pin every constant that defines the strategy. If a future edit
changes a threshold, the cost ratio, the positive class, or the censoring rule
without deliberately bumping the version and this test together, the suite goes
red. That is the mechanical guarantee behind STRATEGY.md.
"""
import re
from pathlib import Path

from src import config

STRATEGY_MD = Path(__file__).resolve().parents[1] / "STRATEGY.md"


def test_strategy_version_is_pinned():
    assert config.STRATEGY_VERSION == "event_driven_v1"


def test_positive_class_and_censoring_are_fixed():
    assert config.POSITIVE_CLASS == "broken"
    assert config.CENSOR_STATUS == "pending"


def test_cost_asymmetry_is_locked():
    assert config.COST_FP == 1.0
    assert config.COST_FN == 15.0
    assert config.COST_FN / config.COST_FP >= 10
    assert config.COST_RATIO_GRID == (5, 10, 15, 20)


def test_sample_floor_is_locked():
    assert config.MIN_SAMPLE_N == 20


def test_momentum_rule_is_retired_not_traded():
    assert config.MOMENTUM_RULESET_STATUS == "retired_baseline"
    assert config.RULESET == "ma5_v1"
    assert config.BUY_THRESHOLD == 0.0025
    assert config.SELL_THRESHOLD == -0.0025
    assert config.MA_WINDOW == 5


def test_contract_doc_matches_config():
    doc = STRATEGY_MD.read_text()
    assert config.STRATEGY_VERSION in doc
    assert f"`COST_FN` | {config.COST_FN}" in doc
    assert f"`COST_FP` | {config.COST_FP}" in doc
    assert f"`MIN_SAMPLE_N` | {config.MIN_SAMPLE_N}" in doc
    assert re.search(r"positive class is the deal BREAKING", doc)


def test_metrics_defaults_come_from_the_contract():
    import inspect

    from src.compute import metrics
    sig = inspect.signature(metrics.optimal_threshold)
    assert sig.parameters["cost_fp"].default == config.COST_FP
    assert sig.parameters["cost_fn"].default == config.COST_FN
