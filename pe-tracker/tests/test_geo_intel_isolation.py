"""Isolation / governance tests for src/geo_intel.

The geopolitical research module must not fit models, must not touch the
locked V1 contract or the first_walkforward_v1 freeze, and must stay out of
the active feature / training / decision code.

The SHA-256 pins below were recorded on branch
feature/geopolitical-event-intelligence at base origin/main 724da08 BEFORE any
geo_intel code was written. If one of these files changes legitimately, that
is a deliberate, separately reviewed act: update the pin in the same commit
and say why.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "src" / "geo_intel"

LOCKED_SHA256 = {
    "data/experiments/first_walkforward_v1/protocol.json":
        "d4bd65c4fab0cc2f09678a7af2438acbc535bf3f5e799ee918de9a0079b95868",
    "data/experiments/first_walkforward_v1/cohort.json":
        "ac8fe6b5f9c74740792dc55333d56afc180fa071711182112bad955affa2927d",
    "data/experiments/first_walkforward_v1/plan.json":
        "e05f97d7fb4f5860db9d217e8572fda3eb358985fef3850a7d51cc9aaf9ffdbf",
    "src/config.py": "79c36c51126b2a5103a8b65360897ffa280086b51ee310cba88981403fb23d30",
    "STRATEGY.md": "5a749231067c8136611de690af30273223581bf2075ea3082235e7677f590d59",
    "src/model/dataset.py": "be276bb156359c042e984401321511292f2a2d401b4349968aa488779ed73ca0",
    "src/model/logistic.py": "7df55d32981b70b03e65f8b0b118e1477605ecdb665378571d06fdf6e4530f69",
    "src/model/experiment_prep.py":
        "73e0ef432c2606bd85fcbebb56d5815006c8d43297aa76d6a536d00a8db08bc4",
    "src/research/features.py": "57407f2bc473aa831c5c971687bd3d2a81bfe2e36730e891b44805f328245329",
    "src/research/bitemporal.py":
        "6fcc565f19404a37fe176c25dd24d2cdb76f3083010c3f3270f75d84aa190377",
    "schema.sql": "b7c2a80be46c72b979eb1c5e51f5727219afe3c30bc579d9bd0bc7b141426dc4",
    "data/sec_deal_manifest.json":
        "4cf61925adff5fb57e55dc9e6ddfe6886b35fca57691b85dce2da359f5c483cd",
    "tests/test_strategy_contract.py":
        "ced9cc4798e7bb5648fdca95346ea8e517e90a26e37c5ad27ece776996571b69",
    # added in PR #53 remediation so the pins equal the 17 files hashed in the
    # original before/after verification (previously only 13 were pinned here)
    "src/research/events.py": "a4ca576b2647bcff78efc50d4e0ea52ee0415f4a88b5ffb2c928de27d34cd247",
    "docs/BREAK_PROBABILITY_MODEL_V1.md":
        "f592d55de37146133d184786ed0b92dc340e8ff515f8c9260112746de00e42cb",
    "docs/MODEL_ARCHITECTURE_V2.md":
        "6cde9083b742ff83ec5a73936fe3bea9a2c6c666900a543ac49b5bf64a6abfec",
    "data/research/canonical_deal_outcomes_2026Q3.csv":
        "c430f26651e29cbe6f672dddbfa07a36a4e193ed64df96f03ab6977c60197c5d",
}
assert len(LOCKED_SHA256) == 17


def test_exactly_17_locked_files_are_pinned():
    assert len(LOCKED_SHA256) == 17

FS_V1 = ["pct_spread", "annualized_spread", "days_to_expected_close",
         "premium_to_unaffected", "log_deal_value", "is_sponsor", "is_all_cash",
         "cfius_exposure", "antitrust_exposure", "cma_eu_exposure", "second_request_open",
         "under_regulatory_challenge", "financing_condition", "shareholder_approval_required"]


def _sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


@pytest.mark.parametrize("rel", sorted(LOCKED_SHA256))
def test_locked_files_are_byte_identical(rel):
    assert _sha(rel) == LOCKED_SHA256[rel], f"{rel} changed — locked artifact"


def test_locked_strategy_parameters_unchanged():
    from src import config
    assert config.STRATEGY_VERSION == "event_driven_v1"
    assert (config.COST_FN, config.COST_FP) == (15.0, 1.0)
    assert config.COST_RATIO_GRID == (5, 10, 15, 20)
    assert config.MIN_SAMPLE_N == 20
    from src.model import logistic
    assert logistic.MODEL_VERSION == "break_logit_v1"
    assert logistic.HYPERPARAMETERS == {
        "penalty": "l2", "C": 1.0, "solver": "lbfgs", "max_iter": 1000,
        "class_weight": None, "standardize": True, "impute": "train_median+missing_indicator"}
    assert logistic.MIN_CLASS_N == 2


def test_fs_v1_contract_is_the_same_14_features_and_has_no_geo_field():
    from src.model import dataset
    assert dataset.FEATURE_SCHEMA_VERSION == "fs_v1"
    assert dataset.FEATURES == FS_V1 and len(dataset.FEATURES) == 14
    draft = json.loads((ROOT / "data/geopolitical/fs_v2_geo_candidates_DRAFT.json").read_text())
    assert draft["status"] == "DESIGN_ONLY_NOT_ACTIVE"
    names = {c["name"] for c in draft["candidates"]}
    assert not names & set(dataset.FEATURES)
    assert all(not f.startswith("geo_") for f in dataset.FEATURES)


def test_authorization_flag_still_false():
    p = json.loads((ROOT / "data/experiments/first_walkforward_v1/protocol.json").read_text())
    assert p["execution_authorized"] is False
    assert p["status"] == "PREPARED_NOT_EXECUTED"


def _imports(path: Path) -> set:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(("." * node.level) + (node.module or ""))
    return mods


def test_geo_module_does_not_import_model_or_research_code():
    for f in GEO.glob("*.py"):
        for m in _imports(f):
            assert "model" not in m.split(".") and "research" not in m.split("."), (f, m)
            assert not m.startswith(("sklearn", "src.db", "..db")), (f, m)


def test_active_code_does_not_import_geo_module():
    for sub in ("model", "research", "arb", "compute", "ingest"):
        for f in (ROOT / "src" / sub).rglob("*.py"):
            assert not any("geo_intel" in m for m in _imports(f)), f
    for f in (ROOT / "src").glob("*.py"):
        assert not any("geo_intel" in m for m in _imports(f)), f


def test_geo_pipeline_never_fits_or_registers(monkeypatch, tmp_path):
    from src.model import logistic, registry, validation

    def boom(*a, **k):
        raise AssertionError("unauthorized model fit / registration from geo_intel")

    monkeypatch.setattr(logistic.BreakModel, "fit", boom)
    for name in ("walk_forward", "chronological_split", "fit_and_score"):
        if hasattr(validation, name):
            monkeypatch.setattr(validation, name, boom)
    monkeypatch.setattr(registry, "register_model", boom)

    from src.geo_intel.pit import research_candidates
    from src.geo_intel.reporting import build_report, render_png, write_report
    from src.geo_intel.store import EvidenceLedger
    rep = build_report(as_of="2026-09-26")
    write_report(rep, tmp_path)
    research_candidates(EvidenceLedger(None), "2026-09-26")
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        pass
    else:
        render_png(rep, tmp_path / "png")
    for rel, h in LOCKED_SHA256.items():
        assert _sha(rel) == h


def test_geo_module_never_writes_canonical_store():
    for f in GEO.glob("*.py"):
        src = f.read_text()
        assert "DB_PATH" not in src, f
        for kw in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE TABLE", "executescript"):
            assert kw not in src, (f, kw)
        n_conn = src.count("sqlite3.connect(")
        if f.name == "reporting.py":
            assert n_conn == 1 and '?mode=ro", uri=True' in src
        else:
            assert n_conn == 0, f
