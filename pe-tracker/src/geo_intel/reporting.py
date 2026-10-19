"""Read-only research reporting layer (chart data + optional PNG rendering).

    python -m src.geo_intel.reporting --out data/geopolitical/report [--png DIR]
                                      [--db PATH] [--as-of YYYY-MM-DD]

Charts available from EXISTING data (no synthetic values):
  resolved_deal_outcomes, deal_coverage_missingness, historical_sample_composition,
  verified_geo_event_timeline, geo_exposure_by_sector, source_verification_coverage
Reserved charts for unexecuted models are emitted as placeholders reading
"NOT AVAILABLE — MODEL NOT EXECUTED". This module never fits, scores or
predicts; the optional SQLite store is opened with ``mode=ro``.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Optional

from . import MODEL_EXECUTION_STATUS, MODULE_STATUS
from .exposure import MANIFEST, DealUniverse, load_links, validate_link
from .pit import research_candidates
from .schema import VERIFICATION_STATUSES
from .store import EvidenceLedger
from .verification import classify

ROOT = Path(__file__).resolve().parents[2]
COHORT = ROOT / "data" / "experiments" / "first_walkforward_v1" / "cohort.json"
RESEARCH_DEALS = ROOT / "data" / "research" / "canonical_deals_2026Q3.csv"
GEO_DIR = ROOT / "data" / "geopolitical"
LEDGER = GEO_DIR / "evidence_ledger.jsonl"
LINKS = GEO_DIR / "exposure_links.jsonl"

NOT_AVAILABLE = "NOT AVAILABLE — MODEL NOT EXECUTED"
RESERVED_V1 = (
    ("v1_ranked_break_probabilities", "Ranked deal-break probabilities"),
    ("v1_roc_pr_curves", "ROC and precision–recall curves"),
    ("v1_calibration", "Probability calibration"),
    ("v1_walkforward_vs_baselines", "Walk-forward performance against baselines"),
    ("v1_ev_sensitivity", "Expected-value sensitivity"),
)
RESERVED_V2 = (
    ("v2_time_varying_state_probs", "Time-varying close/break/continue probabilities"),
    ("v2_competing_risk_cif", "Competing-risk cumulative incidence"),
    ("v2_event_driven_risk_changes", "Event-driven changes in estimated break risk"),
    ("v2_risk_by_horizon", "Risk by forecast horizon"),
)
MANIFEST_FIELDS = ("announcement_timestamp", "announcement_accession", "terms_accession",
                   "offer_price", "exchange_ratio", "resolution_timestamp",
                   "resolution_accession", "resolution_type", "deal_type",
                   "consideration_type", "target_cik")


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(ROOT.parent))
    except ValueError:
        return str(p)


def build_report(manifest: Path = MANIFEST, ledger_path: Path = LEDGER,
                 links_path: Path = LINKS, db_path: Optional[Path] = None,
                 as_of: Optional[str] = None) -> dict:
    deals = json.loads(Path(manifest).read_text())["deals"]
    cohort = set(json.loads(COHORT.read_text())["deal_ids"])
    n = len(deals)
    charts: dict = {}

    # 1 resolved outcomes ------------------------------------------------
    by_year: dict = {}
    for d in deals:
        y = (d.get("announcement_timestamp") or "n/d")[:4]
        by_year.setdefault(y, Counter())[d.get("resolution_type") or "n/d"] += 1
    charts["resolved_deal_outcomes"] = {
        "title": "Resolved deal outcomes (reviewed SEC manifest)",
        "source": _rel(manifest), "n": n,
        "by_resolution_type": dict(Counter(d.get("resolution_type") or "n/d" for d in deals)),
        "by_announcement_year": {y: dict(c) for y, c in sorted(by_year.items())},
        "caveat": "Reviewer-curated corpus; sample prevalence is not a population "
                  "break rate (docs/SAMPLING_FRAME.md).",
    }
    # 2 coverage & missingness ------------------------------------------
    cov = {f: sum(1 for d in deals if d.get(f) is not None) for f in MANIFEST_FIELDS}
    charts["deal_coverage_missingness"] = {
        "title": "Deal field coverage (reviewed SEC manifest)",
        "source": _rel(manifest), "n": n,
        "present": cov, "missing": {f: n - v for f, v in cov.items()},
        "note": "exchange_ratio is structurally absent for cash deals; offer_price for "
                "pure-stock deals. Missing is reported, never filled.",
    }
    if db_path:
        charts["deal_coverage_missingness"]["store"] = _store_missingness(Path(db_path))
    # 3 sample composition ----------------------------------------------
    charts["historical_sample_composition"] = {
        "title": "Historical sample composition",
        "source": _rel(manifest), "n": n,
        "deal_type": dict(Counter(d.get("deal_type") or "n/d" for d in deals)),
        "consideration_type": dict(Counter(d.get("consideration_type") or "n/d" for d in deals)),
        "first_walkforward_v1_cohort": {
            "in_frozen_cohort_N62": sum(1 for d in deals if d["deal_id"] in cohort),
            "outside_cohort": sum(1 for d in deals if d["deal_id"] not in cohort)},
        "cohort_source": _rel(COHORT),
    }
    # 4-6 geopolitical ---------------------------------------------------
    ledger = EvidenceLedger(ledger_path)
    clusters = ledger.clusters()
    status_now = {eid: classify(recs, as_of=as_of, primary_registry=ledger.primary_registry)
                  for eid, recs in clusters.items()}
    timeline = []
    if as_of:
        cand = research_candidates(ledger, as_of)
        timeline = [{"event_id": a["event_id"], "category": a["category"],
                     "valid_time_utc": a["valid_time_utc"], "known_at_utc": a["known_at_utc"],
                     "status": a["status_as_of"]} for a in cand["admitted"]]
    else:
        for eid, r in status_now.items():
            if r.status in ("VERIFIED_PRIMARY", "CORROBORATED_SECONDARY"):
                v = max((x.valid_utc() for x in clusters[eid] if x.valid_utc()), default=None)
                timeline.append({"event_id": eid, "category": clusters[eid][0].category,
                                 "valid_time_utc": v, "status": r.status})
    charts["verified_geo_event_timeline"] = {
        "title": "Verified geopolitical event timeline",
        "source": _rel(ledger_path), "as_of": as_of, "events": sorted(
            timeline, key=lambda e: (e.get("valid_time_utc") or "", e["event_id"])),
        "empty_state": None if timeline else
            "No VERIFIED_PRIMARY or CORROBORATED_SECONDARY events in the ledger.",
    }
    universe = DealUniverse.from_manifest(manifest)
    links, link_errors = [], []
    for l in load_links(links_path):
        try:
            links.append(validate_link(l, ledger, universe, as_of=as_of))
        except Exception as exc:  # report, never silently drop
            link_errors.append({"event_id": l.event_id, "deal_id": l.deal_id, "error": str(exc)})
    research_sector = _research_sector_coverage({d["deal_id"] for d in deals})
    charts["geo_exposure_by_sector"] = {
        "title": "Geopolitical exposure by sector",
        "source": [_rel(links_path), _rel(RESEARCH_DEALS)],
        "links_by_sector_and_type": _links_by_sector(links, clusters),
        "links_by_channel": {f"{k[0]}|{k[1]}": v for k, v in sorted(Counter(
            (x["channel"], x["link_type"]) for x in links).items())},
        "invalid_links": link_errors,
        "corpus_sector_coverage": research_sector,
        "empty_state": None if links else "No validated event→deal exposure links.",
    }
    by_status = Counter(r.status for r in status_now.values())
    charts["source_verification_coverage"] = {
        "title": "Source verification & coverage",
        "source": _rel(ledger_path), "as_of": as_of,
        "n_evidence_records": len(ledger.records), "n_event_clusters": len(clusters),
        "clusters_by_status": {s: by_status.get(s, 0) for s in VERIFICATION_STATUSES},
        "records_by_source_type": dict(Counter(r.source_type for r in ledger.records)),
        "records_by_category": dict(Counter(r.category for r in ledger.records)),
        "records_missing_publication_timestamp":
            sum(1 for r in ledger.records if not r.publication_timestamp),
        "records_missing_valid_timestamp":
            sum(1 for r in ledger.records if not r.event_valid_timestamp),
        "untrusted_only_clusters": sum(1 for r in status_now.values() if r.untrusted_only),
        "empty_state": None if ledger.records else "Evidence ledger is empty.",
    }
    reserved = {k: {"title": t, "status": NOT_AVAILABLE, "model": "break_logit_v1",
                    "reason": "first_walkforward_v1 execution_authorized=false"}
                for k, t in RESERVED_V1}
    reserved.update({k: {"title": t, "status": NOT_AVAILABLE, "model": "break_hazard_v1",
                         "reason": "design-only (docs/MODEL_ARCHITECTURE_V2.md)"}
                     for k, t in RESERVED_V2})
    return {"report": "geopolitical_research_report_v1", "module_status": MODULE_STATUS,
            "model_status": MODEL_EXECUTION_STATUS, "synthetic_values": False,
            "charts": charts, "reserved_charts": reserved}


def _store_missingness(db_path: Path) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(deals)")]
        n = con.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
        miss = {c: con.execute(f'SELECT COUNT(*) FROM deals WHERE "{c}" IS NULL').fetchone()[0]
                for c in cols}
        status = dict(con.execute("SELECT COALESCE(status,'NULL'), COUNT(*) FROM deals GROUP BY 1"))
    finally:
        con.close()
    return {"db": str(db_path), "opened": "read-only", "n_deals": n,
            "null_counts": miss, "status_counts": status}


def _research_sector_coverage(manifest_ids: set) -> dict:
    rows = list(csv.DictReader(RESEARCH_DEALS.open())) if RESEARCH_DEALS.exists() else []
    with_sector = {r["canonical_deal_id"] for r in rows if (r.get("sector") or "").strip()}
    return {"manifest_deals": len(manifest_ids),
            "manifest_deals_with_research_sector_label": len(manifest_ids & with_sector),
            "manifest_deals_without_sector": len(manifest_ids - with_sector),
            "note": "Sector exists only as free text in the research-only 2026Q3 register; "
                    "it is not mapped to the controlled SECTORS vocabulary automatically."}


def _links_by_sector(links: list, clusters: dict) -> dict:
    out: dict = {}
    for l in links:
        if l["link_type"] == "SECTOR_HYPOTHESIS":
            secs = [l["deal_sector"]]
        else:
            secs = sorted({s for r in clusters[l["event_id"]] for s in r.sectors}) or ["unspecified"]
        for s in secs:
            out.setdefault(s, Counter())[l["link_type"]] += 1
    return {s: dict(c) for s, c in sorted(out.items())}


# ---------------------------------------------------------------- writers
def write_report(report: dict, out_dir: Path) -> list:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    j = out_dir / "geo_research_report.json"
    j.write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    m = out_dir / "geo_research_report.md"
    m.write_text(to_markdown(report))
    return [j, m]


def to_markdown(rep: dict) -> str:
    c = rep["charts"]
    L = ["# Geopolitical research report (read-only)", "",
         f"**Module:** `{rep['module_status']}`  ", f"**Models:** {rep['model_status']}  ",
         "**Synthetic values:** none", "",
         "## Resolved deal outcomes", ""]
    o = c["resolved_deal_outcomes"]
    L += [f"Source `{o['source']}`, N = {o['n']}.", "", "| Outcome | N |", "|---|---:|"]
    L += [f"| {k} | {v} |" for k, v in sorted(o["by_resolution_type"].items())]
    L += ["", f"_{o['caveat']}_", "", "## Deal coverage and missingness", "",
          "| Field | Present | Missing |", "|---|---:|---:|"]
    cm = c["deal_coverage_missingness"]
    L += [f"| {f} | {cm['present'][f]} | {cm['missing'][f]} |" for f in cm["present"]]
    s = c["historical_sample_composition"]
    L += ["", "## Historical sample composition", "",
          f"deal_type: {s['deal_type']}  ", f"consideration_type: {s['consideration_type']}  ",
          f"first_walkforward_v1 cohort: {s['first_walkforward_v1_cohort']}", ""]
    for k in ("verified_geo_event_timeline", "geo_exposure_by_sector",
              "source_verification_coverage"):
        L += [f"## {c[k]['title']}", ""]
        if c[k].get("empty_state"):
            L += [f"**{c[k]['empty_state']}**", ""]
    sc = c["source_verification_coverage"]
    L += ["| Status | Clusters |", "|---|---:|"]
    L += [f"| {k} | {v} |" for k, v in sc["clusters_by_status"].items()]
    L += ["", f"Corpus sector coverage: {c['geo_exposure_by_sector']['corpus_sector_coverage']}",
          "", "## Reserved model charts", "", "| Chart | Model | Status |", "|---|---|---|"]
    L += [f"| {v['title']} | {v['model']} | {v['status']} |" for v in rep["reserved_charts"].values()]
    return "\n".join(L) + "\n"


def render_png(report: dict, out_dir: Path) -> list:
    """Optional PNG rendering (needs matplotlib, which is NOT a pe-tracker
    requirement — see docs/DEPENDENCY_ARCHITECTURE.md)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    c, paths = report["charts"], []

    def save(fig, name):
        p = out_dir / name
        fig.tight_layout()
        fig.savefig(p, dpi=120)
        plt.close(fig)
        paths.append(p)

    o = c["resolved_deal_outcomes"]
    years = list(o["by_announcement_year"])
    outs = sorted({k for v in o["by_announcement_year"].values() for k in v})
    fig, ax = plt.subplots(figsize=(9, 4.5))
    bottom = [0] * len(years)
    for out in outs:
        vals = [o["by_announcement_year"][y].get(out, 0) for y in years]
        ax.bar(years, vals, bottom=bottom, label=out)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_title(f"Resolved deal outcomes by announcement year (N={o['n']}, reviewed SEC manifest)")
    ax.set_ylabel("deals"); ax.legend()
    ax.text(0.01, -0.18, o["caveat"], transform=ax.transAxes, fontsize=7)
    save(fig, "01_resolved_deal_outcomes.png")

    cm = c["deal_coverage_missingness"]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    f = list(cm["present"])
    ax.barh(f, [cm["present"][k] for k in f], label="present")
    ax.barh(f, [cm["missing"][k] for k in f], left=[cm["present"][k] for k in f], label="missing")
    ax.set_title(f"Deal field coverage (N={cm['n']})"); ax.legend(loc="lower right")
    save(fig, "02_deal_coverage_missingness.png")

    s = c["historical_sample_composition"]
    fig, axs = plt.subplots(1, 3, figsize=(11, 3.8))
    for ax, key in zip(axs, ("deal_type", "consideration_type", "first_walkforward_v1_cohort")):
        d = s[key]
        ax.bar(list(d), list(d.values())); ax.set_title(key, fontsize=9)
        ax.tick_params(axis="x", labelsize=7, rotation=20)
    fig.suptitle("Historical sample composition (reviewed SEC manifest)")
    save(fig, "03_historical_sample_composition.png")

    for i, key in enumerate(("verified_geo_event_timeline", "geo_exposure_by_sector",
                             "source_verification_coverage"), start=4):
        ch = c[key]
        fig, ax = plt.subplots(figsize=(9, 4))
        if key == "source_verification_coverage":
            st = ch["clusters_by_status"]
            ax.bar(list(st), list(st.values()))
            ax.tick_params(axis="x", labelsize=7, rotation=20)
            ax.set_ylim(0, max(1, max(st.values())))
        if ch.get("empty_state"):
            ax.text(0.5, 0.5, ch["empty_state"], ha="center", va="center",
                    transform=ax.transAxes, fontsize=11)
            if key != "source_verification_coverage":
                ax.set_xticks([]); ax.set_yticks([])
        ax.set_title(ch["title"])
        save(fig, f"0{i}_{key}.png")

    res = report["reserved_charts"]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.axis("off")
    rows = [[v["model"], v["title"], v["status"]] for v in res.values()]
    tbl = ax.table(cellText=rows, colLabels=["model", "reserved chart", "status"],
                   loc="center", cellLoc="left")
    tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 1.4)
    ax.set_title("Reserved model charts — " + NOT_AVAILABLE)
    save(fig, "07_reserved_model_charts.png")
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(GEO_DIR / "report"))
    ap.add_argument("--png", default=None, help="directory for optional PNG charts")
    ap.add_argument("--db", default=None, help="optional SQLite store, opened read-only")
    ap.add_argument("--as-of", default=None)
    a = ap.parse_args(argv)
    rep = build_report(db_path=Path(a.db) if a.db else None, as_of=a.as_of)
    for p in write_report(rep, Path(a.out)):
        print(p)
    if a.png:
        for p in render_png(rep, Path(a.png)):
            print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
