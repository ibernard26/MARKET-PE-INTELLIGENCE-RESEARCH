"""Phase A load-bearing tests: bitemporal point-in-time semantics.

valid time (when true/occurred) vs known_at (when publicly knowable) vs
ingestion time. A read as_of T must require valid <= T AND known_at <= T.
"""
import sqlite3
from pathlib import Path

import pytest

from src.research import events as ev
from src.research import features as ft
from src.research.market_context import (MarketDataOverwriteError,
                                         PointInTimeMarketContext)
from src.research.observations import (Observation, latest_as_of,
                                       record_observation, state_as_of)

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()


def mem(fk=True):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    if fk:
        c.execute("PRAGMA foreign_keys = ON")
    c.execute("INSERT INTO deals (deal_id, announce_date, status) "
              "VALUES ('D1', '2026-01-01', 'pending')")
    return c


# ---------------------------------------------------- A2: events known later
def test_event_invisible_until_known():
    c2 = mem()
    ev.record_event("D1", "2026-01-01", "announcement", "s", conn=c2,
                    known_at="2026-01-01T08:00:00")
    # occurred Jan 1 but only published Jan 10
    ev.record_event("D1", "2026-01-01T12:00:00", "second_request", "s", conn=c2,
                    known_at="2026-01-10T09:00:00")
    assert [e["event_type"] for e in ev.events_as_of("D1", "2026-01-05", conn=c2)] \
        == ["announcement"]
    assert [e["event_type"] for e in ev.events_as_of("D1", "2026-01-11", conn=c2)] \
        == ["announcement", "second_request"]


def test_observation_invisible_until_known():
    c = mem()
    record_observation(Observation("D1", "2026-01-01T00:00:00", "sec_8k",
                                   offer_price=100.0, consideration_type="cash",
                                   known_at="2026-01-10T00:00:00"), conn=c)
    assert latest_as_of("D1", "2026-01-05", conn=c) is None
    assert state_as_of("D1", "2026-01-05", conn=c) is None
    assert latest_as_of("D1", "2026-01-11", conn=c)["offer_price"] == 100.0


def test_known_at_falls_back_to_source_then_ingestion_never_inferred():
    c = mem()
    record_observation(Observation("D1", "2026-01-01", "a", offer_price=1.0,
                                   source_timestamp="2026-01-02T10:00:00"), conn=c)
    record_observation(Observation("D1", "2026-01-01", "b", offer_price=2.0), conn=c)
    rows = {r["source"]: r for r in c.execute("SELECT * FROM deal_market_observations")}
    assert rows["a"]["known_at_basis"] == "source_timestamp"
    assert rows["a"]["known_at"] == "2026-01-02T10:00:00"
    # no supported historical known time -> known only from ingestion (now),
    # so an unsupported backfill is invisible to past as-of reads
    assert rows["b"]["known_at_basis"] == "ingestion"
    assert state_as_of("D1", "2026-06-01", conn=c)["offer_price"] == 1.0


def test_features_ignore_facts_not_yet_known():
    c = mem()
    record_observation(Observation("D1", "2026-01-01", "s", offer_price=100.0,
                                   target_price=95.0, consideration_type="cash",
                                   known_at="2026-01-01"), conn=c)
    ev.record_event("D1", "2026-01-01", "announcement", "s", conn=c, known_at="2026-01-01")
    ev.record_event("D1", "2026-01-02", "doj_challenge", "s", conn=c, known_at="2026-01-10")
    assert ft.build_features_for_deal("D1", "2026-01-05", conn=c)["under_regulatory_challenge"] is False
    assert ft.build_features_for_deal("D1", "2026-01-11", conn=c)["under_regulatory_challenge"] is True


# ------------------------------------------- A3: sparse state reconstruction
def test_state_terms_persist_across_sparse_rows():
    c = mem()
    record_observation(Observation("D1", "2026-01-01", "sec_8k", offer_price=100.0,
                                   consideration_type="cash",
                                   expected_close_date="2026-06-01",
                                   known_at="2026-01-01"), conn=c)
    record_observation(Observation("D1", "2026-02-01T16:00:00", "nyse_close",
                                   target_price=95.0, known_at="2026-02-01T16:05:00"), conn=c)
    st = state_as_of("D1", "2026-02-02", conn=c)
    assert st["offer_price"] == 100.0
    assert st["expected_close_date"] == "2026-06-01"
    assert st["target_price"] == 95.0
    assert st["target_price_timestamp"] == "2026-02-01T16:00:00"
    f = ft.build_features_for_deal("D1", "2026-02-02", conn=c)
    assert f["raw_spread"] == pytest.approx(5.0)


