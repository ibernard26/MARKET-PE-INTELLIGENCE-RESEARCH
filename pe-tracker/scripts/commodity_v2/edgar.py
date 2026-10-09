"""SEC EDGAR access for commodity-exposure v2.

The SEC contact address is taken ONLY from the SEC_CONTACT_EMAIL environment
variable at runtime. There is no default; any network fetch is refused when it
is unset. The address is never written to disk by this module.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data" / "sec_deal_manifest.json"
CACHE_V2 = ROOT / "data" / "cache" / "edgar_commodity_v2"     # gitignored (data/cache/)
CACHE_V1 = ROOT / "data" / "cache" / "edgar_commodity_v1"     # read-only reuse, if present
MIN_INTERVAL_S = 0.12                                        # <= ~8 req/s (SEC limit: 10/s)
UA_PREFIX = "MARKET-PE-INTELLIGENCE-RESEARCH research"
ET = ZoneInfo("America/New_York")

WINDOW_DAYS = 550
ANNUAL_FORMS = {"10-K", "10-K405", "10-KT", "10-KSB", "20-F", "40-F"}
QUARTERLY_FORMS = {"10-Q", "10-QSB"}


class FetchRefused(RuntimeError):
    """Raised when a network fetch is attempted without SEC_CONTACT_EMAIL or offline."""


_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def user_agent() -> str:
    email = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if not email:
        raise FetchRefused("SEC_CONTACT_EMAIL is not set; refusing to contact SEC EDGAR")
    if not _EMAIL.match(email):
        raise FetchRefused("SEC_CONTACT_EMAIL is not a valid email address")
    return f"{UA_PREFIX} {email}"


class Edgar:
    """Cache-first EDGAR client. offline=True never touches the network."""

    def __init__(self, offline: bool = False, cache_dirs=None, session=None):
        self.offline = offline
        self.cache_dirs = list(cache_dirs) if cache_dirs else [CACHE_V2, CACHE_V1]
        self.write_dir = self.cache_dirs[0]
        self._ua = None if offline else user_agent()   # refuse early if unset
        self._session = session
        self._last = 0.0
        self.requests_made = 0

    def _cached(self, name: str):
        for d in self.cache_dirs:
            p = d / name
            if p.exists():
                return p
        return None

    def get(self, url: str, cache_name: str) -> bytes:
        p = self._cached(cache_name)
        if p is not None:
            return p.read_bytes()
        if self.offline:
            raise FetchRefused(f"offline mode: {cache_name} not cached")
        if self._session is None:
            import requests
            self._session = requests.Session()
        for attempt in range(5):
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests_made += 1
            r = self._session.get(url, headers={"User-Agent": self._ua,
                                                "Accept-Encoding": "gzip, deflate"}, timeout=90)
            if r.status_code == 200:
                out = self.write_dir / cache_name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(r.content)
                return r.content
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            raise RuntimeError(f"EDGAR HTTP {r.status_code} for {url}")
        raise RuntimeError(f"EDGAR retries exhausted for {url}")

    # -- submissions ------------------------------------------------------
    def submissions(self, cik: int) -> dict:
        name = f"submissions/CIK{cik:010d}.json"
        sub = json.loads(self.get(f"https://data.sec.gov/{name}", name))
        tables = [sub["filings"]["recent"]]
        for f in sub["filings"].get("files", []):
            nm = "submissions/" + f["name"]
            tables.append(json.loads(self.get("https://data.sec.gov/" + nm, nm)))
        filings = []
        for t in tables:
            n = len(t["accessionNumber"])
            for i in range(n):
                filings.append({
                    "accession": t["accessionNumber"][i], "form": t["form"][i],
                    "filing_date": t["filingDate"][i],
                    "acceptance": (t.get("acceptanceDateTime") or [""] * n)[i],
                    "primary_document": (t.get("primaryDocument") or [""] * n)[i]})
        return {"cik": cik, "name": sub.get("name", ""), "sic": sub.get("sic", ""),
                "sic_description": sub.get("sicDescription", ""), "filings": filings}

    def doc_url(self, cik: int, f: dict) -> str:
        acc = f["accession"].replace("-", "")
        doc = f["primary_document"] or f"{f['accession']}.txt"
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

    def document_text(self, cik: int, f: dict) -> str:
        acc = f["accession"].replace("-", "")
        doc = f["primary_document"] or f"{f['accession']}.txt"
        raw = self.get(self.doc_url(cik, f), f"docs/{cik}/{acc}/{doc}").decode("utf-8", "ignore")
        if doc.endswith(".txt"):
            m = re.search(r"<DOCUMENT>.*?</DOCUMENT>", raw, re.S | re.I)
            raw = m.group(0) if m else raw
        return to_text(raw)

    def full_submission(self, cik: int, accession: str) -> str:
        acc = accession.replace("-", "")
        return self.get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{accession}.txt",
                        f"full/{cik}/{accession}.txt").decode("utf-8", "ignore")

    def cik_lookup(self) -> str:
        return self.get("https://www.sec.gov/Archives/edgar/cik-lookup-data.txt",
                        "cik-lookup-data.txt").decode("latin-1")


def to_text(raw: str) -> str:
    t = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", raw)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", ". ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"(\.\s*){2,}", ". ", t)


def acceptance_et(acceptance: str) -> str:
    """SEC acceptanceDateTime (UTC, '...Z') -> ISO timestamp in America/New_York."""
    if not acceptance:
        return ""
    dt = datetime.fromisoformat(acceptance.replace("Z", "+00:00"))
    return dt.astimezone(ET).isoformat()


def available_before(f: dict, announce: str) -> bool:
    """Chronology rule (prereg §3): filing date AND acceptance date (ET) < announce date."""
    if not f["filing_date"] < announce:
        return False
    acc = acceptance_et(f.get("acceptance", ""))
    return (not acc) or acc[:10] < announce


def select_filings(filings: list[dict], announce: str) -> list[dict]:
    lo = (date.fromisoformat(announce) - timedelta(days=WINDOW_DAYS)).isoformat()
    annual = [f for f in filings if f["form"] in ANNUAL_FORMS and lo <= f["filing_date"]
              and available_before(f, announce)]
    if not annual:
        return []
    a = max(annual, key=lambda f: (f["filing_date"], f["accession"]))
    q = [f for f in filings if f["form"] in QUARTERLY_FORMS
         and a["filing_date"] < f["filing_date"] and available_before(f, announce)]
    return [a] + ([max(q, key=lambda f: (f["filing_date"], f["accession"]))] if q else [])


def load_deals() -> list[dict]:
    return json.loads(MANIFEST.read_text())["deals"]
