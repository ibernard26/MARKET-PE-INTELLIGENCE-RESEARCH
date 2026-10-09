"""Acquirer entity resolution from merger filings (prereg §2).

Identity is taken from the deal's merger filing (manifest announcement_accession,
else a target DEFM14A/PREM14A/SC 14D9/SC TO-T/S-4 within 120 days after the
announcement). Those filings are used for identity only, never as exposure
evidence. PE/fund acquisition vehicles are recorded as unresolved; a sponsor's
listed management company is never substituted.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from .edgar import acceptance_et, select_filings, to_text

FALLBACK_FORMS = ("DEFM14A", "PREM14A", "SC 14D9", "SC TO-T", "S-4")
FALLBACK_DAYS = 120
MAX_TEXT = 4_000_000
MAX_CANDIDATES = 8

SUFFIXES = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
            "plc", "sa", "ag", "aktiengesellschaft", "nv", "se", "llc", "lp", "the", "l p",
            "n v", "s a", "a g", "bv", "b v", "gmbh", "spa", "s p a", "holdings inc"}
ENTITY_TYPES = (r"(?:corporation|company|limited liability company|limited partnership|"
                r"public limited company|exempted company|exempted limited partnership|"
                r"société anonyme|societe anonyme|stock corporation|business trust|statutory trust|"
                r"partnership|limited company|naamloze vennootschap|aktiengesellschaft|"
                r"Aktiengesellschaft|corporation organized[^()]{0,40})")
NAME = r"([A-Z][A-Za-z0-9.,&'’\-/ ]{1,110}?)"
DEF_ROLE = r"(Parent|Acquiror|Acquirer|Buyer|Purchaser Parent|Topco|Holdco)"
R_DEF = re.compile(NAME + r",?\s+an?\s+(?:[A-Z][A-Za-z.]*\s+){0,4}" + ENTITY_TYPES +
                   r"[^()]{0,60}?\(\s*(?:together with [^()]{0,60})?(?:the\s+)?[\"“”']*" + DEF_ROLE +
                   r"[\"“”']*\s*\)")
R_WHOLLY = re.compile(r"(?:direct\s+or\s+indirect\s+|indirect\s+|direct\s+)?wholly[- ]owned\s+"
                      r"(?:direct\s+|indirect\s+)?subsidiary\s+of\s+" + NAME +
                      r"(?=\s*\(|,|\.|;|\s+and\s|\s+that\s|\s+which\s)")
R_PE = re.compile(r"\b(funds?\s+(managed|advised|sponsored|affiliated)|investment\s+funds?|"
                  r"private\s+equity|equity\s+sponsors?|[\"“]Sponsors?[\"”]|Fund\s+[IVXL]+\b|"
                  r"Partners\s+[IVXL]+\b|consortium|investor\s+group|"
                  r"equity\s+commitment\s+letters?)", re.I)


def norm_name(s: str) -> str:
    s = re.sub(r"/[A-Za-z]{2,3}/", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower().replace("&", " and "))
    toks = s.split()
    changed = True
    while changed and toks:
        changed = False
        for k in (2, 1):
            if len(toks) >= k and " ".join(toks[-k:]) in SUFFIXES:
                toks = toks[:-k]
                changed = True
                break
    while toks and toks[0] == "the":
        toks.pop(0)
    return " ".join(toks)


def clean_entity(name: str) -> str:
    name = re.sub(r"^(?:and|with|by|among|between|of|by and among|by and between)\s+", "", name.strip(),
                  flags=re.I)
    # keep the last clause after "among"/"between"/"with" (party lists)
    name = re.split(r"\b(?:by and among|by and between|among|between|with)\s+", name)[-1]
    return name.strip(" ,.;:-’'\"“”")


def build_lookup(raw: str) -> dict:
    lookup = defaultdict(set)
    for line in raw.splitlines():
        parts = line.rsplit(":", 2)
        if len(parts) == 3 and parts[1].isdigit():
            lookup[norm_name(parts[0])].add(int(parts[1]))
    return lookup


def parse_header(full: str) -> dict:
    head = full[:20000]
    m = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", head)
    form = re.search(r"CONFORMED SUBMISSION TYPE:\s*(\S[^\n]*)", head)
    fdate = re.search(r"FILED AS OF DATE:\s*(\d{8})", head)
    roles = []
    for blk in re.finditer(r"\n(FILER|SUBJECT COMPANY|FILED BY):(.*?)(?=\n(?:FILER|SUBJECT COMPANY|"
                           r"FILED BY):|</SEC-HEADER>|\Z)", head, re.S):
        nm = re.search(r"COMPANY CONFORMED NAME:\s*(.+)", blk.group(2))
        ck = re.search(r"CENTRAL INDEX KEY:\s*(\d+)", blk.group(2))
        if nm and ck:
            roles.append({"role": blk.group(1), "name": nm.group(1).strip(), "cik": int(ck.group(1))})
    acc = m.group(1) if m else ""
    acc_iso = (f"{acc[:4]}-{acc[4:6]}-{acc[6:8]}T{acc[8:10]}:{acc[10:12]}:{acc[12:14]}"
               if acc else "")   # EDGAR header acceptance is US Eastern local time
    fd = fdate.group(1) if fdate else ""
    return {"form": form.group(1).strip() if form else "", "acceptance_et": acc_iso,
            "filing_date": f"{fd[:4]}-{fd[4:6]}-{fd[6:]}" if fd else "", "roles": roles}


def extract_acquirer(text: str) -> dict:
    """Returns parent/ultimate names with quotes, and PE signals, from merger-filing text."""
    out = {"parent": "", "parent_quote": "", "ultimate": "", "ultimate_quote": "",
           "pe_signal": False, "pe_quote": ""}
    m = R_DEF.search(text)
    if not m:
        return out
    parent = clean_entity(m.group(1))
    out["parent"] = parent
    s0 = max(0, m.start() - 150)
    out["parent_quote"] = text[s0:m.end() + 50].strip()[:400]
    window = text[m.start(): m.end() + 1500]
    w = R_WHOLLY.search(text, m.end(), m.end() + 400)
    if w:
        ult = clean_entity(w.group(1))
        if norm_name(ult) and norm_name(ult) != norm_name(parent):
            out["ultimate"] = ult
            out["ultimate_quote"] = text[max(0, w.start() - 120): w.end() + 40].strip()[:400]
    pe = R_PE.search(window) or R_PE.search(text[max(0, m.start() - 600): m.start()])
    if pe:
        out["pe_signal"] = True
        src = text[max(0, m.start() - 600): m.end() + 1500]
        k = src.find(pe.group(0))
        out["pe_quote"] = src[max(0, k - 200): k + 200].strip()
    return out


def merger_filing_candidates(deal: dict, target_filings: list[dict]) -> list[dict]:
    ann = deal["announcement_timestamp"][:10]
    out = [{"accession": deal["announcement_accession"], "basis": "manifest_announcement_accession"}]
    hi = (date.fromisoformat(ann) + timedelta(days=FALLBACK_DAYS)).isoformat()
    fb = sorted((f for f in target_filings if f["form"] in FALLBACK_FORMS
                 and ann <= f["filing_date"] <= hi), key=lambda f: (f["filing_date"], f["accession"]))
    for f in fb[:3]:
        if f["accession"] != deal["announcement_accession"]:
            out.append({"accession": f["accession"], "basis": f"fallback_{f['form']}"})
    return out


def manifest_consistent(manifest_name: str, *names: str) -> bool:
    a = norm_name(manifest_name).split()
    for n in names:
        b = norm_name(n).split()
        if a and b and (a[0] == b[0] or set(a) <= set(b) or set(b) <= set(a)):
            return True
    return False


def resolve_acquirer(ed, deal: dict, lookup: dict, target_filings: list[dict]) -> dict:
    ann = deal["announcement_timestamp"][:10]
    tcik = int(deal["target_cik"])
    rec = {"deal_id": deal["deal_id"], "announce_date": ann, "manifest_acquirer": deal["acquirer"],
           "deal_type": deal.get("deal_type", ""), "source_accession": "", "source_form": "",
           "source_filing_date": "", "source_acceptance_et": "", "source_basis": "",
           "parent_entity": "", "parent_quote": "", "ultimate_parent": "", "ultimate_quote": "",
           "pe_signal": False, "pe_quote": "", "matched_name": "", "candidate_ciks": "",
           "cik": "", "sec_name": "", "sic": "", "sic_description": "",
           "manifest_name_consistent": "", "status": "", "unknown_reason": "", "error": ""}
    found = None
    for cand in merger_filing_candidates(deal, target_filings):
        try:
            full = ed.full_submission(tcik, cand["accession"])
        except Exception as exc:                       # recorded, never hidden
            rec["error"] = f"{cand['accession']}: {exc}"
            continue
        hdr = parse_header(full)
        ex = extract_acquirer(to_text(full[:MAX_TEXT]))
        if ex["parent"]:
            found = (cand, hdr, ex)
            break
        if found is None:
            found = (cand, hdr, ex)
    if found is None:
        rec.update(status="unknown", unknown_reason="fetch_error")
        return rec
    cand, hdr, ex = found
    rec.update(source_accession=cand["accession"], source_basis=cand["basis"], source_form=hdr["form"],
               source_filing_date=hdr["filing_date"], source_acceptance_et=hdr["acceptance_et"],
               parent_entity=ex["parent"], parent_quote=ex["parent_quote"],
               ultimate_parent=ex["ultimate"], ultimate_quote=ex["ultimate_quote"],
               pe_signal=ex["pe_signal"], pe_quote=ex["pe_quote"], error="")
    if not ex["parent"]:
        rec.update(status="unknown", unknown_reason="acquirer_not_identified_in_merger_filing")
        return rec
    rec["manifest_name_consistent"] = manifest_consistent(deal["acquirer"], ex["parent"], ex["ultimate"])
    names = [n for n in (ex["ultimate"], ex["parent"]) if n]
    for nm in names:
        cands = sorted(lookup.get(norm_name(nm), set()))
        if not cands or len(cands) > MAX_CANDIDATES:
            continue
        ok = []
        for c in cands:
            try:
                sub = ed.submissions(c)
            except Exception as exc:
                rec["error"] = f"submissions {c}: {exc}"
                continue
            if select_filings(sub["filings"], ann):
                ok.append(sub)
        rec["candidate_ciks"] = ";".join(map(str, cands))
        if len(ok) == 1:
            s = ok[0]
            rec.update(matched_name=nm, cik=s["cik"], sec_name=s["name"], sic=s["sic"],
                       sic_description=s["sic_description"], status="resolved")
            return rec
        if len(ok) > 1:
            rec.update(matched_name=nm, status="unknown", unknown_reason="acquirer_no_unique_sec_registrant")
            return rec
    if ex["pe_signal"] or deal.get("deal_type") == "take_private":
        rec.update(status="unknown", unknown_reason="acquirer_pe_buyer_unresolved")
    elif rec["error"]:
        rec.update(status="unknown", unknown_reason="fetch_error")
    else:
        rec.update(status="unknown", unknown_reason="acquirer_no_unique_sec_registrant")
    return rec
