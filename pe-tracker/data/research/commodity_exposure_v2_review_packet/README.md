# Commodity-exposure v2: blinded review packet

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
