"""Historical provider contract, validation/quarantine, provenance, SEC
provider (mocked EDGAR), dataset-quality report and readiness gate.
All deals here are SYNTHETIC in-memory fixtures."""
import json
import sqlite3
from pathlib import Path

import pytest

from src.ingest.historical import (HistoricalDealRecord, SourceRef,
                                   UnconfiguredProvider, ingest)
from src.ingest.providers.sec_edgar import EdgarClient, SECEdgarProvider, matches
from src.model.data_quality import quality_report, readiness
from src.model.dataset import build_training_set

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()


def mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def ref(ts, ident="https://example.test/doc", acc=None):
    return SourceRef("TEST SOURCE", ident, source_timestamp=ts, known_at=ts, accession_number=acc)


def rec(deal_id="H1", resolution="closed", **kw):
    base = dict(deal_id=deal_id, target="T Corp", acquirer="A Corp",
                announcement_timestamp="2024-03-01T08:00:00",
                announcement_source=ref("2024-03-01T08:05:00"),
                deal_type="strategic", consideration_type="cash",
                terms_source=ref("2024-03-01T08:05:00"), offer_price=50.0,
                sector="Tech", geography="US")
    if resolution:
        base.update(resolution_type=resolution, resolution_timestamp="2024-09-01T16:00:00",
                    resolution_source=ref("2024-09-01T16:10:00"))
    base.update(kw)
    return HistoricalDealRecord(**base)


class ListProvider:
    name = "test_list"

    def __init__(self, recs):
        self.recs = recs

    def records(self):
        return iter(self.recs)


# ------------------------------------------------------------ validation
def test_complete_record_is_valid():
    assert rec().validate() == []


@pytest.mark.parametrize("kw,needle", [
    (dict(target=""), "missing target"),
    (dict(announcement_source=SourceRef("S", "u")), "announcement known_at missing"),
    (dict(offer_price=None), "offer_price required"),
    (dict(consideration_type="stock"), "exchange_ratio required"),
    (dict(consideration_type="barter"), "unknown consideration_type"),
    (dict(resolution_source=None), "resolution source/known_at missing"),
    (dict(resolution_timestamp="2023-01-01"), "resolution precedes announcement"),
    (dict(unaffected_price=40.0), "unaffected_price needs its own date and source"),
])
def test_incomplete_records_are_quarantined_not_written(kw, needle):
    c = mem()
    out = ingest(ListProvider([rec(**kw)]), c)
    assert out["n_written"] == 0 and out["n_quarantined"] == 1
    assert any(needle in p for p in out["quarantined"][0]["problems"])
    assert c.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 0


def test_unconfigured_provider_never_fabricates():
    with pytest.raises(NotImplementedError):
        ingest(UnconfiguredProvider(), mem())


# ------------------------------------------------- writing + provenance
def test_written_record_is_bitemporal_and_traceable():
    c = mem()
    r = rec(unaffected_price=40.0, unaffected_price_date="2024-02-29",
            unaffected_price_source=ref("2024-02-29T23:59:59", "https://example.test/px"))
    out = ingest(ListProvider([r]), c)
    assert out["n_written"] == 1 and "unaffected_price" not in out["written"][0]["missing_optional"]
    ev = {e["event_type"]: dict(e) for e in c.execute("SELECT * FROM deal_events")}
    assert ev["announcement"]["known_at"] == "2024-03-01T08:05:00"
    assert ev["closing"]["known_at"] == "2024-09-01T16:10:00"
    prov = [dict(p) for p in c.execute("SELECT * FROM record_provenance")]
    assert {p["record_type"] for p in prov} == {"deal", "observation", "event"}
    assert all(p["source_name"] and p["source_identifier"] and p["known_at"] for p in prov)
    assert any(p["field"] == "unaffected_price" and p["source_identifier"].endswith("/px")
               for p in prov)
    # the label comes from a sourced, known event -> a model row exists
    ts = build_training_set("2025-01-01", c)
    assert ts["n"] == 1 and ts["rows"][0]["label"] == 0
    assert ts["rows"][0]["x"]["pct_spread"] is None          # no target print: missing, not 0


def test_reingest_is_idempotent():
    c = mem()
    ingest(ListProvider([rec()]), c)
    out = ingest(ListProvider([rec()]), c)
    w = out["written"][0]
    assert w["deal"] is False and w["events"] == 0 and w["duplicates"] >= 2


