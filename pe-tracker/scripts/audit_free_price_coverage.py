#!/usr/bin/env python3
"""Write reconciliation + survivorship bias audit docs from coverage matrix.

Offline — no API credentials required. Expects:

  pe-tracker/data/free_price_coverage_matrix.json

  cd pe-tracker
  python -m scripts.audit_free_price_coverage
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
RECON_DOC = ROOT / "docs" / "TIINGO_YAHOO_PRICE_RECONCILIATION.md"
BIAS_DOC = ROOT / "docs" / "HISTORICAL_PRICE_AVAILABILITY_BIAS_AUDIT.md"
DEAL_MANIFEST = ROOT / "data" / "sec_deal_manifest.json"


def _covered(row: dict) -> bool:
    return int(row.get("combined_n") or row.get("tiingo_n") or 0) >= 3 or (
        int(row.get("yahoo_n") or 0) >= 3)


def write_recon(doc: dict) -> None:
    meta = doc.get("meta") or {}
    recon = meta.get("reconcile") or {}
    conflicts = doc.get("conflict_samples") or []
    deals = doc.get("deals") or []
    overlapping_deals = sum(1 for r in deals if int(r.get("overlap_sessions") or 0) > 0)
    lines = [
        "# Tiingo ↔ Yahoo price reconciliation",
        "",
        f"**Rule:** `price_reconcile_v1` (see `src/ingest/equity_prices/reconciliation.py`)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| OVERLAPPING_DEALS | {overlapping_deals} |",
        f"| OVERLAPPING_SESSIONS | {recon.get('overlap_sessions', 0)} |",
        f"| EXACT_MATCH_COUNT | {recon.get('exact', 0)} |",
        f"| TOLERABLE_MATCH_COUNT | {recon.get('tolerable', 0)} |",
        f"| CORPORATE_ACTION_EXPLAINED_COUNT | n/d (manual review) |",
        f"| MATERIAL_CONFLICT_COUNT | {recon.get('conflict', 0)} |",
        f"| TIINGO_ONLY_COUNT | {sum(1 for r in deals if r.get('tiingo_n', 0) > 0 and r.get('yahoo_n', 0) == 0)} |",
        f"| YAHOO_ONLY_COUNT | {sum(1 for r in deals if r.get('yahoo_n', 0) > 0 and r.get('tiingo_n', 0) == 0)} |",
        "",
        "## Material conflict samples",
        "",
    ]
    if not conflicts:
        lines.append("_No material conflicts recorded._")
    else:
        lines.append("| deal_id | session_date | primary_close | secondary_close |")
        lines.append("|---|---|---|---|")
        for c in conflicts[:40]:
            lines.append(
                f"| {c.get('deal_id')} | {c.get('session_date')} | "
                f"{c.get('primary_close')} | {c.get('secondary_close')} |"
            )
    lines.append("")
    lines.append("Conflicts are never averaged. Unexplained conflicts stay deferred.")
    lines.append("")
    RECON_DOC.write_text("\n".join(lines) + "\n")


def write_bias(doc: dict) -> None:
    deals_cov = {r["deal_id"]: r for r in doc.get("deals") or []}
    canon = json.loads(DEAL_MANIFEST.read_text())["deals"]
    covered = uncovered = 0
    by_outcome = defaultdict(lambda: Counter())
    by_year = defaultdict(lambda: Counter())
    by_consideration = defaultdict(lambda: Counter())
    by_deal_type = defaultdict(lambda: Counter())

    for d in canon:
        row = deals_cov.get(d["deal_id"], {})
        ok = _covered(row) if row else False
        bucket = "PRICE_COVERED" if ok else "PRICE_UNCOVERED"
        if ok:
            covered += 1
        else:
            uncovered += 1
        outcome = d.get("resolution_type") or "unknown"
        by_outcome[outcome][bucket] += 1
        year = (d.get("announcement_timestamp") or "")[:4] or "unknown"
        by_year[year][bucket] += 1
        by_consideration[d.get("consideration_type") or "unknown"][bucket] += 1
        by_deal_type[d.get("deal_type") or "unknown"][bucket] += 1

    def rate(ctr: Counter) -> str:
        c = ctr.get("PRICE_COVERED", 0)
        u = ctr.get("PRICE_UNCOVERED", 0)
        n = c + u
        return f"{c}/{n} ({(c / n):.1%})" if n else "n/d"

    closed = by_outcome.get("closed", Counter())
    # break-like outcomes
    break_ctr = Counter()
    for k in ("terminated", "withdrawn", "broken"):
        break_ctr.update(by_outcome.get(k, Counter()))

    skews = []
    for label, ctr in (("closed", closed), ("break_like", break_ctr)):
        c = ctr.get("PRICE_COVERED", 0)
        n = c + ctr.get("PRICE_UNCOVERED", 0)
        if n:
            skews.append(f"{label} coverage {c}/{n} ({c/n:.1%})")

    year_lines = ["| Year | Coverage |", "|---|---|"]
    for y in sorted(by_year):
        year_lines.append(f"| {y} | {rate(by_year[y])} |")

    cons_lines = ["| Consideration | Coverage |", "|---|---|"]
    for k in sorted(by_consideration):
        cons_lines.append(f"| {k} | {rate(by_consideration[k])} |")

    dt_lines = ["| Deal type | Coverage |", "|---|---|"]
    for k in sorted(by_deal_type):
        dt_lines.append(f"| {k} | {rate(by_deal_type[k])} |")

    n = covered + uncovered
    overall = f"{(covered / n):.1%}" if n else "n/d"
    body = [
        "# Historical price availability bias audit",
        "",
        "Descriptive only — no causal claims. Cohort not altered to balance stats.",
        "",
        f"**Canonical N:** {len(canon)}  ",
        f"**PRICE_COVERED (≥3 prints):** {covered}  ",
        f"**PRICE_UNCOVERED:** {uncovered}  ",
        f"**Overall coverage rate:** {overall}",
        "",
        "## Outcome",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| COVERAGE_RATE_CLOSED | {rate(closed)} |",
        f"| COVERAGE_RATE_BREAK | {rate(break_ctr)} |",
        "",
        "## Coverage by announcement year",
        "",
        *year_lines,
        "",
        "## Coverage by consideration type",
        "",
        *cons_lines,
        "",
        "## Coverage by deal type",
        "",
        *dt_lines,
        "",
        "## Major observed coverage skews",
        "",
    ]
    if skews:
        body.extend(f"- {s}" for s in skews)
    else:
        body.append("_Insufficient data._")
    body.extend([
        "",
        "## Provider mix (from matrix meta)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| TIINGO_DEALS_COVERED | {(doc.get('meta') or {}).get('tiingo_deals_covered', 'n/d')} |",
        f"| YAHOO_DEALS_COVERED | {(doc.get('meta') or {}).get('yahoo_deals_covered', 'n/d')} |",
        f"| MULTI_PROVIDER_CONFIRMED | {(doc.get('meta') or {}).get('multi_provider_confirmed', 'n/d')} |",
        "",
        "Canonical corpus is unchanged. Uncovered deals remain in SEC manifest.",
        "",
    ])
    BIAS_DOC.write_text("\n".join(body))


def main() -> int:
    if not MATRIX.exists():
        print(f"missing {MATRIX}", file=sys.stderr)
        print("Run scripts/run_free_price_coverage.py first.", file=sys.stderr)
        return 2
    doc = json.loads(MATRIX.read_text())
    write_recon(doc)
    write_bias(doc)
    print(f"wrote {RECON_DOC}")
    print(f"wrote {BIAS_DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
