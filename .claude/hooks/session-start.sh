#!/bin/bash
set -euo pipefail

# SessionStart hook: install the pe-tracker Python dependencies so that
# `python -m pytest`, `compileall`, and ruff work from a fresh container in
# Claude Code on the web.
#
# Why this exists: some branches declare deps that a bare container lacks
# (e.g. exchange-calendars on the spread_stress_v2 work). Without them,
# pytest fails at *collection* with ModuleNotFoundError, which looks like
# "all tests failed" even though the code is fine. Installing the declared
# requirements up front removes that whole class of false alarm.
#
# Web-only by default: local Claude Code sessions are left to the developer's
# own environment. Remove the guard below if you want it to run everywhere.

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

pip install -r "$CLAUDE_PROJECT_DIR/pe-tracker/requirements.txt"