def test_pending_record_is_censored():
    c = mem()
    ingest(ListProvider([rec(resolution=None)]), c)
    ts = build_training_set("2025-01-01", c)
    assert ts["n"] == 0 and ts["n_censored"] == 1


# ------------------------------------------------------ SEC EDGAR (mocked)
SUB = {"filings": {"recent": {
    "accessionNumber": ["0000000001-24-000001", "0000000001-24-000002", "0000000001-24-000003"],
    "form": ["8-K", "8-K", "10-Q"],
    "filingDate": ["2024-03-01", "2024-09-03", "2024-05-01"],
    "acceptanceDateTime": ["2024-03-01T08:02:11.000Z", "2024-09-03T16:31:05.000Z",
                           "2024-05-01T12:00:00.000Z"],
    "items": ["1.01,9.01", "2.01,9.01", ""]}, "files": []}}


def manifest(tmp_path, **over):
    m = {"deal_id": "SEC1", "target": "T Corp", "acquirer": "A Corp", "target_cik": 1,
         "announcement_accession": "0000000001-24-000001",
         "terms_accession": "0000000001-24-000001",
         "deal_type": "strategic", "consideration_type": "cash", "offer_price": 25.0,
         "resolution_type": "closed", "resolution_accession": "0000000001-24-000002"}
    m.update(over)
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"schema_version": 1, "deals": [m]}))
    return p


def client():
    return EdgarClient(fetch_json=lambda url: SUB)


def test_sec_provider_uses_edgar_acceptance_time_and_accession(tmp_path):
    c = mem()
    prov = SECEdgarProvider(manifest(tmp_path), client=client())
    out = ingest(prov, c)
    assert out["n_written"] == 1 and prov.rejected == []
    ev = {e["event_type"]: dict(e) for e in c.execute("SELECT * FROM deal_events")}
    assert ev["announcement"]["known_at"] == "2024-03-01T08:02:11"
    assert ev["closing"]["known_at"] == "2024-09-03T16:31:05"
    p = c.execute("SELECT * FROM record_provenance WHERE record_type='event' "
                  "AND record_key LIKE 'event:closing%'").fetchone()
    assert p["accession_number"] == "0000000001-24-000002"
    assert p["company_identifier"] == "CIK0000000001"
    assert p["source_identifier"] == "https://www.sec.gov/Archives/edgar/data/1/000000000124000002/"


def test_sec_provider_rejects_mismatched_filing(tmp_path):
    # claims the 10-Q is a closing filing -> rejected, nothing written
    prov = SECEdgarProvider(manifest(tmp_path, resolution_accession="0000000001-24-000003"),
                            client=client())
    out = ingest(prov, mem())
    assert out["n_written"] == 0 and "not a valid 'closed' filing" in prov.rejected[0]["reason"]


def test_sec_provider_rejects_unknown_accession(tmp_path):
    prov = SECEdgarProvider(manifest(tmp_path, announcement_accession="9999999999-99-999999"),
                            client=client())
    assert ingest(prov, mem())["n_written"] == 0 and prov.rejected


def test_edgar_requires_user_agent(monkeypatch):
    from src.ingest.providers.sec_edgar import EdgarError
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(EdgarError):
        EdgarClient().filing(1, "x")


def test_event_filing_rules():
    assert matches("terminated", {"form": "8-K", "items": "1.02"})
    assert not matches("terminated", {"form": "8-K", "items": "2.01"})
    assert matches("closed", {"form": "25-NSE", "items": ""})


