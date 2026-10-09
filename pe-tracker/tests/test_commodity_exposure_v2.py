"""Commodity-exposure v2 (research only): schema, fetch refusal, chronology, rules,
entity resolution, blinded packet, and gate math incl. the shared-unknown rule."""
import csv
import json
import os
import re
from pathlib import Path

import pytest

from scripts.commodity_v2 import edgar, entities, packets, rules, score
from scripts.commodity_v2.sample import V2_SAMPLE_PREREG, v1_dev_sample, v2_validation_sample

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "data" / "research"
LABELS = RESEARCH / "commodity_exposure_v2_labels.csv"
RUN = RESEARCH / "commodity_exposure_v2_run.json"
IDENT = RESEARCH / "commodity_exposure_v2_identities.csv"
PACKET = RESEARCH / "commodity_exposure_v2_review_packet"
PREREG = ROOT / "docs" / "PREREG_COMMODITY_EXPOSURE_COVERAGE_v2.md"


class _Resp:
    def __init__(self, status=200, content=b"{}"):
        self.status_code, self.content = status, content


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers))
        return _Resp(200, b"ok")


# ------------------------------------------------------------- no fetch without contact
def test_refuses_without_contact_email(monkeypatch):
    monkeypatch.delenv("SEC_CONTACT_EMAIL", raising=False)
    with pytest.raises(edgar.FetchRefused):
        edgar.Edgar(session=_Session())
    with pytest.raises(edgar.FetchRefused):
        edgar.user_agent()


@pytest.mark.parametrize("bad", ["", "   ", "not-an-email", "a@b"])
def test_refuses_invalid_contact_email(monkeypatch, bad):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", bad)
    with pytest.raises(edgar.FetchRefused):
        edgar.user_agent()


def test_offline_never_touches_network(monkeypatch, tmp_path):
    monkeypatch.delenv("SEC_CONTACT_EMAIL", raising=False)
    s = _Session()
    ed = edgar.Edgar(offline=True, cache_dirs=[tmp_path], session=s)
    with pytest.raises(edgar.FetchRefused):
        ed.get("https://www.sec.gov/x", "x.txt")
    assert s.calls == [] and ed.requests_made == 0


def test_user_agent_from_env_only(monkeypatch, tmp_path):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "contact@example.org")
    s = _Session()
    ed = edgar.Edgar(cache_dirs=[tmp_path], session=s)
    ed.get("https://www.sec.gov/x", "x.txt")
    ua = s.calls[0][1]["User-Agent"]
    assert ua == f"{edgar.UA_PREFIX} contact@example.org"
    assert edgar.MIN_INTERVAL_S >= 0.1                       # <= 10 req/s
    # no hard-coded contact address anywhere in the v2 package
    pkg = Path(edgar.__file__).parent
    for f in pkg.glob("*.py"):
        assert not re.search(r"[\w.+-]+@(?!example\.)[\w-]+\.[a-z]{2,}", f.read_text()), f.name


# ------------------------------------------------------------- chronology
def _f(form, fd, acc="", accn="0000000000-00-000001"):
    return {"form": form, "filing_date": fd, "acceptance": acc, "accession": accn,
            "primary_document": "d.htm"}


def test_chronology_strictly_before_announcement():
    fs = [_f("10-K", "2015-03-01", "2015-03-01T21:00:00.000Z", "a1"),
          _f("10-K", "2015-06-01", "2015-06-01T14:00:00.000Z", "a2"),     # announce day: excluded
          _f("10-Q", "2015-05-01", "2015-05-01T14:00:00.000Z", "q1"),
          _f("10-Q", "2015-06-01", "2015-06-01T12:00:00.000Z", "q2")]     # announce day: excluded
    sel = edgar.select_filings(fs, "2015-06-01")
    assert [x["accession"] for x in sel] == ["a1", "q1"]


