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

import contextlib
import fcntl
import json
import os
import tempfile
import time
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


class LedgerLockTimeout(RuntimeError):
    pass


@contextlib.contextmanager
def ledger_lock(path: Path, timeout_s: float = 30.0):
    """Exclusive single-writer lock on ``<ledger>.lock`` (POSIX flock).

    Every writer (any bot, any process) must hold it for the whole
    read-validate-write cycle, so two writers can never interleave or both
    accept the same record."""
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise LedgerLockTimeout(f"could not lock {lock_path} in {timeout_s}s")
                time.sleep(0.01)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_write_lines(path: Path, lines: list) -> None:
    """Write-temp-then-rename in the same directory (fsync'd): readers see the
    old file or the new file, never a partial one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for l in lines:
                f.write(l + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


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
    """Append-only ledger. With a ``path``, every write takes the exclusive
    file lock, re-reads records other writers appended, validates and dedups
    against the full current ledger, then atomically replaces the file with
    old-lines + new-lines. Existing lines are never rewritten (checked)."""

    def __init__(self, path: Optional[Path] = None, clock: Callable[[], str] = _utc_now,
                 primary_registry: Optional[dict] = None, lock_timeout_s: float = 30.0):
        self.path = Path(path) if path else None
        self.clock = clock
        self.primary_registry = primary_registry
        self.lock_timeout_s = lock_timeout_s
        self._records: list[EvidenceRecord] = []
        self._ids: dict[str, EvidenceRecord] = {}
        self._dedup: dict[tuple, str] = {}
        self._stmt: dict[tuple, str] = {}
        self._lines: list[str] = []
        if self.path and self.path.exists():
            self._refresh()

    # ------------------------------------------------------------ io
    def _refresh(self) -> None:
        """Index lines appended by other writers since our last read."""
        if not (self.path and self.path.exists()):
            return
        lines = [l for l in self.path.read_text(encoding="utf-8").splitlines() if l.strip()]
        n = len(self._lines)
        if lines[:n] != self._lines:
            raise LedgerIntegrityError(f"{self.path}: existing lines were modified or removed")
        for i, line in enumerate(lines[n:], n + 1):
            raw = json.loads(line)
            rec = EvidenceRecord.from_dict(raw)
            chk = rec.validate(self.primary_registry)
            if chk.evidence_id != raw.get("evidence_id") or chk.event_id != raw.get("event_id"):
                raise LedgerIntegrityError(
                    f"{self.path}:{i}: stored ids do not match content (edited in place?)")
            self._index(chk, check=True)
            self._lines.append(line)

    def _prepare(self, record: EvidenceRecord) -> EvidenceRecord:
        if not record.first_observed_timestamp:
            # The moment THIS system first saw the source is a real, observed
            # time — never back-dated.
            d = json.loads(record.to_json())
            d["first_observed_timestamp"] = self.clock()
            record = EvidenceRecord.from_dict(d)
        return record.validate(self.primary_registry)

    # ------------------------------------------------------------ write
    def append(self, record: EvidenceRecord) -> EvidenceRecord:
        return self.extend([record])[0]

    def extend(self, records: Iterable[EvidenceRecord]) -> list:
        """All-or-nothing batch append under the single-writer lock; any
        duplicate or invalid record aborts the whole batch."""
        def strict(_ledger, rec):
            return "append", rec
        return [p for _, p in self.apply(records, strict, atomic_batch=True)]

    def apply(self, records: Iterable[EvidenceRecord], resolver,
              atomic_batch: bool = False) -> list:
        """Run ``resolver(ledger, validated_record) -> (action, payload)`` for
        each record while holding the lock, after re-reading the file.

        action 'append' / 'revision' -> payload (a record) is indexed + written;
        any other action (e.g. 'duplicate') -> payload is a reason, nothing written.
        With ``atomic_batch`` a SchemaError aborts everything; otherwise it is
        reported per record as ('rejected', reason)."""
        records = list(records)
        lock = (ledger_lock(self.path, self.lock_timeout_s) if self.path
                else contextlib.nullcontext())
        with lock:
            self._refresh()
            snapshot = (list(self._records), dict(self._ids), dict(self._dedup),
                        dict(self._stmt))
            outcomes, new = [], []
            try:
                for r in records:
                    try:
                        rec = self._prepare(r)
                        action, payload = resolver(self, rec)
                        if action in ("append", "revision"):
                            self._index(payload, check=True)
                            new.append(payload)
                    except SchemaError as exc:
                        if atomic_batch:
                            raise
                        action, payload = "rejected", f"{type(exc).__name__}: {exc}"
                    outcomes.append((action, payload))
                if self.path and new:
                    new_lines = [r.to_json() for r in new]
                    _atomic_write_lines(self.path, self._lines + new_lines)
                    self._lines.extend(new_lines)
            except BaseException:
                self._records, self._ids, self._dedup, self._stmt = snapshot
                raise
            return outcomes

    def dedup_match(self, rec: EvidenceRecord) -> Optional[str]:
        """evidence_id of an already-staged record with the same
        (event, canonical URL, stance, revision target), else None."""
        return self._dedup.get((rec.event_id, canonical_url(rec.source_url), rec.stance,
                                rec.revises_evidence_id))

    def latest_revision(self, evidence_id: str) -> EvidenceRecord:
        cur = self._ids[evidence_id]
        while True:
            nxt = next((r for r in self._records if r.revises_evidence_id == cur.evidence_id),
                       None)
            if nxt is None:
                return cur
            cur = nxt

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
