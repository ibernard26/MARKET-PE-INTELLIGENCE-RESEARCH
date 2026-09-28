"""Outcome-blind Proof C identity review.

Review order is lexicographic deal_id. Outcome labels (resolution_type,
status, broken/closed) are not inputs to ordering or to ticker extraction.

Proof C requires a contemporaneous SEC filing (accession + filing date + form)
that names the historical ticker. Modern company_tickers.json reuse and the
DEAL-{TICKER}-… convention are not Proof C.
"""
from __future__ import annotations

import html as htmlmod
import re
from datetime import date, timedelta
from typing import Iterable, Optional

from .identity import (
    CONTEMPORANEOUS_LOOKBACK_DAYS,
    REVIEWED_SEC_BASIS,
    SEC_ACCESSION,
    deal_id_ticker,
    reviewed_sec_evidence,
)
from ..security_identity.name_match import significant_tokens

PROOF_C = "C_REVIEWED_SEC_MAPPING"
RESOLVED_PROOF_C = "RESOLVED_PROOF_C"
STILL_AMBIGUOUS = "STILL_AMBIGUOUS"
NO_SUFFICIENT_EVIDENCE = "NO_SUFFICIENT_EVIDENCE"
STATUSES = (RESOLVED_PROOF_C, STILL_AMBIGUOUS, NO_SUFFICIENT_EVIDENCE)

PROOF_C_FORMS = frozenset({
    "8-K", "8-K/A",
    "DEFM14A", "PREM14A", "DEFA14A", "PREC14A", "DEFM14C", "PREM14C",
    "SC TO-T", "SC TO-T/A", "SC TO-C", "SC TO-C/A", "SC TO-I", "SC TO-I/A",
    "SC 13E-3", "SC 13E-3/A", "SC 13E3", "SC 13E3/A",
    "S-4", "S-4/A",
    "425",
})
PREFERRED_8K_ITEMS = frozenset({"1.01"})

DEI_TICKER = re.compile(
    r"(?:name=\"dei:TradingSymbol\"[^>]*>|>)?\s*([A-Z][A-Z0-9.]{0,4})\s*<",
    re.I,
)
DEI_TICKER_ATTR = re.compile(
    r"dei:TradingSymbol[^>]*>([A-Z][A-Z0-9.]{0,4})<",
    re.I,
)
SGML_TICKER = re.compile(r"<TICKER>\s*([A-Z][A-Z0-9.]{0,4})", re.I)
SGML_EXCHANGE = re.compile(r"<EXCHANGE>\s*([A-Za-z0-9 .\-]{2,40})", re.I)
PAREN_TICKER = re.compile(
    r"\((?:NASDAQ|NYSE(?:\s+(?:American|MKT|Arca))?|AMEX|OTCQX|OTCQB|"
    r"The Nasdaq(?: Capital| Global(?: Select)?)? Market|"
    r"New York Stock Exchange)[:\s]+([A-Z][A-Z0-9.]{0,4})\)",
    re.I,
)
COVER_TICKER_EXCHANGE = re.compile(
    r"\b([A-Z]{1,5})\s+(?:The\s+)?(?:NASDAQ|NYSE|New York Stock Exchange|Nasdaq Stock Market)\b",
)
INVALID_TICKERS = frozenset({
    "NAME", "THE", "CLASS", "STOCK", "SHARE", "COMMON", "FORM", "ITEM", "DATE",
    "AND", "FOR", "FROM", "THIS", "THAT", "WITH", "NYSE", "NASDA", "AMEX",
    "EXCHA", "INDIC", "YORK", "TITLE", "EACH", "WHICH", "REGIS", "TABLE",
    "PAGE", "UNITED", "STATE", "COMMI", "UNDER", "SECUR",
})
EXCHANGE_NEAR = re.compile(
    r"(NASDAQ|NYSE|NYSE American|NYSE Arca|The Nasdaq Stock Market|New York Stock Exchange)",
    re.I,
)