def test_acceptance_timestamp_gate_and_et_conversion():
    # accepted 2015-06-01 01:30 UTC = 2015-05-31 21:30 ET -> available before 2015-06-01
    assert edgar.acceptance_et("2015-06-01T01:30:00.000Z").startswith("2015-05-31T21:30")
    assert edgar.available_before(_f("10-K", "2015-05-31", "2015-06-01T01:30:00.000Z"), "2015-06-01")
    # acceptance on the announcement date (ET) is not available before it
    assert not edgar.available_before(_f("10-K", "2015-05-31", "2015-06-01T15:00:00.000Z"), "2015-06-01")
    assert edgar.select_filings([_f("10-K", "2013-01-01")], "2015-06-01") == []   # outside 550d


# ------------------------------------------------------------- rules (prereg §1)
@pytest.mark.parametrize("s", [
    "Failure to integrate our systems could result in higher than expected costs and diversion of "
    "management's time and energy, which could adversely affect our results of operations.",
    "Internet access is provided by companies with significant market power that could increase "
    "the cost of our customers' use of our platform.",
    "A decline in oil and natural gas prices could adversely affect our financial position.",
    "We expect ratings pressure given commodity price levels, but we believe our energy portfolio "
    "is well-positioned.",
    "If our credit rating were downgraded, it could increase the cost of corporate debt and restrict "
    "our access to the commercial paper markets.",
    "We continue to invest in energy efficiency, which increases our operating efficiency and "
    "lowers our energy costs over time.",
])
def test_consumer_excludes_v1_false_positive_patterns(s):
    assert "consumer" not in rules.classify(s)


@pytest.mark.parametrize("s", [
    "Climate regulation could result in an increase in the cost of electricity, which is a "
    "significant component of our operational costs.",
    "Increased fuel prices could also have an effect on our costs of producing and procuring "
    "products that we sell.",
    "The price of raw materials, such as steel, copper and aluminum, is one of the most "
    "significant cost impacts on our business.",
])
def test_consumer_positive(s):
    assert rules.classify(s).get("consumer") == "yes"


def test_factor_list_excluded():
    s = ("Factors include our ability to retain customers; changes in fuel prices; the cost of "
         "raw materials; and competition.")
    assert rules.classify(s) == {}


def test_producer_rules():
    assert rules.classify("We raise turkeys and contract with turkey growers to meet our raw "
                          "material needs.").get("producer") == "yes"
    assert rules.classify("We produce, distribute and market chicken, beef and pork.")["producer"] == "yes"
    assert "producer" not in rules.classify(
        "We service the market through the transportation of crude oil and produced water.")
    assert "producer" not in rules.classify(
        "Any increase in steel prices may have a negative impact on our product costs.")


def test_hedge_rules():
    assert rules.classify("We use derivative financial instruments primarily to manage our "
                          "exposure to interest rates and, to a lesser extent, adverse "
                          "fluctuations in commodity prices.").get("hedged") == "yes"
    assert "hedged" not in rules.classify("We use interest rate swaps to manage our exposure to "
                                          "variable-rate debt.")
    assert "hedged" not in rules.classify("There is currently no well-established global market "
                                          "for hedging against increases in the price of steel, "
                                          "which affects our costs.")
    assert "hedged" not in rules.classify("We may in the future enter into commodity futures "
                                          "contracts.")
    assert rules.classify("The Company does not use financial instruments as a hedge against "
                          "changes in commodity prices.").get("hedged") == "no_disclosed"


def test_producer_party_guard_drops_sell_side_consumer():
    meta = {"accession": "a", "form": "10-K", "filing_date": "2014-01-01"}
    text = ("We have proved reserves of oil and natural gas in Texas. We use commodity derivative "
            "contracts to mitigate the risk against the volatility of oil and natural gas prices "
            "and our costs.")
    row, _ = rules.label_text_docs([(meta, text)])
    assert row["producer"] == "yes" and row["consumer"] == "unknown"


