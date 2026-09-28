"""Persisted proof-B identity evidence. Never stores credentials."""
from __future__ import annotations

from datetime import date
from typing import Optional

from ..security_identity.name_match import names_agree, significant_tokens
from .schema import SecurityIdentity
from .tiingo import META_URL, identity_problems

PROOF_B = "B_TIINGO_NAME_AND_LISTING_WINDOW"
PROOF_A = "A_OPENFIGI_MATCHED"
PROOF_C = "C_REVIEWED_SEC_MAPPING"


def listing_window_covers(meta: dict, announcement_date: Optional[str]) -> bool:
    """Same listing-window clause as identity_problems, isolated for the artifact."""
    ann = announcement_date or ""
    start = (meta.get("startDate") or "")[:10]
    end = (meta.get("endDate") or "")[:10]
    if not start or not ann or start > ann:
        return False
    if end and end < ann:
        return False
    return True


def build_identity_evidence(
        *,
        deal_id: str,
        canonical_target_name: Optional[str],
        historical_ticker: Optional[str],
        announcement_date: Optional[str],
        tiingo_meta: dict,
        retrieved_at: str,
        openfigi_status: Optional[str] = None,
        figi: Optional[str] = None,
        composite_figi: Optional[str] = None,
        share_class_figi: Optional[str] = None,
        prior_proofs: Optional[list[str]] = None,
) -> dict:
    """One admitted deal's reconstructable identity record.

    proof_B_earned is recomputed from the provider name and listing window.
    It is not copied from the previous boolean.
    """
    provider_name = tiingo_meta.get("name")
    target_tokens = sorted(significant_tokens(canonical_target_name))
    provider_tokens = sorted(significant_tokens(provider_name))
    agree = names_agree(provider_name, canonical_target_name)
    covers = listing_window_covers(tiingo_meta, announcement_date)
    ident = SecurityIdentity(
        deal_id=deal_id,
        target_name=canonical_target_name,
        ticker=historical_ticker,
        announcement_date=announcement_date,
    )
    problems = identity_problems(
        tiingo_meta, ident, date.fromisoformat(announcement_date) if announcement_date
        else date(1970, 1, 1))
    # identity_problems also checks the window against announcement_date on the
    # identity, which is the admission rule. Recompute the boolean from the
    # same two clauses so a metadata refresh can fail a previously true flag.
    proof_b = bool(agree and covers and not problems)
    symbol = (historical_ticker or "").upper()
    record = {
        "deal_id": deal_id,
        "canonical_target_name": canonical_target_name,
        "historical_ticker": symbol or None,
        "tiingo_provider_name": provider_name,
        "tiingo_listing_start": (tiingo_meta.get("startDate") or "")[:10] or None,
        "tiingo_listing_end": (tiingo_meta.get("endDate") or "")[:10] or None,
        "announcement_date": announcement_date,
        "normalized_target_tokens": target_tokens,
        "normalized_provider_tokens": provider_tokens,
        "names_agree": agree,
        "listing_window_covers_announcement": covers,
        "proof_B_earned": proof_b,
        "retrieved_at": retrieved_at,
        "provider_endpoint": META_URL.format(symbol=symbol) if symbol else META_URL,
    }
    proofs = list(prior_proofs or [])
    if openfigi_status == "MATCHED" or PROOF_A in proofs:
        record["openfigi"] = {
            "status": openfigi_status,
            "figi": figi,
            "composite_figi": composite_figi,
            "share_class_figi": share_class_figi,
            "proof_A": openfigi_status == "MATCHED",
        }
    if PROOF_C in proofs:
        record["proof_C"] = True
    return record
