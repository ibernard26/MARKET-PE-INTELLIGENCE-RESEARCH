"""Unit tests for model cohorts and dataset fingerprints (no live SEC)."""
import pytest

from src.model.cohort import CohortError, ModelCohort
from src.model.dataset import FEATURES
from src.model.fingerprint import canonicalize_training_rows, dataset_fingerprint
from src.model.registry import register_model
from src.model.logistic import BreakModel
from src.model.dataset import build_training_set
from tests.model_fixtures import mem, synthetic_book


def _row(deal_id, label=1, spread=0.1, feature_as_of="2024-01-02T16:05:00",
         label_known_at="2024-06-01T00:00:00"):
    x = {k: None for k in FEATURES}
    x["pct_spread"] = spread
    x["is_all_cash"] = 1.0
    return {
        "deal_id": deal_id,
        "feature_as_of": feature_as_of,
        "label": label,
        "label_known_at": label_known_at,
        "feature_schema_version": "fs_v1",
        "x": x,
    }


# ------------------------------------------------------------------ cohort
def test_cohort_deterministic_ordering_and_uniqueness():
    c = ModelCohort.from_ids(
        cohort_id="fixture_a", cohort_version="v1",
        description="synthetic unit fixture",
        selection_method="unit_test_fixture",
        outcome_blind=False,
        probability_calibration_eligible=False,
        deal_ids=["D-B", "D-A", "D-A"],
        created_from_code_commit="deadbeef",
    )
    assert c.deal_ids == ("D-A", "D-B")
    c.validate()  # no conn: membership-only checks


def test_cohort_rejects_unsorted_tuple():
    with pytest.raises(CohortError, match="sorted"):
        ModelCohort(
            cohort_id="x", cohort_version="v1", description="",
            selection_method="unit_test_fixture",
            outcome_blind=True, probability_calibration_eligible=True,
            deal_ids=("D-B", "D-A"),
            created_from_code_commit="deadbeef",
        ).validate()


def test_cohort_rejects_unknown_ids_against_store():
    conn = synthetic_book(mem(), n=3, seed=0)
    ids = [r[0] for r in conn.execute("SELECT deal_id FROM deals ORDER BY deal_id")]
    ok = ModelCohort.from_ids(
        "fixture_b", "v1", "subset", "unit_test_fixture",
        False, False, ids[:2], "deadbeef")
    ok.validate(conn)
    bad = ModelCohort.from_ids(
        "fixture_c", "v1", "bad", "unit_test_fixture",
        False, False, ids[:2] + ["NO_SUCH_DEAL"], "deadbeef")
    with pytest.raises(CohortError, match="unknown deal_ids"):
        bad.validate(conn)


# ------------------------------------------------------------- fingerprint
def test_fingerprint_order_invariant():
    a = [_row("A", 1), _row("B", 0), _row("C", 1)]
    b = list(reversed(a))
    assert dataset_fingerprint(a) == dataset_fingerprint(b)


def test_fingerprint_sensitivity_to_material_fields():
    base = [_row("A", 1, 0.10), _row("B", 0, 0.20)]
    fp0 = dataset_fingerprint(base)
    assert dataset_fingerprint([_row("A", 0, 0.10), _row("B", 0, 0.20)]) != fp0
    assert dataset_fingerprint([_row("A", 1, 0.11), _row("B", 0, 0.20)]) != fp0
    changed = [_row("A", 1, 0.10), _row("B", 0, 0.20)]
    changed[0]["label_known_at"] = "2099-01-01T00:00:00"
    assert dataset_fingerprint(changed) != fp0
    assert len(canonicalize_training_rows(base)) == 2


def test_fingerprint_null_representation_stable():
    r = _row("A", 1)
    r["x"]["pct_spread"] = None
    fp1 = dataset_fingerprint([r])
    fp2 = dataset_fingerprint([r])
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex


# ----------------------------------------------------- registry metadata
def test_registry_persists_cohort_fingerprint_sample_prevalence():
    c = synthetic_book(mem(), n=60, seed=1)
    ts = build_training_set("2025-06-30", c)
    ids = sorted({r["deal_id"] for r in ts["rows"]})
    cohort = ModelCohort.from_ids(
        "synth_unit", "v0", "synthetic fixture cohort",
        "unit_test_fixture", outcome_blind=False,
        probability_calibration_eligible=False,
        deal_ids=ids, created_from_code_commit="deadbeef")
    m = BreakModel().fit([r["x"] for r in ts["rows"]], [r["label"] for r in ts["rows"]])
    meta = register_model(m, ts, c, cohort=cohort)
    assert meta["cohort_id"] == "synth_unit"
    assert meta["cohort_version"] == "v0"
    assert meta["dataset_fingerprint"] == dataset_fingerprint(ts["rows"])
    assert meta["sample_prevalence"] == meta["prevalence"] == ts["n_pos"] / ts["n"]
    row = c.execute(
        "SELECT cohort_id, cohort_version, dataset_fingerprint, sample_prevalence "
        "FROM model_registry WHERE model_version = ?",
        (meta["model_version"],)).fetchone()
    assert dict(row)["cohort_id"] == "synth_unit"
    assert dict(row)["dataset_fingerprint"] == meta["dataset_fingerprint"]
    assert dict(row)["sample_prevalence"] == meta["sample_prevalence"]