def test_amendment_supersedes_term():
    c = mem()
    record_observation(Observation("D1", "2026-01-01", "s", offer_price=100.0,
                                   known_at="2026-01-01"), conn=c)
    record_observation(Observation("D1", "2026-03-01", "s", offer_price=105.0,
                                   known_at="2026-03-01"), conn=c)
    assert state_as_of("D1", "2026-02-15", conn=c)["offer_price"] == 100.0
    assert state_as_of("D1", "2026-03-02", conn=c)["offer_price"] == 105.0


def test_market_prints_are_not_forward_filled():
    c = mem()
    record_observation(Observation("D1", "2026-02-01T16:00:00", "nyse_close",
                                   target_price=95.0, acquirer_price=50.0,
                                   known_at="2026-02-01T16:05:00"), conn=c)
    st = state_as_of("D1", "2026-03-01", conn=c)   # a month later, no fresh print
    assert st["target_price"] is None and st["acquirer_price"] is None


# --------------------------------------------- A4: point-in-time market ctx
def test_market_print_invisible_before_known():
    m = PointInTimeMarketContext()
    m.add("sp_return", "2026-02-02T16:00:00", 0.01, "fred:SP500", known_at="2026-02-02T16:30:00")
    assert m.snapshot("2026-02-01")["sp_return"] is None
    snap = m.snapshot("2026-02-02")
    assert snap["sp_return"] == 0.01 and snap["sp_return_meta"]["source"] == "fred:SP500"


def test_market_print_published_late_is_hidden_until_published():
    m = PointInTimeMarketContext()
    m.add("ust10y", "2026-02-02T16:00:00", 4.4, "fred:DGS10", known_at="2026-02-03T15:00:00")
    assert m.snapshot("2026-02-03T09:00:00")["ust10y"] is None
    assert m.snapshot("2026-02-03T16:00:00")["ust10y"] == 4.4


def test_market_context_requires_known_at_and_is_append_only():
    m = PointInTimeMarketContext()
    with pytest.raises(ValueError):
        m.add("sp_return", "2026-02-02", 0.01, "s", known_at=None)
    m.add("sp_return", "2026-02-02", 0.01, "s", known_at="2026-02-02")
    with pytest.raises(MarketDataOverwriteError):
        m.add("sp_return", "2026-02-02", 0.02, "s", known_at="2026-02-02")


# ------------------------------------------------- A6: consideration types
def test_stock_deal_uses_exchange_ratio_not_cash_formula():
    o = {"consideration_type": "stock", "offer_price": 999.0, "exchange_ratio": 0.5,
         "acquirer_price": 200.0, "target_price": 95.0}
    f = ft.build_features("2026-02-02", o, [])
    assert f["raw_spread"] == pytest.approx(5.0)          # 0.5*200 - 95
    assert f["offer_value_basis"] == "stock"


def test_stock_deal_without_acquirer_print_has_no_spread():
    o = {"consideration_type": "stock", "exchange_ratio": 0.5, "target_price": 95.0}
    assert ft.build_features("2026-02-02", o, [])["raw_spread"] is None


def test_unknown_consideration_never_gets_cash_spread():
    o = {"offer_price": 100.0, "target_price": 95.0}
    assert ft.build_features("2026-02-02", o, [])["raw_spread"] is None


# ---------------------------------------------- A7: FK + DB append-only
@pytest.mark.parametrize("fk", [True, False])
def test_orphan_rows_rejected_even_without_fk_pragma(fk):
    c = mem(fk=fk)
    with pytest.raises(sqlite3.IntegrityError):
        record_observation(Observation("NOPE", "2026-01-01", "s", offer_price=1.0), conn=c)
    with pytest.raises(sqlite3.IntegrityError):
        ev.record_event("NOPE", "2026-01-01", "announcement", "s", conn=c)


def test_db_layer_blocks_update_and_delete():
    c = mem()
    record_observation(Observation("D1", "2026-01-01", "s", offer_price=1.0), conn=c)
    ev.record_event("D1", "2026-01-01", "announcement", "s", conn=c)
    for sql in ("UPDATE deal_market_observations SET offer_price = 2",
                "DELETE FROM deal_market_observations",
                "UPDATE deal_events SET source = 'x'",
                "DELETE FROM deal_events"):
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(sql)
