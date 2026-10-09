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
            "n v", "s a", "a g", "bv", "b v", "gmbh", "spa", "s p a"}
ENTITY_TYPES = (r"(?:corporation|company|limited liability company|limited partnership|"
                r"public limited company|exempted company|exempted limited partnership|"
                r"société anonyme|societe anonyme|stock corporation|business trust|statutory trust|"
                r"partnership|limited company|naamloze vennootschap|aktiengesellschaft|"
                r"Aktiengesellschaft|corporation organized[^()]{0,40})")
NAME = r"([A-Z][A-Za-z0-9.,&'’\-/ ]{1,110}?)"
DEF_ROLE = r"(Parent|Acquiror|Acquirer|Buyer|Purchaser Parent|Topco|Holdco)"
R_DEF = re.compile(NAME + r"(?:,?\s+an?\s+(?:[A-Z][A-Za-z.]*\s+){0,4}" + ENTITY_TYPES +
                   r"[^()]{0,140}?)?\s*\(\s*(?:together with [^()]{0,60})?(?:the\s+)?[\"“”']*\s*" +
                   DEF_ROLE + r"\s*[\"“”']*\s*\)")
R_PARTY = re.compile(NAME + r",?\s+an?\s+(?:[A-Z][A-Za-z.]*\s+){0,4}" + ENTITY_TYPES +
                     r"([^()]{0,80}?)\s*\(\s*(?:the\s+)?[\"“”']*\s*([A-Z][A-Za-z0-9 .&\-]{0,40}?)"
                     r"\s*[\"“”']*\s*\)")
R_AGREEMENT = re.compile(r"(Agreement and Plan of (Merger|Reorganization)|Merger Agreement|"
                         r"Arrangement Agreement|Transaction Agreement|Business Combination Agreement)")
NON_ACQ_TERMS = re.compile(r"^(the\s+)?(company|merger\s*sub\w*.*|sub|purchaser|offeror|"
                           r"merger\s+subsidiary|acquisition\s+sub\w*|.*merger sub.*|"
                           r"agreement|merger agreement|merger)$", re.I)
DEFINED_TERMS = {"parent", "buyer", "purchaser", "company", "merger sub", "acquiror", "acquirer",
                 "holdco", "topco", "sub", "inc", "corp", "llc", "lp", "l p", "ltd", "plc", ""}
R_WHOLLY = re.compile(r"(?:direct\s+or\s+indirect\s+|indirect\s+|direct\s+)?wholly[- ]owned\s+"
                      r"(?:direct\s+|indirect\s+)?subsidiar(?:y|ies)\s+of\s+" + NAME +
                      r"(?=\s*\(|,|\.|;|\s+and\s|\s+that\s|\s+which\s)")
R_PE = re.compile(r"\b(funds?\s+(managed|advised|sponsored|affiliated)|investment\s+funds?|"
                  r"private\s+equity|equity\s+sponsors?|[\"“]\s*Sponsors?\s*[\"”]|Fund\s+[IVXL]+\b|"
                  r"Partners\s+[IVXL]+\b|consortium|investor\s+group|"
                  r"equity\s+commitment\s+letters?|"
                  r"(Capital|Partners|Equity|Investors?)\s+([IVXL]+\s*,?\s+)?L\.\s?P\.|"
                  r"\b(?-i:Parent|Buyer|Purchaser|Newco|Holdco)\b[^.]{0,60}?\b(affiliates?\s+of|"
                  r"controlled\s+by|owned\s+by|subsidiar\w+\s+of)\s+(funds\s+)?(?-i:[A-Z])"
                  r"[\w&.\- ]{0,40}?\b(?-i:Capital|Partners|Equity|Fund|Funds|Management)\b)", re.I)
PE_SCAN_CHARS = 100_000


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


