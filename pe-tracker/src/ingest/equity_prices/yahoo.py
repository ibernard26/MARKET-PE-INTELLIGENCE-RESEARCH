"""Yahoo Finance adapter implementing HistoricalEquityPriceProvider.

Yahoo is NOT authoritative for securities it does not cover. Delisted /
taken-private targets typically return NO_HISTORY / DELISTED_UNAVAILABLE.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from .calendar_gate import filter_session_observations
from ..security_identity.name_match import names_agree
from .schema import (
    NormalizedEquityObservation,
    ProviderFetchResult,
    ProviderStatus,
    SecurityIdentity,
)

CHART = ("https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
         "?period1={start}&period2={end}&interval=1d")
NY = ZoneInfo("America/New_York")
MIN_INTERVAL_S = 0.15
PROVIDER_NAME = "yahoo_finance_chart"
MAX_TRANSIENT_RETRIES = 2


def session_close_iso(d: date) -> str:
    aware = datetime(d.year, d.month, d.day, 16, 0, 0, tzinfo=NY)
    return aware.replace(tzinfo=None).isoformat()


def yahoo_issuer_name(meta: Optional[dict]) -> Optional[str]:
    """Chart-meta issuer name. Never inferred from the close path."""
    meta = meta or {}
    for key in ("longName", "shortName", "longname", "shortname"):
        val = meta.get(key)
        if val:
            return str(val)
    return None


def yahoo_identity_problems(meta: Optional[dict], identity: SecurityIdentity,
                            window_start: date) -> list[str]:
    """Reconstructable Yahoo issuer check (name + first-trade vs announcement).

    Proof C maps a historical ticker. It does not prove that Yahoo's current
    series for that ticker is the SEC target — tickers get reused.
    Closes are not an input. Empty list = passed.
    """
    problems = []
    name = yahoo_issuer_name(meta)
    if not names_agree(name, identity.target_name):
        problems.append(
            f"yahoo issuer name {name!r} does not agree with "
            f"SEC target {identity.target_name!r}")
    ann = identity.announcement_date or window_start.isoformat()
    first = (meta or {}).get("firstTradeDate")
    first_s = ""
    if first not in (None, "", 0):
        try:
            first_s = datetime.fromtimestamp(int(first), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OSError):
            first_s = ""
    if not first_s or first_s > ann:
        problems.append(
            f"yahoo firstTradeDate {first_s or '?'} does not cover announcement {ann}")
    return problems


class YahooEquityPriceProvider:
    """HistoricalEquityPriceProvider over Yahoo's public chart API."""

    name = PROVIDER_NAME

    def __init__(self, fetch_json: Optional[Callable[[str], dict]] = None,
                 calendar_conn=None):
        self._fetch = fetch_json or self._http_json
        self._last = 0.0
        self._calendar_conn = calendar_conn

    def credentials_required(self) -> bool:
        return False

    def _http_json(self, url: str) -> dict:
        import requests
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            r = requests.get(url, headers={
                "User-Agent": ("Mozilla/5.0 (compatible; "
                               "MARKET-PE-INTELLIGENCE/1.0; research)"),
                "Accept": "application/json",
            }, timeout=30)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise _Transient(str(exc)) from exc
        if r.status_code in (429, 500, 502, 503, 504):
            raise _Transient(f"Yahoo HTTP {r.status_code}")
        if r.status_code in (400, 404):
            return {"chart": {"result": None,
                              "error": {"code": str(r.status_code)}}}
        if r.status_code != 200:
            raise _ProviderError(f"Yahoo HTTP {r.status_code} for {url}")
        return r.json()

    def fetch_history(self, identity: SecurityIdentity,
                      start: date, end: date) -> ProviderFetchResult:
        if not identity.resolved():
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.IDENTITY_UNRESOLVED,
                identity=identity, window=(start.isoformat(), end.isoformat()))
        symbol = identity.ticker
        assert symbol
        last_err = None
        meta: dict = {}
        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            try:
                series, http_code, meta = self._daily_closes(symbol, start, end)
                break
            except _Transient as exc:
                last_err = str(exc)
                if attempt < MAX_TRANSIENT_RETRIES:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return ProviderFetchResult(
                    provider=self.name, status=ProviderStatus.TRANSIENT_FAILURE,
                    identity=identity, error=last_err, provider_symbol=symbol,
                    window=(start.isoformat(), end.isoformat()))
            except _ProviderError as exc:
                return ProviderFetchResult(
                    provider=self.name, status=ProviderStatus.PROVIDER_ERROR,
                    identity=identity, error=str(exc), provider_symbol=symbol,
                    window=(start.isoformat(), end.isoformat()))
        else:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.TRANSIENT_FAILURE,
                identity=identity, error=last_err, provider_symbol=symbol,
                window=(start.isoformat(), end.isoformat()))

        if not series:
            # 400/404 → delisted/unavailable; empty result → no history
            status = (ProviderStatus.DELISTED_UNAVAILABLE
                      if http_code in ("400", "404")
                      else ProviderStatus.NO_HISTORY)
            return ProviderFetchResult(
                provider=self.name, status=status, identity=identity,
                provider_symbol=symbol,
                window=(start.isoformat(), end.isoformat()))

        id_problems = yahoo_identity_problems(meta, identity, start)
        name = yahoo_issuer_name(meta)
        # Chart meta with an issuer name is reconstructable evidence. A name
        # that does not agree with the SEC target is ticker reuse — do not
        # attribute those closes. Empty meta cannot prove identity; those
        # observations stay unverified and are not canonically admitted on
        # Proof C alone.
        if name and id_problems:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.IDENTITY_AMBIGUOUS,
                identity=identity, error="; ".join(id_problems),
                provider_symbol=symbol, identity_verified=False,
                window=(start.isoformat(), end.isoformat()))
        verified = bool(name) and not id_problems

        retrieved = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        obs = []
        for d, close, adj in series:
            ts = session_close_iso(d)
            obs.append(NormalizedEquityObservation(
                deal_id=identity.deal_id,
                session_date=d.isoformat(),
                close=close,
                adjusted_close=adj,
                provider=self.name,
                provider_symbol=symbol,
                retrieval_timestamp=retrieved,
                target_cik=identity.target_cik,
                target_name=identity.target_name,
                ticker=symbol,
                exchange=identity.exchange,
                currency="USD",
                close_field_used="close",
                corporate_action_note=(
                    "adjusted_close preserved when Yahoo supplies it; "
                    "spread_stress_v1 uses unadjusted close"
                ),
                source_metadata={
                    "ticker_basis": identity.ticker_basis,
                    "identity_source": identity.identity_source,
                },
                observation_timestamp=ts,
                known_at=ts,
            ))
        ok, _bad = filter_session_observations(obs, conn=self._calendar_conn)
        if not ok:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.NO_HISTORY,
                identity=identity, provider_symbol=symbol,
                window=(start.isoformat(), end.isoformat()),
                error="all prints rejected by session calendar gate")
        return ProviderFetchResult(
            provider=self.name, status=ProviderStatus.AVAILABLE,
            identity=identity, observations=ok, provider_symbol=symbol,
            identity_verified=verified,
            window=(start.isoformat(), end.isoformat()))

    def _daily_closes(self, symbol: str, start: date, end: date):
        p1 = int(datetime(start.year, start.month, start.day,
                          tzinfo=timezone.utc).timestamp()) - 86400
        p2 = int(datetime(end.year, end.month, end.day,
                          tzinfo=timezone.utc).timestamp()) + 2 * 86400
        url = CHART.format(symbol=symbol, start=p1, end=p2)
        payload = self._fetch(url)
        err = ((payload.get("chart") or {}).get("error") or {})
        http_code = str(err.get("code") or "")
        res = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not res:
            return [], http_code, {}
        meta = dict(res.get("meta") or {})
        ts = res.get("timestamp") or []
        quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        adj_list = ((res.get("indicators") or {}).get("adjclose") or [{}])
        adjs = (adj_list[0].get("adjclose") if adj_list else None) or [None] * len(closes)
        out = []
        for t, c, a in zip(ts, closes, adjs):
            if c is None:
                continue
            d = datetime.fromtimestamp(int(t), tz=NY).date()
            if start <= d <= end:
                out.append((d, float(c), float(a) if a is not None else None))
        return out, http_code, meta


class _Transient(RuntimeError):
    pass


class _ProviderError(RuntimeError):
    pass
