"""FRED ingestion, canonical store, point-in-time market context, derived
features. All HTTP is mocked; no test depends on FRED uptime."""
import sqlite3
from pathlib import Path

import pytest

from src.ingest import fred
from src.ingest.market_series import ALL_SERIES, RATE_SERIES
from src.research import market_data as md
from src.research import features as ft
from src.research.market_context import MARKET_FIELDS

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()
FAKE_KEY = "TEST-ONLY-NOT-A-REAL-KEY"      # dummy; real keys are never in the repo


def mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def payload(*pairs, rt=None):
    return {"observations": [
        {"date": d, "value": v, **({"realtime_start": rt[i], "realtime_end": "9999-12-31"} if rt else {})}
        for i, (d, v) in enumerate(pairs)]}


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body
        self.text = str(body)

    def json(self):
        return self._b


class Session:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        if self.exc:
            raise self.exc
        return self.resp


# --------------------------------------------------------------- parsing
def test_dot_becomes_null_never_zero():
    obs = fred.parse_observations(payload(("2026-01-02", "4800.1"), ("2026-01-05", ".")), "SP500")
    assert obs[0]["value"] == 4800.1 and obs[1]["value"] is None


def test_non_numeric_value_rejected():
    with pytest.raises(fred.FredError):
        fred.parse_observations(payload(("2026-01-02", "abc")), "SP500")


def test_unexpected_payload_rejected():
    with pytest.raises(fred.FredError):
        fred.parse_observations({"error_message": "Bad"}, "SP500")