def name_variants(name: str) -> list[str]:
    """Candidate entity strings, longest first: every trailing run of comma/'and'-separated
    chunks, with defined terms and bare suffixes removed. Used only for SEC name matching."""
    name = re.sub(r"^.*?\bsubsidiar(?:y|ies)\s+of\s+", "", name, flags=re.I)
    name = re.sub(r"^.*?\b(?:that|understand that)\s+", "", name, flags=re.I)
    chunks = [c.strip() for c in re.split(r",\s+|\s+and\s+(?=[A-Z])", name) if c.strip()]
    out = []
    for i in range(len(chunks)):
        v = clean_entity(", ".join(chunks[i:]))
        if norm_name(v) not in DEFINED_TERMS and v not in out and re.match(r"[A-Z0-9]", v):
            out.append(v)
    return out


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


def _norm_quotes(text: str) -> str:
    """Identity-extraction normalization only: tighten spaced quotes, small-caps splits
    ("T APESTRY , I NC .") and spaces before punctuation."""
    text = re.sub(r"([“\"])\s+", r"\1", text)
    text = re.sub(r"\s+([”\"])", r"\1", text)
    text = re.sub(r"\b([A-Z]) ([A-Z]{2,})\b", r"\1\2", text)
    return re.sub(r"\s+([,.](?:\s|$))", r"\1", text)


def extract_acquirer(text: str, target_name: str = "") -> dict:
    """Acquirer legal entity from merger-filing text: a defined "Parent"/"Buyer"-type party,
    else the first merger-agreement party that is neither the target nor a merger sub."""
    text = _norm_quotes(text)
    out = {"parent": "", "parent_quote": "", "ultimate": "", "ultimate_quote": "",
           "pe_signal": False, "pe_quote": "", "method": ""}
    best = None
    for m in R_DEF.finditer(text):
        if [v for v in name_variants(m.group(1))]:
            best, out["method"] = m, "defined_parent_term"
            break
    if best is None:
        tgt = norm_name(target_name).split()[:1]
        for ag in R_AGREEMENT.finditer(text):
            seg_end = ag.end() + 900
            for pm in R_PARTY.finditer(text, ag.end(), seg_end):
                term, between = pm.group(3).strip(), pm.group(2)
                if NON_ACQ_TERMS.match(term) or re.search(r"subsidiar", between, re.I):
                    continue
                vs = name_variants(pm.group(1))
                if not vs or (tgt and norm_name(vs[-1]).split()[:1] == tgt):
                    continue
                best, out["method"] = pm, "merger_agreement_party_clause"
                break
            if best is not None:
                break
    if best is None:
        return out
    m = best
    vs = name_variants(m.group(1))
    out["parent"] = vs[-1] if len(vs[-1]) >= 3 else vs[0]
    out["parent_quote"] = text[max(0, m.start() - 150): m.end() + 50].strip()[:400]
    for w in R_WHOLLY.finditer(text, m.end(), m.end() + 3000):
        uv = name_variants(w.group(1))
        if uv and norm_name(uv[-1]) not in (norm_name(out["parent"]), norm_name(target_name)):
            out["ultimate"] = uv[-1]
            out["ultimate_quote"] = text[max(0, w.start() - 120): w.end() + 40].strip()[:400]
            break
    pe = (R_PE.search(text, max(0, m.start() - 600), m.end() + 1500)
          or R_PE.search(text, 0, PE_SCAN_CHARS))
    if pe:
        out["pe_signal"] = True
        out["pe_quote"] = text[max(0, pe.start() - 200): pe.end() + 200].strip()[:400]
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


HEADER_ACQ_FORMS = {"425", "SC TO-T", "SC TO-C", "SC 14D1", "SC TO-T/A"}


def _eligible(ed, cik, ann, rec, target_cik=None):
    if target_cik is not None and int(cik) == int(target_cik):
        return None                                   # the target is never its own acquirer
    try:
        sub = ed.submissions(cik)
    except Exception as exc:
        rec["error"] = f"submissions {cik}: {exc}"
        return None
    return sub if select_filings(sub["filings"], ann) else None