# Outcome fields that must never affect review order or prioritization.
OUTCOME_FIELDS = frozenset({
    "resolution_type", "status", "label", "y", "broken", "p_break",
    "primary_break_vector", "outcome",
})


def identity_review_order(deal_ids: Iterable[str]) -> list[str]:
    """Deterministic lexicographic deal_id order. No outcome key."""
    return sorted(deal_ids)


def deferred_rows_in_review_order(rows: Iterable[dict]) -> list[dict]:
    """Sort coverage rows by deal_id. Outcome fields, if present, are ignored."""
    deferred = [r for r in rows if r.get("canonical_status") == "DEFERRED_IDENTITY"]
    return sorted(deferred, key=lambda r: r["deal_id"])


def assert_outcome_blind_order(rows: list[dict]) -> list[str]:
    """Same order even if rows are pre-sorted by any outcome field."""
    lex = [r["deal_id"] for r in deferred_rows_in_review_order(rows)]
    scrambled = sorted(
        deferred_rows_in_review_order(rows),
        key=lambda r: (str(r.get("resolution_type") or ""), r["deal_id"]),
        reverse=True,
    )
    again = [r["deal_id"] for r in deferred_rows_in_review_order(scrambled)]
    if lex != again:
        raise AssertionError("identity review order must ignore outcome fields")
    return lex


def contemporaneous_bounds(announcement: str, resolution: Optional[str] = None) -> tuple[date, date]:
    """Same window as reviewed_sec_evidence: [ann-365d, max(ann, resolution)].

    Resolution here is a filing-date cutoff, not an outcome label, and is not
    used to order deals.
    """
    a = date.fromisoformat(announcement[:10])
    r = date.fromisoformat(resolution[:10]) if resolution else a
    return a - timedelta(days=CONTEMPORANEOUS_LOOKBACK_DAYS), max(a, r)


def filing_is_contemporaneous(filed: str, announcement: str,
                              resolution: Optional[str] = None) -> bool:
    lo, hi = contemporaneous_bounds(announcement, resolution)
    try:
        f = date.fromisoformat(filed[:10])
    except ValueError:
        return False
    return lo <= f <= hi


def ticker_reuse_or_convention_is_not_proof(
        *,
        ticker: Optional[str],
        source: Optional[str],
        deal_id: Optional[str] = None,
) -> bool:
    """True when the ticker claim is not Proof C."""
    src = (source or "").lower()
    if src in {"sec_company_tickers", "company_tickers.json", "deal_id_convention"}:
        return True
    if deal_id and ticker and deal_id_ticker(deal_id) == ticker.upper() and "accession" not in src:
        if src in {"", "deal_id", "heuristic"}:
            return True
    return False


def qualifies_as_proof_c(row: dict, announcement: str,
                         resolution: Optional[str] = None) -> bool:
    """Accession + contemporaneous filed date. Self-declared basis is ignored."""
    if ticker_reuse_or_convention_is_not_proof(
            ticker=row.get("ticker") or row.get("historical_ticker"),
            source=row.get("source") or row.get("identity_basis") or row.get("ticker_basis"),
            deal_id=row.get("deal_id")):
        if not (row.get("sec_accession") and row.get("sec_filed_date")):
            return False
    return reviewed_sec_evidence(row, announcement[:10] if announcement else None,
                                 (resolution or "")[:10] or None)


