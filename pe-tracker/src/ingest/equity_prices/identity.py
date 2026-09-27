"""Security-identity resolution — separate from price retrieval.

Never assign an acquirer's ticker to the target. Never assign a modern reused
ticker to an older issuer without evidence. Uncertain identity → defer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Optional

from .schema import ProviderStatus, SecurityIdentity

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TICKER_MAP = ROOT / "data" / "target_ticker_map.json"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"


def deal_id_ticker(deal_id: str) -> Optional[str]:
    """Extract TICKER from DEAL-{TICKER}-… corpus convention."""
    parts = (deal_id or "").split("-")
    if len(parts) < 3 or parts[0] != "DEAL":
        return None
    t = parts[1].strip().upper()
    return t or None


class SecurityIdentityResolver:
    """Resolve deal → SecurityIdentity with explicit basis / deferral."""

    def __init__(self, map_path: Path = DEFAULT_TICKER_MAP,
                 user_agent: Optional[str] = None,
                 fetch_json: Optional[Callable[[str], dict]] = None):
        self.map_path = Path(map_path)
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT", "")
        self._fetch = fetch_json or self._http_json
        self._sec: Optional[dict[int, str]] = None
        self._reviewed = self._load_reviewed()

    def _http_json(self, url: str) -> dict:
        import requests
        if "sec.gov" in url and not self.user_agent:
            raise RuntimeError(
                "SEC_USER_AGENT is not set (required for company_tickers.json)")
        r = requests.get(url, headers={
            "User-Agent": self.user_agent or "MARKET-PE-INTELLIGENCE research",
            "Accept": "application/json",
        }, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} for {url}")
        return r.json()

    def _load_reviewed(self) -> dict[str, dict]:
        if not self.map_path.exists():
            return {}
        data = json.loads(self.map_path.read_text())
        return {row["deal_id"]: row for row in data.get("tickers") or []
                if row.get("deal_id") and row.get("ticker")}

    def _sec_map(self) -> dict[int, str]:
        if self._sec is None:
            raw = self._fetch(SEC_TICKERS)
            self._sec = {int(v["cik_str"]): str(v["ticker"]).upper()
                         for v in raw.values()}
        return self._sec

    def resolve(self, deal: dict) -> tuple[SecurityIdentity, Optional[ProviderStatus]]:
        """Return (identity, defer_status). defer_status is set when unresolved/ambiguous."""
        deal_id = deal["deal_id"]
        cik = deal.get("target_cik")
        cik_i = int(cik) if cik is not None else None
        name = deal.get("target")
        ann = (deal.get("announcement_timestamp") or "")[:10] or None
        res = (deal.get("resolution_timestamp") or "")[:10] or None

        rev = self._reviewed.get(deal_id)
        if rev:
            ident = SecurityIdentity(
                deal_id=deal_id, target_cik=cik_i, target_name=name,
                ticker=rev["ticker"].upper(),
                exchange=rev.get("exchange"),
                ticker_basis=rev.get("basis", "reviewed_map"),
                announcement_date=ann, resolution_date=res,
                identity_source=rev.get("source_identifier") or "reviewed_map",
            )
            return ident, None

        if cik_i is not None:
            try:
                t = self._sec_map().get(cik_i)
            except Exception:
                t = None
            if t:
                ident = SecurityIdentity(
                    deal_id=deal_id, target_cik=cik_i, target_name=name,
                    ticker=t, ticker_basis="sec_company_tickers",
                    announcement_date=ann, resolution_date=res,
                    identity_source=f"sec:company_tickers.json:cik={cik_i}",
                )
                return ident, None

        t = deal_id_ticker(deal_id)
        if t:
            # Heuristic — usable but weaker than reviewed/SEC current map.
            ident = SecurityIdentity(
                deal_id=deal_id, target_cik=cik_i, target_name=name,
                ticker=t, ticker_basis="deal_id_convention",
                announcement_date=ann, resolution_date=res,
                identity_source=f"deal_id:{deal_id}",
                notes=("ticker from DEAL-{TICKER}-… convention; "
                       "may be wrong for reused symbols",),
            )
            return ident, None

        ident = SecurityIdentity(
            deal_id=deal_id, target_cik=cik_i, target_name=name,
            announcement_date=ann, resolution_date=res,
        )
        return ident, ProviderStatus.IDENTITY_UNRESOLVED
