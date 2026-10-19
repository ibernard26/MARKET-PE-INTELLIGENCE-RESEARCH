"""Stage evidence into the append-only geopolitical ledger.

    python -m src.geo_intel.ingest --grok-brief brief.json      # untrusted staging
    python -m src.geo_intel.ingest --records records.jsonl      # reviewer-entered

Ingestion never fits a model, never writes the canonical SQLite store and never
sets a verification status (status is derived; see verification.py).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .reporting import LEDGER
from .schema import EvidenceRecord
from .store import EvidenceLedger, records_from_grok_brief


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ledger", default=str(LEDGER))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--grok-brief")
    g.add_argument("--records")
    a = ap.parse_args(argv)
    led = EvidenceLedger(Path(a.ledger))
    if a.grok_brief:
        recs = records_from_grok_brief(json.loads(Path(a.grok_brief).read_text()))
    else:
        recs = [EvidenceRecord.from_dict(json.loads(l))
                for l in Path(a.records).read_text().splitlines() if l.strip()]
    for r in led.extend(recs):
        print(r.evidence_id, r.event_id, r.source_type, r.known_at_basis)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
