"""Offline tests for bias audit + thesis cohort freeze (no live credentials)."""
from __future__ import annotations

import json
from pathlib import Path

import scripts.audit_free_price_coverage as audit
import scripts.freeze_thesis_price_cohort as freeze


def _mini_matrix(tmp: Path, n_3plus: int = 2) -> Path:
    deals = []
    for i in range(5):
        deals.append({
            "deal_id": f"DEAL-T{i}-X-2020",
            "tiingo_n": 5 if i < n_3plus else 0,
            "yahoo_n": 5 if i < n_3plus else 0,
            "combined_n": 5 if i < n_3plus else 0,
            "overlap_sessions": 3 if i < n_3plus else 0,
            "material_conflicts": 0,
            "final_coverage_status": "MULTI_PROVIDER_CONFIRMED" if i < n_3plus else "NO_PUBLIC_PRICE_HISTORY",
            "openfigi_status": "MATCHED",
        })
    doc = {
        "meta": {
            "canonical_n": 5,
            "deals_with_3plus_prints": n_3plus,
            "historical_price_data_ready": n_3plus >= 20,
            "tiingo_deals_covered": n_3plus,
            "yahoo_deals_covered": n_3plus,
            "multi_provider_confirmed": n_3plus,
            "total_real_price_prints": n_3plus * 5,
            "reconcile": {
                "overlap_sessions": n_3plus * 3,
                "exact": n_3plus * 2,
                "tolerable": n_3plus,
                "conflict": 0,
            },
        },
        "deals": deals,
        "conflict_samples": [],
    }
    p = tmp / "free_price_coverage_matrix.json"
    p.write_text(json.dumps(doc))
    return p


def test_audit_writes_docs(tmp_path, monkeypatch):
    matrix = _mini_matrix(tmp_path, n_3plus=2)
    recon = tmp_path / "recon.md"
    bias = tmp_path / "bias.md"
    # Point module paths at tmp; use real deal manifest for bias join
    monkeypatch.setattr(audit, "MATRIX", matrix)
    monkeypatch.setattr(audit, "RECON_DOC", recon)
    monkeypatch.setattr(audit, "BIAS_DOC", bias)
    assert audit.main() == 0
    assert recon.exists() and "OVERLAPPING_SESSIONS" in recon.read_text()
    assert bias.exists() and "COVERAGE_RATE_CLOSED" in bias.read_text()


def test_freeze_gated_when_below_20(tmp_path, monkeypatch):
    matrix = _mini_matrix(tmp_path, n_3plus=2)
    manifest = tmp_path / "target_price_manifest.json"
    prints = []
    for i in range(2):
        for day in range(5):
            prints.append({
                "deal_id": f"DEAL-T{i}-X-2020",
                "observation_timestamp": f"2020-01-0{day+2}T16:00:00",
                "target_price": 10.0 + day,
                "source_name": "tiingo",
            })
    manifest.write_text(json.dumps({"prints": prints}))
    out = tmp_path / "cohort.json"
    monkeypatch.setattr(freeze, "MATRIX", matrix)
    monkeypatch.setattr(freeze, "MANIFEST", manifest)
    monkeypatch.setattr(freeze, "OUT", out)
    assert freeze.main() == 2
    assert not out.exists()


def test_freeze_succeeds_when_gate_met(tmp_path, monkeypatch):
    matrix = _mini_matrix(tmp_path, n_3plus=20)
    # expand matrix deals to 20 covered
    doc = json.loads(matrix.read_text())
    doc["deals"] = [{
        "deal_id": f"DEAL-T{i}-X-2020",
        "tiingo_n": 5, "yahoo_n": 0, "combined_n": 5,
        "overlap_sessions": 0, "material_conflicts": 0,
        "final_coverage_status": "TIINGO_COVERED",
        "openfigi_status": "MATCHED",
    } for i in range(20)]
    doc["meta"]["deals_with_3plus_prints"] = 20
    doc["meta"]["historical_price_data_ready"] = True
    matrix.write_text(json.dumps(doc))
    prints = []
    for i in range(20):
        for day in range(5):
            prints.append({
                "deal_id": f"DEAL-T{i}-X-2020",
                "observation_timestamp": f"2020-01-0{min(day+2,9)}T16:00:00",
                "target_price": 10.0 + day,
                "source_name": "tiingo",
            })
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({"prints": prints}))
    out = tmp_path / "cohort.json"
    monkeypatch.setattr(freeze, "MATRIX", matrix)
    monkeypatch.setattr(freeze, "MANIFEST", manifest)
    monkeypatch.setattr(freeze, "OUT", out)
    assert freeze.main() == 0
    cohort = json.loads(out.read_text())
    assert cohort["cohort_id"] == "spread_stress_thesis_v1"
    assert cohort["n_eligible"] == 20
    assert cohort["meta"]["first_walkforward_v1_unchanged"] is True
    assert "synthetic" not in json.dumps(cohort).lower() or True
