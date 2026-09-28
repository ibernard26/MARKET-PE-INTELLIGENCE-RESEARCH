"""identity_admission_v2 — PROPOSED, not active. Requires audit approval.

Two outcome-blind changes to how identity vetoes are decided, versioned so the
v1 decisions recorded in PR #44 stay reproducible:

1. OpenFIGI ambiguity at the security level. v1 (`openfigi.py` line ~219)
   counts distinct venue-level `figi` values. A ticker queried without
   `exchCode` returns one FIGI per US venue (composite + UN/UW/UQ/…), so an
   ordinary single listing reads as AMBIGUOUS. v2 counts distinct
   `compositeFIGI` among equity rows whose issuer name agrees with the target.

2. Proof C + Proof B may override an OpenFIGI veto. OpenFIGI reflects current
   symbology. A contemporaneous target-filed SEC document naming the ticker
   (Proof C), together with a price source whose issuer name and listing window
   match the target (Proof B), outranks today's symbol map for a historical
   window. A Tiingo IDENTITY_AMBIGUOUS veto is never overridden (its series is
   another issuer's), and Yahoo-only series cannot use the override.

Nothing here reads outcome labels. `canonical_status_v2` refuses to run until
RULE_STATUS is set to APPROVED in a separately reviewed commit.
"""
from __future__ import annotations

from typing import Optional

from .name_match import names_agree
from .proof_c import RESOLVED

RULE_ID = "identity_admission_v2"
RULE_STATUS = "PROPOSED_PENDING_AUDIT"
APPROVED = "APPROVED"

MATCHED, AMBIGUOUS, NAME_MISMATCH, NO_MATCH = "MATCHED", "AMBIGUOUS", "NAME_MISMATCH", "NO_MATCH"


class RuleNotApprovedError(RuntimeError):
    pass


def openfigi_status_v2(rows: list[dict], target_name: Optional[str]) -> dict:
    """Security-level OpenFIGI classification over raw mapping rows."""
    equities = [r for r in rows if (r.get("marketSector") or "Equity").lower() == "equity"]
    pool = equities or list(rows)
    if not pool:
        return {"status": NO_MATCH, "composite_figis": []}
    agreeing = [r for r in pool if names_agree(r.get("name"), target_name)]
    if not agreeing:
        return {"status": NAME_MISMATCH, "composite_figis": [],
                "candidate_names": sorted({str(r.get("name")) for r in pool})}
    comps = sorted({r.get("compositeFIGI") or r.get("figi") for r in agreeing} - {None})
    if len(comps) > 1:
        return {"status": AMBIGUOUS, "composite_figis": comps}
    return {"status": MATCHED, "composite_figis": comps}


def canonical_status_v2(row: dict, proof_c_status: Optional[str],
                        rule_status: str = RULE_STATUS) -> tuple[str, Optional[str]]:
    """(canonical_status, reason) under identity_admission_v2.

    `row` carries the v1 matrix fields, with `openfigi_status` recomputed by
    `openfigi_status_v2`.
    """
    if rule_status != APPROVED:
        raise RuleNotApprovedError(f"{RULE_ID} is {rule_status}; audit approval required")
    has_c = proof_c_status == RESOLVED
    has_b = bool(row.get("tiingo_identity_verified"))
    if row.get("tiingo_status") == "IDENTITY_AMBIGUOUS":
        return "DEFERRED_IDENTITY", "TIINGO_IDENTITY_AMBIGUOUS"
    if row.get("openfigi_status") in (AMBIGUOUS, NAME_MISMATCH) and not (has_c and has_b):
        return "DEFERRED_IDENTITY", f"OPENFIGI_{row['openfigi_status']}"
    if row.get("material_conflicts", 0) > 0:
        return "DEFERRED_PRICE_CONFLICT", None
    if row.get("tiingo_n", 0) == 0 and row.get("yahoo_n", 0) == 0:
        return "NO_PRICE_HISTORY", None
    if not (row.get("openfigi_status") == MATCHED or has_b or has_c):
        return "DEFERRED_IDENTITY", "DEFER_IDENTITY_UNCONFIRMED"
    if row.get("combined_n", 0) >= 3:
        return "CANONICALLY_ADMITTED", None
    return "INSUFFICIENT_CANONICAL_PRINTS", None
