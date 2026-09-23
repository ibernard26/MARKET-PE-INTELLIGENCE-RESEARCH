"""No FRED API key (or any key-shaped FRED credential) in tracked files."""
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PATTERNS = [re.compile(r"FRED_API_KEY\s*=\s*['\"]?[0-9a-f]{32}", re.I),
            re.compile(r"api_key=[0-9a-f]{32}", re.I)]


def tracked_text_files():
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=REPO, text=True)
    except Exception:
        pytest.skip("not a git checkout")
    for rel in out.splitlines():
        p = REPO / rel
        if p.suffix.lower() in {".xlsx", ".png", ".jpg", ".pdf", ".db", ".parquet", ".duckdb"}:
            continue
        try:
            yield rel, p.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue


def test_no_fred_key_in_tracked_files():
    live = os.getenv("FRED_API_KEY")
    hits = []
    for rel, text in tracked_text_files():
        if any(p.search(text) for p in PATTERNS):
            hits.append(rel)
        if live and len(live) >= 16 and live in text:
            hits.append(rel + " (contains the live FRED_API_KEY)")
    assert not hits, f"possible FRED key committed in: {hits}"


def test_env_files_are_ignored():
    for name in (".env", "pe-tracker/.env", "x.env", ".env.local", "pe-tracker/secrets.env"):
        r = subprocess.run(["git", "check-ignore", "-q", name], cwd=REPO)
        assert r.returncode == 0, f"{name} is not git-ignored"
