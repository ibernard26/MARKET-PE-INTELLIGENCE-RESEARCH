"""Bitemporal / anti-leakage gate for geopolitical research candidates.

A geopolitical event may be offered as a HISTORICAL RESEARCH CANDIDATE for a
prediction at time T only if, using evidence knowable at T:

    status_as_of(T) in {VERIFIED_PRIMARY, CORROBORATED_SECONDARY}
    AND claim describes a completed event (claim_type 'occurred')
    AND valid_time <= T
    AND known_at  <= T      (known_at = when the status first became admissible)

Missing valid_time or known_at => not admissible (never imputed).

"Candidate" means research input to a future, separately authorized fs_v2
experiment. Nothing returned here is wired into fs_v1, break_logit_v1, the
training-set builder or any decision / execution path.
"""
from __future__ import annotations

from typing import Optional

from .schema import ADMISSIBLE_STATUSES, as_of_cutoff
from .verification import classify, knowable, status_history

CANDIDATE_SCOPE = "RESEARCH_CANDIDATE_ONLY__NOT_IN_fs_v1__NOT_A_MODEL_FEATURE"


class LeakageError(AssertionError):
    pass


def _admissible_since(records, cutoff: str, registry) -> Optional[str]:
    """Earliest known_at at which the cluster's status became admissible and
    stayed admissible through `cutoff` (status recomputed at each step)."""
    hist = [h for h in status_history(knowable(records, None, cutoff), registry)
            if h["as_of_utc"] <= cutoff]
    since = None
    for h in hist:
        if h["status"] in ADMISSIBLE_STATUSES:
            since = since or h["as_of_utc"]
        else:
            since = None
    return since


def _valid_time(records, result) -> Optional[str]:
    """Conservative valid time: the LATEST valid timestamp among the trusted,
    retrieved, supporting 'occurred' records knowable at T."""
    vals = [r.valid_utc() for r in records
            if r.is_trusted_source() and r.retrieved_by_reviewer and r.stance == "supports"
            and r.claim_type == "occurred" and r.valid_utc() is not None]
    return max(vals) if vals else None


def research_candidates(ledger, prediction_time: str) -> dict:
    """Split every event cluster into admissible candidates vs rejections."""
    cutoff = as_of_cutoff(prediction_time)
    reg = ledger.primary_registry
    admitted, rejected = [], []
    for eid, recs in sorted(ledger.clusters().items()):
        kn = knowable(recs, None, cutoff)
        res = classify(recs, cutoff_utc=cutoff, primary_registry=reg)
        cat = recs[0].category
        if not kn:
            rejected.append({"event_id": eid, "reason": "no_evidence_known_at_prediction_time"})
            continue
        if res.status not in ADMISSIBLE_STATUSES:
            rejected.append({"event_id": eid, "reason": f"status_{res.status}"})
            continue
        valid = _valid_time(kn, res)
        if valid is None:
            rejected.append({"event_id": eid, "reason": "missing_valid_time"})
            continue
        if valid > cutoff:
            rejected.append({"event_id": eid, "reason": "valid_time_after_prediction_time"})
            continue
        since = _admissible_since(recs, cutoff, reg)
        if since is None or since > cutoff:
            rejected.append({"event_id": eid, "reason": "known_at_after_prediction_time"})
            continue
        admitted.append({
            "event_id": eid, "category": cat, "status_as_of": res.status,
            "valid_time_utc": valid, "known_at_utc": since,
            "geographies": sorted({g for r in kn for g in r.geographies}),
            "sectors": sorted({s for r in kn for s in r.sectors}),
            "scope": CANDIDATE_SCOPE,
        })
    out = {"prediction_time": prediction_time, "cutoff_utc": cutoff,
           "admitted": admitted, "rejected": rejected}
    assert_no_leakage(out)
    return out


def assert_no_leakage(result: dict) -> None:
    c = result["cutoff_utc"]
    for a in result["admitted"]:
        if a["valid_time_utc"] is None or a["known_at_utc"] is None:
            raise LeakageError(f"{a['event_id']}: missing timestamp admitted")
        if a["valid_time_utc"] > c or a["known_at_utc"] > c:
            raise LeakageError(f"{a['event_id']}: post-prediction-time information admitted")
        if a["status_as_of"] not in ADMISSIBLE_STATUSES:
            raise LeakageError(f"{a['event_id']}: unverified status admitted")
