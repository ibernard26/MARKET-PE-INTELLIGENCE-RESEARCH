#!/usr/bin/env python3
"""Autonomous SEC batch expansion: outcome-blind queue + fail-closed admission.

Does NOT modify EVENT_RULES, fs_v1, or break_logit_v1.
Does NOT fit models or execute walk-forward.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "sec_deal_manifest.json"
REVIEW_DIR = ROOT / "data" / "review"
UA = os.getenv("SEC_USER_AGENT", "")
MIN_INTERVAL_S = 0.12

# Import locked EVENT_RULES from the committed provider (do not redefine).
import sys
sys.path.insert(0, str(ROOT))
from src.ingest.providers.sec_edgar import EVENT_RULES, EdgarClient, matches  # noqa: E402


class RateLimitedFetcher:
    def __init__(self, user_agent: str):
        if not user_agent:
            raise RuntimeError("SEC_USER_AGENT required")
        self.ua = user_agent
        self._last = 0.0

    def get_bytes(self, url: str, timeout: int = 45) -> bytes:
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        req = urllib.request.Request(
            url, headers={"User-Agent": self.ua, "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def get_json(self, url: str, timeout: int = 45) -> Any:
        return json.loads(self.get_bytes(url, timeout=timeout).decode("utf-8", "replace"))

    def get_text(self, url: str, timeout: int = 45) -> str:
        return self.get_bytes(url, timeout=timeout).decode("utf-8", "replace")


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text())


def existing_sets(manifest: dict) -> tuple[set[str], set[int], set[str]]:
    deal_ids = {d["deal_id"] for d in manifest["deals"]}
    ciks = {int(d["target_cik"]) for d in manifest["deals"]}
    accs: set[str] = set()
    for d in manifest["deals"]:
        for k in ("announcement_accession", "terms_accession", "resolution_accession"):
            if d.get(k):
                accs.add(d[k])
    return deal_ids, ciks, accs


def efts_search(fetcher: RateLimitedFetcher, *, start: str, end: str,
                query: str, forms: str = "8-K", size: int = 100,
                max_pages: int = 20) -> list[dict]:
    """Paginate EFTS full-text search; return raw hit dicts."""
    hits: list[dict] = []
    for page in range(max_pages):
        params = {
            "q": query,
            "forms": forms,
            "dateRange": "custom",
            "startdt": start,
            "enddt": end,
            "from": page * size,
            "size": size,
        }
        url = "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(params)
        data = fetcher.get_json(url)
        batch = data.get("hits", {}).get("hits", [])
        if not batch:
            break
        hits.extend(batch)
        total = data.get("hits", {}).get("total", {})
        total_n = total.get("value", len(hits)) if isinstance(total, dict) else int(total)
        if len(hits) >= total_n or len(batch) < size:
            break
    return hits


def prior_examined_accessions() -> set[str]:
    """Accessions already decided in prior batch ledgers (continue the stream)."""
    out: set[str] = set()
    if not REVIEW_DIR.exists():
        return out
    for path in sorted(REVIEW_DIR.glob("batch_*_admission_ledger.json")):
        try:
            led = json.loads(path.read_text())
        except Exception:
            continue
        for key in ("admitted", "excluded", "deferred"):
            for rec in led.get(key) or []:
                acc = rec.get("announcement_accession")
                if acc:
                    out.add(acc)
                entry = rec.get("manifest_entry") or {}
                if entry.get("announcement_accession"):
                    out.add(entry["announcement_accession"])
    return out


def build_candidate_queue(
    fetcher: RateLimitedFetcher,
    *,
    existing_accessions: set[str],
    existing_ciks: set[int],
    year_start: int = 2014,
    year_end: int = 2020,
    target_n: int = 80,
    skip_accessions: Optional[set[str]] = None,
) -> list[dict]:
    """Outcome-blind chronological queue of Item 1.01 merger announcements.

    Selection uses announcement-time EFTS evidence only (no resolution lookup).
    """
    # Outcome-blind announcement queries (no resolution / outcome terms).
    # Prefer target-side equity M&A language + per-share consideration.
    queries = [
        '"to be acquired by" "per share in cash"',
        '"to be acquired by" "per share"',
        '"Definitive Agreement to be Acquired"',
        '"will be acquired by" "cash"',
        '"to be acquired" "per share in cash"',
    ]
    skip = set(existing_accessions) | set(skip_accessions or ()) | prior_examined_accessions()
    seen_acc: set[str] = set()
    raw: list[dict] = []
    for year in range(year_start, year_end + 1):
        start, end = f"{year}-01-01", f"{year}-12-31"
        hits = []
        for query in queries:
            try:
                hits.extend(efts_search(fetcher, start=start, end=end, query=query))
            except Exception as exc:
                print(f"WARN efts {year} q={query[:40]}: {exc}")
        for h in hits:
            src = h.get("_source", {})
            adsh = src.get("adsh")
            if not adsh or adsh in skip or adsh in seen_acc:
                continue
            items = src.get("items") or []
            if isinstance(items, str):
                items = [i.strip() for i in items.split(",") if i.strip()]
            if "1.01" not in items:
                continue
            ciks = src.get("ciks") or []
            if not ciks:
                continue
            cik = int(ciks[0])
            if cik in existing_ciks:
                continue
            # Skip exhibit-only hits; keep one row per accession.
            file_type = (src.get("file_type") or src.get("form") or "").upper()
            if file_type.startswith("EX-"):
                # Still a valid pointer to the accession; keep if not seen.
                pass
            names = src.get("display_names") or []
            target_name = names[0] if names else f"CIK{cik:010d}"
            # Strip ticker suffix from display name if present.
            target_name = re.sub(r"\s*\(CIK\s*\d+\)\s*$", "", target_name).strip()
            raw.append({
                "announcement_accession": adsh,
                "target_cik": cik,
                "target": target_name,
                "announcement_filing_date": src.get("file_date"),
                "items": items,
                "form": src.get("form") or src.get("root_forms", ["8-K"])[0],
                "initial_eligibility_basis": (
                    "EFTS 8-K hit for 'Agreement and Plan of Merger' with Item 1.01; "
                    "outcome not inspected at queue construction"
                ),
            })
            seen_acc.add(adsh)
        print(f"year {year}: queue raw unique accessions so far {len(raw)}")
        if len(raw) >= target_n * 3:
            break

    raw.sort(key=lambda r: (r["announcement_filing_date"] or "",
                            r["announcement_accession"]))
    # Freeze ranks after sort; take head of queue (chronological).
    queue = []
    for i, r in enumerate(raw[:target_n], start=1):
        queue.append({"candidate_rank": i, **r, "acquirer": None})
    return queue


def strip_html(text: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text


def filing_index(fetcher: RateLimitedFetcher, cik: int, accession: str) -> dict:
    acc_nodash = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/index.json"
    return fetcher.get_json(url)


def filing_doc_url(cik: int, accession: str, filename: str) -> str:
    acc_nodash = accession.replace("-", "")
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{acc_nodash}/{filename}")


def pick_primary_docs(index: dict) -> dict[str, list[str]]:
    """Split docs into press / 8-K body / agreement. Prefer press for terms."""
    items = index.get("directory", {}).get("item", [])
    press, body, agreement, other = [], [], [], []
    for it in items:
        name = it.get("name") or ""
        low = name.lower()
        if not low.endswith((".htm", ".html", ".txt")):
            continue
        if "index" in low:
            continue
        if re.search(r"ex[-_]?99", low):
            press.append(name)
        elif re.search(r"ex[-_]?2", low):
            agreement.append(name)
        elif re.search(r"8[-_]?k", low) or low.endswith(".txt"):
            body.append(name)
        else:
            other.append(name)
    return {"press": press, "body": body, "agreement": agreement, "other": other}


CASH_PATTERNS = [
    re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s+in\s+(?:an\s+)?(?:all[- ])?cash\s+per\s+share", re.I),
    re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s+per\s+share\s+in\s+(?:an\s+)?(?:all[- ])?cash", re.I),
    re.compile(r"(?:all[- ])?cash\s+transaction[^.]{0,40}\$\s*([0-9]+(?:\.[0-9]+)?)\s+per\s+share", re.I),
    re.compile(r"acquire[sd]?[^.]{0,60}for\s+\$\s*([0-9]+(?:\.[0-9]+)?)\s+per\s+share", re.I),
    re.compile(r"cash\s+consideration\s+of\s+\$\s*([0-9]+(?:\.[0-9]+)?)\s+per\s+share", re.I),
    re.compile(r"per\s+share\s+merger\s+consideration\s+(?:of\s+)?\$\s*([0-9]+(?:\.[0-9]+)?)", re.I),
    re.compile(r"merger\s+consideration\s+of\s+\$\s*([0-9]+(?:\.[0-9]+)?)\s+per\s+share", re.I),
    re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)\s+per\s+share", re.I),
]
RATIO_PATTERNS = [
    re.compile(r"exchange\s+ratio\s+(?:of\s+)?([0-9]+(?:\.[0-9]+)?)", re.I),
    re.compile(r"([0-9]+(?:\.[0-9]+)?)\s+shares?\s+of\s+[^.]{0,40}?common\s+stock\s+for\s+each", re.I),
    re.compile(r"([0-9]+(?:\.[0-9]+)?)\s+of\s+a\s+share\s+of", re.I),
]
ACQUIRER_PATTERNS = [
    # "Apollo Global Management, LLC (NYSE: APO) ... will acquire"
    re.compile(
        r"((?:An?\s+affiliate\s+of\s+)?[A-Z][A-Za-z0-9&.,' \-]{2,70}?)\s*"
        r"\((?:NYSE|NASDAQ|Nasdaq)[^)]*\)[^.]{0,120}?will acquire",
        re.I),
    re.compile(
        r"will be acquired by\s+((?:an?\s+affiliate\s+of\s+)?"
        r"[A-Z][A-Za-z0-9&.,' \-]{2,70}?)(?:\s*\(|,|\.)",
        re.I),
    re.compile(
        r"(?:acquired by|acquisition by|to be acquired by)\s+"
        r"((?:an?\s+affiliate\s+of\s+)?[A-Z][A-Za-z0-9&.,' \-]{2,70}?)"
        r"(?:\s*\(|,|\.)",
        re.I),
    re.compile(
        r"([A-Z][A-Za-z0-9&.,' \-]{2,70}?)\s+would acquire",
        re.I),
    re.compile(
        r"([A-Z][A-Za-z0-9&.,' \-]{2,70}?)\s+\((?:NYSE|NASDAQ|Nasdaq)[^)]*\)"
        r"[^.]{0,80}?(?:to acquire|will acquire|has agreed to acquire)",
        re.I),
]
# Narrow: only real consideration-election / proration / VWAP / CVR mechanics.
UNSUPPORTED = re.compile(
    r"(?:elect(?:ion)?\s+to\s+receive|holder(?:s)?\s+may\s+elect|"
    r"proration\s+(?:factor|provisions|mechanics)|"
    r"volume[- ]weighted\s+average\s+price|\bVWAP\b|"
    r"contingent\s+value\s+right|\bCVRs?\b|"
    r"floating\s+exchange\s+ratio|collar\s+(?:mechanism|structure))",
    re.I,
)


# High-precision target-side cash pattern (Annie's / Vocus style press).
TARGET_SIDE_CASH = re.compile(
    r"(?:to be|will be)\s+acquired\s+by\s+"
    r"((?:an?\s+affiliate\s+of\s+)?[A-Z][A-Za-z0-9&.,' \-]{1,70}?)\s+"
    r"for\s+\$\s*([0-9]+(?:\.[0-9]+)?)\s+per\s+share(?:\s+in\s+cash)?",
    re.I,
)
TARGET_SIDE_CASH_2 = re.compile(
    r"acquired\s+by\s+"
    r"((?:an?\s+affiliate\s+of\s+)?[A-Z][A-Za-z0-9&.,' \-]{1,70}?)\s+"
    r"for\s+(?:approximately\s+)?\$\s*([0-9]+(?:\.[0-9]+)?)\s+per\s+share(?:\s+in\s+(?:an\s+)?(?:all[- ])?cash)?",
    re.I,
)
# "affiliate(s) of Vector Capital ... $9.00 per share"
TARGET_SIDE_CASH_3 = re.compile(
    r"affiliates?\s+of\s+([A-Z][A-Za-z0-9&.,' \-]{1,50}?)\s+"
    r"(?:\([^)]*\)\s*)?(?:under which|pursuant to which)?[^.]{0,80}?"
    r"\$\s*([0-9]+(?:\.[0-9]+)?)\s+per\s+share",
    re.I,
)
# "to be acquired by MaxLinear" then later "$X.XX in cash and N shares"
TARGET_SIDE_ACQ_ONLY = re.compile(
    r"(?:to be|will be)\s+acquired\s+by\s+"
    r"((?:an?\s+affiliate\s+of\s+)?[A-Z][A-Za-z0-9&.,' \-]{1,70}?)"
    r"(?:\s*\(|\s+for\s+|\s+in\s+a|\s*,)",
    re.I,
)


def extract_terms(text: str) -> dict:
    """Fail-closed term extraction for fs_v1-representable structures."""
    out: dict[str, Any] = {
        "consideration_type": None,
        "offer_price": None,
        "exchange_ratio": None,
        "acquirer": None,
        "representability": "UNKNOWN",
        "reason": None,
    }
    # Search the economically relevant head of the press/body (not full EX-2.1).
    head = text[:20000]
    if UNSUPPORTED.search(head):
        out["representability"] = "REPRESENTABILITY_FAIL"
        out["reason"] = "REPRESENTABILITY_FAIL: unsupported consideration mechanics"
        return out

    # Prefer high-precision target-side cash extraction first.
    for pat in (TARGET_SIDE_CASH, TARGET_SIDE_CASH_2, TARGET_SIDE_CASH_3):
        m = pat.search(head)
        if m:
            acq = clean_acquirer_name(m.group(1))
            try:
                price = float(m.group(2))
            except ValueError:
                price = None
            if acq and price and 0.5 <= price <= 5000:
                out["consideration_type"] = "cash"
                out["offer_price"] = price
                out["acquirer"] = acq
                out["representability"] = "OK"
                return out
    m_acq = TARGET_SIDE_ACQ_ONLY.search(head)
    if m_acq:
        out["acquirer"] = clean_acquirer_name(m_acq.group(1))

    cash_vals = []
    for pat in CASH_PATTERNS:
        for m in pat.finditer(head):
            try:
                cash_vals.append(float(m.group(1)))
            except ValueError:
                pass
    ratio_vals = []
    for pat in RATIO_PATTERNS:
        for m in pat.finditer(head):
            try:
                v = float(m.group(1))
                if 0 < v < 50:
                    ratio_vals.append(v)
            except ValueError:
                pass

    for a_pat in ACQUIRER_PATTERNS:
        m = a_pat.search(head)
        if m:
            name = re.sub(r"\s+", " ", m.group(1)).strip(" ,.")
            if 3 <= len(name) <= 80 and "stockholder" not in name.lower():
                out["acquirer"] = name
                break

    uniq_cash = sorted(set(round(v, 4) for v in cash_vals if 0.5 <= v <= 5000))
    uniq_ratio = sorted(set(round(v, 6) for v in ratio_vals))

    has_cash_lang = bool(re.search(
        r"\b(?:all[- ]cash|in cash|cash consideration|cash transaction)\b", head, re.I))
    has_stock_lang = bool(re.search(
        r"\b(?:exchange ratio|shares of [^.]{0,40}common stock for each)\b", head, re.I))
    # Plain "$X per share" + "cash" nearby still counts as cash language.
    if uniq_cash and re.search(r"\bcash\b", head, re.I):
        has_cash_lang = True

    if uniq_cash and uniq_ratio and has_cash_lang and has_stock_lang:
        if len(uniq_cash) > 3 or len(uniq_ratio) > 3:
            out["representability"] = "REPRESENTABILITY_FAIL"
            out["reason"] = f"ambiguous mixed terms cash={uniq_cash[:5]} ratio={uniq_ratio[:5]}"
            return out
        out["consideration_type"] = "mixed"
        rounded_cash = [round(v, 4) for v in cash_vals if 0.5 <= v <= 5000]
        out["offer_price"] = max(uniq_cash, key=lambda v: (rounded_cash.count(v), v))
        rounded_ratio = [round(v, 6) for v in ratio_vals]
        out["exchange_ratio"] = max(uniq_ratio, key=lambda v: (rounded_ratio.count(v), -v))
        out["representability"] = "OK"
        return out

    if uniq_cash and has_cash_lang and not has_stock_lang:
        rounded_hits = [round(v, 4) for v in cash_vals if 0.5 <= v <= 5000]
        counts = {v: rounded_hits.count(v) for v in uniq_cash}
        best = max(uniq_cash, key=lambda v: (counts.get(v, 0), v))
        if len(uniq_cash) > 4:
            out["representability"] = "REPRESENTABILITY_FAIL"
            out["reason"] = f"too many distinct cash prices: {uniq_cash[:8]}"
            return out
        out["consideration_type"] = "cash"
        out["offer_price"] = best
        out["representability"] = "OK"
        return out

    if uniq_ratio and not has_cash_lang and (has_stock_lang or not uniq_cash):
        if uniq_cash:
            out["representability"] = "REPRESENTABILITY_FAIL"
            out["reason"] = (
                f"ambiguous cash+ratio without clear mixed language "
                f"cash={uniq_cash[:5]} ratio={uniq_ratio[:5]}"
            )
            return out
        if len(uniq_ratio) > 3:
            out["representability"] = "REPRESENTABILITY_FAIL"
            out["reason"] = f"ambiguous stock ratios: {uniq_ratio[:5]}"
            return out
        out["consideration_type"] = "stock"
        out["exchange_ratio"] = uniq_ratio[0]
        out["representability"] = "OK"
        return out

    out["representability"] = "REPRESENTABILITY_FAIL"
    out["reason"] = (
        f"REPRESENTABILITY_FAIL: could not faithfully map consideration under fs_v1 "
        f"(cash_vals={uniq_cash[:5]}, ratio_vals={uniq_ratio[:5]})"
    )
    return out


def ticker_token(name: str) -> str:
    """Build a short uppercase token for deal_id (not a claim of official ticker)."""
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", name).upper()
    parts = [p for p in cleaned.split() if p not in {
        "INC", "INCORPORATED", "CORP", "CORPORATION", "COMPANY", "CO", "LTD",
        "PLC", "THE", "AND", "OF", "GROUP", "HOLDINGS", "HOLDING", "LLC", "LP",
        "N", "A", "CLASS", "COMMON", "STOCK", "AFFILIATE", "AFFILIATES"}]
    if not parts:
        return "UNK"
    if len(parts[0]) >= 3:
        return parts[0][:6]
    return ("".join(parts)[:6] or "UNK")


def make_deal_id(target: str, acquirer: str, year: str) -> str:
    return f"DEAL-{ticker_token(target)}-{ticker_token(acquirer)}-{year}"


def clean_acquirer_name(name: str) -> Optional[str]:
    if not name:
        return None
    name = re.sub(r"\s+", " ", name).strip(" ,.;")
    name = re.sub(r"\S+@\S+", " ", name)  # strip emails glued into press HTML
    name = re.sub(r"\s+", " ", name).strip(" ,.;")
    name = re.sub(r"^(?:and|or)\s+", "", name, flags=re.I)
    name = re.sub(r"^(?:an?\s+)?affiliate\s+of\s+", "", name, flags=re.I)
    name = re.sub(r"\s+for\s+\$\s*[0-9].*$", "", name, flags=re.I)
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    # Truncate at common trailers
    name = re.split(
        r"\s+(?:will|to|for approximately|pursuant|has agreed)\b",
        name, maxsplit=1, flags=re.I)[0].strip(" ,.;")
    if len(name) < 3 or len(name) > 80:
        return None
    if name.lower() in {
        "purchaser", "buyer", "parent", "merger sub", "acquisition",
        "affiliate", "affiliates", "company", "the company",
        "a wholly-owned subsidiary", "wholly-owned subsidiary",
    }:
        return None
    # Drop trailing "AFFILIATE" residue from bad HTML joins.
    name = re.sub(r"\s+AFFILIATE\s*$", "", name, flags=re.I).strip()
    return name or None


_ACQ_BAD = re.compile(
    r"signing|definitive|merger agreement|exhibit|\.htm|managed by|"
    r"\binvestment funds\b|\bthe signing\b|\bannounced\b|\bagreement under\b|"
    r"\bpress release\b|\bform\s*8-k\b|\bhas agreed\b|\bpurchaser has\b|"
    r"@|\bhttp\b|\bwww\.",
    re.I,
)
_ACQ_ENTITY_SUFFIX = re.compile(
    r"\b(Inc|Incorporated|Corp|Corporation|LLC|L\.L\.C\.|Ltd|LP|L\.P\.|PLC|"
    r"Partners|Capital|Management|Company|Co|Bancorp|Bank|Holdings|Group|"
    r"Acquisition|AcquireCo|Investments|Advisors|Partnershi)\b",
    re.I,
)


def acquirer_acceptable(acquirer: str, target: str) -> tuple[bool, str]:
    if not acquirer:
        return False, "missing acquirer"
    low = acquirer.lower().strip()
    if low.startswith(("an ", "a ")) or low in {
            "the company", "the operating partnership", "the registrant"}:
        return False, f"acquirer looks non-entity: {acquirer!r}"
    if _ACQ_BAD.search(acquirer):
        return False, f"acquirer string not a clean entity name: {acquirer!r}"
    if "for $" in low or re.search(r"\$\s*\d", acquirer):
        return False, f"acquirer string still contains price residue: {acquirer!r}"
    if re.search(r"\b(operating partnership|credit agreement|indenture)\b", low):
        return False, f"acquirer not a third-party buyer: {acquirer!r}"
    if ticker_token(acquirer) == ticker_token(target):
        return False, "acquirer token equals target token (likely filer≠target confusion)"
    words = [w for w in re.split(r"\s+", acquirer) if w]
    has_suffix = bool(_ACQ_ENTITY_SUFFIX.search(acquirer))
    titleish = sum(1 for w in words if w[:1].isupper()) >= max(1, len(words) // 2)
    # Allow single-token brand/PE names (MaxLinear, GTCR, Permira, Vector).
    single_brand = (
        len(words) == 1 and len(words[0]) >= 4 and words[0][0].isupper()
        and words[0].replace("-", "").isalnum()
    )
    if not has_suffix and not (2 <= len(words) <= 6 and titleish) and not single_brand:
        return False, f"acquirer lacks entity form: {acquirer!r}"
    if len(words) > 8:
        return False, f"acquirer unreasonably long: {acquirer!r}"
    return True, "ok"


def classify_resolution_event(meta: dict) -> Optional[str]:
    """Map EDGAR meta to a single resolution label under EVENT_RULES.

    Item 1.02 matches both `terminated` and `withdrawn` by rule design; prefer
    `terminated` for 1.02. True ambiguity is 2.01/25/15 together with 1.02.
    """
    is_closed = matches("closed", meta)
    is_term = matches("terminated", meta)  # 8-K Item 1.02
    items = {i.strip() for i in (meta.get("items") or "").split(",") if i.strip()}
    form = meta.get("form", "")
    is_withdraw_only = (
        matches("withdrawn", meta)
        and not is_term
        and (form == "RW" or bool(items & {"8.01"}))
    )
    if is_closed and is_term:
        return None  # ambiguous same-filing close+terminate
    if is_term:
        return "terminated"
    if is_withdraw_only:
        return "withdrawn"
    if is_closed:
        return "closed"
    return None


def announcement_is_target_mna(text: str, target_name: str = "") -> tuple[bool, str]:
    """Require equity M&A announcement language; exclude pure financing 1.01s.

    Also fail closed on clear acquirer-side filings (filer will acquire another
    company) — those must not be admitted with the filer as `target`.
    """
    head = text[:16000]
    if re.search(r"\bcredit agreement\b", head, re.I) and not re.search(
            r"\b(merger agreement|agreement and plan of merger|will acquire|"
            r"to be acquired|per share)\b", head, re.I):
        return False, "Item 1.01 appears to be financing/credit, not equity M&A"
    if not re.search(
            r"\b(agreement and plan of merger|merger agreement|will be acquired|"
            r"to be acquired|has agreed to be acquired|will acquire)\b",
            head, re.I):
        return False, "announcement text lacks clear equity M&A language"

    target_side = bool(re.search(
        r"\b(will be acquired|to be acquired|agreed to be acquired|"
        r"to sell(?:s|ing)? itself|has agreed to sell)\b",
        head, re.I))
    # Acquirer-side: "Company will acquire TARGET" without target-side language.
    acquirer_side = bool(re.search(
        r"\b(?:the\s+)?(?:Company|Registrant)\s+will acquire\b", head, re.I))
    tok = ticker_token(target_name) if target_name else ""
    if tok and tok != "UNK":
        if re.search(rf"\b{re.escape(tok)}\b[^.]{{0,60}}\bwill acquire\b", head, re.I):
            acquirer_side = True
    # Name fragment: first meaningful word of target as subject of will acquire
    if target_name:
        first = re.sub(r"[^A-Za-z]", "", target_name.split()[0] if target_name.split() else "")
        if len(first) >= 4 and re.search(
                rf"\b{re.escape(first)}\b[^.]{{0,60}}\bwill acquire\b", head, re.I):
            acquirer_side = True
    if acquirer_side and not target_side:
        return False, (
            "announcement appears acquirer-side (filer acquiring another company); "
            "not admissible with filer as target"
        )
    return True, "ok"


def resolve_candidate(
    fetcher: RateLimitedFetcher,
    client: EdgarClient,
    cand: dict,
    existing_deal_ids: set[str],
) -> dict:
    """SEC evidence resolution → ADMIT / EXCLUDE / DEFER with reason."""
    cik = int(cand["target_cik"])
    ann_acc = cand["announcement_accession"]
    result = {
        "candidate_rank": cand["candidate_rank"],
        "target_cik": cik,
        "target": cand.get("target"),
        "announcement_accession": ann_acc,
        "announcement_filing_date": cand.get("announcement_filing_date"),
        "decision": None,
        "reason": None,
        "manifest_entry": None,
    }
    try:
        meta = client.filing(cik, ann_acc)
    except Exception as exc:
        result["decision"] = "DEFER"
        result["reason"] = f"announcement metadata unavailable: {exc}"
        return result

    if not matches("announcement", meta):
        result["decision"] = "EXCLUDE"
        result["reason"] = (
            f"EVENT_RULES announcement fail: form={meta.get('form')} "
            f"items={meta.get('items')}"
        )
        return result

    # Load filing text for terms (announcement-time snapshot only).
    # Prefer EX-99.x press releases; fall back to 8-K body. Avoid EX-2.1 for
    # primary extraction (boilerplate triggers false representability fails).
    try:
        idx = filing_index(fetcher, cik, ann_acc)
        groups = pick_primary_docs(idx)
        text = ""
        for group_name in ("press", "body", "other"):
            blobs = []
            for name in groups.get(group_name, [])[:3]:
                try:
                    blobs.append(strip_html(
                        fetcher.get_text(filing_doc_url(cik, ann_acc, name))))
                except urllib.error.HTTPError as exc:
                    if exc.code in (503, 429):
                        result["decision"] = "DEFER"
                        result["reason"] = f"filing text fetch failed: {exc}"
                        return result
                    continue
                except Exception:
                    continue
            text = " ".join(blobs)
            if len(text) >= 400:
                break
        if len(text) < 200:
            result["decision"] = "DEFER"
            result["reason"] = "announcement filing text unavailable or too short"
            return result
    except Exception as exc:
        result["decision"] = "DEFER"
        result["reason"] = f"filing text fetch failed: {exc}"
        return result

    ok_mna, mna_reason = announcement_is_target_mna(text, cand.get("target") or "")
    if not ok_mna:
        result["decision"] = "EXCLUDE"
        result["reason"] = mna_reason
        return result

    terms = extract_terms(text)
    if terms["representability"] != "OK":
        result["decision"] = "EXCLUDE"
        result["reason"] = terms.get("reason") or "REPRESENTABILITY_FAIL"
        result["terms_extract"] = terms
        return result

    acquirer = clean_acquirer_name(terms.get("acquirer") or cand.get("acquirer") or "")
    if not acquirer:
        m = re.search(
            r"(?:affiliate of\s+)?([A-Z][^,]{2,70}?)(?:\s*\([^)]+\))?\s+"
            r"(?:will acquire|to acquire|has agreed to acquire)",
            text[:16000], re.I)
        if m:
            acquirer = clean_acquirer_name(m.group(1))
    if not acquirer:
        m = re.search(
            r"Agreement and Plan of Merger[^.]{0,40}(?:by and )?among\s+([^,]{3,80}),",
            text, re.I)
        if m:
            acquirer = clean_acquirer_name(m.group(1))
    ok_acq, acq_reason = acquirer_acceptable(
        acquirer or "", cand.get("target") or "")
    if not ok_acq:
        result["decision"] = "DEFER"
        result["reason"] = f"acquirer validation: {acq_reason}"
        result["terms_extract"] = terms
        return result

    # If press says someone "will acquire <acquirer>", we swapped parties.
    acq_core = re.sub(r"[^A-Za-z0-9 ]+", " ", acquirer).split()
    acq_core = [w for w in acq_core if w.upper() not in {
        "INC", "INCORPORATED", "CORP", "CORPORATION", "LLC", "LTD", "THE", "AND"}]
    if acq_core:
        needle = re.escape(acq_core[0])
        if re.search(rf"\bwill acquire\s+{needle}\b", text[:16000], re.I):
            result["decision"] = "EXCLUDE"
            result["reason"] = (
                "party inversion: extracted acquirer is the acquiree in "
                "'will acquire' prose"
            )
            result["terms_extract"] = terms
            return result

    # Resolution: scan submissions AFTER announcement for closed/terminated/withdrawn.
    try:
        client.filing(cik, ann_acc)
        idx_map = client._cache.get(cik, {})
    except Exception as exc:
        result["decision"] = "DEFER"
        result["reason"] = f"submissions history unavailable: {exc}"
        return result

    ann_date = (meta.get("filingDate") or cand.get("announcement_filing_date") or "")[:10]

    resolutions = []
    ambiguous_res_accs = []
    for acc, mmeta in idx_map.items():
        if acc == ann_acc:
            continue
        fdate = (mmeta.get("filingDate") or "")[:10]
        if fdate and ann_date and fdate < ann_date:
            continue
        label = classify_resolution_event(mmeta)
        if label is None:
            # Distinguish "no match" from "ambiguous close+terminate"
            if matches("closed", mmeta) and matches("terminated", mmeta):
                ambiguous_res_accs.append(acc)
            continue
        resolutions.append((label, acc, mmeta))

    if ambiguous_res_accs and not resolutions:
        result["decision"] = "DEFER"
        result["reason"] = (
            f"ambiguous resolution filing(s) with both close and terminate items: "
            f"{ambiguous_res_accs[:3]}"
        )
        return result

    if not resolutions:
        result["decision"] = "DEFER"
        result["reason"] = "no EVENT_RULES resolution filing found after announcement"
        result["terms_extract"] = terms
        return result

    resolutions.sort(key=lambda x: (
        x[2].get("acceptanceDateTime") or x[2].get("filingDate") or ""))
    types = {r[0] for r in resolutions}
    # Contradictory lifecycle across filings → DEFER
    if (("terminated" in types or "withdrawn" in types) and "closed" in types):
        result["decision"] = "DEFER"
        result["reason"] = (
            "contradictory resolution filings (both close and terminate/withdraw present)"
        )
        return result
    pick = resolutions[0]

    res_type, res_acc, res_meta = pick
    res_date = (res_meta.get("filingDate") or "")[:10]
    if ann_date and res_date and ann_date == res_date and res_type == "closed":
        result["decision"] = "DEFER"
        result["reason"] = "same-day announcement and close (likely non-standard / internalization)"
        return result

    year = ann_date[:4] if ann_date else "0000"
    deal_id = make_deal_id(cand.get("target") or f"CIK{cik}", acquirer, year)
    if deal_id in existing_deal_ids:
        deal_id = f"{deal_id}-{cik}"
    if deal_id in existing_deal_ids:
        result["decision"] = "EXCLUDE"
        result["reason"] = f"duplicate deal_id {deal_id}"
        return result

    deal_type = "strategic"
    if re.search(r"take[- ]private|going private", text[:10000], re.I):
        deal_type = "take_private"

    # Clean target display name
    target_name = re.sub(r"\s*\(CIK\s*\d+\)\s*$", "", cand.get("target") or "")
    target_name = re.sub(r"\s*\([^)]*\)\s*$", "", target_name).strip() or f"CIK{cik:010d}"

    entry = {
        "deal_id": deal_id,
        "target": target_name,
        "acquirer": acquirer,
        "target_cik": cik,
        "announcement_accession": ann_acc,
        "terms_accession": ann_acc,
        "announcement_timestamp": ann_date,
        "deal_type": deal_type,
        "consideration_type": terms["consideration_type"],
        "resolution_type": res_type,
        "resolution_accession": res_acc,
        "resolution_timestamp": res_date,
    }
    if terms.get("offer_price") is not None:
        entry["offer_price"] = terms["offer_price"]
    if terms.get("exchange_ratio") is not None:
        entry["exchange_ratio"] = terms["exchange_ratio"]

    # Schema completeness for HistoricalDealRecord
    if entry["consideration_type"] == "cash" and entry.get("offer_price") is None:
        result["decision"] = "EXCLUDE"
        result["reason"] = "cash deal missing offer_price"
        return result
    if entry["consideration_type"] == "stock" and entry.get("exchange_ratio") is None:
        result["decision"] = "EXCLUDE"
        result["reason"] = "stock deal missing exchange_ratio"
        return result
    if entry["consideration_type"] == "mixed" and (
            entry.get("offer_price") is None or entry.get("exchange_ratio") is None):
        result["decision"] = "EXCLUDE"
        result["reason"] = "mixed deal missing offer_price or exchange_ratio"
        return result

    result["decision"] = "ADMIT"
    result["reason"] = (
        f"EVENT_RULES pass; fs_v1 {entry['consideration_type']}; "
        f"resolution={res_type} via {res_acc}"
    )
    result["manifest_entry"] = entry
    result["terms_extract"] = terms
    return result


def cmd_build_queue(args: argparse.Namespace) -> int:
    fetcher = RateLimitedFetcher(UA)
    manifest = load_manifest()
    _, ciks, accs = existing_sets(manifest)
    queue = build_candidate_queue(
        fetcher,
        existing_accessions=accs,
        existing_ciks=ciks,
        year_start=args.year_start,
        year_end=args.year_end,
        target_n=args.target_n,
    )
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEW_DIR / f"batch_{args.batch}_candidate_queue.json"
    payload = {
        "batch_iteration": args.batch,
        "selection_method": "efts_chronological_item_101_merger_agreement",
        "outcome_blind": True,
        "probability_calibration_eligible_claim": False,
        "year_window": [args.year_start, args.year_end],
        "n_candidates": len(queue),
        "candidates": queue,
        "notes": [
            "Ranks frozen before any resolution inspection.",
            "Corpus remains a research corpus; not a population sample.",
        ],
    }
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps({"wrote": str(out), "n_candidates": len(queue)}, indent=2))
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    fetcher = RateLimitedFetcher(UA)
    client = EdgarClient(user_agent=UA)
    manifest = load_manifest()
    deal_ids, _, _ = existing_sets(manifest)
    qpath = REVIEW_DIR / f"batch_{args.batch}_candidate_queue.json"
    queue = json.loads(qpath.read_text())["candidates"]
    ledger = {
        "batch_iteration": args.batch,
        "max_admit": args.max_admit,
        "admitted": [],
        "excluded": [],
        "deferred": [],
        "examined": 0,
    }
    for cand in queue:
        if len(ledger["admitted"]) >= args.max_admit:
            break
        print(f"resolving rank={cand['candidate_rank']} cik={cand['target_cik']} "
              f"acc={cand['announcement_accession']} ...", flush=True)
        rec = resolve_candidate(fetcher, client, cand, deal_ids)
        ledger["examined"] += 1
        decision = rec["decision"]
        if decision == "ADMIT":
            entry = rec["manifest_entry"]
            deal_ids.add(entry["deal_id"])
            ledger["admitted"].append(rec)
            print(f"  ADMIT {entry['deal_id']}", flush=True)
        elif decision == "EXCLUDE":
            ledger["excluded"].append(rec)
            print(f"  EXCLUDE {rec['reason'][:120]}", flush=True)
        else:
            ledger["deferred"].append(rec)
            print(f"  DEFER {rec['reason'][:120]}", flush=True)

    out = REVIEW_DIR / f"batch_{args.batch}_admission_ledger.json"
    out.write_text(json.dumps(ledger, indent=2) + "\n")
    print(json.dumps({
        "wrote": str(out),
        "examined": ledger["examined"],
        "admitted": len(ledger["admitted"]),
        "excluded": len(ledger["excluded"]),
        "deferred": len(ledger["deferred"]),
    }, indent=2))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """Append ADMIT entries to canonical manifest (sorted append: keep prior order, add new)."""
    manifest = load_manifest()
    ledger = json.loads((REVIEW_DIR / f"batch_{args.batch}_admission_ledger.json").read_text())
    existing_ids = {d["deal_id"] for d in manifest["deals"]}
    added = []
    for rec in ledger["admitted"]:
        entry = rec["manifest_entry"]
        if entry["deal_id"] in existing_ids:
            continue
        manifest["deals"].append(entry)
        existing_ids.add(entry["deal_id"])
        added.append(entry["deal_id"])
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"added": added, "new_n": len(manifest["deals"])}, indent=2))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    bq = sub.add_parser("build-queue")
    bq.add_argument("--batch", type=int, required=True)
    bq.add_argument("--year-start", type=int, default=2014)
    bq.add_argument("--year-end", type=int, default=2018)
    bq.add_argument("--target-n", type=int, default=80)
    bq.set_defaults(func=cmd_build_queue)

    rs = sub.add_parser("resolve")
    rs.add_argument("--batch", type=int, required=True)
    rs.add_argument("--max-admit", type=int, default=20)
    rs.set_defaults(func=cmd_resolve)

    ap_apply = sub.add_parser("apply")
    ap_apply.add_argument("--batch", type=int, required=True)
    ap_apply.set_defaults(func=cmd_apply)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
