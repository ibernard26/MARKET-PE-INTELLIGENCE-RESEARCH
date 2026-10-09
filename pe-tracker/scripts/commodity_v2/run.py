"""Commodity-exposure v2 CLI (research only; prereg docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v2.md).

    python -m scripts.commodity_v2.run resolve   # merger-filing entity resolution + evidence plan
    python -m scripts.commodity_v2.run label     # first-pass rule labels for all 129 deals
    python -m scripts.commodity_v2.run packets   # blinded review packet for the v2 sample
    python -m scripts.commodity_v2.run devrun --v1-labels ... --v1-passb ...   # offline, v1 dev sample

Network stages require SEC_CONTACT_EMAIL (no default) and refuse to fetch otherwise.
Writes only under data/research/ and data/cache/ (gitignored). Never opens the SQLite store.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import entities, packets, rules
from .edgar import CACHE_V1, CACHE_V2, ROOT, Edgar, acceptance_et, load_deals, select_filings
from .sample import V2_SAMPLE_PREREG, v1_dev_sample, v2_validation_sample

RESEARCH = ROOT / "data" / "research"
OUT_IDENT = RESEARCH / "commodity_exposure_v2_identities.csv"
OUT_LABELS = RESEARCH / "commodity_exposure_v2_labels.csv"
OUT_RUN = RESEARCH / "commodity_exposure_v2_run.json"
OUT_PACKET = RESEARCH / "commodity_exposure_v2_review_packet"
PLAN = CACHE_V2 / "plan_v2.json"
STATUSES = {"labeled", "unknown", "not_yet_reviewed"}
UNKNOWN_REASONS = {"no_qualifying_disclosure_in_reviewed_filings",
                   "no_preannouncement_annual_report_in_window",
                   "acquirer_not_identified_in_merger_filing", "acquirer_pe_buyer_unresolved",
                   "acquirer_no_unique_sec_registrant", "fetch_error"}
EVIDENCE_KEYS = ("accession", "form", "filing_date", "acceptance_et", "url", "item", "offset", "quote")


def rules_sha256() -> str:
    h = hashlib.sha256()
    for name in ("rules.py", "entities.py", "edgar.py"):
        h.update((Path(__file__).parent / name).read_bytes())
    return h.hexdigest()


def _filing_meta(ed, cik, f):
    return {"accession": f["accession"], "form": f["form"], "filing_date": f["filing_date"],
            "acceptance_et": acceptance_et(f.get("acceptance", "")), "url": ed.doc_url(cik, f),
            "primary_document": f["primary_document"], "acceptance": f.get("acceptance", "")}


def check_sample():
    ids = [d["deal_id"] for d in load_deals()]
    if v2_validation_sample(ids) != V2_SAMPLE_PREREG:
        raise SystemExit("v2 sample procedure no longer reproduces the preregistered IDs")


# ------------------------------------------------------------------- resolve
def cmd_resolve(a):
    check_sample()
    ed = Edgar(offline=a.offline)
    lookup = entities.build_lookup(ed.cik_lookup())
    plan, idents = [], []
    for d in load_deals():
        ann = d["announcement_timestamp"][:10]
        tcik = int(d["target_cik"])
        parties = []
        try:
            tsub = ed.submissions(tcik)
            tf = select_filings(tsub["filings"], ann)
            terr = None
        except Exception as exc:
            tsub, tf, terr = {"filings": [], "sic": "", "sic_description": "", "name": ""}, [], str(exc)
        parties.append({"party": "target", "name": d["target"], "cik": tcik,
                        "identity": {"basis": "reviewed_manifest_cik", "sec_name": tsub["name"],
                                     "sic_context_only": tsub["sic"],
                                     "sic_description_context_only": tsub["sic_description"]},
                        "filings": [_filing_meta(ed, tcik, f) for f in tf], "error": terr})
        rec = entities.resolve_acquirer(ed, d, lookup, tsub["filings"])
        idents.append(rec)
        acik = int(rec["cik"]) if rec["status"] == "resolved" else None
        af, aerr = [], None
        if acik:
            try:
                af = select_filings(ed.submissions(acik)["filings"], ann)
            except Exception as exc:
                aerr = str(exc)
        parties.append({"party": "acquirer", "name": d["acquirer"], "cik": acik,
                        "identity": {k: rec[k] for k in (
                            "source_accession", "source_form", "source_filing_date",
                            "source_acceptance_et", "source_basis", "parent_entity", "parent_quote",
                            "ultimate_parent", "ultimate_quote", "pe_signal", "matched_name",
                            "sec_name", "manifest_name_consistent", "status", "unknown_reason")}
                        | {"sic_context_only": rec["sic"],
                           "sic_description_context_only": rec["sic_description"]},
                        "unknown_reason": rec["unknown_reason"],
                        "filings": [_filing_meta(ed, acik, f) for f in af], "error": aerr})
        for p in parties:
            for f in p["filings"]:
                try:
                    ed.document_text(p["cik"], f)
                except Exception as exc:
                    p["error"] = str(exc)
        plan.append({"deal_id": d["deal_id"], "announce_date": ann, "deal_type": d.get("deal_type"),
                     "resolution_type": d.get("resolution_type"), "parties": parties})
        print(d["deal_id"], rec["status"], rec["unknown_reason"] or rec["sec_name"], flush=True)
    CACHE_V2.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps(plan, indent=1, default=str))
    RESEARCH.mkdir(parents=True, exist_ok=True)
    with OUT_IDENT.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(idents[0]))
        w.writeheader()
        w.writerows(idents)
    print(f"identities -> {OUT_IDENT.relative_to(ROOT)}; SEC requests this run: {ed.requests_made}")


# ------------------------------------------------------------------- label
def label_party(ed, p) -> dict:
    docs = [(f, ed.document_text(p["cik"], f)) for f in p["filings"]]
    return rules.label_text_docs([({k: f[k] for k in ("accession", "form", "filing_date",
                                                      "acceptance_et", "url")}, t) for f, t in docs])


def build_row(ed, d, p) -> dict:
    base = {"deal_id": d["deal_id"], "announce_date": d["announce_date"], "party": p["party"],
            "party_name": p["name"], "cik": p["cik"] or "",
            "identity_basis": p["identity"].get("basis") or p["identity"].get("source_basis", ""),
            "sic_context_only": p["identity"].get("sic_context_only", ""),
            "filings_reviewed": ";".join(f"{f['form']}|{f['accession']}|{f['filing_date']}|"
                                         f"{f['acceptance_et']}" for f in p["filings"])}
    flags, ev = {f: "unknown" for f in rules.FLAGS}, {}
    if p.get("error"):
        status, reason = "unknown", "fetch_error"
    elif p["party"] == "acquirer" and not p["cik"]:
        status, reason = "unknown", p.get("unknown_reason") or "acquirer_no_unique_sec_registrant"
    elif not p["filings"]:
        status, reason = "unknown", "no_preannouncement_annual_report_in_window"
    else:
        try:
            flags, ev = label_party(ed, p)
            status = "labeled" if "yes" in (flags["producer"], flags["consumer"]) else "unknown"
            reason = "" if status == "labeled" else "no_qualifying_disclosure_in_reviewed_filings"
        except Exception:
            flags, ev = {f: "unknown" for f in rules.FLAGS}, {}
            status, reason = "unknown", "fetch_error"
    row = {**base, **flags, "exposure_status": status, "unknown_reason": reason}
    for f in rules.FLAGS:
        e = ev.get(f, {})
        for k in EVIDENCE_KEYS:
            row[f"{f}_{k}"] = e.get(k, "")
    return row


def summarize(rows, plan) -> dict:
    out = {}
    for party in ("target", "acquirer"):
        rs = [r for r in rows if r["party"] == party]
        out[party] = {"n": len(rs),
                      "exposure_status": dict(Counter(r["exposure_status"] for r in rs)),
                      "unknown_share": sum(r["exposure_status"] == "unknown" for r in rs) / len(rs),
                      "unknown_reason": dict(Counter(r["unknown_reason"] for r in rs if r["unknown_reason"])),
                      **{f: dict(Counter(r[f] for r in rs)) for f in rules.FLAGS},
                      "flag_unknown_rate": {f: sum(r[f] == "unknown" for r in rs) / len(rs)
                                            for f in rules.FLAGS}}
    return out


def cmd_label(a):
    check_sample()
    ed = Edgar(offline=a.offline)
    plan = json.loads(PLAN.read_text())
    rows = [build_row(ed, d, p) for d in plan for p in d["parties"]]
    with OUT_LABELS.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    idents = list(csv.DictReader(OUT_IDENT.open()))
    run = {"protocol": "docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v2.md", "research_only": True,
           "model_fit_executed": False, "backtest_executed": False, "canonical_store_written": False,
           "feature_integration": False, "validated": False,
           "validation_status": "pending separate AI-assisted blinded review (prereg §6-§7)",
           "rules_sha256": rules_sha256(),
           "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "n_deals": len(plan), "n_party_rows": len(rows),
           "not_yet_reviewed": sum(r["exposure_status"] == "not_yet_reviewed" for r in rows),
           "coverage": summarize(rows, plan),
           "deals_with_any_labeled_party": len({r["deal_id"] for r in rows
                                                 if r["exposure_status"] == "labeled"}),
           "entity_resolution": {"status": dict(Counter(i["status"] for i in idents)),
                                 "unknown_reason": dict(Counter(i["unknown_reason"] for i in idents
                                                                if i["unknown_reason"])),
                                 "source_basis": dict(Counter(i["source_basis"] for i in idents)),
                                 "manifest_name_consistent_among_resolved": dict(Counter(
                                     i["manifest_name_consistent"] for i in idents
                                     if i["status"] == "resolved"))},
           "sic_note": "SIC is current-vintage SEC submissions metadata, context only; never "
                       "used as exposure evidence.",
           "validation_sample": V2_SAMPLE_PREREG}
    OUT_RUN.write_text(json.dumps(run, indent=2))
    print(json.dumps(run["coverage"], indent=1))
    print(json.dumps(run["entity_resolution"], indent=1))


# ------------------------------------------------------------------- packets
def cmd_packets(a):
    check_sample()
    ed = Edgar(offline=a.offline)
    plan = {d["deal_id"]: d for d in json.loads(PLAN.read_text())}
    packets.write_packet(ed, plan, V2_SAMPLE_PREREG, OUT_PACKET)
    print(f"packet -> {OUT_PACKET.relative_to(ROOT)}")


# ------------------------------------------------------------------- dev dry-run
def cmd_devrun(a):
    """Offline only, on the v1 DEVELOPMENT sample, with v1 cached identities/filings."""
    ed = Edgar(offline=True)
    v1plan = {d["deal_id"]: d for d in json.loads((CACHE_V1 / "plan.json").read_text())}
    ids = [d["deal_id"] for d in load_deals()]
    sample = v1_dev_sample(ids)
    assert not set(sample) & set(V2_SAMPLE_PREREG)
    v1a = {(r["deal_id"], r["party"]): r for r in csv.DictReader(open(a.v1_labels))}
    v1b = {(r["deal_id"], r["party"]): r for r in csv.DictReader(open(a.v1_passb))}
    out = []
    for did in sample:
        d = v1plan[did]
        for p in d["parties"]:
            row = {f: "unknown" for f in rules.FLAGS}
            ev = {}
            if p["cik"] and p["filings"]:
                docs = [({"accession": f["accession"], "form": f["form"],
                          "filing_date": f["filing_date"]}, ed.document_text(p["cik"], f))
                        for f in p["filings"]]
                row, ev = rules.label_text_docs(docs)
            k = (did, p["party"])
            out.append({"deal_id": did, "party": p["party"], "v2": row,
                        "v1_pass_a": {f: v1a[k][f] for f in rules.FLAGS},
                        "v1_pass_b": {f: v1b[k][f] for f in rules.FLAGS},
                        "v2_quotes": {f: e["quote"][:240] for f, e in ev.items()}})
    Path(a.out).write_text(json.dumps(out, indent=1))
    print(f"dev dry-run ({len(out)} party rows, v1 development sample, offline) -> {a.out}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("resolve", cmd_resolve), ("label", cmd_label), ("packets", cmd_packets)):
        s = sub.add_parser(name)
        s.add_argument("--offline", action="store_true", help="cache only; never fetch")
        s.set_defaults(fn=fn)
    s = sub.add_parser("devrun")
    s.add_argument("--v1-labels", required=True)
    s.add_argument("--v1-passb", required=True)
    s.add_argument("--out", default=str(CACHE_V2 / "devrun_v1_sample.json"))
    s.set_defaults(fn=cmd_devrun)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
