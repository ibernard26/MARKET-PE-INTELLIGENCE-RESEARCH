"""Blinded review packet generator (prereg §5).

Packets contain identity records, evidence-filing references (URLs, acceptance
timestamps, full Item 1/1A/7/7A character-offset spans) and excerpts chosen by a
fixed broad vocabulary that is independent of the labeler rules. They NEVER
contain first-pass labels, rule outputs, or which sentence a rule matched.
"""
from __future__ import annotations

import csv
import json
import re

from .rules import FP, sentences

EXCERPT_VOCAB = re.compile(
    r"\b(commodit\w*|raw materials?|ingredients?|feedstocks?|fuel|diesel|gasoline|jet fuel|energy|"
    r"electricity|power|utilit(y|ies)|natural gas|crude|oil|petroleum|coal|steel|aluminum|aluminium|"
    r"copper|metals?|resins?|plastics?|packaging|paper|pulp|corn|wheat|soybeans?|sugar|coffee|cocoa|"
    r"cotton|dairy|milk|beef|pork|poultry|chicken|meat|grains?|feed|livestock|reserves|mine|mines|"
    r"mining|drill\w*|refin\w*|produc(e|es|er|ers|tion)|hedg\w*|derivative\w*|swaps?|futures|"
    r"forward contracts?|collars?|options?)\b", re.I)
MAX_EXCERPTS_PER_DOC = 80
SECTIONS = {"1": r"Business", "1A": r"Risk\s+Factors", "7": r"Management[’'`s]*\s+Discussion",
            "7A": r"Quantitative\s+and\s+Qualitative"}
RESPONSE_FIELDS = ["deal_id", "party", "producer", "consumer", "hedged", "evidence_ref", "note"]


def section_spans(text: str) -> dict:
    """Character spans for Items 1, 1A, 7, 7A in the normalized text: for each item the
    occurrence followed by the longest span to the next Item heading (skips the TOC)."""
    heads = [(m.start(), m.group(1).upper()) for m in
             re.finditer(r"\bItem\s+(\d{1,2}[AB]?)\b\.?", text, re.I)]
    spans = {}
    for i, (st, it) in enumerate(heads):
        if it not in SECTIONS:
            continue
        if not re.match(r"Item\s+" + it + r"\b\.?\s*[:.\-–—]?\s*" + SECTIONS[it], text[st:st + 80], re.I):
            continue
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        if it not in spans or (end - st) > (spans[it][1] - spans[it][0]):
            spans[it] = (st, end)
    return {k: list(v) for k, v in sorted(spans.items())}


def excerpts(text: str) -> tuple[list, int]:
    hits, seen = [], set()
    for off, s in sentences(text):
        s2 = s.strip()
        if 20 < len(s2) < 1500 and FP.search(s2) and EXCERPT_VOCAB.search(s2):
            k = s2[:120]
            if k not in seen:
                seen.add(k)
                hits.append((off, s2[:600]))
    return hits[:MAX_EXCERPTS_PER_DOC], len(hits)


def party_block(ed, deal_id: str, party: dict) -> tuple[list[str], dict]:
    lines = [f"\n## {party['party'].upper()}: {party['name']}"]
    idx = {"party": party["party"], "name": party["name"], "cik": party["cik"],
           "identity": party["identity"], "filings": []}
    for k, v in party["identity"].items():
        if v not in ("", None, False):
            lines.append(f"- identity.{k}: {v}")
    if not party["filings"]:
        lines.append("- No pre-announcement evidence filings available for this party "
                     "(see identity record).")
    for f in party["filings"]:
        text = ed.document_text(party["cik"], f)
        spans = section_spans(text)
        ex, total = excerpts(text)
        url = ed.doc_url(party["cik"], f)
        lines += [f"\n### {f['form']} {f['accession']}",
                  f"- filed {f['filing_date']}; SEC acceptance (ET) {f['acceptance_et']}",
                  f"- full document: {url}",
                  "- full-section spans (character offsets in whitespace-normalized text): " +
                  (", ".join(f"Item {k} [{a}:{b}]" for k, (a, b) in spans.items()) or "none detected"),
                  f"- excerpts: {len(ex)} of {total} first-person sentences matching the broad "
                  f"review vocabulary (document order; cap {MAX_EXCERPTS_PER_DOC}). Excerpts are NOT "
                  f"a complete evidence set; consult the full sections."]
        lines += [f"  - [{f['accession']}@{off}] {s}" for off, s in ex]
        idx["filings"].append({**{k: f[k] for k in ("accession", "form", "filing_date",
                                                    "acceptance_et")}, "url": url,
                               "sections": spans, "excerpts_shown": len(ex), "excerpts_total": total})
    return lines, idx


README = """# Commodity-exposure v2: blinded review packet

This packet is for the separate **AI-assisted** second review run by Isaiah Bernard
(prereg `docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v2.md` §5–§7). It is **not** an independent
human review. It contains **no first-pass labels**: the reviewer must not be given
`data/research/commodity_exposure_v2_labels.csv` or `commodity_exposure_v2_run.json`.

For each deal × party, fill one row of `response_template.csv`:
- `producer`: yes | unknown
- `consumer`: yes | unknown
- `hedged`:   yes | no_disclosed | unknown
- `evidence_ref`: accession@offset (or Item + accession) supporting each non-unknown value
- `note`: free text

Criteria (verbatim intent of prereg §1):
- Use only the listed filings (all dated before the announcement). Absence of evidence is
  `unknown`, never `no`.
- Ignore generic references to energy, power, or operating efficiency, and
  list-of-factors sentences.
- **producer = yes**: the company itself produces, extracts, mines, drills for, refines, or
  processes (meat/poultry/grain) a named physical commodity, or reports proved reserves.
  Buying, transporting, servicing, or investing does not count.
- **consumer = yes**: evidence that a specific commodity input (or explicit raw
  materials/commodities) affects the company's own costs, with an impact or variability
  statement. Sales-price exposure does not count.
- **hedged = yes**: the company uses or holds commodity derivatives (futures, forwards,
  swaps, options, collars on commodities). Interest-rate/FX/equity/credit hedges do not
  count. **no_disclosed**: it explicitly says it does not hedge its commodity exposure.
- If the acquirer could not be identified as an SEC registrant (identity record shows a
  reason), label all acquirer flags `unknown`.

Excerpts were selected by a broad vocabulary that is independent of the first-pass rules;
they are deliberately over-inclusive and capped. Use the full-section offsets/URLs where needed.
"""


def write_packet(ed, plan_by_id: dict, sample: list[str], out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    index = {"protocol": "docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v2.md", "blinded": True,
             "contains_first_pass_labels": False, "reviewer": "AI-assisted, run separately by "
             "Isaiah Bernard; not independent human review", "deals": {}}
    for did in sample:
        d = plan_by_id[did]
        lines = [f"# {did}", f"Announcement date: {d['announce_date']}. Only filings accepted "
                 f"before this date are evidence."]
        index["deals"][did] = {"announce_date": d["announce_date"], "parties": []}
        for p in d["parties"]:
            blk, pidx = party_block(ed, did, p)
            lines += blk
            index["deals"][did]["parties"].append(pidx)
        (out_dir / f"{did}.md").write_text("\n".join(lines) + "\n")
    (out_dir / "index.json").write_text(json.dumps(index, indent=1, default=str))
    (out_dir / "README.md").write_text(README)
    with (out_dir / "response_template.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=RESPONSE_FIELDS)
        w.writeheader()
        for did in sample:
            for party in ("target", "acquirer"):
                w.writerow({"deal_id": did, "party": party})
