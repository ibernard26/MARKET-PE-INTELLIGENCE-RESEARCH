#!/usr/bin/env python3
"""Build data/spread_stress_v2_cohort.json from the admitted price corpus.

Requires the frozen v2 spec (refuses otherwise). Builds the snapshot panel and
evaluates the deal-level gates. It never fits, scores or calibrates anything.

  python -m scripts.build_spread_stress_v2_cohort [--data-dir DIR] [--source-commit SHA]

--data-dir points at a directory holding sec_deal_manifest.json,
free_price_coverage_matrix.json and target_price_manifest.json (default: repo
data/). Input sha256s are recorded so the cohort can be re-derived and checked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.model.spread_stress_v2 import assert_frozen, build_panel, cohort_gates  # noqa: E402
from src.model.spread_stress_v2.spec import sha256_file  # noqa: E402

OUT = ROOT / "data" / "spread_stress_v2_cohort.json"
INPUTS = ("sec_deal_manifest.json", "free_price_coverage_matrix.json",
          "target_price_manifest.json")


def fingerprint(panel: dict, policy: dict) -> str:
    rows = sorted((d["deal_id"], tuple(s["snapshot"] for s in d["snapshots"]
                                       if s["status"] == "ELIGIBLE"))
                  for d in panel["deals"] if not d["excluded"])
    blob = json.dumps({"spec_sha256": policy["spec_sha256"], "rows": rows},
                      separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def build(data_dir: Path, source_commit: str | None = None) -> dict:
    policy = assert_frozen()
    deals = json.loads((data_dir / INPUTS[0]).read_text())["deals"]
    matrix = json.loads((data_dir / INPUTS[1]).read_text())["deals"]
    prints = json.loads((data_dir / INPUTS[2]).read_text())["prints"]
    admitted = {r["deal_id"] for r in matrix
                if r.get("canonical_status") == policy["eligibility"]["canonical_status"]}
    prints = [p for p in prints if p["deal_id"] in admitted]
    panel = build_panel(deals, prints, admitted, policy)
    gates = cohort_gates(panel, policy)
    stop = not (gates["min_sample_pass"] and gates["min_class_pass"])
    return {
        "schema_version": 1,
        "cohort_id": "spread_stress_v2_cohort",
        "spec_id": policy["spec_id"],
        "spec_sha256": policy["spec_sha256"],
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_commit": source_commit,
        "input_sha256": {name: sha256_file(data_dir / name) for name in INPUTS},
        "summary": {k: v for k, v in panel.items() if k != "deals"},
        "gates": gates,
        "status": "STOP_CLASS_OR_SAMPLE_GATE" if stop else "GATES_PASS_AWAITING_AUTHORIZATION",
        "model_fit_executed": False,
        "dataset_fingerprint": fingerprint(panel, policy),
        "deals": [{"deal_id": d["deal_id"], "excluded": d["excluded"],
                   "n_eligible_snapshots": d.get("n_eligible", 0),
                   "snapshot_status_counts": _counts(d["snapshots"]),
                   "eligible_snapshots": [s["snapshot"] for s in d["snapshots"]
                                          if s["status"] == "ELIGIBLE"]}
                  for d in panel["deals"]],
    }


def _counts(snaps: list[dict]) -> dict:
    out: dict[str, int] = {}
    for s in snaps:
        out[s["status"]] = out.get(s["status"], 0) + 1
    return dict(sorted(out.items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data")
    ap.add_argument("--source-commit", default=None)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    doc = build(a.data_dir, a.source_commit)
    a.out.write_text(json.dumps(doc, indent=2) + "\n")
    print(json.dumps({k: doc[k] for k in ("summary", "gates", "status",
                                          "dataset_fingerprint")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
