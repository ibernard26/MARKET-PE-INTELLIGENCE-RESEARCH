"""Stage 1 tests: append-only observations and event lifecycle integrity.

An in-memory database (built from schema.sql) keeps these off the real store.
"""
import sqlite3
from pathlib import Path

import pytest

from src.research import events as ev
from src.research.observations import (Observation, ObservationOverwriteError,
                                       latest_as_of, record_observation)

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()


def mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("PRAGMA foreign_keys = ON")
    for d in ("D1", "D2"):   # observations/events must reference a real deal
        c.execute("INSERT INTO deals (deal_id, announce_date, status) VALUES (?, '2026-01-01', 'pending')", (d,))
    return c


def O(*a, **k):
    """Observation published at its valid time (explicit known_at)."""
    k.setdefault("known_at", a[1])
    return Observation(*a, **k)


def rec_event(*a, **k):
    """Event published when it occurred (explicit known_at)."""
    k.setdefault("known_at", a[1])
    return ev.record_event(*a, **k)


# ------------------------------------------------------------- observations
def test_observation_is_append_only():
    c = mem()
    o = O("D1", "2026-01-05T00:00:00", "sec_filing", target_price=95.0)
    record_observation(o, conn=c)
    with pytest.raises(ObservationOverwriteError):
        record_observation(o, conn=c)   # same key must not overwrite


def test_point_in_time_read_excludes_the_future():
    c = mem()
    record_observation(O("D1", "2026-01-05T00:00:00", "s", target_price=95.0), conn=c)
    record_observation(O("D1", "2026-02-01T00:00:00", "s", target_price=98.0), conn=c)
    # as-of mid-January: only the Jan 5 observation is knowable
    row = latest_as_of("D1", "2026-01-15", conn=c)
    assert row["target_price"] == 95.0
    # as-of February: the later observation is now visible
    assert latest_as_of("D1", "2026-02-15", conn=c)["target_price"] == 98.0


def test_missing_fields_stay_none_not_fabricated():
    c = mem()
    record_observation(O("D1", "2026-01-05T00:00:00", "s", offer_price=100.0), conn=c)
    row = latest_as_of("D1", "2026-01-06", conn=c)
    assert row["offer_price"] == 100.0
    assert row["target_price"] is None          # never coerced to 0.0
    assert row["unaffected_price"] is None


def test_provenance_is_required():
    with pytest.raises(ValueError):
        O("D1", "2026-01-05T00:00:00", "")   # empty source rejected


def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        O("D1", "2026-01-05T00:00:00", "s", status="maybe")


def test_json_attrs_roundtrip():
    c = mem()
    record_observation(O("D1", "2026-01-05T00:00:00", "s",
                                   regulatory_attrs={"cfius": True, "hsr": "filed"}), conn=c)
    row = latest_as_of("D1", "2026-01-06", conn=c)
    assert row["regulatory_attrs"] == {"cfius": True, "hsr": "filed"}


# ------------------------------------------------------------------- events
def test_event_type_must_be_known():
    c = mem()
    with pytest.raises(ValueError):
        rec_event("D1", "2026-01-05", "made_up_event", "s", conn=c)


def test_resolution_cannot_precede_announcement():
    c = mem()
    rec_event("D1", "2026-02-01", "announcement", "s", conn=c)
    with pytest.raises(ev.LifecycleError):
        rec_event("D1", "2026-01-01", "closing", "s", conn=c)   # before announce


def test_events_are_append_only():
    c = mem()
    rec_event("D1", "2026-02-01", "announcement", "s", conn=c)
    with pytest.raises(ev.EventOverwriteError):
        rec_event("D1", "2026-02-01", "announcement", "s", conn=c)


def test_events_as_of_is_point_in_time():
    c = mem()
    rec_event("D1", "2026-02-01", "announcement", "s", conn=c)
    rec_event("D1", "2026-05-01", "closing", "s", conn=c)
    early = ev.events_as_of("D1", "2026-03-01", conn=c)
    assert [e["event_type"] for e in early] == ["announcement"]   # closing not yet knowable
    full = ev.events_as_of("D1", "2026-06-01", conn=c)
    assert [e["event_type"] for e in full] == ["announcement", "closing"]
