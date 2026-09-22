"""FRED ingestion.

FRED serves all four series the tracker needs, so the pipeline has exactly
one external dependency and one API key. FRED encodes a missing observation
as the string "." -- that becomes SQL NULL here, never a carried value.
"""
import requests

from ..config import FRED_API_KEY, FRED_BASE, SERIES, START_DATE
from ..db import upsert_prices


class FredError(RuntimeError):
    pass


def fetch_series(series_id: str, start: str = START_DATE, end: str = None,
                 timeout: int = 30):
    """Return [(obs_date, close_or_None), ...] for one FRED series."""
    if not FRED_API_KEY:
        raise FredError(
            "FRED_API_KEY is not set. Copy .env.example to .env and add a free "
            "key from https://fred.stlouisfed.org/docs/api/api_key.html"
        )
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start,
    }
    if end:
        params["observation_end"] = end

    resp = requests.get(FRED_BASE, params=params, timeout=timeout)
    if resp.status_code != 200:
        raise FredError(f"FRED returned {resp.status_code} for {series_id}: {resp.text[:200]}")

    payload = resp.json()
    if "observations" not in payload:
        raise FredError(f"Unexpected FRED payload for {series_id}: {str(payload)[:200]}")

    out = []
    for obs in payload["observations"]:
        raw = obs.get("value", ".")
        value = None if raw in (".", "", None) else float(raw)
        out.append((obs["date"], value))
    return out


def ingest_all(start: str = START_DATE, end: str = None):
    """Pull every configured series into the prices table. Returns a summary."""
    summary = {}
    for series_id in SERIES:
        obs = fetch_series(series_id, start=start, end=end)
        rows = [(series_id, d, v, "FRED") for d, v in obs]
        upsert_prices(rows)
        summary[series_id] = {
            "fetched": len(obs),
            "with_value": sum(1 for _, v in obs if v is not None),
        }
    return summary