def resolve_acquirer(ed, deal: dict, lookup: dict, target_filings: list[dict]) -> dict:
    ann = deal["announcement_timestamp"][:10]
    tcik = int(deal["target_cik"])
    rec = {"deal_id": deal["deal_id"], "announce_date": ann, "manifest_acquirer": deal["acquirer"],
           "deal_type": deal.get("deal_type", ""), "source_accession": "", "source_form": "",
           "source_filing_date": "", "source_acceptance_et": "", "source_basis": "",
           "extraction_method": "", "parent_entity": "", "parent_quote": "", "ultimate_parent": "",
           "ultimate_quote": "", "header_filer": "", "pe_signal": False, "pe_quote": "",
           "matched_name": "", "candidate_ciks": "", "cik": "", "sec_name": "", "sic": "",
           "sic_description": "", "manifest_name_consistent": "", "status": "",
           "unknown_reason": "", "identity_note": "", "error": ""}
    found = None
    for cand in merger_filing_candidates(deal, target_filings):
        try:
            full = ed.full_submission(tcik, cand["accession"])
        except Exception as exc:                       # recorded, never hidden
            rec["error"] = f"{cand['accession']}: {exc}"
            continue
        hdr = parse_header(full)
        hfil = [r for r in hdr["roles"] if r["role"] in ("FILER", "FILED BY") and r["cik"] != tcik]
        ex = extract_acquirer(to_text(full[:MAX_TEXT]), deal.get("target", ""))
        item = (cand, hdr, ex, hfil if hdr["form"] in HEADER_ACQ_FORMS else [])
        if ex["parent"] or item[3]:
            found = item
            break
        if found is None:
            found = item
    if found is None:
        rec.update(status="unknown", unknown_reason="fetch_error")
        return rec
    cand, hdr, ex, hfil = found
    rec.update(source_accession=cand["accession"], source_basis=cand["basis"], source_form=hdr["form"],
               source_filing_date=hdr["filing_date"], source_acceptance_et=hdr["acceptance_et"],
               extraction_method=ex["method"], parent_entity=ex["parent"],
               parent_quote=ex["parent_quote"], ultimate_parent=ex["ultimate"],
               ultimate_quote=ex["ultimate_quote"], pe_signal=ex["pe_signal"],
               pe_quote=ex["pe_quote"], error="",
               header_filer=";".join(f"{r['role']}:{r['name']}:{r['cik']}" for r in hfil))
    # (a) SEC header of a bidder-filed merger filing (425 / tender offer): registrant CIK directly
    if len({r["cik"] for r in hfil}) == 1:
        s = _eligible(ed, hfil[0]["cik"], ann, rec, tcik)
        if s and not manifest_consistent(deal["acquirer"], s["name"], hfil[0]["name"]):
            rec["identity_note"] = (f"header filer {s['name']} conflicts with manifest acquirer; "
                                    "not used")
            s = None
        if s:
            rec.update(extraction_method=(rec["extraction_method"] + "+" if rec["extraction_method"]
                                          else "") + "sec_header_filer",
                       matched_name=hfil[0]["name"], candidate_ciks=str(hfil[0]["cik"]),
                       cik=s["cik"], sec_name=s["name"], sic=s["sic"],
                       sic_description=s["sic_description"], status="resolved",
                       manifest_name_consistent=manifest_consistent(deal["acquirer"], s["name"]))
            return rec
    if not ex["parent"]:
        rec.update(status="unknown", unknown_reason="acquirer_not_identified_in_merger_filing")
        return rec
    rec["manifest_name_consistent"] = manifest_consistent(deal["acquirer"], ex["parent"], ex["ultimate"])
    # (b) exact normalized-name match of the extracted legal entity (ultimate parent first)
    for nm in [v for n in (ex["ultimate"], ex["parent"]) if n for v in name_variants(n)]:
        cands = sorted(lookup.get(norm_name(nm), set()))
        if not cands or len(cands) > MAX_CANDIDATES:
            continue
        ok = [s for s in (_eligible(ed, c, ann, rec, tcik) for c in cands) if s]
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
