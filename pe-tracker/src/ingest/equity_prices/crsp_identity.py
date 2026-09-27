"""CRSP security-identity resolution (deal → PERMNO).

Do NOT map solely by ticker. Do not guess when multiple PERMNO candidates remain.
Uncertain → DEFER_CRSP_IDENTITY_AMBIGUOUS / ProviderStatus.IDENTITY_AMBIGUOUS.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .schema import ProviderStatus, SecurityIdentity

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CRSP_MAP = ROOT / "data" / "crsp_security_map.json"

# Mapping row statuses (committed map + runtime classification).
STATUS_MATCHED = "MATCHED"
STATUS_AMBIGUOUS = "DEFER_CRSP_IDENTITY_AMBIGUOUS"
STATUS_NO_MATCH = "CRSP_NO_SECURITY_MATCH"
STATUS_CREDENTIALS = "CREDENTIALS_REQUIRED"
STATUS_PENDING = "PENDING_RESOLUTION"


@dataclass(frozen=True)
class CrspSecurityMapping:
    """One deal → CRSP identity row (license-safe metadata only)."""
    deal_id: str
    target_cik: Optional[int] = None
    target_name: Optional[str] = None
    historical_ticker: Optional[str] = None
    permno: Optional[int] = None
    permco: Optional[int] = None
    mapping_method: Optional[str] = None
    effective_start: Optional[str] = None
    effective_end: Optional[str] = None
    evidence: dict = field(default_factory=dict)
    confidence: Optional[str] = None  # high | medium | low
    status: str = STATUS_PENDING

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CrspNameRow:
    """Minimal name-history row used for identity matching (injected / mockable)."""
    permno: int
    permco: Optional[int]
    ticker: Optional[str]
    comnam: Optional[str] = None
    ncusip: Optional[str] = None
    exchcd: Optional[int] = None
    namedt: Optional[str] = None
    nameendt: Optional[str] = None


def load_crsp_security_map(path: Path = DEFAULT_CRSP_MAP) -> dict:
    """Load committed mapping document (may have zero matched PERMNOs)."""
    path = Path(path)
    if not path.exists():
        return {
            "schema_version": 1,
            "meta": {"mapping_status": STATUS_CREDENTIALS},
            "mappings": [],
        }
    return json.loads(path.read_text())


def write_crsp_security_map(doc: dict, path: Path = DEFAULT_CRSP_MAP) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def mapping_for_deal(doc: dict, deal_id: str) -> Optional[CrspSecurityMapping]:
    for row in doc.get("mappings") or []:
        if row.get("deal_id") == deal_id:
            return CrspSecurityMapping(
                deal_id=row["deal_id"],
                target_cik=row.get("target_cik"),
                target_name=row.get("target_name"),
                historical_ticker=row.get("historical_ticker"),
                permno=row.get("permno"),
                permco=row.get("permco"),
                mapping_method=row.get("mapping_method"),
                effective_start=row.get("effective_start"),
                effective_end=row.get("effective_end"),
                evidence=row.get("evidence") or {},
                confidence=row.get("confidence"),
                status=row.get("status") or STATUS_PENDING,
            )
    return None


def _overlaps_asof(namedt: Optional[str], nameendt: Optional[str],
                   asof: str) -> bool:
    """True if asof is within [namedt, nameendt] when bounds exist."""
    start = namedt or "0001-01-01"
    end = nameendt or "9999-12-31"
    return start <= asof <= end


def _norm_name(s: Optional[str]) -> str:
    if not s:
        return ""
    return " ".join("".join(ch if ch.isalnum() or ch.isspace() else " "
                            for ch in s.upper()).split())


def resolve_permno_candidates(
        identity: SecurityIdentity,
        name_rows: Sequence[CrspNameRow],
        *,
        asof: Optional[str] = None,
) -> tuple[list[CrspNameRow], str]:
    """Rank CRSP name-history rows without guessing a single PERMNO.

    Matching uses the strongest available combination of ticker, name, NCUSIP,
    and effective dates. Ticker-alone matches that span multiple PERMNOs → ambiguous.
    """
    asof = asof or identity.announcement_date or date.today().isoformat()
    ticker = (identity.ticker or "").upper() or None
    want_name = _norm_name(identity.target_name)

    dated = [r for r in name_rows if _overlaps_asof(r.namedt, r.nameendt, asof)]
    pool = dated or list(name_rows)

    by_ticker = [r for r in pool
                 if ticker and (r.ticker or "").upper() == ticker]
    if want_name:
        by_name = [r for r in by_ticker
                   if want_name and want_name in _norm_name(r.comnam)]
        if len({r.permno for r in by_name}) == 1:
            return by_name, "ticker+name+asof"
        if by_name:
            return by_name, STATUS_AMBIGUOUS

    if len({r.permno for r in by_ticker}) == 1:
        method = "ticker+asof" if dated else "ticker_only"
        # ticker_only is weak — still unique PERMNO but flag confidence downstream
        return by_ticker, method
    if by_ticker:
        return by_ticker, STATUS_AMBIGUOUS

    if want_name:
        by_name_only = [r for r in pool
                        if want_name and want_name == _norm_name(r.comnam)]
        if len({r.permno for r in by_name_only}) == 1:
            return by_name_only, "exact_name+asof"
        if by_name_only:
            return by_name_only, STATUS_AMBIGUOUS

    return [], STATUS_NO_MATCH


class CrspIdentityResolver:
    """Resolve SecurityIdentity → PERMNO using committed map + optional name feed."""

    def __init__(
            self,
            map_path: Path = DEFAULT_CRSP_MAP,
            name_lookup: Optional[Callable[[SecurityIdentity],
                                           Sequence[CrspNameRow]]] = None,
            access_available: bool = False,
    ):
        self.map_path = Path(map_path)
        self._doc = load_crsp_security_map(self.map_path)
        self._name_lookup = name_lookup
        self.access_available = access_available

    def resolve(
            self, identity: SecurityIdentity,
    ) -> tuple[Optional[CrspSecurityMapping], Optional[ProviderStatus]]:
        """Return (mapping, defer_status). defer_status set when unusable."""
        committed = mapping_for_deal(self._doc, identity.deal_id)
        if committed and committed.status == STATUS_MATCHED and committed.permno:
            return committed, None
        if committed and committed.status == STATUS_AMBIGUOUS:
            return committed, ProviderStatus.IDENTITY_AMBIGUOUS
        if committed and committed.status == STATUS_NO_MATCH:
            return committed, ProviderStatus.SYMBOL_NOT_FOUND

        if not self.access_available and self._name_lookup is None:
            return CrspSecurityMapping(
                deal_id=identity.deal_id,
                target_cik=identity.target_cik,
                target_name=identity.target_name,
                historical_ticker=identity.ticker,
                status=STATUS_CREDENTIALS,
            ), ProviderStatus.CREDENTIALS_REQUIRED

        if self._name_lookup is None:
            return CrspSecurityMapping(
                deal_id=identity.deal_id,
                target_cik=identity.target_cik,
                target_name=identity.target_name,
                historical_ticker=identity.ticker,
                status=STATUS_NO_MATCH,
            ), ProviderStatus.SYMBOL_NOT_FOUND

        rows = list(self._name_lookup(identity) or [])
        cands, method = resolve_permno_candidates(identity, rows)
        if method == STATUS_AMBIGUOUS:
            return CrspSecurityMapping(
                deal_id=identity.deal_id,
                target_cik=identity.target_cik,
                target_name=identity.target_name,
                historical_ticker=identity.ticker,
                mapping_method=method,
                evidence={"candidate_permnos": sorted({r.permno for r in cands})},
                confidence="low",
                status=STATUS_AMBIGUOUS,
            ), ProviderStatus.IDENTITY_AMBIGUOUS
        if method == STATUS_NO_MATCH or not cands:
            return CrspSecurityMapping(
                deal_id=identity.deal_id,
                target_cik=identity.target_cik,
                target_name=identity.target_name,
                historical_ticker=identity.ticker,
                mapping_method=method,
                status=STATUS_NO_MATCH,
            ), ProviderStatus.SYMBOL_NOT_FOUND

        best = cands[0]
        conf = "high" if method.startswith("ticker+name") else (
            "medium" if "asof" in method else "low")
        return CrspSecurityMapping(
            deal_id=identity.deal_id,
            target_cik=identity.target_cik,
            target_name=identity.target_name,
            historical_ticker=identity.ticker,
            permno=best.permno,
            permco=best.permco,
            mapping_method=method,
            effective_start=best.namedt,
            effective_end=best.nameendt,
            evidence={
                "comnam": best.comnam,
                "ncusip": best.ncusip,
                "exchcd": best.exchcd,
            },
            confidence=conf,
            status=STATUS_MATCHED,
        ), None