def test_no_silent_zero_values():
    row, ev = rules.label_text_docs([({"accession": "a"}, "We sell software to banks.")])
    assert row == {"producer": "unknown", "consumer": "unknown", "hedged": "unknown"} and ev == {}


# ------------------------------------------------------------- entity resolution (prereg §2)
MERGER = ("This Agreement and Plan of Merger is entered into by and among Microsoft Corporation, "
          "a Washington corporation (“Parent”), Liberty Merger Sub Inc., a Delaware corporation "
          "(“Merger Sub”), and LinkedIn Corporation, a Delaware corporation (the “Company”).")
PE_MERGER = ("Agreement and Plan of Merger among Ascend Holdings LLC, a Delaware limited liability "
             "company (“Parent”), Ascend Merger Sub, Inc. and the Company. Parent is controlled by "
             "investment funds managed by Apollo Global Management, which delivered an equity "
             "commitment letter.")
SUB_MERGER = ("Merger agreement with Tyson Acquisition Corp., a Maryland corporation (“Parent”), "
              "a wholly owned subsidiary of Tyson Foods, Inc., and the Company.")


def test_extract_parent_and_ultimate():
    ex = entities.extract_acquirer(MERGER)
    assert ex["parent"] == "Microsoft Corporation" and not ex["pe_signal"]
    ex = entities.extract_acquirer(SUB_MERGER)
    assert entities.norm_name(ex["ultimate"]) == "tyson foods"
    assert entities.extract_acquirer(PE_MERGER)["pe_signal"]
    assert entities.norm_name("ORACLE CORP /DE/") == entities.norm_name("Oracle Corporation")


class _FakeEd:
    def __init__(self, full_text, subs):
        self.full_text, self.subs = full_text, subs

    def full_submission(self, cik, acc):
        return ("<SEC-HEADER>\nCONFORMED SUBMISSION TYPE:\t8-K\nFILED AS OF DATE:\t20160613\n"
                "<ACCEPTANCE-DATETIME>20160613071500\n</SEC-HEADER>\n" + self.full_text)

    def submissions(self, cik):
        return self.subs[cik]


def _sub(cik, name):
    return {"cik": cik, "name": name, "sic": "7372", "sic_description": "Services",
            "filings": [_f("10-K", "2015-07-31", "2015-07-31T20:00:00.000Z", f"k{cik}")]}


def _deal(acq, dtype="strategic"):
    return {"deal_id": "DEAL-X", "announcement_timestamp": "2016-06-13", "acquirer": acq,
            "target_cik": 1, "announcement_accession": "0000000001-16-000001", "deal_type": dtype}


def test_resolve_from_merger_filing_not_manifest_name():
    lookup = {"microsoft": {789019}, "some other buyer": {42}}
    ed = _FakeEd(MERGER, {789019: _sub(789019, "MICROSOFT CORP"), 42: _sub(42, "OTHER")})
    rec = entities.resolve_acquirer(ed, _deal("Some Other Buyer"), lookup, [])
    assert rec["status"] == "resolved" and rec["cik"] == 789019
    assert rec["manifest_name_consistent"] is False          # manifest name is cross-check only
    assert rec["source_acceptance_et"] == "2016-06-13T07:15:00"


def test_pe_buyer_recorded_unknown_never_substituted():
    lookup = {"apollo global management": {1411494}}
    ed = _FakeEd(PE_MERGER, {1411494: _sub(1411494, "APOLLO GLOBAL MANAGEMENT")})
    rec = entities.resolve_acquirer(ed, _deal("Apollo Global Management", "take_private"), lookup, [])
    assert rec["status"] == "unknown" and rec["unknown_reason"] == "acquirer_pe_buyer_unresolved"
    assert rec["cik"] == ""


def test_unidentified_acquirer():
    ed = _FakeEd("Press release: the companies announced a combination.", {})
    rec = entities.resolve_acquirer(ed, _deal("X"), {}, [])
    assert rec["unknown_reason"] == "acquirer_not_identified_in_merger_filing"