def test_key_read_from_env_only(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    with pytest.raises(fred.FredError):
        fred.fetch_series("SP500", session=Session(Resp(200, payload())))
    monkeypatch.setenv("FRED_API_KEY", FAKE_KEY)
    s = Session(Resp(200, payload(("2026-01-02", "1"))))
    fred.fetch_series("DGS10", session=s)
    assert s.calls[0]["api_key"] == FAKE_KEY and s.calls[0]["series_id"] == "DGS10"


def test_errors_never_leak_the_key(monkeypatch):
    import requests
    monkeypatch.setenv("FRED_API_KEY", FAKE_KEY)
    exc = requests.ConnectionError(f"failed https://api.stlouisfed.org/x?api_key={FAKE_KEY}&a=1")
    with pytest.raises(fred.FredError) as e:
        fred.fetch_series("SP500", session=Session(exc=exc))
    assert FAKE_KEY not in str(e.value) and "***" in str(e.value)
    with pytest.raises(fred.FredError) as e2:
        fred.fetch_series("SP500", session=Session(Resp(400, f"bad key {FAKE_KEY}")))
    assert FAKE_KEY not in str(e2.value)


def test_first_release_vintage_requests_alfred(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", FAKE_KEY)
    s = Session(Resp(200, payload(("2026-01-02", "4.1"), rt=["2026-01-05"])))
    obs = fred.fetch_series("DGS10", vintage="first_release", session=s)
    assert s.calls[0]["output_type"] == 4 and obs[0]["realtime_start"] == "2026-01-05"


# ----------------------------------------------------- canonical storage
def test_store_provenance_and_nulls():
    c = mem()
    obs = fred.parse_observations(payload(("2026-01-02", "4.10"), ("2026-01-05", ".")), "DGS10")
    fred.store_observations("DGS10", obs, "current", c, fetched_at="2026-01-06T12:00:00")
    rows = [dict(r) for r in c.execute("SELECT * FROM market_observations ORDER BY obs_date")]
    assert rows[1]["value"] is None                         # NULL preserved
    assert {r["source"] for r in rows} == {"FRED"}
    assert rows[0]["source_identifier"] == "FRED:DGS10"
    assert rows[0]["known_at"] == "2026-01-06T12:00:00" and rows[0]["known_at_basis"] == "ingestion"
    assert rows[0]["ingestion_timestamp"]


def test_duplicate_pull_is_idempotent_revision_is_appended():
    c = mem()
    o = fred.parse_observations(payload(("2026-01-02", "80.0")), "DCOILWTICO")
    assert fred.store_observations("DCOILWTICO", o, "current", c, "2026-01-03T09:00:00")["appended"] == 1
    assert fred.store_observations("DCOILWTICO", o, "current", c, "2026-01-04T09:00:00")["appended"] == 0
    rev = fred.parse_observations(payload(("2026-01-02", "80.5")), "DCOILWTICO")
    assert fred.store_observations("DCOILWTICO", rev, "current", c, "2026-01-10T09:00:00")["appended"] == 1
    # the earlier view keeps the original value; the later view sees the revision
    assert md.level(c, "DCOILWTICO", "2026-01-05")["value"] == 80.0
    assert md.level(c, "DCOILWTICO", "2026-01-11")["value"] == 80.5
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE market_observations SET value = 1")


def test_first_release_known_at_is_end_of_release_day():
    c = mem()
    o = fred.parse_observations(payload(("2026-01-02", "4.1"), rt=["2026-01-05"]), "DGS10")
    fred.store_observations("DGS10", o, "first_release", c)
    r = c.execute("SELECT known_at, known_at_basis FROM market_observations").fetchone()
    assert tuple(r) == ("2026-01-05T23:59:59.999999", "fred_first_release")


def test_treasury_series_registered_but_not_a_model_feature():
    from src.model.dataset import FEATURES
    assert "DGS10" in RATE_SERIES and "DGS10" in ALL_SERIES
    for s in ("SP500", "NASDAQCOM", "DCOILWTICO", "DCOILBRENTEU"):
        assert s in ALL_SERIES
    assert not any(f.startswith(("ust10y", "sp_", "nasdaq", "wti", "brent")) for f in FEATURES)


# ------------------------------------------------ point-in-time + derived
def _seed(c, series, rows, fetched):
    fred.store_observations(series, fred.parse_observations(payload(*rows), series),
                            "current", c, fetched_at=fetched)


def test_value_invisible_before_known():
    c = mem()
    _seed(c, "SP500", [("2026-02-02", "5000")], "2026-02-03T08:00:00")
    assert md.level(c, "SP500", "2026-02-02") is None           # not ingested yet
    assert md.level(c, "SP500", "2026-02-03")["value"] == 5000.0


def test_returns_skip_gaps_never_fill():
    c = mem()
    _seed(c, "SP500", [("2026-02-02", "100"), ("2026-02-03", "."), ("2026-02-04", "110")],
          "2026-02-05T00:00:00")
    r = md.simple_return(c, "SP500", "2026-02-05")
    assert r["value"] == pytest.approx(0.10)                     # 110 vs last REAL print
    assert r["obs_dates"] == ["2026-02-04", "2026-02-02"]
    assert r["source"] == "FRED" and r["known_at"] == "2026-02-05T00:00:00"
    _seed(c, "NASDAQCOM", [("2026-02-04", "200")], "2026-02-05T00:00:00")
    assert md.simple_return(c, "NASDAQCOM", "2026-02-05") is None   # one print only


def test_treasury_level_and_change_and_brent_wti_spread():
    c = mem()
    _seed(c, "DGS10", [("2026-02-02", "4.10"), ("2026-02-03", "4.25")], "2026-02-04T00:00:00")
    assert md.level(c, "DGS10", "2026-02-04")["value"] == 4.25
    assert md.change(c, "DGS10", "2026-02-04")["value"] == pytest.approx(0.15)
    _seed(c, "DCOILBRENTEU", [("2026-02-02", "85"), ("2026-02-03", ".")], "2026-02-04T00:00:00")
    _seed(c, "DCOILWTICO", [("2026-02-02", "80"), ("2026-02-03", "81")], "2026-02-04T00:00:00")
    s = md.brent_wti_spread(c, "2026-02-04")
    assert s["value"] == 5.0 and s["obs_dates"] == ["2026-02-02", "2026-02-02"]


def test_market_context_from_store_feeds_features_point_in_time():
    c = mem()
    _seed(c, "SP500", [("2026-02-02", "100"), ("2026-02-03", "102")], "2026-02-03T22:00:00")
    _seed(c, "DGS10", [("2026-02-03", "4.2")], "2026-02-03T22:00:00")
    ctx = md.market_context_from_store(c, ["2026-02-03", "2026-02-04"])
    early = ctx.snapshot("2026-02-03T21:00:00")               # before ingestion
    assert early["sp_return"] is None and early["ust10y"] is None
    snap = ctx.snapshot("2026-02-04")
    assert snap["sp_return"] == pytest.approx(0.02) and snap["ust10y"] == 4.2
    assert snap["sp_return_meta"]["source"] == "FRED:SP500"
    f = ft.build_features("2026-02-04", {}, [], market_ctx=ctx)
    assert f["sp_return"] == pytest.approx(0.02)
    assert set(MARKET_FIELDS) <= set(md.RESEARCH_FEATURES)


def test_research_features_have_provenance():
    c = mem()
    for s in ("SP500", "NASDAQCOM", "DCOILWTICO", "DCOILBRENTEU", "DGS10"):
        _seed(c, s, [("2026-02-02", "10"), ("2026-02-03", "11")], "2026-02-04T00:00:00")
    out = md.research_features(c, "2026-02-04")
    assert set(out) == {"sp_return", "nasdaq_return", "wti_return", "brent_return",
                        "brent_wti_spread", "ust10y", "ust10y_change"}
    for v in out.values():
        assert {"series_id", "obs_dates", "source", "known_at", "ingestion_timestamp"} <= set(v)


def test_ingest_all_end_to_end_mocked(monkeypatch, tmp_path):
    import src.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    monkeypatch.setenv("FRED_API_KEY", FAKE_KEY)
    body = payload(("2026-01-02", "1.5"), ("2026-01-05", "."))
    monkeypatch.setattr(fred.requests, "get", lambda *a, **k: Resp(200, body))
    out = fred.ingest_all(start="2026-01-01")
    assert set(out) == set(ALL_SERIES)
    d = out["DGS10"]
    assert d["rows_fetched"] == 2 and d["null_observations"] == 1
    assert d["latest_non_null_value"] == 1.5 and d["source"] == "FRED"
    with db.connect() as c:
        assert c.execute("SELECT close FROM prices WHERE series_id='DGS10' AND obs_date='2026-01-05'").fetchone()[0] is None
        assert c.execute("SELECT COUNT(*) FROM market_observations").fetchone()[0] == 2 * len(ALL_SERIES)
