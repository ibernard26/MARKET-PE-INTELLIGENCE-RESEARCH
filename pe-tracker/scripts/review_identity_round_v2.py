#!/usr/bin/env python3
"""Outcome-blind Proof C review of DEFERRED_IDENTITY deals.

Lexicographic deal_id order. Does not read resolution_type/status to prioritize.
Does not fit a model. Writes data/identity_resolution_round_v2.json.

  cd pe-tracker
  python3 -m scripts.review_identity_round_v2
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.equity_prices.identity_review_v2 import (  # noqa: E402
    NO_SUFFICIENT_EVIDENCE,
    PROOF_C_FORMS,
    RESOLVED_PROOF_C,
    STILL_AMBIGUOUS,
    assert_outcome_blind_order,
    classify_extracted,
    deferred_rows_in_review_order,
    extract_identity_from_filing,
    filing_is_contemporaneous,
    identity_review_order,
    map_row_from_review,
    prefer_filings,
    qualifies_as_proof_c,
    review_record,
)
from src.ingest.providers.sec_edgar import MIN_INTERVAL_S, SUBMISSIONS  # noqa: E402

MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
DEALS = ROOT / "data" / "sec_deal_manifest.json"
OUT = ROOT / "data" / "identity_resolution_round_v2.json"
MAP = ROOT / "data" / "target_ticker_map.json"
CACHE = ROOT / "data" / "cache" / "sec_identity_v2"
DEFAULT_UA = (
    "MARKET-PE-INTELLIGENCE research (ibernard26; identity expansion) "
    "ibernard1116@gmail.com"
)
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{name}"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ua() -> str:
    return os.getenv("SEC_USER_AGENT") or DEFAULT_UA


class SecFetcher:
    def __init__(self):
        self.ua = _ua()
        self._last = 0.0
        CACHE.mkdir(parents=True, exist_ok=True)

    def _sleep(self) -> None:
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get_bytes(self, url: str, cache_key: str, max_bytes: int | None = None) -> bytes:
        path = CACHE / cache_key
        if path.exists():
            return path.read_bytes()
        self._sleep()
        r = requests.get(url, headers={"User-Agent": self.ua}, timeout=45, stream=True)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} for {url}")
        buf = b""
        for chunk in r.iter_content(8192):
            buf += chunk
            if max_bytes is not None and len(buf) >= max_bytes:
                break
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf)
        return buf

    def get_json(self, url: str, cache_key: str) -> dict:
        raw = self.get_bytes(url, cache_key)
        return json.loads(raw.decode("utf-8"))

    def submissions(self, cik: int) -> dict:
        return self.get_json(
            SUBMISSIONS.format(cik=int(cik)),
            f"submissions/CIK{int(cik):010d}.json",
        )

    def all_filings(self, cik: int) -> list[dict]:
        sub = self.submissions(cik)
        tables = [sub["filings"]["recent"]]
        for f in sub["filings"].get("files") or []:
            tables.append(self.get_json(
                "https://data.sec.gov/submissions/" + f["name"],
                "submissions/" + f["name"],
            ))
        out = []
        for t in tables:
            n = len(t["accessionNumber"])
            primary = t.get("primaryDocument") or [""] * n
            items = t.get("items") or [""] * n
            for i, acc in enumerate(t["accessionNumber"]):
                out.append({
                    "accessionNumber": acc,
                    "form": t["form"][i],
                    "filingDate": t["filingDate"][i],
                    "primaryDocument": primary[i] if i < len(primary) else "",
                    "items": items[i] if i < len(items) else "",
                })
        return out


def _archive_name(cik: int, acc: str, name: str) -> str:
    return ARCHIVE.format(cik=int(cik), acc_nodash=acc.replace("-", ""), name=name)


def filing_texts(fetcher: SecFetcher, cik: int, filing: dict) -> list[tuple[str, str]]:
    """Return (location_label, text) candidates, cheapest first."""
    acc = filing["accessionNumber"]
    acc_nodash = acc.replace("-", "")
    cik_i = int(cik)
    texts = []
    txt_name = f"{acc}.txt"
    try:
        raw = fetcher.get_bytes(
            _archive_name(cik_i, acc, txt_name),
            f"filings/{cik_i}/{acc_nodash}/{txt_name}",
            max_bytes=120_000,
        )
        texts.append((f"complete_submission:{txt_name}", raw.decode("latin-1", "replace")))
    except Exception as exc:
        texts.append((f"complete_submission_error:{exc}", ""))
    primary = filing.get("primaryDocument") or ""
    if primary and primary.lower() not in {txt_name.lower()}:
        try:
            raw = fetcher.get_bytes(
                _archive_name(cik_i, acc, primary),
                f"filings/{cik_i}/{acc_nodash}/{primary.replace('/', '_')}",
                max_bytes=250_000,
            )
            texts.append((f"primary:{primary}", raw.decode("latin-1", "replace")))
        except Exception as exc:
            texts.append((f"primary_error:{exc}", ""))
    # index.json exhibits (press releases)
    try:
        idx = fetcher.get_json(
            _archive_name(cik_i, acc, "index.json"),
            f"filings/{cik_i}/{acc_nodash}/index.json",
        )
        names = [it["name"] for it in (idx.get("directory") or {}).get("item") or []
                 if isinstance(it, dict)]
        exhibits = [n for n in names if re_ex99(n)]
        for name in exhibits[:3]:
            raw = fetcher.get_bytes(
                _archive_name(cik_i, acc, name),
                f"filings/{cik_i}/{acc_nodash}/{name.replace('/', '_')}",
                max_bytes=200_000,
            )
            texts.append((f"exhibit:{name}", raw.decode("latin-1", "replace")))
    except Exception:
        pass
    return texts


def re_ex99(name: str) -> bool:
    n = name.lower()
    return any(tag in n for tag in ("ex99", "ex-99", "dex99", "ex991", "exhibit99"))


def review_one(fetcher: SecFetcher, deal: dict, coverage: dict, index: int) -> dict:
    deal_id = deal["deal_id"]
    cik = deal.get("target_cik")
    name = deal.get("target")
    ann = (deal.get("announcement_timestamp") or "")[:10]
    res = (deal.get("resolution_timestamp") or "")[:10] or None
    hypothesized = coverage.get("historical_ticker") or coverage.get("ticker")
    modern = coverage.get("identity_basis") == "sec_company_tickers"
    modern_ticker = hypothesized if modern else None

    if not cik:
        return review_record(
            deal_id=deal_id, historical_ticker=None, exchange=None,
            sec_accession=None, filing_date=None, form=None,
            evidence_location=None,
            identity_rationale="No target_cik; cannot fetch issuer submissions.",
            status=NO_SUFFICIENT_EVIDENCE, announcement_date=ann,
            target_name=name, target_cik=None, review_order_index=index,
        )

    try:
        filings = fetcher.all_filings(int(cik))
    except Exception as exc:
        return review_record(
            deal_id=deal_id, historical_ticker=None, exchange=None,
            sec_accession=None, filing_date=None, form=None,
            evidence_location=None,
            identity_rationale=f"SEC submissions unavailable: {exc}",
            status=NO_SUFFICIENT_EVIDENCE, announcement_date=ann,
            target_name=name, target_cik=int(cik), review_order_index=index,
        )

    candidates = [
        f for f in filings
        if f.get("form") in PROOF_C_FORMS
        and filing_is_contemporaneous(f.get("filingDate") or "", ann, res)
    ]
    ranked = prefer_filings(candidates)
    if not ranked:
        return review_record(
            deal_id=deal_id, historical_ticker=None, exchange=None,
            sec_accession=None, filing_date=None, form=None,
            evidence_location=None,
            identity_rationale=(
                "No contemporaneous 8-K/proxy/S-4/TO/13E-3/425 on the target CIK "
                "within the Proof C window. deal_id convention and modern "
                "company_tickers.json were not used."
            ),
            status=NO_SUFFICIENT_EVIDENCE, announcement_date=ann,
            target_name=name, target_cik=int(cik), review_order_index=index,
        )

    best = None
    for filing in ranked[:8]:
        texts = filing_texts(fetcher, int(cik), filing)
        for loc, raw in texts:
            if not raw:
                continue
            extracted = extract_identity_from_filing(
                raw, target_name=name, filer_is_target=True)
            status = classify_extracted(
                extracted, deal_id=deal_id, modern_ticker=modern_ticker)
            rec = review_record(
                deal_id=deal_id,
                historical_ticker=extracted.get("historical_ticker"),
                exchange=extracted.get("exchange"),
                sec_accession=filing["accessionNumber"],
                filing_date=filing["filingDate"],
                form=filing["form"],
                evidence_location=extracted.get("evidence_location") or loc,
                identity_rationale=_rationale(extracted, filing, loc, status, hypothesized),
                status=status,
                announcement_date=ann,
                target_name=name,
                target_cik=int(cik),
                review_order_index=index,
            )
            if status == RESOLVED_PROOF_C and qualifies_as_proof_c({
                "deal_id": deal_id,
                "ticker": rec["historical_ticker"],
                "sec_accession": rec["sec_accession"],
                "sec_filed_date": rec["filing_date"],
            }, ann, res):
                return rec
            if best is None or (status == STILL_AMBIGUOUS and best["status"] == NO_SUFFICIENT_EVIDENCE):
                best = rec
    if best is None:
        best = review_record(
            deal_id=deal_id, historical_ticker=None, exchange=None,
            sec_accession=ranked[0]["accessionNumber"],
            filing_date=ranked[0]["filingDate"], form=ranked[0]["form"],
            evidence_location=None,
            identity_rationale="Contemporaneous filings present but no ticker extracted.",
            status=NO_SUFFICIENT_EVIDENCE, announcement_date=ann,
            target_name=name, target_cik=int(cik), review_order_index=index,
        )
    return best


def _rationale(extracted, filing, loc, status, hypothesized) -> str:
    ticker = extracted.get("historical_ticker")
    bits = [
        f"Form {filing.get('form')} acc {filing.get('accessionNumber')} "
        f"filed {filing.get('filingDate')} ({loc}).",
        f"Evidence location: {extracted.get('evidence_location')}.",
    ]
    if ticker:
        bits.append(f"Extracted historical ticker {ticker}.")
    if hypothesized and ticker and hypothesized.upper() != ticker.upper():
        bits.append(
            f"Differs from hypothesized {hypothesized}; hypothesized value was "
            f"not used as proof."
        )
    if status != RESOLVED_PROOF_C:
        bits.append("Not admitted as Proof C from this document.")
    bits.append(
        "Modern company_tickers.json and DEAL-{TICKER} convention are not Proof C."
    )
    return " ".join(bits)


def _write_map(reviews: list[dict]) -> None:
    existing = json.loads(MAP.read_text()) if MAP.exists() else {"schema_version": 1, "tickers": []}
    by_id = {r["deal_id"]: r for r in existing.get("tickers") or []}
    for rec in reviews:
        row = map_row_from_review(rec)
        if row:
            by_id[row["deal_id"]] = row
    existing["schema_version"] = 1
    existing["_doc"] = (
        "Reviewed target tickers backed by contemporaneous SEC accessions "
        "(Proof C). deal_id convention and current company_tickers.json are "
        "not sufficient."
    )
    existing["tickers"] = [by_id[k] for k in sorted(by_id)]
    MAP.write_text(json.dumps(existing, indent=2) + "\n")


def main() -> int:
    os.environ.setdefault("SEC_USER_AGENT", DEFAULT_UA)
    matrix = json.loads(MATRIX.read_text())
    sec = json.loads(DEALS.read_text())
    deals_by_id = {d["deal_id"]: d for d in sec["deals"]}
    deferred = deferred_rows_in_review_order(matrix["deals"])
    order = assert_outcome_blind_order(matrix["deals"])
    if order != identity_review_order(r["deal_id"] for r in deferred):
        print("review order invariant failed", file=sys.stderr)
        return 2

    fetcher = SecFetcher()
    reviews = []
    for i, row in enumerate(deferred):
        deal = deals_by_id[row["deal_id"]]
        rec = review_one(fetcher, deal, row, i)
        reviews.append(rec)
        print(json.dumps({
            "i": i, "n": len(deferred), "deal_id": rec["deal_id"],
            "status": rec["status"], "ticker": rec.get("historical_ticker"),
            "form": rec.get("form"), "accession": rec.get("sec_accession"),
        }), flush=True)

    counts = {
        RESOLVED_PROOF_C: sum(1 for r in reviews if r["status"] == RESOLVED_PROOF_C),
        STILL_AMBIGUOUS: sum(1 for r in reviews if r["status"] == STILL_AMBIGUOUS),
        NO_SUFFICIENT_EVIDENCE: sum(1 for r in reviews if r["status"] == NO_SUFFICIENT_EVIDENCE),
    }
    doc = {
        "schema_version": 1,
        "round_id": "identity_resolution_round_v2",
        "created_at": _now(),
        "review_order": "lexicographic_deal_id",
        "outcome_fields_used_for_prioritization": [],
        "proof_c_forms": sorted(PROOF_C_FORMS),
        "IDENTITIES_REVIEWED": len(reviews),
        "NEW_PROOF_C": counts[RESOLVED_PROOF_C],
        "STILL_AMBIGUOUS": counts[STILL_AMBIGUOUS],
        "NO_SUFFICIENT_EVIDENCE": counts[NO_SUFFICIENT_EVIDENCE],
        "deals": reviews,
    }
    OUT.write_text(json.dumps(doc, indent=2) + "\n")
    _write_map(reviews)
    print(json.dumps({k: doc[k] for k in (
        "IDENTITIES_REVIEWED", "NEW_PROOF_C", "STILL_AMBIGUOUS",
        "NO_SUFFICIENT_EVIDENCE")}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