# ------------------------------------------------------------- sample (prereg §5)
def test_v2_sample_reproducible_fresh_and_in_prereg():
    ids = [d["deal_id"] for d in json.loads((ROOT / "data/sec_deal_manifest.json").read_text())["deals"]]
    s = v2_validation_sample(ids)
    assert s == V2_SAMPLE_PREREG and len(s) == 20
    assert not set(s) & set(v1_dev_sample(ids))
    text = PREREG.read_text()
    assert all(d in text for d in s)


# ------------------------------------------------------------- gate math (prereg §7)
def _grid(fill):
    return {(d, p): {f: fill(d, p, f) for f in rules.FLAGS}
            for d in V2_SAMPLE_PREREG for p in ("target", "acquirer")}


def test_shared_unknowns_cannot_pass():
    a = _grid(lambda d, p, f: "unknown")
    rep = score.score(a, a, V2_SAMPLE_PREREG)
    assert rep["G1_exact_deals"] == 20 and rep["G1_pass"]
    assert rep["G2_status"] == "not_evaluable" and not rep["agreement_gates_pass"]
    assert rep["per_flag"]["consumer"]["g3_status"] == "insufficient_substantive_labels"


def _rich(d, p, f):
    i = V2_SAMPLE_PREREG.index(d)
    if f == "consumer":
        return "yes" if i % 2 == 0 else "unknown"
    if f == "producer":
        return "yes" if i % 4 == 0 and p == "target" else "unknown"
    return "yes" if i % 3 == 0 else "unknown"


def test_full_substantive_agreement_passes():
    a = _grid(_rich)
    rep = score.score(a, a, V2_SAMPLE_PREREG)
    assert rep["G2_substantive_cells"] >= score.G2_MIN_SUBSTANTIVE
    assert rep["G1_pass"] and rep["G2_status"] == "pass" and rep["G3_pass"]
    assert rep["agreement_gates_pass"]


def test_g1_needs_18_of_20_and_g2_threshold():
    a = _grid(_rich)
    b = {k: dict(v) for k, v in a.items()}
    flip = [d for d in V2_SAMPLE_PREREG if V2_SAMPLE_PREREG.index(d) % 2 == 0][:3]
    for d in flip:                                    # 3 deals disagree on consumer
        b[(d, "target")]["consumer"] = "unknown"
    rep = score.score(a, b, V2_SAMPLE_PREREG)
    assert rep["G1_exact_deals"] == 17 and not rep["G1_pass"] and not rep["agreement_gates_pass"]
    n = rep["G2_substantive_cells"]
    assert rep["G2_agreement_substantive"] == pytest.approx((n - 3) / n)


def test_kappa_and_invalid_values():
    assert score.kappa(["yes", "unknown"] * 5, ["yes", "unknown"] * 5) == 1.0
    assert score.kappa(["unknown"] * 4, ["unknown"] * 4) is None
    a = _grid(_rich)
    b = {k: dict(v) for k, v in a.items()}
    b[(V2_SAMPLE_PREREG[0], "target")]["producer"] = "no"          # 'no' is never valid
    with pytest.raises(ValueError):
        score.score(a, b, V2_SAMPLE_PREREG)


# ------------------------------------------------------------- blinded packet format
def test_packet_contains_no_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(packets, "party_block",
                        lambda ed, did, p: ([f"\n## {p['party']}"], {"party": p["party"]}))
    plan = {d: {"announce_date": "2015-01-01",
                "parties": [{"party": "target"}, {"party": "acquirer"}]} for d in V2_SAMPLE_PREREG}
    packets.write_packet(None, plan, V2_SAMPLE_PREREG, tmp_path)
    idx = json.loads((tmp_path / "index.json").read_text())
    assert idx["contains_first_pass_labels"] is False and "AI-assisted" in idx["reviewer"]
    rows = list(csv.DictReader((tmp_path / "response_template.csv").open()))
    assert len(rows) == 40 and all(not r["producer"] and not r["consumer"] and not r["hedged"]
                                   for r in rows)


