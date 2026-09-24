"""Normalize the Q3 2026 research staging into canonical deals + lifecycle events.

Reads the register and ChatGPT staging files (never modifies them) and writes
the canonical_* CSVs in data/research/. See src/research/canonical.py for the
identity and label rules. Does not touch the SQLite store or any model.
Run:  python scripts/build_canonical_2026q3.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research.canonical_q3_2026 import build, write  # noqa: E402


def main():
    b = build()
    for name, n in write(b).items():
        print(f"{n:>4} rows -> data/research/{name}")
    print()
    for k, v in b.stats.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