def test_shipped_manifest_has_exactly_twenty_four_reviewed_deals():
    """Seven reviewed batches: 12 closed (Y=0) + 12 terminated (Y=1). CA/Broadcom withdrawn; SkyWater/Theravance excluded."""
    p = Path(__file__).resolve().parents[1] / "data" / "sec_deal_manifest.json"
    deals = json.loads(p.read_text())["deals"]
    ids = [d["deal_id"] for d in deals]
    assert ids == [
        "DEAL-CRNX-VRTX-2026",
        "DEAL-ESI-SOLS-2026",
        "DEAL-EA-PIFSLAFF-2025",
        "DEAL-SSTK-GETY-2025",
        "DEAL-JNPR-HPE-2024",
        "DEAL-HCP-IBM-2024",
        "DEAL-CPRI-TPR-2023",
        "DEAL-WLTW-AON-2020",
        "DEAL-RHT-IBM-2018",
        "DEAL-LNKD-MSFT-2016",
        "DEAL-ODP-SPLS-2015",
        "DEAL-HUM-AET-2015",
        "DEAL-WFM-AMZN-2017",
        "DEAL-MON-BAYER-2016",
        "DEAL-CI-ANTM-2015",
        "DEAL-BHI-HAL-2014",
        "DEAL-ATVI-MSFT-2022",
        "DEAL-TWTR-XHOLDINGS-2022",
        "DEAL-TWC-CMCSA-2014",
        "DEAL-PACB-ILMN-2018",
        "DEAL-CERN-ORCL-2021",
        "DEAL-NUAN-MSFT-2021",
        "DEAL-FIVN-ZM-2021",
        "DEAL-MNTV-ZEN-2021",
    ]
    assert "DEAL-SKYT-IONQ-2026" not in ids and "DEAL-TBPH-ZYME-2026" not in ids
    assert "DEAL-CA-AVGO-2018" not in ids
    by_id = {d["deal_id"]: d for d in deals}
    crnx, esi = by_id["DEAL-CRNX-VRTX-2026"], by_id["DEAL-ESI-SOLS-2026"]
    assert crnx["resolution_type"] == "closed" and crnx["offer_price"] == 85.0
    assert crnx["announcement_accession"] == crnx["terms_accession"] == "0001140361-26-027642"
    assert crnx["resolution_accession"] == "0001140361-26-035195"
    assert crnx["resolution_timestamp"] == "2026-09-01"
    assert esi["resolution_type"] == "terminated" and esi["consideration_type"] == "mixed"
    assert esi["offer_price"] == 10.0 and esi["exchange_ratio"] == 0.5
    assert esi["announcement_accession"] == esi["terms_accession"] == "0001104659-26-080825"
    assert esi["resolution_accession"] == "0001104659-26-102559"
    assert esi["resolution_timestamp"] == "2026-08-27T16:00:00"
    ea, sstk = by_id["DEAL-EA-PIFSLAFF-2025"], by_id["DEAL-SSTK-GETY-2025"]
    assert ea["deal_type"] == "take_private" and ea["consideration_type"] == "cash"
    assert ea["offer_price"] == 210.0 and ea["resolution_type"] == "closed"
    assert ea["announcement_accession"] == ea["terms_accession"] == "0001140361-25-036415"
    assert ea["resolution_accession"] == "0001140361-26-031157"
    assert ea["resolution_timestamp"] == "2026-08-04"
    assert sstk["consideration_type"] == "mixed" and sstk["resolution_type"] == "terminated"
    assert sstk["offer_price"] == 9.5 and sstk["exchange_ratio"] == 9.17
    assert sstk["announcement_accession"] == sstk["terms_accession"] == "0001140361-25-000468"
    assert sstk["resolution_accession"] == "0001140361-26-028035"
    assert sstk["resolution_timestamp"] == "2026-07-07"
    jnpr, hcp = by_id["DEAL-JNPR-HPE-2024"], by_id["DEAL-HCP-IBM-2024"]
    assert jnpr["offer_price"] == 40.0 and jnpr["resolution_type"] == "closed"
    assert jnpr["announcement_accession"] == jnpr["terms_accession"] == "0001193125-24-005659"
    assert jnpr["resolution_accession"] == "0001193125-25-154400"
    assert jnpr["resolution_timestamp"] == "2025-07-02"
    assert hcp["offer_price"] == 35.0 and hcp["resolution_type"] == "closed"
    assert hcp["announcement_accession"] == hcp["terms_accession"] == "0001193125-24-114310"
    assert hcp["resolution_accession"] == "0001193125-25-037910"
    assert hcp["resolution_timestamp"] == "2025-02-27"
    cpri, wltw = by_id["DEAL-CPRI-TPR-2023"], by_id["DEAL-WLTW-AON-2020"]
    assert cpri["offer_price"] == 57.0 and cpri["resolution_type"] == "terminated"
    assert cpri["announcement_accession"] == cpri["terms_accession"] == "0001193125-23-208278"
    assert cpri["resolution_accession"] == "0001193125-24-258691"
    assert cpri["resolution_timestamp"] == "2024-11-13"
    assert wltw["consideration_type"] == "stock" and wltw["exchange_ratio"] == 1.08
    assert wltw.get("offer_price") is None
    assert wltw["announcement_accession"] == "0001193125-20-066129"
    assert wltw["terms_accession"] == "0001193125-20-067406"
    assert wltw["announcement_accession"] != wltw["terms_accession"]
    assert wltw["resolution_type"] == "terminated"
    assert wltw["resolution_accession"] == "0001193125-21-224367"
    assert wltw["resolution_timestamp"] == "2021-07-26"
    rht, lnkd = by_id["DEAL-RHT-IBM-2018"], by_id["DEAL-LNKD-MSFT-2016"]
    assert rht["offer_price"] == 190.0 and rht["resolution_type"] == "closed"
    assert rht["announcement_accession"] == rht["terms_accession"] == "0001193125-18-310577"
    assert rht["resolution_accession"] == "0000950142-19-001516"
    assert rht["resolution_timestamp"] == "2019-07-09"
    assert lnkd["offer_price"] == 196.0 and lnkd["resolution_type"] == "closed"
    assert lnkd["announcement_accession"] == lnkd["terms_accession"] == "0001104659-16-126712"
    assert lnkd["resolution_accession"] == "0001104659-16-161289"
    assert lnkd["announcement_timestamp"] == "2016-06-11"
    assert lnkd["resolution_timestamp"] == "2016-12-08"
    odp, hum = by_id["DEAL-ODP-SPLS-2015"], by_id["DEAL-HUM-AET-2015"]
    assert odp["consideration_type"] == "mixed" and odp["resolution_type"] == "terminated"
    assert odp["offer_price"] == 7.25 and odp["exchange_ratio"] == 0.2188
    assert odp["announcement_accession"] == odp["terms_accession"] == "0001193125-15-033873"
    assert odp["announcement_accession"] != "0001193125-15-033875"
    assert odp["resolution_accession"] == "0001193125-16-592186"
    assert odp["resolution_timestamp"] == "2016-05-16"
    assert hum["consideration_type"] == "mixed" and hum["resolution_type"] == "terminated"
    assert hum["offer_price"] == 125.0 and hum["exchange_ratio"] == 0.8375
    assert hum["announcement_accession"] == hum["terms_accession"] == "0001193125-15-246897"
    assert hum["resolution_accession"] == "0000049071-17-000016"
    assert hum["resolution_timestamp"] == "2017-02-14"
    wfm, mon = by_id["DEAL-WFM-AMZN-2017"], by_id["DEAL-MON-BAYER-2016"]
    assert wfm["offer_price"] == 42.0 and wfm["resolution_type"] == "closed"
    assert wfm["announcement_accession"] == wfm["terms_accession"] == "0001047469-17-004058"
    assert wfm["announcement_timestamp"] == "2017-06-15"
    assert wfm["resolution_accession"] == "0001144204-17-045261"
    assert wfm["resolution_timestamp"] == "2017-08-28"
    assert mon["offer_price"] == 128.0 and mon["resolution_type"] == "closed"
    assert mon["announcement_accession"] == mon["terms_accession"] == "0001193125-16-714915"
    assert mon["resolution_accession"] == "0001193125-18-188226"
    assert mon["resolution_timestamp"] == "2018-06-07"
    ci, bhi = by_id["DEAL-CI-ANTM-2015"], by_id["DEAL-BHI-HAL-2014"]
    assert ci["consideration_type"] == "mixed" and ci["resolution_type"] == "terminated"
    assert ci["offer_price"] == 103.4 and ci["exchange_ratio"] == 0.5152
    assert ci["announcement_accession"] == ci["terms_accession"] == "0000950159-15-000230"
    assert ci["resolution_accession"] == "0000950159-17-000134"
    assert ci["resolution_timestamp"] == "2017-05-12"
    assert bhi["consideration_type"] == "mixed" and bhi["resolution_type"] == "terminated"
    assert bhi["offer_price"] == 19.0 and bhi["exchange_ratio"] == 1.12
    assert bhi["announcement_accession"] == bhi["terms_accession"] == "0000950103-14-008110"
    assert bhi["resolution_accession"] == "0000950103-16-013026"
    assert bhi["resolution_timestamp"] == "2016-04-30"
    atvi, twtr = by_id["DEAL-ATVI-MSFT-2022"], by_id["DEAL-TWTR-XHOLDINGS-2022"]
    assert atvi["offer_price"] == 95.0 and atvi["resolution_type"] == "closed"
    assert atvi["announcement_accession"] == atvi["terms_accession"] == "0001104659-22-005154"
    assert atvi["announcement_timestamp"] == "2022-01-18"
    assert atvi["resolution_accession"] == "0001104659-23-108985"
    assert atvi["resolution_timestamp"] == "2023-10-13"
    assert twtr["deal_type"] == "take_private" and twtr["offer_price"] == 54.2
    assert twtr["announcement_accession"] == twtr["terms_accession"] == "0001193125-22-120461"
    assert twtr["resolution_type"] == "closed"
    assert twtr["resolution_accession"] == "0001193125-22-272772"
    assert twtr["resolution_timestamp"] == "2022-10-27"
    twc, pacb = by_id["DEAL-TWC-CMCSA-2014"], by_id["DEAL-PACB-ILMN-2018"]
    assert twc["consideration_type"] == "stock" and twc.get("offer_price") is None
    assert twc["exchange_ratio"] == 2.875 and twc["resolution_type"] == "terminated"
    assert twc["announcement_accession"] == twc["terms_accession"] == "0001193125-14-051452"
    assert twc["resolution_accession"] == "0000950142-15-000864"
    assert twc["resolution_timestamp"] == "2015-04-24"
    assert pacb["offer_price"] == 8.0 and pacb["resolution_type"] == "terminated"
    assert pacb["announcement_accession"] == pacb["terms_accession"] == "0001193125-18-318421"
    assert pacb["resolution_accession"] == "0001193125-20-000641"
    assert pacb["resolution_timestamp"] == "2020-01-02"
    cern, nuan = by_id["DEAL-CERN-ORCL-2021"], by_id["DEAL-NUAN-MSFT-2021"]
    assert cern["offer_price"] == 95.0 and cern["resolution_type"] == "closed"
    assert cern["announcement_accession"] == cern["terms_accession"] == "0001193125-21-363898"
    assert cern["announcement_timestamp"] == "2021-12-20"
    assert cern["resolution_accession"] == "0001193125-22-169841"
    assert cern["resolution_timestamp"] == "2022-06-08"
    assert nuan["offer_price"] == 56.0 and nuan["resolution_type"] == "closed"
    assert nuan["announcement_accession"] == nuan["terms_accession"] == "0001193125-21-113796"
    assert nuan["announcement_timestamp"] == "2021-04-11"
    assert nuan["resolution_accession"] == "0001193125-22-066065"
    assert nuan["resolution_timestamp"] == "2022-03-04"
    fivn, mntv = by_id["DEAL-FIVN-ZM-2021"], by_id["DEAL-MNTV-ZEN-2021"]
    assert fivn["consideration_type"] == "stock" and fivn.get("offer_price") is None
    assert fivn["exchange_ratio"] == 0.5533 and fivn["resolution_type"] == "terminated"
    assert fivn["announcement_accession"] == fivn["terms_accession"] == "0001193125-21-217962"
    assert fivn["announcement_timestamp"] == "2021-07-16"
    assert fivn["resolution_accession"] == "0001193125-21-289272"
    assert fivn["resolution_timestamp"] == "2021-09-30"
    assert mntv["consideration_type"] == "stock" and mntv.get("offer_price") is None
    assert mntv["exchange_ratio"] == 0.225 and mntv["resolution_type"] == "terminated"
    assert mntv["announcement_accession"] == mntv["terms_accession"] == "0001193125-21-313506"
    assert mntv["announcement_timestamp"] == "2021-10-28"
    assert mntv["resolution_accession"] == "0001193125-22-056288"
    assert mntv["resolution_timestamp"] == "2022-02-25"


# ------------------------------------------------- quality + readiness
@pytest.mark.parametrize("n,pos,status", [
    (0, 0, "NO_REAL_LABELS"),
    (10, 3, "INSUFFICIENT_SAMPLE"),
    (40, 1, "INSUFFICIENT_POSITIVE_CLASS"),
    (40, 39, "INSUFFICIENT_POSITIVE_CLASS"),
    (40, 6, "READY_FOR_EXPERIMENTAL_WALK_FORWARD"),
])
def test_readiness_states(n, pos, status):
    assert readiness(n, pos) == status


def test_quality_report_counts_and_does_not_fit():
    c = mem()
    ingest(ListProvider([rec("H1"), rec("H2", resolution="terminated"),
                         rec("H3", resolution=None)]), c)
    q = quality_report(c, "2025-01-01")
    assert (q["total_deals"], q["closed"], q["broken_terminated_withdrawn"],
            q["pending_deals"]) == (3, 1, 1, 1)
    assert q["class_prevalence_pi"] == 0.5
    assert q["break_logit_v1_eligible_rows"] == 2
    assert q["MODEL_DATA_STATUS"] == "INSUFFICIENT_SAMPLE"
    assert q["source_coverage"]["TEST SOURCE"] > 0
    assert c.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 0
