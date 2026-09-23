"""SEC EDGAR provider: primary-source timestamps for deal lifecycle events.

What EDGAR supplies reliably, and what this provider takes from it:
  * the filing's acceptance timestamp  -> known_at of the announcement/resolution
  * form type and 8-K item numbers     -> checks that the cited filing really is
                                          what the manifest says it is
  * accession number, CIK, archive URL -> provenance for every written fact

What EDGAR does NOT give in structured form: offer price, exchange ratio,
unaffected price, etc. — those live in filing prose/exhibits. This provider does
not parse prose. Terms come from a REVIEWED MANIFEST (data/sec_deal_manifest.json)
in which each value cites the accession number it was read from. A manifest entry
whose filings cannot be verified on EDGAR is quarantined, never written.

Event <-> filing rules (verified against EDGAR metadata):
  announcement : 8-K with Item 1.01 (material definitive agreement), or 425
  closed       : 8-K with Item 2.01 (completion of acquisition), or 25-NSE / 15-12B
  terminated   : 8-K with Item 1.02 (termination of material definitive agreement)
  withdrawn    : 8-K with Item 1.02 or 8.01, or RW

Access: https://data.sec.gov/submissions/CIK##########.json. No key, but SEC's
fair-access policy requires a descriptive User-Agent with contact details
(set SEC_USER_AGENT; nothing is defaulted) and <= 10 requests/second.

Timestamp caveat: `acceptanceDateTime` is formatted with a trailing 'Z' but is
widely reported to be U.S. Eastern time. We store it as a naive timestamp
(Z stripped), consistent with the rest of the store, and document the ambiguity
rather than invent a timezone conversion.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..historical import HistoricalDealRecord, SourceRef

SOURCE = "SEC EDGAR"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
MIN_INTERVAL_S = 0.11                     # stay under 10 requests/second

EVENT_RULES = {
    "announcement": ({"8-K", "8-K/A"}, {"1.01"}, {"425"}),
    "closed": ({"8-K", "8-K/A"}, {"2.01"}, {"25-NSE", "15-12B", "15-12G"}),
    "terminated": ({"8-K", "8-K/A"}, {"1.02"}, set()),
    "withdrawn": ({"8-K", "8-K/A"}, {"1.02", "8.01"}, {"RW"}),
}


class EdgarError(RuntimeError):
    pass


class EdgarClient:
    """Minimal, rate-limited EDGAR metadata client (injectable fetch for tests)."""

    def __init__(self, user_agent: Optional[str] = None,
                 fetch_json: Optional[Callable[[str], dict]] = None):
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT", "")
        self._fetch = fetch_json or self._http_json
        self._last = 0.0
        self._cache: dict = {}

    def _http_json(self, url: str) -> dict:
        import requests
        if not self.user_agent:
            raise EdgarError("SEC_USER_AGENT is not set (SEC fair-access policy requires "
                             "a descriptive User-Agent with contact details)")
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = requests.get(url, headers={"User-Agent": self.user_agent}, timeout=30)
        if r.status_code != 200:
            raise EdgarError(f"EDGAR {r.status_code} for {url}")
        return r.json()

    def filing(self, cik: int, accession: str) -> dict:
        """Metadata for one accession from the company's submissions history."""
        if cik not in self._cache:
            sub = self._fetch(SUBMISSIONS.format(cik=int(cik)))
            tables = [sub["filings"]["recent"]]
            for f in sub["filings"].get("files", []):       # older history pages
                tables.append(self._fetch("https://data.sec.gov/submissions/" + f["name"]))
            idx = {}
            for t in tables:
                for i, acc in enumerate(t["accessionNumber"]):
                    idx[acc] = {k: t[k][i] for k in ("accessionNumber", "form", "filingDate",
                                                    "acceptanceDateTime", "items")
                                if k in t}
            self._cache[cik] = idx
        meta = self._cache[cik].get(accession)
        if meta is None:
            raise EdgarError(f"accession {accession} not found for CIK {cik}")
        return meta


