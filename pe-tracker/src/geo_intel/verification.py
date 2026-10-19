"""Derive an event cluster's verification status from its evidence, as of T.

The status is never copied from a source (``claimed_status_by_source`` is
recorded for audit only). It is recomputed from the evidence that was
*knowable* at T, so the status itself is bitemporal: an event that was
UNCONFIRMED on Monday and VERIFIED_PRIMARY on Wednesday reads as UNCONFIRMED
for any prediction time on Monday.

Rules (first match wins)
------------------------
1. Revisions are applied first: a correction supersedes the record it revises
   from the correction's known_at; a retraction withdraws it.
2. RETRACTED            every trusted supporting record has been retracted.
3. DISPUTED             a retrieved primary source contradicts the claim, or
                        trusted retrieved sources conflict with no primary
                        support.
4. VERIFIED_PRIMARY     >= 1 retrieved primary_official record from a registered
                        authority, with a publication timestamp, claim_type
                        'occurred', stance 'supports'. (Secondary contradictions
                        are kept as recorded conflicts.)
5. CORROBORATED_SECONDARY  >= 2 INDEPENDENT retrieved reputable_secondary
                        publishers ('occurred', 'supports'); syndicated copies
                        of one story count once.
6. ATTRIBUTED_CLAIM     >= 1 retrieved trusted record attributes the claim to a
                        named entity (attributed_statement, a 'scheduled'
                        announcement, or a single trusted 'occurred' report).
7. UNCONFIRMED          everything else — including anything supported only by
                        Grok/X briefs, social posts, rumors, predictions, or
                        sources nobody actually retrieved.

Grok/X (ai_brief / social_post) records never contribute to rules 3–6.
Rumors and predictions can never describe a completed event.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .schema import EvidenceRecord, as_of_cutoff, primary_authority

STATUS_RANK = {"UNCONFIRMED": 0, "ATTRIBUTED_CLAIM": 1, "CORROBORATED_SECONDARY": 2,
               "VERIFIED_PRIMARY": 3, "DISPUTED": -1, "RETRACTED": -2}


@dataclass
class VerificationResult:
    event_id: str
    status: str
    as_of: Optional[str]
    n_records_considered: int
    basis: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    primary_authorities: list = field(default_factory=list)
    independent_secondary_publishers: list = field(default_factory=list)
    untrusted_only: bool = False
    ignored_untrusted: int = 0
    claimed_statuses_ignored: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def knowable(records: Iterable[EvidenceRecord], as_of: Optional[str],
             cutoff_utc: Optional[str] = None) -> list:
    """Records whose effective known_at <= T. Missing known_at => never knowable
    at a historical T (only in the unbounded 'current' view, as_of=None)."""
    recs = list(records)
    if as_of is None and cutoff_utc is None:
        return recs
    t = cutoff_utc if cutoff_utc is not None else as_of_cutoff(as_of)
    out = []
    for r in recs:
        k = r.known_at_utc()
        if k is not None and k <= t:
            out.append(r)
    return out


def apply_revisions(records: list) -> tuple[list, list]:
    """Return (effective records, retracted originals). Corrections replace the
    record they revise; retractions withdraw it. Chains are followed."""
    by_id = {r.evidence_id: r for r in records}
    superseded, retracted = set(), []
    for r in records:
        if r.revises_evidence_id and r.revises_evidence_id in by_id:
            superseded.add(r.revises_evidence_id)
            if r.revision_type == "retraction":
                retracted.append(by_id[r.revises_evidence_id])
    effective = [r for r in records
                 if r.evidence_id not in superseded and r.revision_type != "retraction"]
    return effective, retracted


def _independent_publishers(recs: list) -> list:
    """Distinct publishers, with syndicated copies collapsed onto their origin."""
    keys = []
    for r in recs:
        k = (r.syndicated_from or r.publisher).strip().lower()
        if k not in keys:
            keys.append(k)
    return keys


def classify(records: Iterable[EvidenceRecord], as_of: Optional[str] = None,
             primary_registry: Optional[dict] = None,
             cutoff_utc: Optional[str] = None) -> VerificationResult:
    """`as_of` is a user-facing prediction time; `cutoff_utc` an already
    normalized naive-UTC cutoff (internal use)."""
    recs = knowable(records, as_of, cutoff_utc)
    eids = {r.event_id for r in recs}
    if len(eids) > 1:
        raise ValueError(f"classify() expects one event cluster, got {sorted(eids)}")
    event_id = next(iter(eids)) if eids else ""
    res = VerificationResult(event_id=event_id, status="UNCONFIRMED",
                             as_of=as_of if as_of is not None else cutoff_utc,
                             n_records_considered=len(recs))
    res.claimed_statuses_ignored = sorted({r.claimed_status_by_source for r in recs
                                           if r.claimed_status_by_source})
    if not recs:
        res.basis.append("no evidence knowable at as_of")
        return res

    eff, retracted = apply_revisions(recs)
    trusted = [r for r in eff if r.is_trusted_source() and r.retrieved_by_reviewer]
    res.ignored_untrusted = sum(1 for r in eff if not r.is_trusted_source())
    res.untrusted_only = not any(r.is_trusted_source() for r in eff)

    sup = [r for r in trusted if r.stance == "supports"]
    con = [r for r in trusted if r.stance == "contradicts"]

    prim_sup = [r for r in sup if r.source_type == "primary_official"
                and r.claim_type == "occurred" and r.publication_timestamp
                and primary_authority(r.source_url, primary_registry)]
    prim_con = [r for r in con if r.source_type == "primary_official"
                and primary_authority(r.source_url, primary_registry)]
    sec_sup = [r for r in sup if r.source_type == "reputable_secondary"
               and r.claim_type == "occurred"]
    res.primary_authorities = sorted({primary_authority(r.source_url, primary_registry)
                                      for r in prim_sup})
    res.independent_secondary_publishers = _independent_publishers(sec_sup)
    res.conflicts = [{"evidence_id": r.evidence_id, "publisher": r.publisher,
                      "source_type": r.source_type} for r in con]

    # 2. RETRACTED
    trusted_retracted = [r for r in retracted if r.is_trusted_source()]
    if trusted_retracted and not sup:
        res.status = "RETRACTED"
        res.basis.append(f"{len(trusted_retracted)} trusted record(s) retracted; "
                         "no remaining trusted support")
        return res
    # 3. DISPUTED
    if prim_con:
        res.status = "DISPUTED"
        res.basis.append("a retrieved primary source contradicts the claim")
        return res
    if con and not prim_sup:
        res.status = "DISPUTED"
        res.basis.append("trusted sources conflict and no primary source resolves it")
        return res
    # 4. VERIFIED_PRIMARY
    if prim_sup:
        res.status = "VERIFIED_PRIMARY"
        res.basis.append("retrieved primary source(s): " + ", ".join(res.primary_authorities))
        if con:
            res.basis.append(f"{len(con)} secondary contradiction(s) recorded as conflicts")
        return res
    # 5. CORROBORATED_SECONDARY
    if len(res.independent_secondary_publishers) >= 2:
        res.status = "CORROBORATED_SECONDARY"
        res.basis.append("independent retrieved secondary publishers: "
                         + ", ".join(res.independent_secondary_publishers))
        return res
    # 6. ATTRIBUTED_CLAIM
    attributable = [r for r in sup if r.claim_type in ("attributed_statement", "scheduled", "occurred")]
    if attributable:
        res.status = "ATTRIBUTED_CLAIM"
        res.basis.append("claim attributable to a named entity via a retrieved trusted source; "
                         "not independently corroborated")
        return res
    # 7. UNCONFIRMED
    if res.untrusted_only:
        res.basis.append("only untrusted (Grok/X/social/other) evidence")
    else:
        res.basis.append("no retrieved trusted evidence of a completed event "
                         "(rumor / prediction / unretrieved source)")
    return res


def status_history(records: Iterable[EvidenceRecord],
                   primary_registry: Optional[dict] = None) -> list:
    """Status transitions at each distinct known_at in the cluster (audit trail)."""
    recs = list(records)
    times = sorted({r.known_at_utc() for r in recs if r.known_at_utc()})
    out, last = [], None
    for t in times:
        s = classify(recs, cutoff_utc=t, primary_registry=primary_registry).status
        if s != last:
            out.append({"as_of_utc": t, "status": s})
            last = s
    return out
