"""Project coverage window and DFF registration.

The April 20, 2026 floor is a PROJECT data-coverage policy (the tracker's first
logged session), not a FRED limitation: fetch_series clamps any earlier start.
DFF is research context only and must stay out of fs_v1.
"""
import pytest

from src.config import SERIES, START_DATE
from src.ingest import fred
from src.ingest.market_series import ALL_SERIES, RATE_SERIES
from src.model import dataset
from src.research import market_context, market_data

FAKE_KEY = "0" * 32


class _Resp:
    status_code = 200
    text = ""

    def json(self):
        return {"observations": []}


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append(dict(params))
        return _Resp()


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", FAKE_KEY)
    return _Session()


def test_project_floor_is_april_20_2026():
    assert START_DATE == "2026-04-20"


@pytest.mark.parametrize("vintage", ["current", "first_release"])
def test_earlier_start_is_clamped_to_floor(session, vintage):
    fred.fetch_series("DFF", start="1954-07-01", vintage=vintage, session=session)
    assert session.calls[0]["observation_start"] == START_DATE


def test_missing_start_uses_floor(session):
    fred.fetch_series("DFF", start=None, session=session)
    assert session.calls[0]["observation_start"] == START_DATE


def test_later_start_is_kept(session):
    fred.fetch_series("DFF", start="2026-09-01", end="2026-09-15", session=session)
    assert session.calls[0]["observation_start"] == "2026-09-01"
    assert session.calls[0]["observation_end"] == "2026-09-15"


def test_dff_registered_as_rate_series_not_in_config():
    assert RATE_SERIES["DFF"] == ("Effective Federal Funds Rate", "percent")
    assert "DFF" in ALL_SERIES
    assert "DFF" not in SERIES          # config.py (strategy contract) untouched


def test_dff_is_research_context_only():
    assert dataset.FEATURE_SCHEMA_VERSION == "fs_v1"
    assert not any("dff" in f.lower() or "fed_funds" in f.lower() for f in dataset.FEATURES)
    assert not any("dff" in f.lower() or "fed_funds" in f.lower()
                   for f in market_data.RESEARCH_FEATURES)
    assert not any("dff" in f.lower() or "fed_funds" in f.lower()
                   for f in market_context.MARKET_FIELDS)