def _strip_markup(text: str) -> str:
    t = re.sub(r"(?is)<script.*?</script>", " ", text)
    t = re.sub(r"(?is)<style.*?</style>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmlmod.unescape(t)
    t = t.replace("\xa0", " ")
    return re.sub(r"\s+", " ", t)


def extract_header_ticker(raw: str) -> Optional[str]:
    m = SGML_TICKER.search(raw)
    return m.group(1).upper() if m else None


def extract_header_exchange(raw: str) -> Optional[str]:
    m = SGML_EXCHANGE.search(raw)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def extract_dei_tickers(raw: str) -> list[str]:
    found = [m.upper() for m in DEI_TICKER_ATTR.findall(raw)]
    # iXBRL sometimes uses name="dei:TradingSymbol" ... >HCP</ix:nonNumeric>
    extra = re.findall(
        r'name="dei:TradingSymbol"[^>]*>\s*([A-Z][A-Z0-9.]{0,4})\s*<',
        raw, flags=re.I)
    for t in extra:
        found.append(t.upper())
    # unique, stable
    out, seen = [], set()
    for t in found:
        if t not in seen and t not in {"ISO", "USD", "FORM"}:
            seen.add(t)
            out.append(t)
    return out


def extract_cover_ticker(plain: str) -> Optional[str]:
    idx = plain.lower().find("trading symbol")
    if idx < 0:
        return None
    region = plain[idx: idx + 600]
    m = COVER_TICKER_EXCHANGE.search(region)
    if not m:
        return None
    tok = m.group(1).upper()
    if tok in INVALID_TICKERS:
        return None
    return tok


def extract_parenthetical_tickers(plain: str) -> list[tuple[str, int]]:
    return [(m.group(1).upper(), m.start()) for m in PAREN_TICKER.finditer(plain)]


def ticker_near_target_name(plain: str, target_name: Optional[str]) -> Optional[str]:
    """Parenthetical ticker whose span sits next to the target's significant tokens."""
    tokens = [t for t in sorted(significant_tokens(target_name), key=len, reverse=True) if len(t) >= 4]
    if not tokens:
        tokens = [t for t in sorted(significant_tokens(target_name), key=len, reverse=True)]
    hits = extract_parenthetical_tickers(plain)
    if not hits:
        return None
    lower = plain.lower()
    scored = []
    for ticker, pos in hits:
        # Issuer names precede "(NASDAQ: TICKER)". Do not look forward —
        # that would score the acquirer's ticker using the target's later name.
        window = lower[max(0, pos - 50): pos]
        score = sum(1 for tok in tokens if tok in window)
        scored.append((score, -pos, ticker))
    scored.sort(reverse=True)
    if scored and scored[0][0] > 0:
        best = scored[0][0]
        best_tickers = {t for s, _, t in scored if s == best}
        if len(best_tickers) == 1:
            return next(iter(best_tickers))
    return None


def extract_identity_from_filing(
        raw: str,
        *,
        target_name: Optional[str],
        filer_is_target: bool,
) -> dict:
    """Pull ticker/exchange evidence from one filing body + header."""
    plain = _strip_markup(raw)
    header = extract_header_ticker(raw)
    dei = extract_dei_tickers(raw)
    cover = extract_cover_ticker(plain)
    near = ticker_near_target_name(plain, target_name)
    exchange = extract_header_exchange(raw)
    if not exchange:
        m = EXCHANGE_NEAR.search(plain)
        exchange = m.group(1) if m else None

    chosen = None
    location = None
    if filer_is_target and dei:
        cand = next((t for t in dei if t not in INVALID_TICKERS), None)
        if cand:
            chosen = cand
            location = "dei:TradingSymbol"
    elif filer_is_target and cover and cover not in INVALID_TICKERS:
        chosen = cover
        location = "8-K_cover_trading_symbol"
    elif filer_is_target and header and header not in INVALID_TICKERS:
        chosen = header
        location = "SEC_HEADER_TICKER"
    elif near and near not in INVALID_TICKERS:
        chosen = near
        location = "parenthetical_ticker_adjacent_to_target_name"

    return {
        "historical_ticker": chosen,
        "exchange": exchange,
        "evidence_location": location,
        "header_ticker": header,
        "dei_tickers": dei,
        "cover_ticker": cover,
        "name_adjacent_ticker": near,
        "parenthetical_tickers": [t for t, _ in extract_parenthetical_tickers(plain)],
    }


def prefer_filings(filings: list[dict]) -> list[dict]:
    """Deterministic rank: 8-K item 1.01, other 8-K, proxy/S-4/TO/13E-3, 425."""
    def key(f: dict) -> tuple:
        form = f.get("form") or ""
        items = {i.strip() for i in (f.get("items") or "").split(",") if i.strip()}
        pref = 3
        if form in {"8-K", "8-K/A"} and items & PREFERRED_8K_ITEMS:
            pref = 0
        elif form in {"8-K", "8-K/A"}:
            pref = 1
        elif form in {"DEFM14A", "PREM14A", "S-4", "S-4/A", "SC TO-T", "SC 13E-3", "SC 13E3"}:
            pref = 2
        return (pref, f.get("filingDate") or "", f.get("accessionNumber") or "")
    return sorted(filings, key=key)


def classify_extracted(
        extracted: dict,
        *,
        deal_id: str,
        modern_ticker: Optional[str] = None,
) -> str:
    """Status for one filing's extraction. Convention/reuse cannot resolve."""
    ticker = extracted.get("historical_ticker")
    if not ticker:
        return NO_SUFFICIENT_EVIDENCE
    if modern_ticker and ticker.upper() == modern_ticker.upper() and extracted.get("evidence_location") is None:
        return NO_SUFFICIENT_EVIDENCE
    if extracted.get("evidence_location") is None:
        return NO_SUFFICIENT_EVIDENCE
    parentheticals = set(extracted.get("parenthetical_tickers") or [])
    dei = set(extracted.get("dei_tickers") or [])
    if len(parentheticals) > 1 and extracted.get("evidence_location") == "parenthetical_ticker_adjacent_to_target_name":
        if extracted.get("name_adjacent_ticker"):
            return RESOLVED_PROOF_C
        return STILL_AMBIGUOUS
    if len(dei) > 1 and extracted.get("evidence_location") == "dei:TradingSymbol":
        if ticker != deal_id_ticker(deal_id):
            # still resolved from the filer's first DEI symbol
            return RESOLVED_PROOF_C
    return RESOLVED_PROOF_C


def review_record(
        *,
        deal_id: str,
        historical_ticker: Optional[str],
        exchange: Optional[str],
        sec_accession: Optional[str],
        filing_date: Optional[str],
        form: Optional[str],
        evidence_location: Optional[str],
        identity_rationale: str,
        status: str,
        announcement_date: Optional[str] = None,
        target_name: Optional[str] = None,
        target_cik: Optional[int] = None,
        review_order_index: Optional[int] = None,
) -> dict:
    if status not in STATUSES:
        raise ValueError(status)
    rec = {
        "deal_id": deal_id,
        "historical_ticker": historical_ticker,
        "exchange": exchange,
        "sec_accession": sec_accession,
        "filing_date": filing_date,
        "form": form,
        "evidence_location": evidence_location,
        "identity_rationale": identity_rationale,
        "status": status,
        "review_order_index": review_order_index,
        "announcement_date": announcement_date,
        "target_name": target_name,
        "target_cik": target_cik,
    }
    return rec


def map_row_from_review(rec: dict) -> Optional[dict]:
    """target_ticker_map.json row that can earn REVIEWED_SEC_BASIS."""
    if rec.get("status") != RESOLVED_PROOF_C:
        return None
    if not rec.get("historical_ticker") or not rec.get("sec_accession"):
        return None
    return {
        "deal_id": rec["deal_id"],
        "ticker": rec["historical_ticker"],
        "exchange": rec.get("exchange"),
        "sec_accession": rec["sec_accession"],
        "sec_filed_date": rec["filing_date"],
        "sec_form": rec.get("form"),
        "source_identifier": rec.get("evidence_location"),
        "basis_earned": REVIEWED_SEC_BASIS,
        "proof": PROOF_C,
    }
