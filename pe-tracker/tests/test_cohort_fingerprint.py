"""Unit tests for model cohorts and dataset fingerprints (no live SEC)."""
import pytest

from src.model.cohort import CohortError, ModelCohort
from src.model.dataset import FEATURES, build_training_set
from src.model.fingerprint import canonicalize_training_rows, dataset_fingerprint
from src.model.logistic import BreakModel
from src.model.registry import load_model_run, register_model
from tests.model_fixtures import mem, synthetic_book


def _row(deal_id, label=1, spread=0.1, feature_as_of="2024-01-02T16:05:00",
         label_known_at="2024-06-01T00:00:00", schema="fs_v1"):
    x = {k: None for k in FEATURES}
    x["pct_spread"] = spread
    x["is_all_cash"] = 1.0
    return {
        "deal_id": deal_id,
        "feature_as_of": feature_as_of,
        "label": label,
        "label_known_at": label_known_at,
        "feature_schema_version": schema,
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
    n_deals_before = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
    ok = ModelCohort.from_ids(
        "fixture_b", "v1", "subset", "unit_test_fixture",
        False, False, ids[:2], "deadbeef")
    ok.validate(conn)
    # validation must not mutate the canonical store
    assert conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == n_deals_before
    bad = ModelCohort.from_ids(
        "fixture_c", "v1", "bad", "unit_test_fixture",
        False, False, ids[:2] + ["NO_SUCH_DEAL"], "deadbeef")
    with pytest.raises(CohortError, match="unknown deal_ids"):
        bad.validate(conn)
    assert conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == n_deals_before


def test_cohort_is_frozen():
    c = ModelCohort.from_ids(
        "f", "v1", "d", "unit_test_fixture", False, False, ["A"], "deadbeef")
    with pytest.raises(Exception):
        c.deal_ids = ("B",)  # type: ignore[misc]


# ------------------------------------------------------------- fingerprint
def test_fingerprint_order_invariant_distinct_keys():
    a = [_row("A", 1), _row("B", 0), _row("C", 1)]
    assert dataset_fingerprint(a) == dataset_fingerprint(list(reversed(a)))


def test_fingerprint_order_invariant_equal_primary_sort_tuple():
    """Adversarial case: same (deal_id, feature_as_of, label), different contents.

    Prior sort key omitted label_known_at / feature values, so stable sort
    preserved input order and broke order-invariance.
    """
    a = _row("SAME", label=1, spread=0.10,
             label_known_at="2024-06-01T00:00:00")
    b = _row("SAME", label=1, spread=0.20,
             label_known_at="2024-07-01T00:00:00")
    assert a["deal_id"] == b["deal_id"]
    assert a["feature_as_of"] == b["feature_as_of"]
    assert a["label"] == b["label"]
    assert a["label_known_at"] != b["label_known_at"]
    assert a["x"]["pct_spread"] != b["x"]["pct_spread"]
    assert dataset_fingerprint([a, b]) == dataset_fingerprint([b, a])


def test_fingerprint_sensitivity_to_each_material_field():
    base = [_row("A", 1, 0.10), _row("B", 0, 0.20)]
    fp0 = dataset_fingerprint(base)

    # deal_id
    assert dataset_fingerprint([_row("Z", 1, 0.10), _row("B", 0, 0.20)]) != fp0
    # feature_as_of
    r = _row("A", 1, 0.10, feature_as_of="2024-01-03T16:05:00")
    assert dataset_fingerprint([r, _row("B", 0, 0.20)]) != fp0
    # label
    assert dataset_fingerprint([_row("A", 0, 0.10), _row("B", 0, 0.20)]) != fp0
    # label_known_at
    r = _row("A", 1, 0.10, label_known_at="2099-01-01T00:00:00")
    assert dataset_fingerprint([r, _row("B", 0, 0.20)]) != fp0
    # feature schema version
    r = _row("A", 1, 0.10, schema="fs_other")
    assert dataset_fingerprint([r, _row("B", 0, 0.20)]) != fp0
    # feature values
    assert dataset_fingerprint([_row("A", 1, 0.11), _row("B", 0, 0.20)]) != fp0
    # ordered feature names (permutation changes fingerprint)
    names = list(FEATURES)
    swapped = [names[1], names[0]] + names[2:]
    assert dataset_fingerprint(base, feature_names=swapped) != fp0
    # same names, same order → same fingerprint
    assert dataset_fingerprint(base, feature_names=list(FEATURES)) == fp0


def test_fingerprint_null_deterministic_and_repeatable():
    r = _row("A", 1)
    r["x"]["pct_spread"] = None
    r["label_known_at"] = None
    fp1 = dataset_fingerprint([r])
    fp2 = dataset_fingerprint([r])
    assert fp1 == fp2
    assert len(fp1) == 64
    assert all(c in "0123456789abcdef" for c in fp1)
    canon = canonicalize_training_rows([r])[0]
    assert canon["label_known_at"] == "__NULL__"
    assert "__NULL__" in canon["feature_values"]


def test_fingerprint_sha256_hex_length_stable_across_runs():
    rows = [_row("A", 1), _row("B", 0)]
    fps = {dataset_fingerprint(rows) for _ in range(5)}
    assert len(fps) == 1
    assert len(next(iter(fps))) == 64


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
    assert meta["model_run_id"]
    assert meta["dataset_fingerprint"] == dataset_fingerprint(ts["rows"])
    # reversing training-set row order must not change the registered fingerprint
    assert meta["dataset_fingerprint"] == dataset_fingerprint(list(reversed(ts["rows"])))
    assert meta["sample_prevalence"] == meta["prevalence"] == ts["n_pos"] / ts["n"]
    row = c.execute(
        "SELECT model_run_id, cohort_id, cohort_version, dataset_fingerprint, sample_prevalence "
        "FROM model_registry WHERE model_run_id = ?",
        (meta["model_run_id"],)).fetchone()
    assert dict(row)["cohort_id"] == "synth_unit"
    assert dict(row)["dataset_fingerprint"] == meta["dataset_fingerprint"]
    assert dict(row)["sample_prevalence"] == meta["sample_prevalence"]
    assert load_model_run(meta["model_run_id"], c).to_dict() == m.to_dict()


def test_fresh_schema_has_model_run_id_pk():
    c = mem()
    cols = {r[1] for r in c.execute("PRAGMA table_info(model_registry)")}
    for col in ("model_run_id", "cohort_id", "cohort_version", "dataset_fingerprint",
                "sample_prevalence", "prevalence"):
        assert col in cols
    pk = sorted((r[5], r[1]) for r in c.execute("PRAGMA table_info(model_registry)") if r[5])
    assert [name for _, name in pk] == ["model_run_id"]
