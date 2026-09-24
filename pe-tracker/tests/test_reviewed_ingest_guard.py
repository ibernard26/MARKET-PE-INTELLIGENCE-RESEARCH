"""The only legal historical-deal path into the canonical/model store is

    HistoricalDealRecord.validate() -> sec_deal_manifest.json -> SECEdgarProvider
    -> record_provenance

Research/staging material (the Q3 register, public_mna_intelligence staging,
canonical_* research outputs, seed_deals illustrative quotes, automation
outputs) must never write into deals / deal_events / deal_market_observations.
"""
import re
import sqlite3
from pathlib import Path

import pytest

import src.config as config
from src.ingest.historical import (PROHIBITED_SOURCE_MARKERS, ProhibitedSourceError,
                                   SourceRef, ingest)
from src.ingest.providers.sec_edgar import SECEdgarProvider
from tests.test_historical_ingest import SCHEMA, ListProvider, client, manifest, mem, rec

ROOT = Path(__file__).resolve().parents[1]


def _disk_store(tmp_path, monkeypatch):
    db = tmp_path / "store.db"
    monkeypatch.setattr(config, "DB_PATH", db)
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def test_on_disk_store_rejects_any_non_sec_provider(tmp_path, monkeypatch):
    c = _disk_store(tmp_path, monkeypatch)
    with pytest.raises(ProhibitedSourceError, match="only legal path"):
        ingest(ListProvider([rec()]), c)
    assert c.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 0


def test_on_disk_store_accepts_reviewed_sec_provider(tmp_path, monkeypatch):
    c = _disk_store(tmp_path, monkeypatch)
    out = ingest(SECEdgarProvider(manifest(tmp_path), client=client()), c)
    assert out["n_written"] == 1


@pytest.mark.parametrize("ident", [
    "pe-tracker/data/research/deal_register_2026Q3.csv#2026Q3-001",
    "data/public_mna_intelligence/2026-07-01_2026-09-24/staging_chatgpt/public_mna_events.csv",
    "data/research/canonical_deal_events_2026Q3.csv",
    "seed_deals.py (illustrative arb quotes)",
    "automation/daily_tracker_loop.md",
    "outputs/Deal_Research_2026Q3.md",
])
def test_research_or_staging_sources_are_quarantined(ident):
    bad = SourceRef("research", ident, source_timestamp="2024-03-01T08:05:00",
                    known_at="2024-03-01T08:05:00")
    c = mem()
    out = ingest(ListProvider([rec(terms_source=bad)]), c)
    assert out["n_written"] == 0 and "prohibited source" in out["quarantined"][0]["problems"][0]
    for t in ("deals", "deal_events", "deal_market_observations"):
        assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0


WRITERS = re.compile(r"record_event|record_observation|write_record|\bingest\(|"
                     r"INSERT\s+(OR\s+\w+\s+)?INTO\s+(deals|deal_events|deal_market_observations|"
                     r"model_registry|model_predictions)|UPDATE\s+deals|"
                     r"from\s+(\.\.|src\.)db\s+import|from\s+\.\.\s*import\s+db")


def test_no_module_reading_research_data_can_write_the_store():
    files = [p for p in list(ROOT.glob("src/**/*.py")) + list(ROOT.glob("scripts/*.py"))
             + list(ROOT.glob("*.py")) if p.name != "historical.py"]
    offenders = []
    for p in files:
        text = p.read_text()
        if any(m in text for m in ("deal_register_2026Q3", "public_mna_intelligence",
                                   "canonical_deal")) and WRITERS.search(text):
            offenders.append(str(p.relative_to(ROOT)))
    assert offenders == [], f"research/staging readers must not write the store: {offenders}"


def test_seed_illustrative_quotes_are_kept_but_never_written():
    text = (ROOT / "seed_deals.py").read_text()
    assert not re.search(r"UPDATE\s+deals", text)
    for v in ("690.0, 662.0, 505.0", "42.00, 39.60, 31.50"):     # values unchanged
        assert v in text


def test_markers_cover_every_prohibited_source():
    for m in ("deal_register_2026Q3", "public_mna_intelligence", "seed_deals",
              "automation/", "outputs/"):
        assert m in PROHIBITED_SOURCE_MARKERS
