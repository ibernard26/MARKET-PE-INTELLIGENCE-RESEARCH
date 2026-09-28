"""Proof C: contemporaneous SEC evidence that a ticker was the target's.

A deal's historical ticker is RESOLVED_PROOF_C only when a filing that meets
all of the following contains the ticker in an exchange/symbol context:

  * filed by the target itself (filer CIK == target CIK)
  * of an allowed form (target cover pages and merger documents)
  * filed within [announcement − 365 days, resolution] (or announcement + 365
    days if unresolved)

Current SEC metadata (submissions `tickers`), today's symbology, the deal_id
convention and filings from after the deal window never qualify, so modern
ticker reuse cannot produce a proof.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Optional

RESOLVED = "RESOLVED_PROOF_C"
STILL_AMBIGUOUS = "STILL_AMBIGUOUS"
NO_EVIDENCE = "NO_SUFFICIENT_EVIDENCE"

# Target-filed forms whose text states the target's trading symbol, in fixed
# review priority: merger documents first (they name the listing), then
# periodic-report cover pages (symbols on covers only from 2019), then 8-K.
ALLOWED_FORMS = ("DEFM14A", "PREM14A", "SC 14D9", "SC 13E3", "10-K", "10-Q",
                 "DEFA14A", "8-K")
LOOKBACK_DAYS = 365
UNRESOLVED_LOOKAHEAD_DAYS = 365

_EXCH = (r"(?:NYSE(?:\s+(?:American|MKT|Arca))?|New York Stock Exchange|"
         r"NASDAQ|Nasdaq(?:\s+(?:Global Select|Global|Capital)\s+Market)?|"
         r"The Nasdaq Stock Market(?:\s+LLC)?)")
_Q_OPEN, _Q_CLOSE = r"[\"'“‘]", r"[\"'”’]"


def _patterns(ticker: str) -> list[re.Pattern]:
    t = re.escape(ticker)
    return [
        re.compile(rf"\b{_EXCH}\s*:\s*{t}\b"),
        re.compile(rf"(?:ticker|trading)?\s*symbol\s+{_Q_OPEN}{t}{_Q_CLOSE}", re.I),
        re.compile(rf"Trading\s+Symbol\(?s?\)?.{{0,400}}?(?<![A-Za-z]){t}(?![A-Za-z])",
                   re.S),
    ]


_ANY_SYMBOL = re.compile(rf"\b{_EXCH}\s*:\s*([A-Z]{{1,5}}(?:\.[A-Z])?)\b")


def html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))).strip()


@dataclass(frozen=True)
class Filing:
    accession: str
    form: str
    filing_date: str
    filer_cik: int
    primary_document: str
    url: str


@dataclass
class Evidence:
    deal_id: str
    ticker: str
    accession: str
    form: str
    filing_date: str
    filer_cik: int
    url: str
    document_sha256: str
    matched: bool
    snippet: Optional[str] = None
    other_symbols: list[str] = field(default_factory=list)
    reject_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def evidence_window(announcement: str, resolution: Optional[str]) -> tuple[date, date]:
    a = date.fromisoformat(announcement[:10])
    end = (date.fromisoformat(resolution[:10]) if resolution
           else a + timedelta(days=UNRESOLVED_LOOKAHEAD_DAYS))
    return a - timedelta(days=LOOKBACK_DAYS), max(a, end)


def admissible_filing(f: Filing, target_cik: int, announcement: str,
                      resolution: Optional[str]) -> Optional[str]:
    """None if the filing may serve as Proof C evidence, else the reason not."""
    if int(f.filer_cik) != int(target_cik):
        return "FILER_NOT_TARGET"
    if f.form not in ALLOWED_FORMS:
        return "FORM_NOT_ALLOWED"
    lo, hi = evidence_window(announcement, resolution)
    if not lo <= date.fromisoformat(f.filing_date[:10]) <= hi:
        return "NOT_CONTEMPORANEOUS"
    return None


def extract(deal_id: str, ticker: str, f: Filing, raw_document: str, target_cik: int,
            announcement: str, resolution: Optional[str]) -> Evidence:
    sha = hashlib.sha256(raw_document.encode("utf-8", "replace")).hexdigest()
    ev = Evidence(deal_id=deal_id, ticker=ticker, accession=f.accession, form=f.form,
                  filing_date=f.filing_date, filer_cik=f.filer_cik, url=f.url,
                  document_sha256=sha, matched=False)
    reason = admissible_filing(f, target_cik, announcement, resolution)
    if reason:
        ev.reject_reason = reason
        return ev
    text = html_to_text(raw_document)
    ev.other_symbols = sorted({m.group(1) for m in _ANY_SYMBOL.finditer(text)} - {ticker})
    for p in _patterns(ticker):
        m = p.search(text)
        if m:
            ev.matched = True
            ev.snippet = text[max(0, m.start() - 120): m.end() + 120]
            break
    return ev


def classify(evidence: list[Evidence]) -> dict:
    """Deal-level status from its evidence records (never forced)."""
    good = [e for e in evidence if e.reject_reason is None]
    hits = sorted((e for e in good if e.matched), key=lambda e: (e.filing_date, e.accession))
    if hits:
        best = hits[0]
        return {"status": RESOLVED, "sec_accession": best.accession,
                "sec_filed_date": best.filing_date, "form": best.form,
                "evidence_url": best.url, "snippet": best.snippet,
                "n_supporting_documents": len(hits)}
    if good and any(e.other_symbols for e in good):
        return {"status": STILL_AMBIGUOUS,
                "note": "target-filed contemporaneous documents cite other symbols only",
                "other_symbols": sorted({s for e in good for s in e.other_symbols})}
    return {"status": NO_EVIDENCE,
            "n_admissible_documents": len(good), "n_documents": len(evidence)}