def _accept_ts(meta: dict) -> str:
    raw = meta["acceptanceDateTime"]
    return raw.replace("Z", "").split(".")[0]


def matches(event: str, meta: dict) -> bool:
    forms_items, items, other_forms = EVENT_RULES[event]
    form = meta.get("form", "")
    got = {i.strip() for i in (meta.get("items") or "").split(",") if i.strip()}
    return (form in forms_items and bool(items & got)) or form in other_forms


def ref_for(cik: int, meta: dict) -> SourceRef:
    acc = meta["accessionNumber"]
    ts = _accept_ts(meta)
    return SourceRef(source_name=SOURCE,
                     source_identifier=ARCHIVE.format(cik=int(cik), acc_nodash=acc.replace("-", "")),
                     source_timestamp=ts, known_at=ts, accession_number=acc,
                     company_identifier=f"CIK{int(cik):010d}")


class SECEdgarProvider:
    """HistoricalDealProvider over a reviewed manifest, verified against EDGAR."""
    name = "sec_edgar"

    def __init__(self, manifest_path, client: Optional[EdgarClient] = None):
        self.manifest = json.loads(Path(manifest_path).read_text())
        self.client = client or EdgarClient()
        self.rejected: list[dict] = []

    def records(self) -> Iterable[HistoricalDealRecord]:
        for m in self.manifest.get("deals", []):
            try:
                yield self._record(m)
            except (EdgarError, KeyError, ValueError) as exc:
                self.rejected.append({"deal_id": m.get("deal_id"), "reason": str(exc)})

    def _verified(self, cik, accession, event) -> SourceRef:
        meta = self.client.filing(cik, accession)
        if not matches(event, meta):
            raise ValueError(f"{accession} ({meta.get('form')} items={meta.get('items')}) "
                             f"is not a valid '{event}' filing")
        return ref_for(cik, meta)

    def _record(self, m: dict) -> HistoricalDealRecord:
        cik = int(m["target_cik"])
        ann = self._verified(cik, m["announcement_accession"], "announcement")
        terms_meta = self.client.filing(cik, m["terms_accession"])
        terms = ref_for(cik, terms_meta)
        res_type = m.get("resolution_type")
        res_ref = res_ts = None
        if res_type:
            res_ref = self._verified(cik, m["resolution_accession"], res_type)
            # the event may predate its filing (e.g. closed, 8-K filed days later):
            # use a cited valid time if the manifest gives one, else the filing time
            res_ts = m.get("resolution_timestamp") or res_ref.known_at
        unaff_ref = None
        if m.get("unaffected_price") is not None:
            u = m["unaffected_price_source"]      # a cited market-data source, not EDGAR
            unaff_ref = SourceRef(u["source_name"], u["source_identifier"],
                                  u.get("source_timestamp"), u.get("known_at"))
        return HistoricalDealRecord(
            deal_id=m["deal_id"], target=m["target"], acquirer=m["acquirer"],
            announcement_timestamp=m.get("announcement_timestamp") or ann.known_at,
            announcement_source=ann, deal_type=m["deal_type"],
            consideration_type=m["consideration_type"], terms_source=terms,
            offer_price=m.get("offer_price"), exchange_ratio=m.get("exchange_ratio"),
            unaffected_price=m.get("unaffected_price"),
            unaffected_price_date=m.get("unaffected_price_date"),
            unaffected_price_source=unaff_ref,
            deal_value_usd_mm=m.get("deal_value_usd_mm"), sector=m.get("sector"),
            geography=m.get("geography"), sponsor=m.get("sponsor"),
            expected_close_date=m.get("expected_close_date"),
            regulatory_attrs=m.get("regulatory_attrs"),
            financing_attrs=m.get("financing_attrs"),
            resolution_type=res_type, resolution_timestamp=res_ts,
            resolution_source=res_ref)
