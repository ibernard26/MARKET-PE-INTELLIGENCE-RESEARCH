#!/usr/bin/env python3
"""One-shot resume for the free thesis data stack.

Chains: credential check → smoke → full coverage (+ audit / cohort freeze).
Never prints credential values. Exits 3 if secrets missing.

  cd pe-tracker
  python -m scripts.resume_free_thesis_stack
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.equity_prices.credentials import (  # noqa: E402
    credential_presence,
    missing_credential_names,
)


def main() -> int:
    presence = credential_presence()
    print(json.dumps({"credential_presence": presence}, indent=2))
    missing = missing_credential_names()
    if missing:
        print("CREDENTIAL_ENVIRONMENT_NOT_VISIBLE", file=sys.stderr)
        for name in missing:
            print(name, file=sys.stderr)
        print(
            "See docs/FREE_THESIS_CREDENTIAL_BLOCKER.md — "
            "add Runtime Secrets and start a new agent.",
            file=sys.stderr,
        )
        return 3

    from scripts.smoke_free_providers import main as smoke_main
    rc = smoke_main()
    if rc != 0:
        print(f"smoke failed rc={rc}", file=sys.stderr)
        return rc

    from scripts.run_free_price_coverage import main as cover_main
    return cover_main()


if __name__ == "__main__":
    raise SystemExit(main())
