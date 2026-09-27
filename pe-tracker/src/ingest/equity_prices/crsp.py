"""CRSP adapter implementing HistoricalEquityPriceProvider.

Authoritative historical research source for delisted U.S. equities when
licensed access is configured. Without credentials:

  credentials_required() -> True
  status -> CREDENTIALS_REQUIRED

Never fabricate CRSP responses. Never commit licensed raw CRSP files to Git.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from zoneinfo import ZoneInfo

from .calendar_gate import filter_session_observations
from .crsp_access import CrspAccessConfig, detect_crsp_access
from .crsp_identity import (
    DEFAULT_CRSP_MAP,
    CrspIdentityResolver,
    CrspNameRow,
    CrspSecurityMapping,
)
from .schema import (
    NormalizedEquityObservation,
    ProviderFetchResult,
    ProviderStatus,
    SecurityIdentity,
)

PROVIDER_NAME = "crsp"
NY = ZoneInfo("America/New_York")

# Versioned acceptance rule for CRSP CIZ daily prices used by spread_stress_v1.
# Prefer true closing-trade observations. Bid/ask averages are NOT treated as
# traded closes unless a future versioned rule explicitly permits them.
CRSP_PRICE_ACCEPTANCE_RULE = "crsp_dlyprc_acceptance_v1"
# CIZ DlyPrcFlg: blank/None → last trade close; "A" → bid/ask average (reject).
ACCEPT_DLYPRC_FLAGS = frozenset({None, "", " ", "T"})
REJECT_DLYPRC_FLAGS = frozenset({"A", "a"})


@dataclass(frozen=True)
class CrspDailyRow:
    """Provider-internal daily row (CIZ-shaped). Not exposed to modeling code."""
    permno: int
    dly_cal_dt: str
    dly_prc: Optional[float]
    dly_prc_flg: Optional[str] = None
    dly_ret: Optional[float] = None
    dly_retx: Optional[float] = None
    dly_vol: Optional[float] = None


@dataclass(frozen=True)
class CrspDelistingRow:
    """Delisting metadata — separate from regular-session closes."""
    permno: int
    delisting_dt: Optional[str] = None
    del_dt_prc: Optional[float] = None
    del_dt_prc_flg: Optional[str] = None
    del_action_type: Optional[str] = None
    del_status_type: Optional[str] = None
    delisting_return: Optional[float] = None


def session_close_iso(d: date) -> str:
    aware = datetime(d.year, d.month, d.day, 16, 0, 0, tzinfo=NY)
    return aware.replace(tzinfo=None).isoformat()


def dlyprc_usable_for_spread(flg: Optional[str]) -> bool:
    """crsp_dlyprc_acceptance_v1 — traded close only."""
    if flg in ACCEPT_DLYPRC_FLAGS:
        return True
    if flg in REJECT_DLYPRC_FLAGS:
        return False
    # Unknown flags: reject for spread model (retainable in provenance only).
    return False


def normalize_crsp_daily_rows(
        identity: SecurityIdentity,
        mapping: CrspSecurityMapping,
        rows: Sequence[CrspDailyRow],
        *,
        retrieval_timestamp: Optional[str] = None,
        calendar_conn=None,
) -> tuple[list[NormalizedEquityObservation], list[dict]]:
    """Map CIZ daily rows → NormalizedEquityObservation; drop non-trade flags."""
    retrieved = retrieval_timestamp or (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    obs: list[NormalizedEquityObservation] = []
    rejected: list[dict] = []
    seen_dates: set[str] = set()
    for row in rows:
        sd = row.dly_cal_dt[:10]
        if sd in seen_dates:
            rejected.append({
                "session_date": sd, "reason": "duplicate_date",
                "permno": row.permno, "dly_prc_flg": row.dly_prc_flg,
            })
            continue
        if row.dly_prc is None:
            rejected.append({
                "session_date": sd, "reason": "missing_dly_prc",
                "permno": row.permno, "dly_prc_flg": row.dly_prc_flg,
            })
            continue
        try:
            prc = float(row.dly_prc)
        except (TypeError, ValueError):
            rejected.append({
                "session_date": sd, "reason": "non_numeric_dly_prc",
                "permno": row.permno,
            })
            continue
        if not (prc > 0 and prc == prc):
            rejected.append({
                "session_date": sd, "reason": "non_positive_dly_prc",
                "permno": row.permno, "dly_prc": row.dly_prc,
            })
            continue
        if not dlyprc_usable_for_spread(row.dly_prc_flg):
            rejected.append({
                "session_date": sd,
                "reason": "dly_prc_flg_rejected_by_" + CRSP_PRICE_ACCEPTANCE_RULE,
                "permno": row.permno,
                "dly_prc": prc,
                "dly_prc_flg": row.dly_prc_flg,
            })
            continue
        seen_dates.add(sd)
        ts = session_close_iso(date.fromisoformat(sd))
        obs.append(NormalizedEquityObservation(
            deal_id=identity.deal_id,
            session_date=sd,
            close=prc,
            adjusted_close=None,  # do not invent; CRSP returns separate from DlyPrc
            provider=PROVIDER_NAME,
            provider_symbol=str(mapping.permno),
            retrieval_timestamp=retrieved,
            target_cik=identity.target_cik,
            target_name=identity.target_name,
            ticker=identity.ticker or mapping.historical_ticker,
            exchange=identity.exchange,
            currency="USD",
            close_field_used="close",  # DlyPrc as unadjusted session price
            corporate_action_note=(
                f"{CRSP_PRICE_ACCEPTANCE_RULE}: DlyPrc used as unadjusted close; "
                "DlyPrcFlg must indicate traded close; adjusted series not mixed"
            ),
            source_metadata={
                "permno": mapping.permno,
                "permco": mapping.permco,
                "dly_prc_flg": row.dly_prc_flg,
                "dly_ret": row.dly_ret,
                "dly_retx": row.dly_retx,
                "dly_vol": row.dly_vol,
                "mapping_method": mapping.mapping_method,
                "mapping_confidence": mapping.confidence,
                "price_acceptance_rule": CRSP_PRICE_ACCEPTANCE_RULE,
                "identity_source": identity.identity_source,
            },
            observation_timestamp=ts,
            known_at=ts,
        ))
    ok, bad = filter_session_observations(obs, conn=calendar_conn)
    for b in bad:
        rejected.append({
            "session_date": b.session_date,
            "reason": "non_session_date",
            "permno": mapping.permno,
        })
    return ok, rejected


class CRSPEquityPriceProvider:
    """HistoricalEquityPriceProvider over WRDS CRSP or licensed flat files."""

    name = PROVIDER_NAME

    def __init__(
            self,
            access: Optional[CrspAccessConfig] = None,
            identity_resolver: Optional[CrspIdentityResolver] = None,
            daily_lookup: Optional[Callable[
                [int, date, date], Sequence[CrspDailyRow]]] = None,
            delist_lookup: Optional[Callable[
                [int], Optional[CrspDelistingRow]]] = None,
            name_lookup: Optional[Callable[
                [SecurityIdentity], Sequence[CrspNameRow]]] = None,
            map_path: Path = DEFAULT_CRSP_MAP,
            calendar_conn=None,
            force_credentials_required: Optional[bool] = None,
    ):
        self.access = access if access is not None else detect_crsp_access()
        self._daily_lookup = daily_lookup
        self._delist_lookup = delist_lookup
        self._calendar_conn = calendar_conn
        self._force_creds = force_credentials_required
        access_ok = self.access.available and not self.credentials_required()
        # Injected lookups (tests) count as available even without live WRDS.
        if daily_lookup is not None or name_lookup is not None:
            access_ok = True if force_credentials_required is not True else False
        self.identity = identity_resolver or CrspIdentityResolver(
            map_path=map_path,
            name_lookup=name_lookup,
            access_available=access_ok and (
                name_lookup is not None or self.access.available),
        )

    def credentials_required(self) -> bool:
        if self._force_creds is not None:
            return self._force_creds
        if self._daily_lookup is not None:
            return False  # test / injected backend
        return not self.access.available

    def fetch_delisting_metadata(
            self, permno: int,
    ) -> Optional[CrspDelistingRow]:
        """Return delisting fields separately — never as a normal daily close."""
        if self._delist_lookup is not None:
            return self._delist_lookup(permno)
        if self.credentials_required():
            return None
        # Live WRDS/flat-file delisting pull is enabled only with access + impl.
        return None

    def fetch_history(self, identity: SecurityIdentity,
                      start: date, end: date) -> ProviderFetchResult:
        window = (start.isoformat(), end.isoformat())
        if self.credentials_required() and self._daily_lookup is None:
            return ProviderFetchResult(
                provider=self.name,
                status=ProviderStatus.CREDENTIALS_REQUIRED,
                identity=identity, window=window,
                error="CRSP/WRDS access not configured "
                      "(set WRDS_USERNAME or CRSP_DATA_DIR; see docs/CRSP_ACCESS.md)",
            )

        mapping, defer = self.identity.resolve(identity)
        if defer is not None:
            return ProviderFetchResult(
                provider=self.name, status=defer, identity=identity,
                window=window,
                provider_symbol=(str(mapping.permno)
                                 if mapping and mapping.permno else None),
                error=(mapping.status if mapping else defer.value),
            )
        assert mapping is not None and mapping.permno is not None

        rows = self._fetch_daily(mapping.permno, start, end)
        if rows is None:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.PROVIDER_ERROR,
                identity=identity, window=window,
                provider_symbol=str(mapping.permno),
                error="CRSP daily lookup failed",
            )
        if not rows:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.NO_HISTORY,
                identity=identity, window=window,
                provider_symbol=str(mapping.permno),
                error="CRSP_NO_PRICE_WINDOW",
            )

        obs, rejected = normalize_crsp_daily_rows(
            identity, mapping, rows, calendar_conn=self._calendar_conn)
        if not obs:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.NO_HISTORY,
                identity=identity, window=window,
                provider_symbol=str(mapping.permno),
                error=f"no usable DlyPrc under {CRSP_PRICE_ACCEPTANCE_RULE} "
                      f"(rejected={len(rejected)})",
            )
        # Attach delisting metadata in result error field only as structured note
        # via first observation source_metadata (not as a close).
        delist = self.fetch_delisting_metadata(mapping.permno)
        if delist is not None:
            meta = dict(obs[0].source_metadata)
            meta["delisting"] = {
                "DelistingDt": delist.delisting_dt,
                "DelDtPrc": delist.del_dt_prc,
                "DelDtPrcFlg": delist.del_dt_prc_flg,
                "DelActionType": delist.del_action_type,
                "DelStatusType": delist.del_status_type,
                "delisting_return": delist.delisting_return,
                "note": ("Delisting fields are NOT used as regular-session closes; "
                         "retained for terminal-state / survivorship research only"),
            }
            # frozen dataclass — rebuild first obs with enriched metadata
            o0 = obs[0]
            obs[0] = NormalizedEquityObservation(
                deal_id=o0.deal_id, session_date=o0.session_date, close=o0.close,
                provider=o0.provider, provider_symbol=o0.provider_symbol,
                retrieval_timestamp=o0.retrieval_timestamp,
                target_cik=o0.target_cik, target_name=o0.target_name,
                ticker=o0.ticker, exchange=o0.exchange,
                adjusted_close=o0.adjusted_close, currency=o0.currency,
                close_field_used=o0.close_field_used,
                corporate_action_note=o0.corporate_action_note,
                source_metadata=meta,
                observation_timestamp=o0.observation_timestamp,
                known_at=o0.known_at,
            )
        return ProviderFetchResult(
            provider=self.name, status=ProviderStatus.AVAILABLE,
            identity=identity, observations=obs,
            provider_symbol=str(mapping.permno), window=window,
        )

    def _fetch_daily(self, permno: int, start: date,
                     end: date) -> Optional[list[CrspDailyRow]]:
        if self._daily_lookup is not None:
            return list(self._daily_lookup(permno, start, end) or [])
        # Live backends are intentionally stubbed until credentials exist.
        # Callers with access should inject a WRDS/flat-file lookup or extend
        # this method in a follow-up PR that exercises a real connection.
        return None

    def access_report(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "credentials_required": self.credentials_required(),
            "access": self.access.as_dict(),
            "price_acceptance_rule": CRSP_PRICE_ACCEPTANCE_RULE,
            "accept_dlyprc_flags": [repr(x) for x in sorted(
                ACCEPT_DLYPRC_FLAGS, key=lambda x: str(x))],
            "reject_dlyprc_flags": sorted(REJECT_DLYPRC_FLAGS),
        }
