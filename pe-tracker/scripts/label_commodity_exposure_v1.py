"""Commodity-exposure coverage v1 (research only). See
docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v1.md for the preregistered protocol.

Reads the reviewed manifest and SEC EDGAR filings dated strictly before each
announcement; writes research artifacts under data/research/. It never opens the
SQLite store and is not wired into any model, feature set or strategy.

    python scripts/label_commodity_exposure_v1.py fetch     # identities + filings -> cache
    python scripts/label_commodity_exposure_v1.py label     # pass A -> labels CSV
    python scripts/label_commodity_exposure_v1.py packets   # pass B review packets (no labels)
    python scripts/label_commodity_exposure_v1.py report    # agreement + coverage summary

Requires SEC_USER_AGENT (descriptive, with contact). Requests are spaced >= 0.12 s
(under SEC's 10 requests/second fair-access limit).
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "sec_deal_manifest.json"
CACHE = ROOT / "data" / "cache" / "edgar_commodity_v1"          # gitignored
OUT_LABELS = ROOT / "data" / "research" / "commodity_exposure_labels_v1.csv"
OUT_PASSB = ROOT / "data" / "research" / "commodity_exposure_passB_v1.csv"
OUT_SUMMARY = ROOT / "data" / "research" / "commodity_exposure_coverage_v1.json"
PACKETS = CACHE / "passB_packets"

SEED = 20261009
SAMPLE_N = 20
WINDOW_DAYS = 550
ANNUAL_FORMS = {"10-K", "10-K405", "10-KT", "10-KSB", "20-F", "40-F"}
QUARTERLY_FORMS = {"10-Q", "10-QSB"}
MIN_INTERVAL_S = 0.12
FLAGS = ("producer", "consumer", "shipping_dependent", "hedged")

SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
            "plc", "sa", "ag", "aktiengesellschaft", "nv", "se", "llc", "lp", "the"}


# ---------------------------------------------------------------- EDGAR access
class Edgar:
    def __init__(self):
        self.ua = os.getenv("SEC_USER_AGENT", "")
        if not self.ua:
            sys.exit("SEC_USER_AGENT is required (SEC fair-access policy)")
        self._last = 0.0
        CACHE.mkdir(parents=True, exist_ok=True)

    def get(self, url: str, cache_name: str, binary: bool = False):
        p = CACHE / cache_name
        if p.exists():
            return p.read_bytes() if binary else p.read_text(errors="ignore")
        import requests
        for attempt in range(4):
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = requests.get(url, headers={"User-Agent": self.ua}, timeout=60)
            if r.status_code == 200:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(r.content)
                return r.content if binary else r.content.decode("utf-8", "ignore")
            if r.status_code in (429, 503):
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"EDGAR {r.status_code} for {url}")
        raise RuntimeError(f"EDGAR retries exhausted for {url}")

    def filings(self, cik: int) -> list[dict]:
        sub = json.loads(self.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                                  f"submissions/CIK{cik:010d}.json"))
        tables = [sub["filings"]["recent"]]
        for f in sub["filings"].get("files", []):
            tables.append(json.loads(self.get("https://data.sec.gov/submissions/" + f["name"],
                                              "submissions/" + f["name"])))
        out = []
        for t in tables:
            for i, acc in enumerate(t["accessionNumber"]):
                out.append({"accession": acc, "form": t["form"][i],
                            "filing_date": t["filingDate"][i],
                            "primary_document": t.get("primaryDocument", [""] * len(t["form"]))[i]})
        return out

    def document_text(self, cik: int, f: dict) -> str:
        acc = f["accession"].replace("-", "")
        doc = f["primary_document"] or f"{f['accession']}.txt"
        raw = self.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}",
                       f"docs/{cik}/{acc}/{doc}")
        if doc.endswith(".txt"):          # full submission: keep only the first document
            m = re.search(r"<DOCUMENT>.*?</DOCUMENT>", raw, re.S | re.I)
            raw = m.group(0) if m else raw
        return to_text(raw)


def to_text(raw: str) -> str:
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", raw)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", ". ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"(\.\s*){2,}", ". ", t)


def norm_name(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("&", " and "))
    toks = s.split()
    while toks and toks[-1] in SUFFIXES:
        toks.pop()
    while toks and toks[0] == "the":
        toks.pop(0)
    return " ".join(toks)


def select_filings(filings: list[dict], announce: str) -> list[dict]:
    lo = (date.fromisoformat(announce) - timedelta(days=WINDOW_DAYS)).isoformat()
    annual = [f for f in filings if f["form"] in ANNUAL_FORMS and lo <= f["filing_date"] < announce]
    if not annual:
        return []
    a = max(annual, key=lambda f: (f["filing_date"], f["accession"]))
    q = [f for f in filings if f["form"] in QUARTERLY_FORMS
         and a["filing_date"] < f["filing_date"] < announce]
    return [a] + ([max(q, key=lambda f: (f["filing_date"], f["accession"]))] if q else [])


# ---------------------------------------------------------------- fetch stage
def cmd_fetch(_args):
    ed = Edgar()
    deals = json.loads(MANIFEST.read_text())["deals"]
    lookup = defaultdict(set)
    raw = ed.get("https://www.sec.gov/Archives/edgar/cik-lookup-data.txt", "cik-lookup-data.txt",
                 binary=True).decode("latin-1")
    for line in raw.splitlines():
        parts = line.rsplit(":", 2)
        if len(parts) == 3 and parts[1].isdigit():
            lookup[norm_name(parts[0])].add(int(parts[1]))
    plan = []
    for d in deals:
        ann = d["announcement_timestamp"][:10]
        parties = []
        # target
        tcik = int(d["target_cik"])
        try:
            sel = select_filings(ed.filings(tcik), ann)
            parties.append({"party": "target", "name": d["target"], "cik": tcik,
                            "identity_basis": "reviewed_manifest_cik", "filings": sel,
                            "error": None})
        except Exception as exc:                     # recorded, never hidden
            parties.append({"party": "target", "name": d["target"], "cik": tcik,
                            "identity_basis": "reviewed_manifest_cik", "filings": [],
                            "error": str(exc)})
        # acquirer
        cands = sorted(lookup.get(norm_name(d["acquirer"]), set()))
        ok, err = [], None
        if 0 < len(cands) <= 8:
            for c in cands:
                try:
                    s = select_filings(ed.filings(c), ann)
                except Exception as exc:
                    err = str(exc)
                    continue
                if s:
                    ok.append((c, s))
        if len(ok) == 1:
            parties.append({"party": "acquirer", "name": d["acquirer"], "cik": ok[0][0],
                            "identity_basis": "exact_normalized_name_match",
                            "filings": ok[0][1], "error": None})
        else:
            parties.append({"party": "acquirer", "name": d["acquirer"], "cik": None,
                            "identity_basis": f"unresolved(candidates={len(cands)},"
                                              f"with_eligible_annual={len(ok)})",
                            "filings": [], "error": err})
        for p in parties:
            for f in p["filings"]:
                try:
                    ed.document_text(p["cik"], f)
                except Exception as exc:
                    p["error"] = str(exc)
        plan.append({"deal_id": d["deal_id"], "announce_date": ann, "parties": parties})
        print(d["deal_id"], [(p["party"], p["cik"], [f["form"] + "@" + f["filing_date"]
                                                    for f in p["filings"]]) for p in parties],
              flush=True)
    (CACHE / "plan.json").write_text(json.dumps(plan, indent=1))


# ---------------------------------------------------------------- pass A rules
FP = r"\b(we|our|us|the company)\b"
COMMOD_PROD = (r"(crude oil|oil and (natural )?gas|oil, natural gas|natural gas liquids|natural gas|"
               r"ngls?|coal|copper|gold|silver|iron ore|aluminum|aluminium|steel|zinc|nickel|"
               r"lithium|uranium|potash|phosphate|ethanol|timber|lumber|grains?|corn|soybeans?|"
               r"wheat|beef|pork|chicken|poultry|cattle|hogs|metals?|ores?|petrochemicals?)")
R_PRODUCER = re.compile(
    FP + r".{0,80}?\b(produc(e|es|ed|ing)|production of|extract\w*|min(e|es|ed|ing)|drill\w*|"
    r"refin(e|es|ed|ing)|explor(e|es|ing|ation) for|market(s|ed|ing)?)\b.{0,120}?\b"
    + COMMOD_PROD + r"\b|\bproved (developed )?reserves\b", re.I)
R_INPUT = re.compile(r"\b(raw materials?|commodit(y|ies)|fuel|jet fuel|diesel|gasoline|energy|"
                     r"natural gas|electricity|power|steel|aluminum|aluminium|copper|resins?|"
                     r"plastics?|packaging materials?|corn|wheat|soybeans?|sugar|coffee|cocoa|"
                     r"cotton|tobacco|grains?|feed|pulp|paper)\b", re.I)
R_PRICE = re.compile(r"\b(prices?|costs?)\b", re.I)
R_IMPACT = re.compile(r"\b(increas\w*|ris(e|es|ing)|fluctuat\w*|volatil\w*|higher|affect\w*|"
                      r"impact\w*|adverse\w*)\b", re.I)
R_FREIGHT = re.compile(r"\b(freight|shipping|ocean carriers?|common carriers?|third[- ]party "
                       r"carriers?|transportation costs?|trucking|fuel surcharges?)\b", re.I)
R_SHIPCOND = re.compile(r"\b(costs?|rates?|prices?|depend\w*|rel(y|ies|iance)|disrupt\w*|"
                        r"delay\w*|interrupt\w*)\b", re.I)
R_HEDGE = re.compile(r"\b(hedg\w*|derivatives?|swaps?|futures|forward (contracts?|purchases?|"
                     r"purchase contracts?)|collars?)\b", re.I)
R_HCOMM = re.compile(r"\b(commodit(y|ies)|fuel|diesel|natural gas|crude|oil|aluminum|aluminium|"
                     r"copper|steel|corn|wheat|soybeans?|electricity|power|metals?)\b", re.I)
R_NEG = re.compile(r"\b(do|does|did) not (currently )?(hedge|use|enter into|utilize|engage in)\b",
                   re.I)
R_SPEC = re.compile(r"(trading|speculative) purposes", re.I)
R_FPS = re.compile(FP, re.I)
R_ITEM = re.compile(r"\bItem\s+(\d{1,2}[AB]?)\b\.?", re.I)


def sentences(text: str):
    pos = 0
    for s in re.split(r"(?<=[.!?;])\s+(?=[A-Z(])", text):
        yield pos, s
        pos += len(s) + 1


def item_at(text: str, off: int) -> str:
    last = None
    for m in R_ITEM.finditer(text, 0, off):
        last = m.group(1).upper()
    return f"Item {last}" if last else "pre-Item (cover/intro)"


def classify(sentence: str) -> dict:
    s = sentence
    if len(s) < 20 or len(s) > 2500:
        return {}
    out = {}
    fp = bool(R_FPS.search(s))
    if R_PRODUCER.search(s) and (fp or re.search(r"proved (developed )?reserves", s, re.I)):
        out["producer"] = "yes"
    if fp and R_INPUT.search(s) and R_PRICE.search(s) and R_IMPACT.search(s):
        out["consumer"] = "yes"
    if fp and R_FREIGHT.search(s) and R_SHIPCOND.search(s):
        out["shipping_dependent"] = "yes"
    if fp and R_HEDGE.search(s) and R_HCOMM.search(s):
        if R_NEG.search(s) and not R_SPEC.search(s):
            out["hedged"] = "no_disclosed"
        else:
            out["hedged"] = "yes"
    return out


def label_party(ed: Edgar, p: dict) -> dict:
    row = {f: "unknown" for f in FLAGS}
    ev = {}
    for f in p["filings"]:
        text = ed.document_text(p["cik"], f)
        for off, s in sentences(text):
            for flag, val in classify(s).items():
                cur = row[flag]
                better = (cur == "unknown") or (flag == "hedged" and cur == "no_disclosed"
                                                and val == "yes")
                if better:
                    row[flag] = val
                    ev[flag] = {"accession": f["accession"], "form": f["form"],
                                "filing_date": f["filing_date"], "item": item_at(text, off),
                                "offset": off, "quote": s.strip()[:400]}
    return row, ev


def cmd_label(_args):
    ed = Edgar()
    plan = json.loads((CACHE / "plan.json").read_text())
    rows = []
    for d in plan:
        for p in d["parties"]:
            base = {"deal_id": d["deal_id"], "announce_date": d["announce_date"],
                    "party": p["party"], "party_name": p["name"], "cik": p["cik"] or "",
                    "identity_basis": p["identity_basis"],
                    "filings_reviewed": ";".join(f"{f['form']}|{f['accession']}|{f['filing_date']}"
                                                 for f in p["filings"])}
            flags, ev = {f: "unknown" for f in FLAGS}, {}
            if p["error"]:
                status, reason = "unknown", "fetch_error"
            elif p["party"] == "acquirer" and not p["cik"]:
                status, reason = "unknown", "acquirer_identity_unresolved"
            elif not p["filings"]:
                status, reason = "unknown", "no_preannouncement_annual_report_in_window"
            else:
                flags, ev = label_party(ed, p)
                if any(flags[f] == "yes" for f in ("producer", "consumer", "shipping_dependent")):
                    status, reason = "labeled", ""
                else:
                    status, reason = "unknown", "no_qualifying_disclosure_in_reviewed_filings"
            row = {**base, **flags, "exposure_status": status, "unknown_reason": reason}
            for f in FLAGS:
                e = ev.get(f, {})
                for k in ("accession", "form", "filing_date", "item", "offset", "quote"):
                    row[f"{f}_{k}"] = e.get(k, "")
            rows.append(row)
    with OUT_LABELS.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows -> {OUT_LABELS.relative_to(ROOT)}")


# ---------------------------------------------------------------- pass B packets
R_BROAD = re.compile(r"\b(commodit\w*|raw materials?|fuel|diesel|gasoline|energy|natural gas|"
                     r"crude|oil|electricity|steel|aluminum|copper|resin\w*|corn|wheat|grain\w*|"
                     r"freight|shipping|carriers?|hedg\w*|derivative\w*|swaps?|futures|"
                     r"reserves|mine|mining|refin\w*|drill\w*)\b", re.I)


def sample_ids() -> list[str]:
    ids = sorted(d["deal_id"] for d in json.loads(MANIFEST.read_text())["deals"])
    return sorted(random.Random(SEED).sample(ids, SAMPLE_N))


def cmd_packets(args):
    ed = Edgar()
    plan = {d["deal_id"]: d for d in json.loads((CACHE / "plan.json").read_text())}
    PACKETS.mkdir(parents=True, exist_ok=True)
    for did in sample_ids():
        d = plan[did]
        lines = [f"# {did} (announced {d['announce_date']})"]
        for p in d["parties"]:
            lines.append(f"\n## {p['party']}: {p['name']} | CIK {p['cik']} | "
                         f"{p['identity_basis']} | error={p['error']}")
            for f in p["filings"]:
                text = ed.document_text(p["cik"], f)
                lines.append(f"\n### {f['form']} {f['accession']} filed {f['filing_date']}")
                m = re.search(r"Item\s+1\.?\s*Business(?!.{0,40}\d+\s*Item)", text, re.I)
                starts = [x.start() for x in re.finditer(r"Item\s+1\.?\s*Business", text, re.I)]
                if starts:
                    st = starts[1] if len(starts) > 1 else starts[0]   # skip table of contents
                    lines.append("BUSINESS OPENING: " + text[st:st + args.opening])
                hits = [s.strip() for _, s in sentences(text)
                        if R_BROAD.search(s) and R_FPS.search(s) and 20 < len(s) < 1200]
                seen, keep = set(), []
                for h in hits:
                    k = h[:120]
                    if k not in seen:
                        seen.add(k)
                        keep.append(h[:500])
                lines.append(f"BROAD-VOCAB SENTENCES ({len(keep)} total, first {args.max_sent}):")
                lines += [f"- {h}" for h in keep[:args.max_sent]]
        (PACKETS / f"{did}.md").write_text("\n".join(lines))
    print(f"packets -> {PACKETS}")


# ---------------------------------------------------------------- report
def kappa(a, b):
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def cmd_report(_args):
    deals = {d["deal_id"]: d for d in json.loads(MANIFEST.read_text())["deals"]}
    A = list(csv.DictReader(OUT_LABELS.open()))
    B = {(r["deal_id"], r["party"]): r for r in csv.DictReader(OUT_PASSB.open())}
    sample = sample_ids()
    # agreement
    per_deal, per_party, per_flag, disagreements = [], [], {f: ([], []) for f in FLAGS}, []
    for did in sample:
        ok_deal = True
        for party in ("target", "acquirer"):
            a = next(r for r in A if r["deal_id"] == did and r["party"] == party)
            b = B[(did, party)]
            match = all(a[f] == b[f] for f in FLAGS)
            per_party.append(match)
            ok_deal &= match
            for f in FLAGS:
                per_flag[f][0].append(a[f]); per_flag[f][1].append(b[f])
                if a[f] != b[f]:
                    disagreements.append({"deal_id": did, "party": party, "flag": f,
                                          "pass_a": a[f], "pass_b": b[f],
                                          "pass_b_note": b.get("note", "")})
        per_deal.append(ok_deal)
    # coverage
    def outcome(did):
        return "break" if deals[did]["resolution_type"] in ("terminated", "withdrawn") else "close"
    cov = {"by_party": {}, "by_year": defaultdict(Counter), "by_outcome": defaultdict(Counter)}
    for party in ("target", "acquirer"):
        rows = [r for r in A if r["party"] == party]
        cov["by_party"][party] = {
            "n": len(rows),
            "exposure_status": dict(Counter(r["exposure_status"] for r in rows)),
            "unknown_reason": dict(Counter(r["unknown_reason"] for r in rows if r["unknown_reason"])),
            **{f: dict(Counter(r[f] for r in rows)) for f in FLAGS}}
        for r in rows:
            cov["by_year"][f"{party}:{r['announce_date'][:4]}"][r["exposure_status"]] += 1
            cov["by_outcome"][f"{party}:{outcome(r['deal_id'])}"][r["exposure_status"]] += 1
    deal_any = Counter()
    for did in deals:
        st = [r["exposure_status"] for r in A if r["deal_id"] == did]
        deal_any["at_least_one_party_labeled" if "labeled" in st else "no_party_labeled"] += 1
    chron_ok = all(r[f"{f}_filing_date"] < r["announce_date"]
                   for r in A for f in FLAGS if r[f] in ("yes", "no_disclosed"))
    complete = all(r["exposure_status"] in ("labeled", "unknown") and
                   (r["exposure_status"] == "labeled" or r["unknown_reason"]) for r in A)
    summary = {
        "protocol": "docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v1.md",
        "research_only": True, "model_fit_executed": False, "backtest_executed": False,
        "canonical_store_written": False, "n_deals": len(deals), "n_party_rows": len(A),
        "coverage": {"by_party": cov["by_party"],
                     "deals": dict(deal_any),
                     "by_year": {k: dict(v) for k, v in sorted(cov["by_year"].items())},
                     "by_outcome": {k: dict(v) for k, v in sorted(cov["by_outcome"].items())},
                     "sector": "unknown for all 129 deals in the store (ledger sector missing)"},
        "agreement": {
            "sample": sample, "reviewer": "same AI assistant, blind to pass A, judgment-based",
            "primary_deal_exact": sum(per_deal) / len(per_deal),
            "deals_agreeing": sum(per_deal),
            "party_exact": sum(per_party) / len(per_party),
            "per_flag": {f: {"agreement": sum(x == y for x, y in zip(*per_flag[f])) / len(per_flag[f][0]),
                             "cohen_kappa": kappa(*per_flag[f])} for f in FLAGS},
            "disagreements": disagreements},
        "success_criteria": {
            "coverage_100pct_labeled_or_explicit_unknown": complete,
            "chronology_all_cited_filings_pre_announcement": chron_ok,
            "agreement_primary_ge_0_90": sum(per_deal) / len(per_deal) >= 0.90},
    }
    summary["all_success_criteria_met"] = all(summary["success_criteria"].values())
    summary["status"] = ("v1 gates met" if summary["all_success_criteria_met"] else
                         "v1 FAILED preregistered success criteria; labels are not fit for "
                         "research use beyond diagnosing the rules")
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps({k: summary[k] for k in ("success_criteria",)}, indent=2))
    print(json.dumps(summary["agreement"]["per_flag"], indent=1),
          summary["agreement"]["primary_deal_exact"], summary["agreement"]["party_exact"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch").set_defaults(fn=cmd_fetch)
    sub.add_parser("label").set_defaults(fn=cmd_label)
    pk = sub.add_parser("packets")
    pk.add_argument("--opening", type=int, default=1200)
    pk.add_argument("--max-sent", type=int, default=14)
    pk.set_defaults(fn=cmd_packets)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)
