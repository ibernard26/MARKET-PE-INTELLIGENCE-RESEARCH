"""FRED ingestion (market indices, crude, Treasury rates).

Path:  FRED API -> parse -> canonical store (prices + append-only
       market_observations with known_at / provenance) -> research layer.

Rules:
* The API key is read ONLY from the FRED_API_KEY environment variable and is
  never logged, printed or included in exception text (URLs are redacted).
* FRED encodes a missing observation as "." — it becomes SQL NULL, never a
  carried or interpolated value.
* known_at: live pulls are stamped with the ingestion time. With
  vintage="first_release", ALFRED's initial-release vintage date is used
  (end of that day — FRED does not publish the time of day). Nothing else is
  inferred.
"""
from __future__ import annotations

import os
import re
import sqlite3
from typing import Optional

import requests

from ..config import FRED_BASE, START_DATE
from ..db import connect, upsert_prices
from ..research.bitemporal import normalize_as_of, now_iso
from .market_series import ALL_SERIES

SOURCE = "FRED"
_KEY_RE = re.compile(r"(api_key=)[^&\s]+", re.IGNORECASE)


class FredError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.getenv("FRED_API_KEY", "")
    if not key or key == "your_key_here":
        raise FredError("FRED_API_KEY is not set in the environment "
                        "(see .env.example; the key is never stored in the repo)")
    return key


def redact(text: str) -> str:
    """Strip any api_key=... (and the literal key value) from text."""
    text = _KEY_RE.sub(r"\1***", str(text))
    key = os.getenv("FRED_API_KEY")
    return text.replace(key, "***") if key else text


def parse_observations(payload: dict, series_id: str) -> list[dict]:
    """FRED JSON -> [{obs_date, value|None, realtime_start, realtime_end}]."""
    if not isinstance(payload, dict) or "observations" not in payload:
        raise FredError(f"unexpected FRED payload for {series_id}: {redact(str(payload)[:200])}")
    out = []
    for o in payload["observations"]:
        raw = o.get("value", ".")
        try:
            value = None if raw in (".", "", None) else float(raw)
        except ValueError as exc:
            raise FredError(f"{series_id} {o.get('date')}: non-numeric value {raw!r}") from exc
        out.append({"obs_date": o["date"], "value": value,
                    "realtime_start": o.get("realtime_start"),
                    "realtime_end": o.get("realtime_end")})
    return out


def fetch_series(series_id: str, start: str = START_DATE, end: str = None,
                 vintage: str = "current", timeout: int = 30,
                 session: Optional[requests.Session] = None) -> list[dict]:
    """Fetch one series. vintage='current' (latest values) or 'first_release'
    (ALFRED initial-release values with their release dates)."""
    params = {"series_id": series_id, "api_key": _api_key(), "file_type": "json",
              "observation_start": start}
    if end:
        params["observation_end"] = end
    if vintage == "first_release":
        params.update(realtime_start="1776-07-04", realtime_end="9999-12-31", output_type=4)
    elif vintage != "current":
        raise ValueError("vintage must be 'current' or 'first_release'")
    get = (session or requests).get
    try:
        resp = get(FRED_BASE, params=params, timeout=timeout)
    except requests.RequestException as exc:          # URL would contain the key
        raise FredError(f"FRED request failed for {series_id}: {redact(exc)}") from None
    if resp.status_code != 200:
        raise FredError(f"FRED returned {resp.status_code} for {series_id}: "
                        f"{redact(resp.text[:200])}")
    return parse_observations(resp.json(), series_id)


def store_observations(series_id: str, obs: list[dict], vintage: str,
                       conn: sqlite3.Connection, fetched_at: str = None) -> dict:
    """Append to market_observations. Idempotent: a value identical to the latest
    stored value for (series, date) is not re-appended; a CHANGED value (a FRED
    revision) is appended as a new row with its own known_at."""
    fetched_at = fetched_at or now_iso()
    added = unchanged = 0
    for o in obs:
        if vintage == "first_release" and o.get("realtime_start"):
            known_at, basis = normalize_as_of(o["realtime_start"]), "fred_first_release"
        else:
            known_at, basis = fetched_at, "ingestion"
        prev = conn.execute(
            "SELECT value FROM market_observations WHERE series_id = ? AND obs_date = ? "
            "ORDER BY known_at DESC LIMIT 1", (series_id, o["obs_date"])).fetchone()
        if prev is not None and prev[0] == o["value"]:
            unchanged += 1
            continue
        try:
            conn.execute(
                "INSERT INTO market_observations (series_id, obs_date, value, source, "
                "source_identifier, realtime_start, realtime_end, known_at, known_at_basis) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (series_id, o["obs_date"], o["value"], SOURCE, f"FRED:{series_id}",
                 o.get("realtime_start"), o.get("realtime_end"), known_at, basis))
            added += 1
        except sqlite3.IntegrityError:
            unchanged += 1        # same (series, date, known_at) already stored
    return {"appended": added, "unchanged": unchanged}


def ingest_all(start: str = START_DATE, end: str = None, vintage: str = "current",
               series=None) -> dict:
    """Pull every registered series into prices (current values) and the
    append-only market_observations store. Returns a per-series summary."""
    summary = {}
    for series_id in (series or ALL_SERIES):
        obs = fetch_series(series_id, start=start, end=end, vintage=vintage)
        if vintage == "current":      # legacy table holds current values only
            upsert_prices([(series_id, o["obs_date"], o["value"], SOURCE) for o in obs])
        with connect() as c:
            st = store_observations(series_id, obs, vintage, c)
        non_null = [o for o in obs if o["value"] is not None]
        summary[series_id] = {
            "rows_fetched": len(obs), "null_observations": len(obs) - len(non_null),
            "latest_observation_date": obs[-1]["obs_date"] if obs else None,
            "latest_non_null_date": non_null[-1]["obs_date"] if non_null else None,
            "latest_non_null_value": non_null[-1]["value"] if non_null else None,
            "source": SOURCE, **st}
    return summary
