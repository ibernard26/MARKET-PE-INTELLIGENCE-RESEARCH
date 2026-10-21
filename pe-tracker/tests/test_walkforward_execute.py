"""Tests for src.model.walkforward_execute.

ALL fitting in this file uses SYNTHETIC in-memory deals (tests/model_fixtures.py).
Nothing here touches the real cohort, the network or the on-disk store, and no
number produced here is a result of first_walkforward_v1.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.db import _migrate_model_run_identity, _upgrade_model_registry_columns
from src.model import walkforward_execute as wfx
from src.model.cohort import ModelCohort
from src.model.experiment_prep import ExperimentPrepError, prepare_walkforward_plan
from src.research.bitemporal import normalize_as_of
from tests.model_fixtures import mem, synthetic_book

EXP = Path(__file__).resolve().parents[1] / "data" / "experiments" / "first_walkforward_v1"
PHRASE = "AUTHORIZE FIRST REAL WALKFORWARD"
SYN_CUTOFFS = ["2024-10-31", "2025-03-31"]
SYN_HORIZON = "2026-06-30"


def _real_protocol() -> dict:
    return json.loads((EXP / "protocol.json").read_text())


def _syn_store():
    """SYNTHETIC book of 80 generated deals (not real transactions)."""
    c = mem()
    _upgrade_model_registry_columns(c)
    _migrate_model_run_identity(c)
    synthetic_book(c, n=80, seed=0, start="2024-01-02")
    return c


def _syn_cohort(c) -> ModelCohort:
    ids = [r[0] for r in c.execute("SELECT deal_id FROM deals ORDER BY deal_id")]
    return ModelCohort.from_ids("synthetic_cohort", "v1", "SYNTHETIC test cohort",
                                "unit_test_synthetic", False, False, ids, "deadbeef")


def _syn_protocol(authorized=True) -> dict:
    p = copy.deepcopy(_real_protocol())
    p["experiment_id"] = "synthetic_walkforward_test"
    p["walk_forward"]["cutoffs"] = list(SYN_CUTOFFS)
    p["walk_forward"]["horizon"] = SYN_HORIZON
    p["execution_authorized"] = authorized
    p["status"] = "AUTHORIZED_PENDING_EXECUTE" if authorized else "PREPARED_NOT_EXECUTED"
    p["authorization_record"] = {"approver": "SYNTHETIC-TEST", "authorized_at": "synthetic"}
    return p


def _frozen_plan(c, cohort, protocol) -> dict:
    view = dict(protocol, execution_authorized=False)
    return json.loads(json.dumps(prepare_walkforward_plan(
        c, cohort=cohort, protocol=view, code_commit="deadbeef")))


def _run(c=None):
    c = c or _syn_store()
    cohort = _syn_cohort(c)
    p = _syn_protocol()
    return c, wfx.execute_walkforward(c, cohort=cohort, protocol=p,
                                      frozen_plan=_frozen_plan(c, cohort, p), phrase=PHRASE)


# --------------------------------------------------------------------- gates
def test_real_protocol_is_refused_while_flag_false_or_phrase_wrong():
    p = _real_protocol()
    if p["execution_authorized"] is False:
        with pytest.raises(ExperimentPrepError, match="NOT AUTHORIZED"):
            wfx.check_authorization(p, PHRASE)
    else:  # after an approved flip, a wrong/missing phrase must still refuse
        with pytest.raises(wfx.WalkforwardExecuteError, match="phrase"):
            wfx.check_authorization(p, "authorize")


def test_cli_refuses_before_any_network_when_unauthorized(monkeypatch):
    p = _syn_protocol(authorized=False)
    monkeypatch.setattr(wfx, "load_json", lambda path: p)
    monkeypatch.setattr(wfx, "_open_store",
                        lambda *a, **k: pytest.fail("store/network must not be touched"))
    with pytest.raises(ExperimentPrepError, match="NOT AUTHORIZED"):
        wfx.main(["--authorize", PHRASE])


def test_gate_refuses_flag_false():
    with pytest.raises(ExperimentPrepError, match="NOT AUTHORIZED"):
        wfx.check_authorization(_syn_protocol(authorized=False), PHRASE)


@pytest.mark.parametrize("phrase", [None, "", "authorize first real walkforward",
                                    PHRASE + " ", "AUTHORIZE"])
def test_gate_requires_exact_phrase(phrase):
    with pytest.raises(wfx.WalkforwardExecuteError, match="phrase"):
        wfx.check_authorization(_syn_protocol(), phrase)


@pytest.mark.parametrize("key", ["approver", "authorized_at"])
def test_gate_requires_authorization_record(key):
    p = _syn_protocol()
    p["authorization_record"][key] = ""
    with pytest.raises(wfx.WalkforwardExecuteError, match=key):
        wfx.check_authorization(p, PHRASE)


def test_gate_refuses_rerun_and_forbidden_options():
    p = _syn_protocol()
    p["status"] = "EXECUTED"
    with pytest.raises(wfx.WalkforwardExecuteError, match="EXECUTED"):
        wfx.check_authorization(p, PHRASE)
    for key in ("calibration", "hyperparameter_tuning", "random_kfold"):
        p = _syn_protocol()
        p["walk_forward"][key] = True
        with pytest.raises(wfx.WalkforwardExecuteError, match=key):
            wfx.check_authorization(p, PHRASE)


def test_gate_refuses_locked_contract_drift():
    p = _syn_protocol()
    p["locked_model_contract"]["C"] = 0.5
    with pytest.raises(ExperimentPrepError, match="drift"):
        wfx.check_authorization(p, PHRASE)


def test_cli_exposes_no_tuning_knobs():
    import inspect
    src = inspect.getsource(wfx.main)
    for knob in ("--C", "--cutoff", "--horizon", "--threshold", "--seed", "--exp-dir",
                 "--penalty", "--calibrat"):
        assert knob not in src


# ----------------------------------------------------------- plan / splits
def test_plan_drift_is_refused():
    c = _syn_store()
    cohort = _syn_cohort(c)
    p = _syn_protocol()
    plan = _frozen_plan(c, cohort, p)
    plan["windows"][0]["dataset_fingerprint"] = "0" * 64
    with pytest.raises(wfx.WalkforwardExecuteError, match="frozen plan"):
        wfx.execute_walkforward(c, cohort=cohort, protocol=p, frozen_plan=plan, phrase=PHRASE)
    assert c.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 0


def test_splits_honor_cutoffs_and_no_lookahead():
    c, res = _run()
    assert res["cutoffs"] == SYN_CUTOFFS and res["horizon"] == SYN_HORIZON
    ends = SYN_CUTOFFS[1:] + [SYN_HORIZON]
    rows = wfx._window_rows(c, _syn_cohort(c), SYN_CUTOFFS, SYN_HORIZON)
    for w, end, r in zip(res["windows"], ends, rows):
        cut = normalize_as_of(w["train_cutoff"])
        assert (w["test_start"], w["test_end"]) == (w["train_cutoff"], end)
        for row in r["train_rows"]:
            assert normalize_as_of(row["feature_as_of"]) <= cut
            assert normalize_as_of(row["label_known_at"]) <= cut
        for t in w["test_predictions"]:
            assert cut < normalize_as_of(t["feature_as_of"]) <= normalize_as_of(end)
        assert not ({x["deal_id"] for x in r["train_rows"]}
                    & {t["deal_id"] for t in w["test_predictions"]})


def test_threshold_is_selected_on_training_only(monkeypatch):
    """Changing TEST labels must not move t* (frozen from training predictions)."""
    from src.model import validation
    seen = []
    orig = validation.select_threshold

    def spy(p, y, **kw):
        seen.append(len(y))
        return orig(p, y, **kw)
    monkeypatch.setattr(validation, "select_threshold", spy)
    _, res = _run()
    n_train = {w["n_train"] for w in res["windows"]}
    assert seen and set(seen) <= n_train


def test_determinism_and_registration_ephemeral():
    _, a = _run()
    _, b = _run()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert all(w["status"] == "FITTED_AND_REGISTERED_EPHEMERAL" for w in a["windows"])
    assert a["run_type"] == "REPLICATION_OF_PUBLIC_PR23_RESULTS"
    assert a["fresh_out_of_sample_test"] is False and a["validated"] is False
    assert a["registry_target"].startswith("ephemeral")


def test_metrics_match_reporting_contract():
    _, res = _run()
    for w in res["windows"]:
        pm = w["model"]["probability_metrics"]
        for k in ("pi", "roc_auc", "average_precision", "average_precision_baseline_pi",
                  "brier", "log_loss", "calibration"):
            assert k in pm
        assert "baseline_constant" in w and "baseline_spread" in w
        assert w["meets_min_test_n"] == (w["n_test"] >= res["min_sample_n"])


# ------------------------------------------------------------- manifest/output
def test_manifest_contents_and_secret_redaction(tmp_path, monkeypatch):
    secret = "Research Bot synthetic-contact@example.invalid"
    monkeypatch.setenv("SEC_USER_AGENT", secret)
    c, res = _run()
    m = wfx.build_manifest(results=res, input_files={"a": "b"},
                           data_hashes=wfx.data_snapshot_hashes(c),
                           command=["python", "-m", "src.model.walkforward_execute"],
                           started_at="s", finished_at="f", head="abc123", tree_clean=True)
    for k in ("code_commit", "command", "environment", "input_sha256", "data_snapshot",
              "authorization_record", "window_fingerprints", "run_type", "notice"):
        assert k in m
    assert m["environment"]["sec_user_agent_set"] is True
    assert set(m["data_snapshot"]) == set(wfx.DATA_TABLES)
    wfx.write_outputs(tmp_path, res, m)
    for f in ("results.json", "run_manifest.json"):
        assert "synthetic-contact@example.invalid" not in (tmp_path / f).read_text()
    leaky = dict(res, note=secret)
    with pytest.raises(wfx.WalkforwardExecuteError, match="SEC_USER_AGENT"):
        wfx.write_outputs(tmp_path / "x", leaky, m)


def test_data_snapshot_hash_is_deterministic():
    assert wfx.data_snapshot_hashes(_syn_store()) == wfx.data_snapshot_hashes(_syn_store())


def test_locked_input_hashes_cover_pinned_files():
    from tests.test_geo_intel_isolation import LOCKED_SHA256
    h = wfx._locked_input_hashes(EXP)
    on_path = {r for r in LOCKED_SHA256 if not r.startswith("data/research/")}
    assert len(on_path) == 16 and on_path <= set(h)
    for rel in on_path:
        assert h[rel] == LOCKED_SHA256[rel]


# ------------------------------------------------- frozen manifest projection
def _syn_manifest(ids, tag="v"):
    return {"schema_version": 1, "deals": [{"deal_id": d, "x": tag} for d in ids]}


def test_manifest_projection_restricts_to_cohort_and_matches_freeze():
    cohort = ModelCohort.from_ids("syn", "v1", "SYNTHETIC", "unit_test", False, False,
                                  ["A", "B"], "deadbeef")
    p = _syn_protocol()
    cur = _syn_manifest(["A", "B", "C"])
    proj = wfx.frozen_manifest_projection(cohort, p, manifest=cur,
                                          frozen=_syn_manifest(["A", "B"]))
    assert [d["deal_id"] for d in proj["deals"]] == ["A", "B"]
    with pytest.raises(wfx.WalkforwardExecuteError, match="changed since freeze"):
        wfx.frozen_manifest_projection(cohort, p, manifest=cur,
                                       frozen=_syn_manifest(["A", "B"], tag="old"))
    with pytest.raises(wfx.WalkforwardExecuteError, match="missing"):
        wfx.frozen_manifest_projection(cohort, p, manifest=_syn_manifest(["A"]),
                                       frozen=_syn_manifest(["A", "B"]))


def test_real_cohort_projection_matches_freeze_commit_offline():
    """Real manifest bytes only (no network, no fit): the 62 cohort entries in the
    current reviewed manifest equal those at manifest_freeze_commit."""
    import subprocess
    p = _real_protocol()
    try:
        frozen = json.loads(subprocess.check_output(
            ["git", "show", f"{p['dataset_freeze']['manifest_freeze_commit']}:"
             f"{p['dataset_freeze']['manifest_path']}"], cwd=wfx.REPO_ROOT, text=True,
            stderr=subprocess.DEVNULL))
    except Exception:
        pytest.skip("freeze commit not available in this checkout (shallow clone)")
    from src.model.experiment_prep import cohort_from_file
    cohort = cohort_from_file(EXP / "cohort.json")
    proj = wfx.frozen_manifest_projection(cohort, p, frozen=frozen)
    assert len(proj["deals"]) == 62
