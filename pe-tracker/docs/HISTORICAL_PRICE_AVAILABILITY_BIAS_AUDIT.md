# Historical price availability bias audit

**Status:** blocked — live coverage pass not run (`CREDENTIAL_ENVIRONMENT_NOT_VISIBLE`).

This audit compares `PRICE_COVERED` vs `PRICE_UNCOVERED` across canonical variables
after the full 129-deal free-stack pass. Descriptive only — no causal claims.
Do not alter the cohort to balance statistics.

## Planned tables (populate after `free_price_coverage_matrix.json` exists)

| Metric | Value |
|---|---|
| COVERAGE_RATE_CLOSED | n/d |
| COVERAGE_RATE_BREAK | n/d |
| COVERAGE_BY_YEAR | n/d |
| COVERAGE_BY_DEAL_SIZE | n/d |
| MAJOR_OBSERVED_COVERAGE_SKEWS | n/d |

## Principles

- `CANONICAL_CORPUS` ≠ `PRICE_COVERED_CORPUS` ≠ `THESIS_MODEL_COHORT`
- Uncovered deals remain in the canonical SEC corpus
- Gate ≥20 deals with ≥3 real prints is unchanged
