"""Cross-check the deal register against EDGAR metadata (data.sec.gov only).

For every row with a sec_cik, pulls the company's submissions JSON and keeps
M&A-relevant filings since 2026-01-01 (8-K with items, proxy/tender/425 forms,
Form 25 / 15 delistings). Checks that each cited accession exists for that CIK.
Metadata only: filing documents live on www.sec.gov, which this environment
cannot reach, so filing CONTENT is never read here.

No personal contact data is sent: set SEC_USER_AGENT to override the generic UA.
Run:  python scripts/verify_deals_sec.py
"""
import csv
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "research"
REGISTER = DATA / "deal_register_2026Q3.csv"
EVIDENCE = DATA / "sec_filings_2026Q3.json"
UA = os.getenv("SEC_USER_AGENT", "MI-PE-Research/1.0 (pe-tracker research script)")
SINCE = "2026-01-01"   # covers pre-window agreements cited (e.g. WBD 2026-02-27)
FORMS = {"8-K", "DEFM14A", "PREM14A", "SC 14D9", "SC14D9C", "SC TO-T", "SC TO-T/A", "425",
         "DEFA14A", "25-NSE", "25", "15-12B", "15-12G", "S-4", "SC 13E3"}


def submissions(cik: int) -> dict:
    req = urllib.request.Request(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                                 headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main() -> int:
    rows = list(csv.DictReader(REGISTER.open()))
    evidence, problems = {}, []
    for cik in sorted({int(r["sec_cik"]) for r in rows if r["sec_cik"]}):
        d = submissions(cik)
        rec = d["filings"]["recent"]
        keep = [dict(form=f, filed=fd, accepted=at, accession=acc, items=it)
                for f, fd, acc, at, it in zip(rec["form"], rec["filingDate"], rec["accessionNumber"],
                                              rec["acceptanceDateTime"], rec["items"])
                if fd >= SINCE and f in FORMS]
        evidence[str(cik)] = {"sec_name": d["name"], "tickers": d.get("tickers"), "filings": keep}
        time.sleep(0.15)                       # stay well under SEC's 10 req/s guidance
    checked = 0
    for r in rows:
        if r["verification"] == "sec_metadata_confirmed" and not (
                r["sec_announce_accession"] or r["sec_resolution_accession"]):
            problems.append(f"{r['deal_id']} is sec_metadata_confirmed but cites no accession")
        if r.get("filing_content_verified", "no") != "no":
            problems.append(f"{r['deal_id']} claims filing content was read; nothing here reads it")
        if not r["sec_cik"]:
            continue
        accs = {f["accession"] for f in evidence[r["sec_cik"]]["filings"]}
        for col in ("sec_announce_accession", "sec_resolution_accession"):
            if r[col]:
                checked += 1
                if r[col] not in accs:
                    problems.append(f"{r['deal_id']} {col} {r[col]} not found for CIK {r['sec_cik']}")
    EVIDENCE.write_text(json.dumps(evidence, indent=1))
    n_meta = sum(r["verification"] == "sec_metadata_confirmed" for r in rows)
    print(f"evidence for {len(evidence)} CIKs -> {EVIDENCE}")
    print(f"{checked} cited accessions checked across {len(rows)} rows "
          f"({n_meta} sec_metadata_confirmed; filing content read: 0)")
    for p in problems:
        print("MISMATCH:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
