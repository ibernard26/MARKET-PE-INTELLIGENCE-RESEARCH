# Public M&A Intelligence Snapshot

Coverage: **2026-07-01 through 2026-09-24 inclusive**.

This is a staging/research corpus for `MARKET-PE-INTELLIGENCE-RESEARCH`, designed to work without SEC/EDGAR developer access. It relies on public regulator pages, issuer investor-relations pages, and selected Reuters reports.

Do **not** train directly from these files. Use the repo chain: public source -> verification -> canonical bitemporal event/deal -> dataset-quality report -> training-readiness gate -> reviewed model run.

Key label rules:
- Primary company completion can become a strong `Y=0` candidate after the original deal terms/announcement record are sourced.
- Regulatory clearance is not automatically `Y=0`.
- Court/regulatory blocking is not automatically `Y=1` until transaction termination is verified.
- Rejected non-binding bids are not broken mergers.
- Preserve date-only precision; do not invent intraday source times.

Files:
- `public_mna_events.csv`
- `public_mna_events.json`
- `CLAUDE_CODE_PUBLIC_INGEST_PROMPT.md`

This snapshot is curated, not an exhaustive global M&A tape.