def test_section_spans_skip_table_of_contents():
    text = ("Item 1. Business 3 Item 1A. Risk Factors 9 Item 7. Management's Discussion 30 "
            "Item 1. Business " + "x" * 500 + " Item 1A. Risk Factors " + "y" * 800 + " Item 2. Properties")
    sp = packets.section_spans(text)
    assert sp["1"][1] - sp["1"][0] > 400 and sp["1A"][1] - sp["1A"][0] > 700


# ------------------------------------------------------------- committed artifacts (if present)
def _rows():
    if not LABELS.exists():
        pytest.skip("v2 labels not generated yet")
    return list(csv.DictReader(LABELS.open()))


def test_labels_schema_and_coverage():
    rows = _rows()
    assert len(rows) == 258
    assert len({(r["deal_id"], r["party"]) for r in rows}) == 258
    reasons = {"no_qualifying_disclosure_in_reviewed_filings",
               "no_preannouncement_annual_report_in_window",
               "acquirer_not_identified_in_merger_filing", "acquirer_pe_buyer_unresolved",
               "acquirer_no_unique_sec_registrant", "fetch_error"}
    for r in rows:
        for f in rules.FLAGS:
            assert r[f] in rules.FLAG_VALUES[f]
        assert r["exposure_status"] in {"labeled", "unknown"}       # no not_yet_reviewed
        if r["exposure_status"] == "unknown":
            assert r["unknown_reason"] in reasons
        else:
            assert "yes" in (r["producer"], r["consumer"]) and not r["unknown_reason"]


def test_labels_chronology_and_provenance():
    for r in _rows():
        for f in rules.FLAGS:
            if r[f] == "unknown":
                assert not r[f"{f}_accession"]
                continue
            assert r[f"{f}_filing_date"] < r["announce_date"]
            assert r[f"{f}_acceptance_et"][:10] < r["announce_date"]
            assert r[f"{f}_quote"] and r[f"{f}_accession"] in r["filings_reviewed"]


def test_run_summary_research_only_and_no_contact_leak():
    if not RUN.exists():
        pytest.skip("v2 run summary not generated yet")
    run = json.loads(RUN.read_text())
    assert run["research_only"] and not run["model_fit_executed"] and not run["backtest_executed"]
    assert not run["canonical_store_written"] and not run["feature_integration"]
    assert run["validated"] is False and run["not_yet_reviewed"] == 0
    email = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    paths = [RUN, LABELS, IDENT] + (sorted(PACKET.glob("*")) if PACKET.exists() else [])
    for p in paths:
        if p.exists() and p.is_file():
            t = p.read_text(errors="ignore")
            assert "User-Agent" not in t
            if email:
                assert email not in t, p.name


def test_committed_packet_is_blinded():
    if not PACKET.exists():
        pytest.skip("packet not generated yet")
    idx = json.loads((PACKET / "index.json").read_text())
    assert set(idx["deals"]) == set(V2_SAMPLE_PREREG) and idx["contains_first_pass_labels"] is False
    for p in PACKET.glob("*.md"):
        t = p.read_text()
        assert "exposure_status" not in t and not re.search(r"\b(producer|consumer|hedged)\s*[:=]\s*"
                                                            r"(yes|unknown|no_disclosed)\b", t)


