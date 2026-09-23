# Automation map

| Layer | Owner | Purpose |
|---|---|---|
| GitHub Actions CI (`.github/workflows/ci.yml`) | GitHub | pytest (all network calls mocked) and dbt invariants on every PR and push to main |
| Claude saved task: **MI-PE · Data Pipeline Daily** (weekdays; Fridays add a weekly roll-up) | Claude | **Repository and data-pipeline monitoring:** FRED freshness and gaps, dataset-quality report, `MODEL_DATA_STATUS`, newly resolved deals as candidate provider entries, regulatory items that affect break risk |
| ChatGPT weekday market-intelligence automation | ChatGPT | **Human-readable market reporting.** Not duplicated by Claude |
| Claude: IC-001 daily memo and weekly brief | Claude | A separate thesis memo (CFTC carve-outs); unrelated to this pipeline |

## Guardrails
* Automations **never write to model training tables** directly. Deal facts enter only
  through `HistoricalDealProvider` → validation → `record_provenance`.
* Nothing triggers a model fit. The flow is: ingestion → validation →
  `python -m src.model.data_quality` → readiness gate → reviewed, manual model run.
* Data that is unavailable is reported as unavailable, never estimated.
