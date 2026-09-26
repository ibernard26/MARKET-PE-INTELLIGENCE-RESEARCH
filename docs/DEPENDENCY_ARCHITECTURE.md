# Dependency architecture

Two Python environments, two responsibilities. Do **not** merge them into one
kitchen-sink `requirements.txt`.

## 1. `pe-tracker/` — research / model application

**Owns:** FRED + SEC ingestion, SQLite canonical store, point-in-time research
layer, `break_logit_v1`, validation harness, registry, portfolio/simulation
prototypes.

**Current `pe-tracker/requirements.txt` (intentionally small):**

| Package | Why it is present |
|---|---|
| `requests` | HTTP (FRED, SEC) |
| `pandas` / `numpy` | tabular / numeric research |
| `openpyxl` | workbook export |
| `python-dotenv` | local secrets |
| `pytest` | tests |
| `scikit-learn` | logistic regression + metrics for `break_logit_v1` |

**Do not add** packages merely because they are common in quant finance.

**Future / optional research dependencies** (document only — not added until
code imports them):

| Package | Intended use |
|---|---|
| `scipy` | statistical diagnostics, confidence intervals |
| `statsmodels` | robust inference / classical stats |
| `matplotlib` | research visualization |

**Explicitly deferred (not added):**

`xgboost`, `lightgbm`, `torch`, `tensorflow`, `jax`, `lifelines`,
`scikit-survival`, C++/pybind11 stacks.

## 2. `arb-intelligence/` — analytical data estate

**Owns:** DuckDB warehouse, dbt models/tests, Dagster orchestration,
Pydantic configs. Read-optimized projection of research data — **not** a
competing source of truth and **not** a canonical writer for deal facts.

Dependencies live in that project's own install path (CI currently installs
`duckdb`, `dbt-core`, `dbt-duckdb` for the dbt job). Keep Dagster / dbt /
DuckDB / Pydantic **there**.

## Boundary rule

| Concern | Environment |
|---|---|
| Canonical deal identity, provenance, model registry | pe-tracker SQLite |
| Analytical marts, invariant dbt tests | arb-intelligence |
| Probability model fit / walk-forward (when authorized) | pe-tracker |
| Orchestrating DuckDB refresh | Dagster in arb-intelligence (read/replicate only) |
