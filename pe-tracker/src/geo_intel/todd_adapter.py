"""Adapter: Todd's daily ``events-YYYY-MM-DD.jsonl`` feed -> geo_intel ledger.

Todd is another bot. Everything it relays — news, law-firm notes, X posts,
X trend summaries and even links to official pages — enters as UNTRUSTED,
UNRETRIEVED evidence (``ingested_via='todd_feed'``). It can open an event
cluster; it can never verify or corroborate one. Verification needs a
reviewer to retrieve the underlying (primary) source and stage it as its own
record.

    python -m src.geo_intel.todd_adapter FEED.jsonl --ledger STAGING.jsonl [--report OUT.json]

Rules
-----
* Missing optional fields are absent, never defaulted. ``null`` timestamps stay
  ``None`` (never coerced to the brief date, first-observed time or anything
  else). Unparseable / zone-less timestamps reject the item.
* ``primary_source_leads`` are copied to ``lead_urls`` — leads only.
* ``source_kind``/``claim_type`` are mapped below; the originals are kept in
  ``upstream_source_kind``/``upstream_claim_type``; the raw line is fingerprinted
  in ``provenance``.
* Free-text geography/sectors are preserved raw (``upstream_*``); only exact
  country names map to ISO codes; sectors are NOT auto-mapped to the controlled
  vocabulary (a reviewed step).
* ``market_data`` items are rejected: price/rate prints are series that belong
  in the FRED market_observations store, not discrete events.
* Each item is its own cluster (key = category + canonical URL + statement
  prefix). Cross-source clustering is a reviewed step, never automatic.
* Re-ingesting the same file is idempotent. A later item with the same cluster
  key and URL but different text (e.g. an untruncated X post) is appended as an
  ``update`` revision of the earlier record; the original is never mutated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Optional

from .schema import EvidenceRecord, SchemaError, parse_ts
from .store import EvidenceLedger, canonical_url
from .verification import classify

CATEGORY_MAP = {
    "sanctions": "sanctions",
    "russia_ukraine_energy": "russia_ukraine_energy_infrastructure",
    "iran_us_diplomacy": "iran_us_diplomacy",
    "hormuz_maritime": "strait_of_hormuz_maritime",
    "energy_supply": "energy_supply_interruption",
    "rates_financing": "rates_and_acquisition_financing",
    "procurement_regulatory": "government_procurement_regulatory",
    "sector_exposure": "sector_geopolitical_exposure",
}
# Todd claim_type -> geo_intel claim_type (None = rejected by policy)
CLAIM_MAP = {
    "reported_fact": "occurred",
    "official_document": "occurred",
    "attributed_claim": "attributed_statement",
    "unconfirmed_report": "rumor",
    "market_data": None,
}
# Todd source_kind -> geo_intel source_type. ALL untrusted by construction.
SOURCE_KIND_MAP = {
    "primary_official": "other",       # a relayed link to an official page is a LEAD until retrieved
    "news_outlet": "other",
    "law_firm_analysis": "other",
    "x_post": "social_post",
    "x_trend_summary": "ai_brief",     # auto-generated summary
}
COUNTRY_ISO = {
    "united states": "US", "usa": "US", "us": "US", "russia": "RU", "ukraine": "UA",
    "iran": "IR", "france": "FR", "germany": "DE", "united kingdom": "GB", "uk": "GB",
    "israel": "IL", "saudi arabia": "SA", "yemen": "YE", "china": "CN", "qatar": "QA",
    "united arab emirates": "AE", "oman": "OM", "iraq": "IQ", "global": "GLOBAL",
    "european union": "EU",
}
REQUIRED = ("category", "statement", "reporting_entity", "publisher", "source_url",
            "first_observed_at", "claim_type", "source_kind", "brief_date")
KNOWN_FIELDS = set(REQUIRED) | {"published_at", "event_time", "geography", "sectors",
                                "companies", "primary_source_leads", "notes"}
NOTE_FLAGS = (
    ("truncated", "statement_truncated"),
    ("mirrored", "statement_from_syndicated_copy"),
    ("standfirst", "statement_is_standfirst_or_snippet"),
    ("paywalled", "source_paywalled"),
    ("lower confidence", "lower_confidence_upstream"),
    ("blocked", "source_blocked_for_relay"),
)


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def map_item(raw: dict, provenance: str) -> tuple[Optional[EvidenceRecord], Optional[str], list]:
    """Return (record, rejection_reason, flags)."""
    flags = []
    miss = [f for f in REQUIRED if raw.get(f) in (None, "")]
    if miss:
        return None, "missing_required_field:" + ",".join(miss), flags
    flags += [f"unknown_field:{k}" for k in sorted(set(raw) - KNOWN_FIELDS)]
    notes = raw.get("notes") or ""
    flags += [flag for needle, flag in NOTE_FLAGS if needle in notes.lower()]
    if raw.get("published_at") is None:
        flags.append("published_at_missing")
    if raw.get("event_time") is None:
        flags.append("event_time_missing")
    cat = CATEGORY_MAP.get(raw["category"])
    if cat is None:
        return None, f"unknown_category:{raw['category']}", flags
    if raw["claim_type"] not in CLAIM_MAP:
        return None, f"unknown_claim_type:{raw['claim_type']}", flags
    claim = CLAIM_MAP[raw["claim_type"]]
    if claim is None:
        return None, "market_data_not_an_event (series belong in FRED store)", flags
    stype = SOURCE_KIND_MAP.get(raw["source_kind"])
    if stype is None:
        return None, f"unknown_source_kind:{raw['source_kind']}", flags
    pub, evt = raw.get("published_at"), raw.get("event_time")
    try:
        p_pub, p_obs = parse_ts(pub), parse_ts(raw["first_observed_at"])
        parse_ts(evt)
    except SchemaError as exc:
        return None, f"bad_timestamp: {exc}", flags
    if p_obs is None:
        return None, "missing_required_field:first_observed_at", flags
    if p_pub is not None and p_pub.precision == "second" and p_obs.latest_utc < p_pub.latest_utc:
        return None, "first_observed_before_published (impossible ordering)", flags
    geos, raw_geo = [], list(raw.get("geography") or [])
    for g in raw_geo:
        iso = COUNTRY_ISO.get(_norm(g))
        if iso and iso not in geos:
            geos.append(iso)
    if any(COUNTRY_ISO.get(_norm(g)) is None for g in raw_geo):
        flags.append("unmapped_geography_preserved_raw")
    stmt = raw["statement"]
    key = "todd:%s:%s:%s" % (cat, canonical_url(raw["source_url"]), _norm(stmt)[:60])
    rec = EvidenceRecord(
        event_key=key, category=cat, original_statement=stmt,
        reporting_entity=raw["reporting_entity"], source_url=raw["source_url"],
        publisher=raw["publisher"], source_type=stype, claim_type=claim,
        publication_timestamp=pub, event_valid_timestamp=evt,
        first_observed_timestamp=raw["first_observed_at"], known_at=None,
        retrieved_by_reviewer=False, geographies=tuple(geos), sectors=(),
        affected_company_ids=tuple(raw.get("companies") or ()),
        ingested_via="todd_feed", relayed_by=f"Todd news brief {raw['brief_date']}",
        upstream_source_kind=raw["source_kind"], upstream_claim_type=raw["claim_type"],
        upstream_geography=tuple(raw_geo), upstream_sectors=tuple(raw.get("sectors") or ()),
        lead_urls=tuple(raw.get("primary_source_leads") or ()),
        provenance=provenance,
        notes="; ".join(x for x in (notes, ("flags=" + ",".join(flags)) if flags else "") if x))
    return rec, None, flags


def _resolver(ledger: EvidenceLedger, rec: EvidenceRecord):
    if ledger.get(rec.evidence_id) is not None:
        return "duplicate", rec.evidence_id
    hit = ledger.dedup_match(rec)
    if hit is None:
        return "append", rec
    latest = ledger.latest_revision(hit)
    if _norm(latest.original_statement) == _norm(rec.original_statement):
        return "duplicate", latest.evidence_id
    d = json.loads(rec.to_json())
    d.update(revises_evidence_id=latest.evidence_id, revision_type="update")
    rev = EvidenceRecord.from_dict(d).validate(ledger.primary_registry)
    if ledger.get(rev.evidence_id) is not None:
        return "duplicate", rev.evidence_id
    return "revision", rev


def ingest_todd_file(path: Path, ledger: EvidenceLedger) -> dict:
    path = Path(path)
    rows, recs, idx = [], [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        prov = f"{path.name}#L{n} sha256={hashlib.sha256(line.encode()).hexdigest()}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            rows.append({"line": n, "outcome": "rejected", "reason": f"invalid_json: {exc}"})
            continue
        rec, why, flags = map_item(raw, prov)
        row = {"line": n, "category": raw.get("category"), "publisher": raw.get("publisher"),
               "source_kind": raw.get("source_kind"), "claim_type": raw.get("claim_type"),
               "source_url": raw.get("source_url"), "flags": flags,
               "published_at": raw.get("published_at"), "event_time": raw.get("event_time")}
        if rec is None:
            row.update(outcome="rejected", reason=why)
        else:
            idx.append(len(rows))
            recs.append(rec)
        rows.append(row)
    for i, (action, payload) in zip(idx, ledger.apply(recs, _resolver)):
        rows[i]["outcome"] = {"append": "accepted"}.get(action, action)
        if isinstance(payload, EvidenceRecord):
            rows[i]["evidence_id"], rows[i]["event_id"] = payload.evidence_id, payload.event_id
        else:
            rows[i]["reason" if action == "rejected" else "duplicate_of"] = payload
            dup = ledger.get(payload) if action == "duplicate" else None
            if dup is not None:
                rows[i]["evidence_id"], rows[i]["event_id"] = dup.evidence_id, dup.event_id
    clusters = ledger.clusters()
    for r in rows:
        if r.get("event_id"):
            r["status"] = classify(clusters[r["event_id"]],
                                   primary_registry=ledger.primary_registry).status
            r["needs_for_verification"] = verification_needs(r)
    return {"feed": str(path), "ledger": str(ledger.path) if ledger.path else None,
            "counts": dict(Counter(r["outcome"] for r in rows)),
            "missing_published_at": sum(1 for r in rows if r.get("published_at") is None),
            "missing_event_time": sum(1 for r in rows if r.get("event_time") is None),
            "status_counts": dict(Counter(r["status"] for r in rows if "status" in r)),
            "rows": rows}


def verification_needs(row: dict) -> str:
    sk, ct = row.get("source_kind"), row.get("claim_type")
    need = []
    if sk == "primary_official":
        need.append("reviewer retrieves the cited official page and stages it as a "
                    "primary_official record (publication time from the page)")
    elif sk in ("x_post", "x_trend_summary"):
        need.append("locate the original reporting / official statement behind the post; "
                    "X text cannot verify")
    else:
        need.append("retrieve the cited article (full text, not a mirror/snippet) and find "
                    "the primary source it relies on")
    if ct == "attributed_claim":
        need.append("the named entity's own statement (official channel) for VERIFIED_PRIMARY, "
                    "or 2 independent retrieved outlets for CORROBORATED_SECONDARY")
    if ct == "unconfirmed_report":
        need.append("on-record confirmation; until then it stays a rumor")
    if row.get("event_time") is None:
        need.append("a sourced event time (none stated)")
    if row.get("published_at") is None:
        need.append("a sourced publication timestamp with zone")
    return "; ".join(need)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("feed")
    ap.add_argument("--ledger", required=True,
                    help="staging ledger path (do NOT point at data/geopolitical/ for pilots)")
    ap.add_argument("--report")
    a = ap.parse_args(argv)
    rep = ingest_todd_file(Path(a.feed), EvidenceLedger(Path(a.ledger)))
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if a.report:
        Path(a.report).write_text(out + "\n")
    print(json.dumps({k: rep[k] for k in ("counts", "missing_published_at",
                                          "missing_event_time", "status_counts")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
