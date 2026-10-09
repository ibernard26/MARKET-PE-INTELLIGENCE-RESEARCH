"""Agreement scorer for the v2 blinded validation (prereg §7).

Run only after the separate AI-assisted reviewer's CSV exists:
    python -m scripts.commodity_v2.score --review path/to/review.csv
The first-pass author does not run this on real review data.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter

from .rules import FLAG_VALUES, FLAGS

G1_MIN_DEALS = 18
G2_MIN_SUBSTANTIVE = 15
G2_MIN_AGREEMENT = 0.85
G3_MIN_FLAG_SUBSTANTIVE = 5
G3_KAPPA_FLOOR = 0.60
PARTIES = ("target", "acquirer")


def kappa(a: list, b: list):
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if pe == 1:
        return None
    return (po - pe) / (1 - pe)


def validate_rows(rows: dict, sample: list[str], who: str):
    for did in sample:
        for p in PARTIES:
            r = rows.get((did, p))
            if r is None:
                raise ValueError(f"{who}: missing row {did}/{p}")
            for f in FLAGS:
                if r.get(f) not in FLAG_VALUES[f]:
                    raise ValueError(f"{who}: invalid {f}={r.get(f)!r} for {did}/{p}")


def score(first: dict, review: dict, sample: list[str]) -> dict:
    """first/review: {(deal_id, party): {flag: value}} -> gate report."""
    validate_rows(first, sample, "first_pass")
    validate_rows(review, sample, "review")
    deal_exact, cells, disagreements = [], [], []
    for did in sample:
        ok = True
        for p in PARTIES:
            for f in FLAGS:
                a, b = first[(did, p)][f], review[(did, p)][f]
                cells.append((did, p, f, a, b))
                if a != b:
                    ok = False
                    disagreements.append({"deal_id": did, "party": p, "flag": f,
                                          "first_pass": a, "review": b})
        deal_exact.append(ok)
    subst = [c for c in cells if c[3] != "unknown" or c[4] != "unknown"]
    s_agree = (sum(c[3] == c[4] for c in subst) / len(subst)) if subst else None
    per_flag = {}
    for f in FLAGS:
        fc = [c for c in cells if c[2] == f]
        fs = [c for c in fc if c[3] != "unknown" or c[4] != "unknown"]
        k = kappa([c[3] for c in fc], [c[4] for c in fc])
        evaluable = len(fs) >= G3_MIN_FLAG_SUBSTANTIVE
        per_flag[f] = {
            "n_cells": len(fc), "agreement_all": sum(c[3] == c[4] for c in fc) / len(fc),
            "n_substantive": len(fs),
            "agreement_substantive": (sum(c[3] == c[4] for c in fs) / len(fs)) if fs else None,
            "shared_unknown_cells": sum(c[3] == c[4] == "unknown" for c in fc),
            "unknown_rate_first_pass": sum(c[3] == "unknown" for c in fc) / len(fc),
            "unknown_rate_review": sum(c[4] == "unknown" for c in fc) / len(fc),
            "cohen_kappa": k,
            "g3_status": ("insufficient_substantive_labels" if not evaluable else
                          "pass" if (k is not None and k >= G3_KAPPA_FLOOR) else "fail")}
    n_exact = sum(deal_exact)
    g1 = n_exact >= G1_MIN_DEALS
    if len(subst) < G2_MIN_SUBSTANTIVE:
        g2 = "not_evaluable"
    else:
        g2 = "pass" if s_agree >= G2_MIN_AGREEMENT else "fail"
    evaluable = [f for f in FLAGS if per_flag[f]["g3_status"] != "insufficient_substantive_labels"]
    g3 = (per_flag["consumer"]["g3_status"] == "pass"
          and all(per_flag[f]["g3_status"] == "pass" for f in evaluable))
    return {
        "n_deals": len(sample), "n_cells": len(cells),
        "G1_exact_deals": n_exact, "G1_pass": g1,
        "G2_substantive_cells": len(subst), "G2_agreement_substantive": s_agree, "G2_status": g2,
        "G2_shared_unknown_cells": sum(c[3] == c[4] == "unknown" for c in cells),
        "G3_pass": g3, "per_flag": per_flag,
        "agreement_gates_pass": bool(g1 and g2 == "pass" and g3),
        "disagreements": disagreements}


def load(path, sample) -> dict:
    out = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if r["deal_id"] in sample:
                out[(r["deal_id"], r["party"])] = {f: (r.get(f) or "").strip() for f in FLAGS}
    return out


def main(argv=None):
    from .sample import V2_SAMPLE_PREREG
    from .run import OUT_LABELS, ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", required=True)
    ap.add_argument("--labels", default=str(OUT_LABELS))
    ap.add_argument("--out", default=str(ROOT / "data/research/commodity_exposure_v2_agreement.json"))
    a = ap.parse_args(argv)
    rep = score(load(a.labels, V2_SAMPLE_PREREG), load(a.review, V2_SAMPLE_PREREG), V2_SAMPLE_PREREG)
    rep["reviewer"] = "AI-assisted review run separately by Isaiah Bernard (not independent human)"
    with open(a.out, "w") as fh:
        json.dump(rep, fh, indent=2)
    print(json.dumps({k: rep[k] for k in ("G1_exact_deals", "G1_pass", "G2_substantive_cells",
                                          "G2_agreement_substantive", "G2_status", "G3_pass",
                                          "agreement_gates_pass")}, indent=2))


if __name__ == "__main__":
    main()
