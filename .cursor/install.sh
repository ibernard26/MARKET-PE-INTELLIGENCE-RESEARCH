#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the Market & PE Intelligence repo.
# Runs after the repository is checked out. Safe to run repeatedly.
set -euo pipefail

cd "$(dirname "$0")/.."

# Repo docs and CLI entry points invoke `python` (not `python3`). Make sure it
# resolves. On the default image this installs the python-is-python3 alias.
if ! command -v python >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python-is-python3
fi

# 1) Research pipeline (SQLite): requests / pandas / numpy / openpyxl / pytest /
#    scikit-learn / python-dotenv.
python -m pip install --user -r pe-tracker/requirements.txt

# 2) Data estate (DuckDB + dbt + Dagster) installed editable so the
#    `orchestrator` package and console scripts (dbt, dagster) are available.
python -m pip install --user -e arb-intelligence

# 3) Seed the local SQLite store: schema + NYSE trading calendar + deal ledger.
#    Both commands are idempotent (INSERT OR REPLACE). The DB is gitignored.
( cd pe-tracker && python -m src.cli init && python seed_deals.py )

# 4) Land the DuckDB silver/gold warehouse from the bundled 6-deal fixture so the
#    dbt models and Dagster job have data to build against out of the box.
( cd arb-intelligence && python scripts/migrate_sqlite_to_silver.py )

echo "[cloud-agent install] complete"
