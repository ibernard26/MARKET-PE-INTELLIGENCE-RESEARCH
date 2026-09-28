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
    # Canonical coverage only: raw provider counts never make a deal covered.
    if "canonical_status" in row:
        return row["canonical_status"] == "CANONICALLY_ADMITTED"
    if row.get("prints_admitted") is False:
        return False
    return int(row.get("combined_n") or row.get("tiingo_n") or 0) >= 3 or (
        int(row.get("yahoo_n") or 0) >= 3)


def write_recon(doc: dict) -> None:
    meta = doc.get("meta") or {}
    recon = meta.get("reconcile") or {}
    conflicts = doc.get("conflict_samples") or []
    deals = doc.get("deals") or []
    overlapping_deals = sum(1 for r in deals if int(r.get("overlap_sessions") or 0) > 0)
    per_overlap = per_exact = per_tolerable = per_conflict = 0
    per_deal_complete = True
    for row in deals:
        if "exact_matches" not in row or "tolerable_matches" not in row:
            per_deal_complete = False
            continue
        per_overlap += int(row.get("overlap_sessions") or 0)
        per_exact += int(row.get("exact_matches") or 0)
        per_tolerable += int(row.get("tolerable_matches") or 0)
        per_conflict += int(row.get("material_conflicts") or 0)
    headline = (
        int(recon.get("overlap_sessions") or 0),
        int(recon.get("exact") or 0),
        int(recon.get("tolerable") or 0),
        int(recon.get("conflict") or 0),
    )
    sums_match = per_deal_complete and headline == (
        per_overlap, per_exact, per_tolerable, per_conflict)
    if sums_match:
        partition_note = (
            "Per-deal `exact_matches` + `tolerable_matches` + `material_conflicts` "
            "equal `meta.reconcile`. `historical_debug` is not added to those totals."
        )
    elif meta.get("reconcile_pre_retry") and not meta.get("historical_debug"):
        partition_note = (
            "Per-deal classification fields do not equal `meta.reconcile`. "
            "The gap is `meta.reconcile_pre_retry`, a side ledger that is not "
            "session-level evidence. It must not be treated as an audited partition."
        )
    else:
        partition_note = (
            "Per-deal classification fields do not equal `meta.reconcile`. "
            "Headline totals are not an audited partition."
        )
    lines = [
        "# Tiingo ↔ Yahoo price reconciliation",
        "",
        f"**Rule:** `{meta.get('reconcile_rule', 'price_reconcile_v1')}` "
        "(see `src/ingest/equity_prices/reconciliation.py`)",
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
        "## Overlap versus canonical admission",
        "",
        "Overlapping Tiingo/Yahoo sessions are not the admitted cohort. "
        "A zero material-conflict count is computed only on deals that have "
        "both series. It does not independently validate admitted Tiingo "
        "series that have no Yahoo overlap.",
        "",
        partition_note,
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| OVERLAP_DEALS_CANONICALLY_ADMITTED | {sum(1 for r in deals if int(r.get('overlap_sessions') or 0) > 0 and r.get('canonical_status') == 'CANONICALLY_ADMITTED')} |",
        f"| OVERLAP_DEALS_IDENTITY_DEFERRED | {sum(1 for r in deals if int(r.get('overlap_sessions') or 0) > 0 and r.get('canonical_status') == 'DEFERRED_IDENTITY')} |",
        f"| OVERLAP_DEALS_NO_PRICE_HISTORY | {sum(1 for r in deals if int(r.get('overlap_sessions') or 0) > 0 and r.get('canonical_status') == 'NO_PRICE_HISTORY')} |",
        f"| ADMITTED_DEALS_WITH_SECONDARY_OVERLAP | {sum(1 for r in deals if r.get('canonical_status') == 'CANONICALLY_ADMITTED' and int(r.get('overlap_sessions') or 0) > 0)} |",
        "",
        "## Raw vs canonical coverage (readiness uses CANONICALLY_ADMITTED only)",
        "",
        "| Status | Deals |",
        "|---|---|",
        f"| RAW_PROVIDER_COVERED | {meta.get('raw_provider_covered', 'n/d')} |",
        f"| CANONICALLY_ADMITTED | {meta.get('canonically_admitted', 'n/d')} |",
        f"| DEFERRED_IDENTITY | {meta.get('deferred_identity', 'n/d')} |",
        f"| DEFERRED_PRICE_CONFLICT | {meta.get('deferred_price_conflict', 'n/d')} |",
        f"| NO_PRICE_HISTORY | {meta.get('no_price_history', 'n/d')} |",
        f"| INSUFFICIENT_CANONICAL_PRINTS | {meta.get('insufficient_canonical_prints', 'n/d')} |",
        f"| identity deferral reasons | {meta.get('identity_deferral_reasons', 'n/d')} |",
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
    by_uncovered_status = defaultdict(lambda: Counter())
    by_offer_present = defaultdict(lambda: Counter())

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
        if not ok:
            by_uncovered_status[row.get("canonical_status") or "unknown"][bucket] += 1
        by_offer_present["offer_price_present" if d.get("offer_price") is not None else "offer_price_absent"][bucket] += 1

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

    outcome_lines = ["| Resolution type | Coverage |", "|---|---|"]
    for k in sorted(by_outcome):
        outcome_lines.append(f"| {k} | {rate(by_outcome[k])} |")

    offer_lines = ["| Offer-price field | Coverage |", "|---|---|"]
    for k in sorted(by_offer_present):
        offer_lines.append(f"| {k} | {rate(by_offer_present[k])} |")

    uc_lines = ["| Uncovered canonical status | N |", "|---|---|"]
    for k in sorted(by_uncovered_status):
        uc_lines.append(f"| {k} | {by_uncovered_status[k].get('PRICE_UNCOVERED', 0)} |")

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
        "## Coverage by resolution type",
        "",
        *outcome_lines,
        "",
        "## Coverage by offer-price field presence",
        "",
        *offer_lines,
        "",
        "## Uncovered deals by canonical status",
        "",
        *uc_lines,
        "",
        "## Sponsor and regulatory flags",
        "",
        "Sponsor status and regulatory flags are not fields on the canonical SEC manifest, so those slices are not computed.",
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
