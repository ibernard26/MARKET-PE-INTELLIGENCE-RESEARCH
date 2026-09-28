#!/usr/bin/env python3
"""Outcome-blind identity resolution round v2 for DEFERRED_IDENTITY deals.

Ordering rule (pre-declared): deal_id ascending. The review queue exposes only
identity/timing fields (deal_id, target, target_cik, ticker, announcement and
resolution dates). Outcome labels are never loaded, so they cannot influence
order, effort or status.

Steps (each writes data/identity_resolution_round_v2.json):

  --plan      list target-filed, contemporaneous, allowed-form filings per deal
              from data.sec.gov submissions metadata (no filing text)
  --fetch     download those filings from www.sec.gov, extract Proof C
              evidence, classify RESOLVED_PROOF_C / STILL_AMBIGUOUS /
              NO_SUFFICIENT_EVIDENCE
  --openfigi-v2-from-cache
              recompute security-level OpenFIGI status (identity_admission_v2,
              PROPOSED) from the cached raw OpenFIGI responses (no new calls)

  python -m scripts.identity_resolution_round_v2 --plan --matrix PATH
  python -m scripts.identity_resolution_round_v2 --fetch            # needs www.sec.gov
  python -m scripts.identity_resolution_round_v2 --openfigi-v2-from-cache

Nothing here admits prices or edits target_ticker_map.json. Promotion of
RESOLVED_PROOF_C rows and use of identity_admission_v2 are separate, reviewed
steps (see docs/THESIS_PHASE2_ARCHITECTURE.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.security_identity.proof_c import (  # noqa: E402
    ALLOWED_FORMS, Filing, admissible_filing, classify, evidence_window, extract)

OUT = ROOT / "data" / "identity_resolution_round_v2.json"
DEFAULT_MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
DEAL_MANIFEST = ROOT / "data" / "sec_deal_manifest.json"
SUBMISSIONS = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
ORDERING_RULE = "deal_id ascending"
MAX_FILINGS_PER_DEAL = 8
QUEUE_FIELDS = ("deal_id", "target", "target_cik", "ticker",
                "announcement_date", "resolution_date")


def review_queue(matrix_path: Path, manifest_path: Path = DEAL_MANIFEST) -> list[dict]:
    """DEFERRED_IDENTITY deals with identity/timing fields only, deal_id order."""
    rows = json.loads(Path(matrix_path).read_text())["deals"]
    deals = {d["deal_id"]: d for d in json.loads(Path(manifest_path).read_text())["deals"]}
    queue = []
    for r in rows:
        if r.get("canonical_status") != "DEFERRED_IDENTITY":
            continue
        d = deals[r["deal_id"]]
        queue.append({
            "deal_id": r["deal_id"],
            "target": d.get("target"),
            "target_cik": d.get("target_cik"),
            "ticker": r.get("historical_ticker"),
            "announcement_date": (d.get("announcement_timestamp") or "")[:10],
            "resolution_date": (d.get("resolution_timestamp") or "")[:10] or None,
        })
    return sorted(queue, key=lambda q: q["deal_id"])


def _user_agent() -> str:
    return os.getenv("SEC_USER_AGENT") or "MARKET-PE-INTELLIGENCE-RESEARCH research-bot"


def _http_json(url: str) -> dict:
    import requests
    time.sleep(0.15)
    r = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=30)
    r.raise_for_status()
    return r.json()


def _http_text(url: str) -> str:
    import requests
    time.sleep(0.15)
    r = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=60)
    r.raise_for_status()
    return r.text


def _rows(block: dict) -> list[dict]:
    keys = ("accessionNumber", "form", "filingDate", "primaryDocument")
    return [dict(zip(keys, vals)) for vals in zip(*(block.get(k, []) for k in keys))]


def candidate_filings(q: dict, fetch_json: Callable[[str], dict]) -> list[Filing]:
    cik = int(q["target_cik"])
    sub = fetch_json(SUBMISSIONS.format(name=f"CIK{cik:010d}.json"))
    rows = _rows(sub["filings"]["recent"])
    lo, _ = evidence_window(q["announcement_date"], q["resolution_date"])
    for f in sub["filings"].get("files", []):
        if f.get("filingTo", "9999") >= lo.isoformat():
            rows += _rows(fetch_json(SUBMISSIONS.format(name=f["name"])))
    out = []
    for r in rows:
        acc = r["accessionNumber"]
        f = Filing(accession=acc, form=r["form"], filing_date=r["filingDate"],
                   filer_cik=cik, primary_document=r["primaryDocument"],
                   url=ARCHIVE.format(cik=cik, acc=acc.replace("-", ""),
                                      doc=r["primaryDocument"]))
        if admissible_filing(f, cik, q["announcement_date"], q["resolution_date"]) is None:
            out.append(f)
    ann = date.fromisoformat(q["announcement_date"])
    out.sort(key=lambda f: (ALLOWED_FORMS.index(f.form),
                            abs((date.fromisoformat(f.filing_date) - ann).days),
                            f.accession))
    return out[:MAX_FILINGS_PER_DEAL]


def plan(queue: list[dict], fetch_json: Callable[[str], dict] = _http_json) -> list[dict]:
    out = []
    for q in queue:
        try:
            files = candidate_filings(q, fetch_json)
            out.append({**q, "status": "PLANNED", "candidate_filings": [f.__dict__ for f in files]})
        except Exception as exc:  # metadata failure is recorded, never guessed around
            out.append({**q, "status": "PLAN_FAILED", "error": type(exc).__name__,
                        "candidate_filings": []})
    return out


def fetch_and_classify(planned: list[dict],
                       fetch_text: Callable[[str], str] = _http_text) -> list[dict]:
    out = []
    for p in planned:
        evidence = []
        for fd in p.get("candidate_filings", []):
            f = Filing(**fd)
            try:
                raw = fetch_text(f.url)
            except Exception as exc:
                evidence.append({"accession": f.accession, "fetch_error": type(exc).__name__})
                continue
            evidence.append(extract(p["deal_id"], p["ticker"], f, raw, int(p["target_cik"]),
                                    p["announcement_date"], p["resolution_date"]))
        records = [e for e in evidence if not isinstance(e, dict)]
        errors = [e for e in evidence if isinstance(e, dict)]
        result = classify(records) if records or not errors else {"status": "FETCH_FAILED"}
        out.append({**{k: p[k] for k in QUEUE_FIELDS}, **result,
                    "evidence": [e.to_dict() for e in records], "fetch_errors": errors,
                    "review_status": "auto_strict_pattern_needs_spot_check"
                    if result["status"] == "RESOLVED_PROOF_C" else "n/a"})
    return out


def summarize(results: list[dict]) -> dict:
    keys = ("RESOLVED_PROOF_C", "STILL_AMBIGUOUS", "NO_SUFFICIENT_EVIDENCE")
    reviewed = [r for r in results if r.get("status") in keys]
    return {"queue_size": len(results), "reviewed": len(reviewed),
            **{k: sum(1 for r in reviewed if r["status"] == k) for k in keys},
            "not_reviewed": len(results) - len(reviewed)}


def write(results: list[dict], step: str, out: Path = OUT) -> dict:
    doc = {"schema_version": 1, "round": "identity_resolution_round_v2",
           "ordering_rule": ORDERING_RULE, "outcome_blind": True, "step": step,
           "allowed_forms": list(ALLOWED_FORMS),
           "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
           "summary": summarize(results), "deals": results}
    out.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def openfigi_v2_from_cache(queue: list[dict]) -> list[dict]:
    """Recompute security-level OpenFIGI status from cached raw responses."""
    from src.ingest.security_identity.admission_v2 import openfigi_status_v2
    from src.ingest.security_identity.openfigi import OpenFIGISecurityIdentityResolver
    resolver = OpenFIGISecurityIdentityResolver(api_key="cache-only", env={})
    out = []
    for q in queue:
        payload = [{"idType": "TICKER", "idValue": q["ticker"], "marketSecDes": "Equity"}]
        cached = resolver._read_cache(payload)
        if not isinstance(cached, list) or not cached:
            out.append({"deal_id": q["deal_id"], "openfigi_v2": "NO_CACHED_RESPONSE"})
            continue
        rows = list((cached[0] or {}).get("data") or [])
        out.append({"deal_id": q["deal_id"], **{f"openfigi_v2_{k}": v for k, v in
                                               openfigi_status_v2(rows, q["target"]).items()}})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", action="store_true")
    g.add_argument("--fetch", action="store_true")
    g.add_argument("--openfigi-v2-from-cache", action="store_true")
    ap.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    ap.add_argument("--manifest", type=Path, default=DEAL_MANIFEST)
    a = ap.parse_args(argv)
    if a.plan:
        doc = write(plan(review_queue(a.matrix, a.manifest)), "plan")
    elif a.fetch:
        planned = json.loads(OUT.read_text())["deals"]
        doc = write(fetch_and_classify(planned), "fetch_and_classify")
    else:
        res = openfigi_v2_from_cache(review_queue(a.matrix, a.manifest))
        path = ROOT / "data" / "openfigi_v2_recompute.json"
        path.write_text(json.dumps({"rule": "identity_admission_v2 (PROPOSED)",
                                    "deals": res}, indent=2) + "\n")
        print(f"wrote {path}")
        return 0
    print(json.dumps(doc["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
