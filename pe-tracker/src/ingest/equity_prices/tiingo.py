"""Tiingo Equity Price Provider — primary free historical EOD source.

Credentials: TIINGO_API_TOKEN (alias TIINGO_API_KEY accepted). Never log values.
Does not overwrite close with adjClose. No interpolation / forward-fill.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from .calendar_gate import filter_session_observations
from .schema import (
    NormalizedEquityObservation,
    ProviderFetchResult,
    ProviderStatus,
    SecurityIdentity,
)

PROVIDER_NAME = "tiingo"
ENV_TOKEN = "TIINGO_API_TOKEN"
ENV_TOKEN_ALIAS = "TIINGO_API_KEY"
NY = ZoneInfo("America/New_York")
META_URL = "https://api.tiingo.com/tiingo/daily/{symbol}"
EOD_URL = ("https://api.tiingo.com/tiingo/daily/{symbol}/prices"
           "?startDate={start}&endDate={end}&format=json")
MIN_INTERVAL_S = 0.2
MAX_TRANSIENT_RETRIES = 2


def tiingo_api_token_present(env: Optional[dict] = None) -> bool:
    e = env if env is not None else os.environ
    return bool((e.get(ENV_TOKEN) or e.get(ENV_TOKEN_ALIAS) or "").strip())


def _token_from_env(env: Optional[dict] = None) -> str:
    e = env if env is not None else os.environ
    return (e.get(ENV_TOKEN) or e.get(ENV_TOKEN_ALIAS) or "").strip()


def session_close_iso(d: date) -> str:
    aware = datetime(d.year, d.month, d.day, 16, 0, 0, tzinfo=NY)
    return aware.replace(tzinfo=None).isoformat()


class TiingoEquityPriceProvider:
    """HistoricalEquityPriceProvider over Tiingo daily EOD."""

    name = PROVIDER_NAME

    def __init__(
            self,
            token: Optional[str] = None,
            fetch_json: Optional[Callable[[str, dict], tuple[int, Any]]] = None,
            calendar_conn=None,
            env: Optional[dict] = None,
            min_interval_s: float = MIN_INTERVAL_S,
    ):
        self._token = token if token is not None else _token_from_env(env)
        self._fetch = fetch_json or self._http_json
        self._calendar_conn = calendar_conn
        self._min_interval = min_interval_s
        self._last = 0.0

    def credentials_required(self) -> bool:
        return not bool(self._token)

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Token {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _http_json(self, url: str, headers: dict) -> tuple[int, Any]:
        import requests
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            r = requests.get(url, headers=headers, timeout=30)
        except (requests.Timeout, requests.ConnectionError):
            return 599, {"detail": "transient_network_error"}
        try:
            data = r.json()
        except Exception:
            data = {"detail": "non_json_response"}
        return r.status_code, data

    def fetch_metadata(self, symbol: str) -> tuple[ProviderStatus, dict]:
        if self.credentials_required():
            return ProviderStatus.CREDENTIALS_REQUIRED, {}
        url = META_URL.format(symbol=symbol)
        status, data = self._fetch(url, self._auth_headers())
        if status in (401, 403):
            return ProviderStatus.PROVIDER_ERROR, {"http_status": status,
                                                   "error": "AUTH_FAILURE"}
        if status == 404:
            return ProviderStatus.SYMBOL_NOT_FOUND, {"http_status": status}
        if status in (429, 500, 502, 503, 504, 599):
            return ProviderStatus.TRANSIENT_FAILURE, {"http_status": status}
        if status != 200 or not isinstance(data, dict):
            return ProviderStatus.PROVIDER_ERROR, {"http_status": status}
        return ProviderStatus.AVAILABLE, data

    def fetch_history(self, identity: SecurityIdentity,
                      start: date, end: date) -> ProviderFetchResult:
        window = (start.isoformat(), end.isoformat())
        if self.credentials_required():
            return ProviderFetchResult(
                provider=self.name,
                status=ProviderStatus.CREDENTIALS_REQUIRED,
                identity=identity, window=window,
                error=f"{ENV_TOKEN} not set",
            )
        if not identity.resolved():
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.IDENTITY_UNRESOLVED,
                identity=identity, window=window,
            )
        symbol = identity.ticker
        assert symbol

        meta_status, meta = self.fetch_metadata(symbol)
        if meta_status == ProviderStatus.SYMBOL_NOT_FOUND:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.SYMBOL_NOT_FOUND,
                identity=identity, provider_symbol=symbol, window=window,
                error="TIINGO_NO_SYMBOL",
            )
        if meta_status == ProviderStatus.TRANSIENT_FAILURE:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.TRANSIENT_FAILURE,
                identity=identity, provider_symbol=symbol, window=window,
                error=f"Tiingo meta HTTP {meta.get('http_status')}",
            )
        if meta_status != ProviderStatus.AVAILABLE:
            return ProviderFetchResult(
                provider=self.name, status=meta_status,
                identity=identity, provider_symbol=symbol, window=window,
                error=str(meta.get("error") or meta.get("http_status")),
            )

        # Soft identity consistency check — do not invent; may defer later upstream
        meta_ticker = (meta.get("ticker") or symbol).upper()
        rows, err_status, err = self._fetch_eod(symbol, start, end)
        if err_status is not None:
            return ProviderFetchResult(
                provider=self.name, status=err_status, identity=identity,
                provider_symbol=symbol, window=window, error=err,
            )
        if not rows:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.NO_HISTORY,
                identity=identity, provider_symbol=symbol, window=window,
                error="TIINGO_NO_HISTORY",
            )

        retrieved = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        obs: list[NormalizedEquityObservation] = []
        for row in rows:
            sd = str(row.get("date") or "")[:10]
            if not sd:
                continue
            close = row.get("close")
            if close is None:
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if not (close_f > 0 and close_f == close_f):
                continue
            adj = row.get("adjClose")
            adj_f = float(adj) if adj is not None else None
            if adj_f is not None and not (adj_f > 0 and adj_f == adj_f):
                adj_f = None
            try:
                d = date.fromisoformat(sd)
            except ValueError:
                continue
            if not (start <= d <= end):
                continue
            ts = session_close_iso(d)
            obs.append(NormalizedEquityObservation(
                deal_id=identity.deal_id,
                session_date=sd,
                close=close_f,
                adjusted_close=adj_f,
                provider=self.name,
                provider_symbol=meta_ticker,
                retrieval_timestamp=retrieved,
                target_cik=identity.target_cik,
                target_name=identity.target_name,
                ticker=symbol,
                exchange=identity.exchange,
                currency="USD",
                close_field_used="close",
                corporate_action_note=(
                    "tiingo: raw close used for spread_stress_v1; "
                    "adjClose/divCash/splitFactor preserved in source_metadata only"
                ),
                source_metadata={
                    "tiingo_symbol": meta_ticker,
                    "tiingo_name": meta.get("name"),
                    "tiingo_exchangeCode": meta.get("exchangeCode"),
                    "tiingo_startDate": meta.get("startDate"),
                    "tiingo_endDate": meta.get("endDate"),
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "volume": row.get("volume"),
                    "adjOpen": row.get("adjOpen"),
                    "adjHigh": row.get("adjHigh"),
                    "adjLow": row.get("adjLow"),
                    "adjClose": row.get("adjClose"),
                    "adjVolume": row.get("adjVolume"),
                    "divCash": row.get("divCash"),
                    "splitFactor": row.get("splitFactor"),
                    "identity_source": identity.identity_source,
                    "ticker_basis": identity.ticker_basis,
                },
                observation_timestamp=ts,
                known_at=ts,
            ))
        ok, _bad = filter_session_observations(obs, conn=self._calendar_conn)
        if not ok:
            return ProviderFetchResult(
                provider=self.name, status=ProviderStatus.NO_HISTORY,
                identity=identity, provider_symbol=symbol, window=window,
                error="all prints rejected by session calendar gate",
            )
        return ProviderFetchResult(
            provider=self.name, status=ProviderStatus.AVAILABLE,
            identity=identity, observations=ok, provider_symbol=symbol,
            window=window,
        )

    def _fetch_eod(self, symbol: str, start: date, end: date):
        url = EOD_URL.format(
            symbol=symbol, start=start.isoformat(), end=end.isoformat())
        last_err = None
        for attempt in range(MAX_TRANSIENT_RETRIES + 1):
            status, data = self._fetch(url, self._auth_headers())
            if status in (401, 403):
                return None, ProviderStatus.PROVIDER_ERROR, "AUTH_FAILURE"
            if status == 404:
                return None, ProviderStatus.SYMBOL_NOT_FOUND, "TIINGO_NO_SYMBOL"
            if status in (429, 500, 502, 503, 504, 599):
                last_err = f"Tiingo EOD HTTP {status}"
                if attempt < MAX_TRANSIENT_RETRIES:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                return None, ProviderStatus.TRANSIENT_FAILURE, last_err
            if status != 200:
                return None, ProviderStatus.PROVIDER_ERROR, f"Tiingo EOD HTTP {status}"
            if not isinstance(data, list):
                return None, ProviderStatus.PROVIDER_ERROR, "unexpected_eod_payload"
            return data, None, None
        return None, ProviderStatus.TRANSIENT_FAILURE, last_err