# ------------------------------------------------------------- extraction mechanics (live-run fixes)
def test_extract_spaced_quotes_and_short_defined_names():
    t = ("On October 26, 2020, Xilinx, Inc., a Delaware corporation (“ Xilinx ”), entered into an "
         "Agreement and Plan of Merger (the “ Merger Agreement ”), by and among Advanced Micro "
         "Devices, Inc., a Delaware corporation (“ AMD ”), Thrones Merger Sub, Inc., a Delaware "
         "corporation and wholly owned subsidiary of AMD (“ Merger Sub ”), and Xilinx.")
    ex = entities.extract_acquirer(t, "Xilinx, Inc.")
    assert entities.norm_name(ex["parent"]) == "advanced micro devices"
    t2 = ("the Company entered into a Merger Agreement with MRGB Hold Co. (“ Parent ”) and MRVK Hold "
          "Co. Parent and Merger Sub are currently wholly-owned subsidiaries of Mill Road Capital II, "
          "L.P. (“ Mill Road ”).")
    ex2 = entities.extract_acquirer(t2, "R. G. Barry Corporation")
    assert entities.norm_name(ex2["parent"]) == "mrgb hold" and ex2["pe_signal"]


def test_defined_term_never_used_as_entity():
    assert entities.name_variants("Parent") == []
    assert entities.name_variants("Splunk, Cisco Systems, Inc")[-1] == "Cisco Systems, Inc"
    assert entities.name_variants("Company, Microsoft Corporation")[-1] == "Microsoft Corporation"


def test_header_filer_of_bidder_filed_425_resolves():
    class Ed(_FakeEd):
        def full_submission(self, cik, acc):
            return ("<SEC-HEADER>\nCONFORMED SUBMISSION TYPE:\t425\nFILED AS OF DATE:\t20201201\n"
                    "<ACCEPTANCE-DATETIME>20201201161000\nSUBJECT COMPANY:\n\tCOMPANY DATA:\n"
                    "\t\tCOMPANY CONFORMED NAME:\t\t\tSlack Technologies, Inc.\n"
                    "\t\tCENTRAL INDEX KEY:\t\t\t0000000001\nFILED BY:\n\tCOMPANY DATA:\n"
                    "\t\tCOMPANY CONFORMED NAME:\t\t\tsalesforce.com, inc.\n"
                    "\t\tCENTRAL INDEX KEY:\t\t\t0001108524\n</SEC-HEADER>\n"
                    "salesforce.com, inc. (the “Company”) entered into a merger agreement.")
    sub = _sub(1108524, "SALESFORCE.COM, INC.")
    sub["filings"] = [_f("10-K", "2020-03-05", "2020-03-05T21:00:00.000Z", "k1")]
    ed = Ed("", {1108524: sub})
    d = {**_deal("Salesforce"), "announcement_timestamp": "2020-12-01"}
    rec = entities.resolve_acquirer(ed, d, {}, [])
    assert rec["status"] == "resolved" and rec["cik"] == 1108524
    assert "sec_header_filer" in rec["extraction_method"]


def test_target_never_its_own_acquirer_and_small_caps():
    t = ("This AGREEMENT AND PLAN OF MERGER is by and among T APESTRY , I NC . , a Maryland "
         "corporation (“Parent”), S UNRISE M ERGER S UB , I NC . , a British Virgin Islands company "
         "(“Merger Sub”), and Capri Holdings Limited (the “Company”).")
    assert entities.norm_name(entities.extract_acquirer(t, "Capri Holdings Limited")["parent"]) == "tapestry"
    lookup = {"microsoft": {1}}                       # resolves to the target's own CIK
    ed = _FakeEd(MERGER, {1: _sub(1, "MICROSOFT CORP")})
    rec = entities.resolve_acquirer(ed, _deal("Microsoft"), lookup, [])
    assert rec["status"] == "unknown" and rec["cik"] == ""


def test_pe_signal_requires_sponsor_language_about_buyer():
    assert not entities.R_PE.search("units owned by the Minority Limited Partners immediately prior")
    assert not entities.R_PE.search("Aegis entered into Voting Agreements with affiliates of Union "
                                    "Capital Corporation")
    assert entities.R_PE.search("Parent and Sub are affiliates of Webster Capital")
