"""OpenFIGI security-identity resolver.

OpenFIGI is an IDENTITY provider, not a price provider. Never log or persist
API key values. Deterministic disk cache for successful mappings.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = ROOT / "data" / "cache" / "openfigi"
OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
ENV_KEY = "OPENFIGI_API_KEY"


class OpenFIGIMappingStatus(str, Enum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    INVALID_REQUEST = "INVALID_REQUEST"
    AUTH_FAILURE = "AUTH_FAILURE"
    CREDENTIALS_REQUIRED = "CREDENTIALS_REQUIRED"


def openfigi_api_key_present(env: Optional[dict] = None) -> bool:
    e = env if env is not None else os.environ
    return bool((e.get(ENV_KEY) or "").strip())


def _redact_headers(headers: dict) -> dict:
    out = dict(headers)
    if "X-OPENFIGI-APIKEY" in out:
        out["X-OPENFIGI-APIKEY"] = "***"
    return out


@dataclass
class OpenFIGIIdentity:
    deal_id: str
    target_cik: Optional[int] = None
    target_name: Optional[str] = None
    announcement_date: Optional[str] = None
    historical_ticker: Optional[str] = None
    historical_exchange: Optional[str] = None
    identifier_type: Optional[str] = None
    identifier_value: Optional[str] = None
    figi: Optional[str] = None
    composite_figi: Optional[str] = None
    share_class_figi: Optional[str] = None
    mapped_name: Optional[str] = None
    mapped_exchange: Optional[str] = None
    security_type: Optional[str] = None
    market_sector: Optional[str] = None
    mapping_status: str = OpenFIGIMappingStatus.NO_MATCH.value
    retrieved_at: Optional[str] = None
    source: str = "openfigi"
    candidates: list[dict] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cache_key(payload: list[dict]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class OpenFIGISecurityIdentityResolver:
    """Map ticker (+ optional exchCode / name hints) → FIGI identity."""

    def __init__(
            self,
            api_key: Optional[str] = None,
            cache_dir: Path = DEFAULT_CACHE_DIR,
            post_json: Optional[Callable[[str, dict, list], tuple[int, Any]]] = None,
            min_interval_s: float = 0.3,
            env: Optional[dict] = None,
    ):
        e = env if env is not None else os.environ
        # Prefer explicit inject for tests; else env. Never log the value.
        self._api_key = api_key if api_key is not None else (e.get(ENV_KEY) or "").strip()
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._post = post_json or self._http_post
        self._min_interval = min_interval_s
        self._last = 0.0

    def credentials_required(self) -> bool:
        return not bool(self._api_key)

    def _http_post(self, url: str, headers: dict, body: list) -> tuple[int, Any]:
        import requests
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            r = requests.post(url, headers=headers, json=body, timeout=30)
        except (requests.Timeout, requests.ConnectionError) as exc:
            return 599, {"error": type(exc).__name__}
        try:
            data = r.json()
        except Exception:
            data = {"error": "non_json_response", "status_code": r.status_code}
        return r.status_code, data

    def resolve_deal(
            self,
            deal: dict,
            *,
            ticker: Optional[str] = None,
            exchange: Optional[str] = None,
            id_type: str = "TICKER",
            use_cache: bool = True,
    ) -> OpenFIGIIdentity:
        deal_id = deal["deal_id"]
        cik = deal.get("target_cik")
        cik_i = int(cik) if cik is not None else None
        name = deal.get("target")
        ann = (deal.get("announcement_timestamp") or "")[:10] or None
        t = (ticker or "").strip().upper() or None
        exch = (exchange or "").strip() or None

        base = OpenFIGIIdentity(
            deal_id=deal_id, target_cik=cik_i, target_name=name,
            announcement_date=ann, historical_ticker=t,
            historical_exchange=exch, identifier_type=id_type,
            identifier_value=t,
            retrieved_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
        if self.credentials_required():
            base.mapping_status = OpenFIGIMappingStatus.CREDENTIALS_REQUIRED.value
            base.error = f"{ENV_KEY} not set"
            return base
        if not t:
            base.mapping_status = OpenFIGIMappingStatus.INVALID_REQUEST.value
            base.error = "historical_ticker required"
            return base

        job: dict[str, Any] = {"idType": id_type, "idValue": t}
        if exch:
            job["exchCode"] = exch
        # Optional name filter helps against ticker reuse when OpenFIGI supports it
        # via query; keep marketSecDes US Equity bias when ticker-only.
        job.setdefault("marketSecDes", "Equity")
        payload = [job]

        if use_cache:
            cached = self._read_cache(payload)
            if cached is not None:
                return self._normalize(base, cached, from_cache=True)

        headers = {
            "Content-Type": "application/json",
            "X-OPENFIGI-APIKEY": self._api_key,
        }
        # Never include raw headers in raised messages
        status, data = self._post(OPENFIGI_MAPPING_URL, headers, payload)
        if status in (401, 403):
            base.mapping_status = OpenFIGIMappingStatus.AUTH_FAILURE.value
            base.error = f"OpenFIGI HTTP {status}"
            return base
        if status == 429:
            base.mapping_status = OpenFIGIMappingStatus.RATE_LIMITED.value
            base.error = "OpenFIGI HTTP 429"
            return base
        if status in (500, 502, 503, 504, 599):
            base.mapping_status = OpenFIGIMappingStatus.TRANSIENT_FAILURE.value
            base.error = f"OpenFIGI HTTP {status}"
            return base
        if status != 200:
            base.mapping_status = OpenFIGIMappingStatus.INVALID_REQUEST.value
            base.error = f"OpenFIGI HTTP {status}"
            return base

        if use_cache:
            self._write_cache(payload, data)
        return self._normalize(base, data, from_cache=False)

    def _normalize(self, base: OpenFIGIIdentity, data: Any,
                   from_cache: bool) -> OpenFIGIIdentity:
        rows: list[dict] = []
        if isinstance(data, list) and data:
            block = data[0] or {}
            if block.get("error"):
                # OpenFIGI returns {"error":"No identifier found."}
                base.mapping_status = OpenFIGIMappingStatus.NO_MATCH.value
                base.error = str(block.get("error"))
                return base
            rows = list(block.get("data") or [])
        elif isinstance(data, dict) and data.get("error"):
            base.mapping_status = OpenFIGIMappingStatus.INVALID_REQUEST.value
            base.error = "openfigi_error"
            return base

        # Filter to equity-like US candidates when possible
        equities = [r for r in rows if _is_plausible_equity(r)]
        pool = equities or rows
        # Further filter by issuer name overlap when we have a target name
        if base.target_name and len(pool) > 1:
            narrowed = [r for r in pool if _name_overlap(base.target_name, r.get("name"))]
            if narrowed:
                pool = narrowed

        uniq_figi = {r.get("figi") for r in pool if r.get("figi")}
        base.candidates = [
            {k: r.get(k) for k in (
                "figi", "compositeFIGI", "shareClassFIGI", "name",
                "exchCode", "ticker", "securityType", "marketSector",
            )} for r in pool[:10]
        ]
        if len(uniq_figi) == 0:
            base.mapping_status = OpenFIGIMappingStatus.NO_MATCH.value
            return base
        if len(uniq_figi) > 1:
            base.mapping_status = OpenFIGIMappingStatus.AMBIGUOUS.value
            base.error = "DEFER_SECURITY_IDENTITY_AMBIGUOUS"
            return base

        hit = next(r for r in pool if r.get("figi") in uniq_figi)
        base.figi = hit.get("figi")
        base.composite_figi = hit.get("compositeFIGI")
        base.share_class_figi = hit.get("shareClassFIGI")
        base.mapped_name = hit.get("name")
        base.mapped_exchange = hit.get("exchCode")
        base.security_type = hit.get("securityType")
        base.market_sector = hit.get("marketSector")
        if hit.get("ticker"):
            base.historical_ticker = str(hit.get("ticker")).upper()
        base.mapping_status = OpenFIGIMappingStatus.MATCHED.value
        if from_cache:
            base.candidates = base.candidates  # already set
        return base

    def _cache_path(self, payload: list[dict]) -> Path:
        return self.cache_dir / f"{_cache_key(payload)}.json"

    def _read_cache(self, payload: list[dict]) -> Optional[Any]:
        p = self._cache_path(payload)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            return None

    def _write_cache(self, payload: list[dict], data: Any) -> None:
        p = self._cache_path(payload)
        # Never write API keys into cache files
        p.write_text(json.dumps(data, indent=2) + "\n")


def _is_plausible_equity(row: dict) -> bool:
    sector = (row.get("marketSector") or "").lower()
    st = (row.get("securityType") or "").lower()
    if sector and sector not in ("equity",):
        return False
    if "adr" in st and "common" not in st:
        # keep ADRs — often valid for US-listed targets
        return True
    return True


def _name_overlap(target: str, mapped: Optional[str]) -> bool:
    if not mapped:
        return False
    def toks(s: str) -> set[str]:
        stop = {"INC", "CORP", "CORPORATION", "LTD", "LLC", "CO", "THE", "AND", "PLC"}
        parts = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in s.upper()).split()
        return {p for p in parts if p not in stop and len(p) > 1}
    a, b = toks(target), toks(mapped)
    if not a or not b:
        return False
    return len(a & b) >= 1
