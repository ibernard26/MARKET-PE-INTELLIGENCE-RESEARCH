"""Yahoo Finance daily equity closes for target-price paths.

SOURCE DISCIPLINE
-----------------
* Prices come from Yahoo's public chart API (query2.finance.yahoo.com).
  This is a research fetch, not a licensed CRSP/Bloomberg feed. Every print
  carries source_name='yahoo_finance_chart' and a reproducible source_identifier.
* Delisted / taken-private tickers often return NO history from this endpoint.
  Gaps stay gaps — nothing is fabricated or interpolated.
* known_at is set to the session regular close (16:00 America/New_York calendar
  date of the print) under the exchange-session-close rule: a daily close print
  was publicly knowable at that session's close. observation_timestamp uses the
  same instant (valid time = session close).

Ticker resolution (in order):
  1. reviewed map row in data/target_ticker_map.json (preferred)
  2. SEC company_tickers.json match on target_cik (current filers only)
  3. deal_id convention DEAL-{TICKER}-… (documented heuristic; quarantined if
     Yahoo returns no series for the deal window)
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional
from zoneinfo import ZoneInfo

from ..historical import SourceRef
from ..target_prices import TargetPricePrint

ROOT = Path(__file__).resolve().parents[3]  # pe-tracker/
DEFAULT_DEAL_MANIFEST = ROOT / "data" / "sec_deal_manifest.json"
DEFAULT_TICKER_MAP = ROOT / "data" / "target_ticker_map.json"
CHART = ("https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
         "?period1={start}&period2={end}&interval=1d")
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
NY = ZoneInfo("America/New_York")
MIN_INTERVAL_S = 0.15


class YahooEquityError(RuntimeError):
    pass


def session_close_iso(d: date) -> str:
    """NYSE regular-session close instant as naive ISO (store convention)."""
    aware = datetime(d.year, d.month, d.day, 16, 0, 0, tzinfo=NY)
    # Store naive local-session wall time, consistent with EDGAR caveat style.
    return aware.replace(tzinfo=None).isoformat()


def deal_id_ticker(deal_id: str) -> Optional[str]:
    """Extract TICKER from DEAL-{TICKER}-… convention used in this corpus."""
    parts = (deal_id or "").split("-")
    if len(parts) < 3 or parts[0] != "DEAL":
        return None
    t = parts[1].strip().upper()
    return t or None


class TickerResolver:
    """Resolve target_cik / deal_id → ticker with provenance."""

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
            raise YahooEquityError(
                "SEC_USER_AGENT is not set (required for company_tickers.json)")
        headers = {"User-Agent": self.user_agent or "MARKET-PE-INTELLIGENCE research",
                   "Accept": "application/json"}
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            raise YahooEquityError(f"HTTP {r.status_code} for {url}")
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

    def resolve(self, deal_id: str, target_cik: Optional[int]) -> dict:
        """Return {ticker, basis} or {ticker: None, basis, reason}."""
        rev = self._reviewed.get(deal_id)
        if rev:
            return {"ticker": rev["ticker"].upper(),
                    "basis": rev.get("basis", "reviewed_map"),
                    "source_identifier": rev.get("source_identifier")}
        if target_cik is not None:
            t = self._sec_map().get(int(target_cik))
            if t:
                return {"ticker": t, "basis": "sec_company_tickers",
                        "source_identifier": f"sec:company_tickers.json:cik={int(target_cik)}"}
        t = deal_id_ticker(deal_id)
        if t:
            return {"ticker": t, "basis": "deal_id_convention",
                    "source_identifier": f"deal_id:{deal_id}"}
        return {"ticker": None, "basis": None,
                "reason": "no_ticker_resolution"}


class YahooChartClient:
    """Rate-limited Yahoo chart client (injectable for tests)."""

    def __init__(self, fetch_json: Optional[Callable[[str], dict]] = None):
        self._fetch = fetch_json or self._http_json
        self._last = 0.0

    def _http_json(self, url: str) -> dict:
        import requests
        wait = MIN_INTERVAL_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; MARKET-PE-INTELLIGENCE/1.0; research)",
            "Accept": "application/json",
        }, timeout=30)
        # 404/400 = delisted, recycled ticker, or no series for the window.
        # Treat as empty history (gap), not a hard infrastructure failure.
        if r.status_code in (400, 404):
            return {"chart": {"result": None,
                              "error": {"code": str(r.status_code)}}}
        if r.status_code != 200:
            raise YahooEquityError(f"Yahoo HTTP {r.status_code} for {url}")
        return r.json()

    def daily_closes(self, symbol: str, start: date, end: date) -> list[tuple[date, float]]:
        """Return [(session_date, close), …] with null closes dropped."""
        # Yahoo period2 is exclusive-ish; pad one day.
        p1 = int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()) - 86400
        p2 = int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 2 * 86400
        url = CHART.format(symbol=symbol, start=p1, end=p2)
        payload = self._fetch(url)
        res = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not res:
            return []
        ts = res.get("timestamp") or []
        closes = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        out = []
        for t, c in zip(ts, closes):
            if c is None:
                continue
            # Yahoo timestamps are session open in exchange tz; convert to NY date.
            d = datetime.fromtimestamp(int(t), tz=NY).date()
            if start <= d <= end:
                out.append((d, float(c)))
        return out


def prints_for_deal(deal: dict, resolver: TickerResolver,
                    client: YahooChartClient,
                    pad_days: int = 3) -> dict:
    """Build TargetPricePrint list for one SEC manifest deal. Never fabricates."""
    deal_id = deal["deal_id"]
    cik = deal.get("target_cik")
    resolved = resolver.resolve(deal_id, int(cik) if cik is not None else None)
    ticker = resolved.get("ticker")
    if not ticker:
        return {"deal_id": deal_id, "accepted": [], "status": "no_ticker",
                "resolved": resolved}
    ann = date.fromisoformat(deal["announcement_timestamp"][:10])
    res_s = deal.get("resolution_timestamp") or deal["announcement_timestamp"]
    res = date.fromisoformat(res_s[:10])
    start = ann - timedelta(days=pad_days)
    end = res + timedelta(days=pad_days)
    try:
        series = client.daily_closes(ticker, start, end)
    except YahooEquityError as exc:
        return {"deal_id": deal_id, "accepted": [], "status": "fetch_error",
                "ticker": ticker, "error": str(exc), "resolved": resolved}
    if not series:
        return {"deal_id": deal_id, "accepted": [], "status": "no_price_history",
                "ticker": ticker, "resolved": resolved,
                "window": [start.isoformat(), end.isoformat()]}
    prints = []
    for d, px in series:
        # Restrict to announce..resolution inclusive for the stress path
        if d < ann or d > res:
            continue
        ts = session_close_iso(d)
        ref = SourceRef(
            source_name="yahoo_finance_chart",
            source_identifier=(
                f"yahoo_finance_chart:{ticker}@{d.isoformat()}"
                f"?basis={resolved.get('basis')}"
            ),
            known_at=ts,
            source_timestamp=ts,
            company_identifier=f"ticker:{ticker}" + (
                f"|cik:{int(cik)}" if cik is not None else ""),
        )
        prints.append(TargetPricePrint(
            deal_id=deal_id, observation_timestamp=ts,
            target_price=px, source=ref))
    return {"deal_id": deal_id, "accepted": prints, "status": "ok",
            "ticker": ticker, "n_prints": len(prints), "resolved": resolved}


def fetch_manifest_prints(
        deal_manifest: Path = DEFAULT_DEAL_MANIFEST,
        ticker_map: Path = DEFAULT_TICKER_MAP,
        user_agent: Optional[str] = None,
        client: Optional[YahooChartClient] = None,
        resolver: Optional[TickerResolver] = None,
) -> dict:
    """Fetch real target prints for every SEC manifest deal; return audit + prints."""
    deals = json.loads(Path(deal_manifest).read_text())["deals"]
    resolver = resolver or TickerResolver(map_path=ticker_map, user_agent=user_agent)
    client = client or YahooChartClient()
    all_prints: list[TargetPricePrint] = []
    audit = []
    for d in deals:
        r = prints_for_deal(d, resolver, client)
        audit.append({k: v for k, v in r.items() if k != "accepted"})
        all_prints.extend(r["accepted"])
    n_ok = sum(1 for a in audit if a.get("status") == "ok" and a.get("n_prints", 0) >= 3)
    return {
        "provider": "yahoo_finance_chart",
        "n_deals": len(deals),
        "n_prints": len(all_prints),
        "n_deals_with_ge3_prints": n_ok,
        "audit": audit,
        "prints": all_prints,
    }


def write_price_manifest(prints: Iterable[TargetPricePrint],
                         path: Path,
                         meta: Optional[dict] = None) -> Path:
    """Serialize fetched prints to the reviewed target_price_manifest schema."""
    path = Path(path)
    rows = []
    for p in prints:
        rows.append({
            "deal_id": p.deal_id,
            "observation_timestamp": p.observation_timestamp,
            "target_price": p.target_price,
            "source_name": p.source.source_name,
            "source_identifier": p.source.source_identifier,
            "known_at": p.source.known_at,
            "source_timestamp": p.source.source_timestamp,
            "company_identifier": p.source.company_identifier,
        })
    doc = {
        "schema_version": 1,
        "_doc": (
            "Longitudinal target-price prints for spread_stress_v1. "
            "Populated from yahoo_finance_chart for deals with accessible history. "
            "Never invent prices. Delisted/unavailable tickers are omitted."
        ),
        "meta": meta or {},
        "prints": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path
