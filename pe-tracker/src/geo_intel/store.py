"""Append-only evidence ledger (JSONL) with dedup and revision chains.

The ledger is a research staging file, NOT the canonical SQLite store. It has
no update or delete operation: a correction, update or retraction is a new
record that points at the record it revises (``revises_evidence_id``).

Dedup rules
-----------
* the same validated record twice                   -> DuplicateEvidenceError
* the same (event, canonical URL, stance, revision)  -> DuplicateEvidenceError
  (re-ingesting one source with reworded text is still one source)
* the same (canonical URL, statement) under two different event clusters
                                                     -> ClusterConflictError
* a revision must target an existing record in the same cluster from the
  same publisher (a different publisher disagreeing is a *contradiction*,
  not a correction)                                  -> RevisionError
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .schema import VERIFICATION_STATUSES, EvidenceRecord, SchemaError


class DuplicateEvidenceError(SchemaError):
    pass


class ClusterConflictError(SchemaError):
    pass


class RevisionError(SchemaError):
    pass


class LedgerIntegrityError(RuntimeError):
    pass


def canonical_url(url: str) -> str:
    p = urlparse(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not k.lower().startswith("utm_")]
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), (p.hostname or "").lower(), path, "",
                       urlencode(sorted(q)), ""))


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EvidenceLedger:
    def __init__(self, path: Optional[Path] = None, clock: Callable[[], str] = _utc_now,
                 primary_registry: Optional[dict] = None):
        self.path = Path(path) if path else None
        self.clock = clock
        self.primary_registry = primary_registry
        self._records: list[EvidenceRecord] = []
        self._ids: dict[str, EvidenceRecord] = {}
        self._dedup: dict[tuple, str] = {}
        self._stmt: dict[tuple, str] = {}
        if self.path and self.path.exists():
            self._load()

    # ------------------------------------------------------------ io
    def _load(self) -> None:
        for n, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            rec = EvidenceRecord.from_dict(raw)
            chk = rec.validate(self.primary_registry)
            if chk.evidence_id != raw.get("evidence_id") or chk.event_id != raw.get("event_id"):
                raise LedgerIntegrityError(
                    f"{self.path}:{n}: stored ids do not match content (edited in place?)")
            self._index(chk, check=True)

    # ------------------------------------------------------------ write
    def append(self, record: EvidenceRecord) -> EvidenceRecord:
        if not record.first_observed_timestamp:
            # The moment THIS system first saw the source is a real, observed
            # time — never back-dated.
            d = json.loads(record.to_json())
            d["first_observed_timestamp"] = self.clock()
            record = EvidenceRecord.from_dict(d)
        rec = record.validate(self.primary_registry)
        self._index(rec, check=True)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(rec.to_json() + "\n")
        return rec

    def extend(self, records: Iterable[EvidenceRecord]) -> list:
        return [self.append(r) for r in records]

    def _index(self, rec: EvidenceRecord, check: bool) -> None:
        if rec.evidence_id in self._ids:
            raise DuplicateEvidenceError(f"duplicate evidence {rec.evidence_id}")
        curl = canonical_url(rec.source_url)
        dkey = (rec.event_id, curl, rec.stance, rec.revises_evidence_id)
        if dkey in self._dedup:
            raise DuplicateEvidenceError(
                f"source {curl} already staged for {rec.event_id} "
                f"(as {self._dedup[dkey]}); re-ingestion is a duplicate")
        skey = (curl, " ".join(rec.original_statement.split()).lower())
        if skey in self._stmt and self._stmt[skey] != rec.event_id:
            raise ClusterConflictError(
                f"the same statement from {curl} is already staged under "
                f"{self._stmt[skey]}; one source statement cannot describe two events")
        if rec.revises_evidence_id:
            orig = self._ids.get(rec.revises_evidence_id)
            if orig is None:
                raise RevisionError(f"revises unknown evidence {rec.revises_evidence_id}")
            if orig.event_id != rec.event_id:
                raise RevisionError("a revision must stay in the revised record's event cluster")
            if orig.publisher.strip().lower() != rec.publisher.strip().lower():
                raise RevisionError("only the original publisher can correct/retract its "
                                    "record; stage other publishers as stance='contradicts'")
        self._ids[rec.evidence_id] = rec
        self._dedup[dkey] = rec.evidence_id
        self._stmt.setdefault(skey, rec.event_id)
        self._records.append(rec)

    # ------------------------------------------------------------ read
    @property
    def records(self) -> tuple:
        return tuple(self._records)

    def get(self, evidence_id: str) -> Optional[EvidenceRecord]:
        return self._ids.get(evidence_id)

    def clusters(self) -> dict:
        out: dict = {}
        for r in self._records:
            out.setdefault(r.event_id, []).append(r)
        return out

    def revision_history(self, evidence_id: str) -> list:
        """The chain original -> correction(s)/retraction for one record."""
        chain = [self._ids[evidence_id]]
        changed = True
        while changed:
            changed = False
            for r in self._records:
                if r.revises_evidence_id == chain[-1].evidence_id:
                    chain.append(r)
                    changed = True
                    break
        return [{"evidence_id": r.evidence_id, "revision_type": r.revision_type,
                 "known_at_utc": r.known_at_utc(), "statement": r.original_statement}
                for r in chain]


# ---------------------------------------------------------------- Grok / X briefs
def records_from_grok_brief(brief: dict) -> list:
    """Stage a structured Grok/X brief as UNTRUSTED ai_brief records.

    Expected shape::

        {"brief_id": "...", "source_url": "https://x.com/...",   # where the brief lives
         "generated_at": "2026-10-19T12:00:00Z",                  # optional
         "items": [{"event_key", "category", "statement", "reporting_entity",
                    "claim_type", "event_timestamp"?, "geographies"?, "sectors"?,
                    "affected_deal_ids"?, "cited_urls"?, "status"?}]}

    * Any status the brief asserts is kept only as ``claimed_status_by_source``.
    * Cited URLs are recorded as LEADS in ``notes``; each must be retrieved and
      staged as its own record before it can count toward verification.
    * The brief's own timestamp is the brief's publication time — it says
      nothing about when the underlying event became public.
    """
    url = brief.get("source_url")
    if not url:
        raise SchemaError("brief.source_url required (where the brief can be audited)")
    out = []
    for i, it in enumerate(brief.get("items") or []):
        leads = it.get("cited_urls") or []
        claimed = it.get("status")
        note = []
        if leads:
            note.append("lead_urls=" + json.dumps(leads))
        if claimed and claimed not in VERIFICATION_STATUSES:
            note.append("claimed_status_raw=" + json.dumps(claimed))
        out.append(EvidenceRecord(
            event_key=it["event_key"], category=it["category"],
            original_statement=it["statement"],
            reporting_entity=it.get("reporting_entity") or "unattributed (Grok brief)",
            source_url=url + ("#item-%d" % i if "#" not in url else ""),
            publisher="Grok/X brief " + str(brief.get("brief_id", "")).strip(),
            source_type="ai_brief", claim_type=it.get("claim_type", "rumor"),
            publication_timestamp=brief.get("generated_at"),
            event_valid_timestamp=it.get("event_timestamp"),
            retrieved_by_reviewer=False,
            geographies=tuple(it.get("geographies") or ()),
            sectors=tuple(it.get("sectors") or ()),
            affected_deal_ids=tuple(it.get("affected_deal_ids") or ()),
            claimed_status_by_source=claimed if claimed in VERIFICATION_STATUSES else None,
            ingested_via="grok_brief",
            notes="; ".join(note)))
    return out
