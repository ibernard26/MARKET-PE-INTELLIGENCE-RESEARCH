#!/usr/bin/env python3
"""Full-corpus OpenFIGI + Tiingo + Yahoo coverage pass.

Requires OPENFIGI_API_KEY and TIINGO_API_TOKEN in the environment.
Never prints credential values. Stops with CREDENTIAL_ENVIRONMENT_NOT_VISIBLE
when either variable is missing.

  cd pe-tracker
  python -m scripts.run_free_price_coverage
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.equity_prices.credentials import (  # noqa: E402
    credential_presence,
    missing_credential_names,
)
from src.ingest.equity_prices.fetch import (  # noqa: E402
    CRSP_STATUS,
    DEFAULT_DEAL_MANIFEST,
    default_providers,
)
from src.ingest.equity_prices.identity import (  # noqa: E402
    DEFAULT_TICKER_MAP,
    SecurityIdentityResolver,
)
from src.ingest.equity_prices.normalize import write_normalized_manifest  # noqa: E402
from src.ingest.equity_prices.orchestrator import PriceProviderOrchestrator  # noqa: E402
from src.ingest.equity_prices.identity import REVIEWED_SEC_BASIS  # noqa: E402
from src.ingest.equity_prices.reconciliation import (  # noqa: E402
    THESIS_RECONCILE_RULE,
    reconcile_series,
)
from src.ingest.equity_prices.tiingo import TiingoEquityPriceProvider  # noqa: E402
from src.ingest.equity_prices.yahoo import YahooEquityPriceProvider  # noqa: E402
from src.ingest.security_identity.openfigi import (  # noqa: E402
    OpenFIGISecurityIdentityResolver,
)
from src.ingest.target_prices import DEFAULT_MANIFEST  # noqa: E402

OUT_MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
OUT_AUDIT = ROOT / "data" / "free_price_fetch_audit.json"
PAD_DAYS = 3


# Negative identity evidence: the ticker is not shown to be the SEC target.
FIGI_IDENTITY_VETO = frozenset({"AMBIGUOUS", "NAME_MISMATCH"})
MIN_PRINTS = 3

# Exclusive per-deal canonical status (readiness uses CANONICALLY_ADMITTED only).
CANONICALLY_ADMITTED = "CANONICALLY_ADMITTED"
DEFERRED_IDENTITY = "DEFERRED_IDENTITY"
DEFERRED_PRICE_CONFLICT = "DEFERRED_PRICE_CONFLICT"
NO_PRICE_HISTORY = "NO_PRICE_HISTORY"
INSUFFICIENT_CANONICAL_PRINTS = "INSUFFICIENT_CANONICAL_PRINTS"
DEFER_IDENTITY_UNCONFIRMED = "DEFER_IDENTITY_UNCONFIRMED"

# Tiingo Starter is 50 requests/hour. One deal is metadata + EOD (2 calls).
# Stay under the cap and do not retry a 429 in a tight loop — that burns the
# next window. Identity admission rules are unchanged.
HOURLY_TIINGO_DEALS = 18
HOURLY_RESET_BUFFER_S = 120

# Cached coverage rows are reusable only at this schema. A row from an older
# pass that lacks the current fields is not a price outcome and is not reused.
ROW_SCHEMA_VERSION = 2
REQUIRED_ROW_FIELDS = (
    "exact_matches",
    "tolerable_matches",
    "material_conflicts",
    "canonical_status",
    "identity_proofs",
    "reconcile_rule",
    "tiingo_identity_verified",
)
MAX_HOURLY_429_WAITS = 3
MAX_NON429_TRANSIENT_ATTEMPTS = 3
INFRA_STATUSES = frozenset({
    "TRANSIENT_FAILURE", "PROVIDER_ERROR", "CREDENTIALS_REQUIRED",
})
UNRESOLVED_INFRASTRUCTURE = "UNRESOLVED_INFRASTRUCTURE"
INCOMPLETE_COVERAGE = ROOT / "data" / "free_price_coverage_incomplete.json"


def _trace_is_http_429(trace: dict) -> bool:
    if not isinstance(trace, dict):
        return False
    if trace.get("http_status") == 429:
        return True
    return "429" in str(trace.get("error") or "")


def tiingo_hourly_limited(res: dict) -> bool:
    """True only for explicit HTTP 429 evidence on a Tiingo transient failure.

    An empty TRANSIENT_FAILURE trace is not a 429. A 500/599/network failure
    is not hourly-cap behavior.
    """
    if res.get("status") != "TRANSIENT_FAILURE":
        return False
    traces = res.get("provider_trace") or []
    return any(_trace_is_http_429(t) for t in traces)


def plan_tiingo_retry(res: dict, prior_attempts: int) -> str:
    """Return accept, hourly_wait, bounded_retry, or unresolved.

    Explicit 429 gets a bounded number of hourly waits. Any other transient
    failure gets a bounded short retry. Neither result is NO_PRICE_HISTORY.
    """
    if res.get("status") != "TRANSIENT_FAILURE":
        return "accept"
    if tiingo_hourly_limited(res):
        if prior_attempts >= MAX_HOURLY_429_WAITS:
            return "unresolved"
        return "hourly_wait"
    if prior_attempts >= MAX_NON429_TRANSIENT_ATTEMPTS:
        return "unresolved"
    return "bounded_retry"


def unresolved_infrastructure(row: dict) -> bool:
    """Provider/network failure with no prints is not a price outcome."""
    if (row.get("tiingo_n") or 0) > 0 or (row.get("yahoo_n") or 0) > 0:
        return False
    return any(row.get(f"{side}_status") in INFRA_STATUSES for side in ("tiingo", "yahoo"))


def row_cache_reusable(cached: dict) -> bool:
    """Reuse a cached row only when every current-schema field is present."""
    if not cached or cached.get("row_schema_version") != ROW_SCHEMA_VERSION:
        return False
    if cached.get("tiingo_status") == "TRANSIENT_FAILURE":
        return False
    if cached.get("yahoo_status") == "TRANSIENT_FAILURE":
        return False
    if unresolved_infrastructure(cached):
        return False
    for field in REQUIRED_ROW_FIELDS:
        if field not in cached or cached[field] is None:
            return False
    overlap = int(cached.get("overlap_sessions") or 0)
    parts = (int(cached["exact_matches"]) + int(cached["tolerable_matches"])
             + int(cached["material_conflicts"]))
    return overlap == parts


class CacheMigrationError(ValueError):
    """Raised when a stale row cannot be migrated from auditable evidence."""


def migrate_cached_row(cached: dict) -> dict:
    """Stamp ROW_SCHEMA_VERSION without inventing overlap classifications.

    A zero-overlap row is migrated by setting exact and tolerable to 0: there
    are no sessions to classify. A positive overlap that lacks those fields
    must be recomputed from session-level raw closes.
    """
    if row_cache_reusable(cached):
        return dict(cached)
    if (cached.get("tiingo_status") == "TRANSIENT_FAILURE"
            or unresolved_infrastructure(cached)):
        raise CacheMigrationError("infrastructure rows are not migrated as price outcomes")
    out = dict(cached)
    overlap = int(out.get("overlap_sessions") or 0)
    if "exact_matches" not in out or "tolerable_matches" not in out:
        if overlap != 0:
            raise CacheMigrationError(
                "positive overlap is missing classifications; refetch session evidence")
        out["exact_matches"] = 0
        out["tolerable_matches"] = 0
        out["material_conflicts"] = int(out.get("material_conflicts") or 0)
        out["row_migration"] = "zero_overlap_classifications_are_identically_zero"
    else:
        out["row_migration"] = "stamped_row_schema_version_from_complete_fields"
    for field in REQUIRED_ROW_FIELDS:
        if field not in out or out[field] is None:
            raise CacheMigrationError(f"missing {field}")
    parts = (int(out["exact_matches"]) + int(out["tolerable_matches"])
             + int(out["material_conflicts"]))
    if overlap != parts:
        raise CacheMigrationError(
            f"overlap {overlap} != exact+tolerable+conflict {parts}")
    out["row_schema_version"] = ROW_SCHEMA_VERSION
    if not row_cache_reusable(out):
        raise CacheMigrationError("migration did not produce a reusable row")
    return out


def reconcile_totals_from_rows(rows: list) -> dict:
    """Scientific reconciliation totals from per-deal fields only.

    reconcile_pre_retry is not an input.
    """
    overlap = exact = tolerable = conflict = 0
    for row in rows:
        overlap += int(row.get("overlap_sessions") or 0)
        exact += int(row["exact_matches"])
        tolerable += int(row["tolerable_matches"])
        conflict += int(row["material_conflicts"])
    if overlap != exact + tolerable + conflict:
        raise ValueError(
            "reconcile invariant failed: "
            f"overlap={overlap} exact+tolerable+conflict="
            f"{exact + tolerable + conflict}")
    return {
        "overlap_sessions": overlap,
        "exact": exact,
        "tolerable": tolerable,
        "conflict": conflict,
    }


def run_is_complete(rows: list) -> bool:
    """A scientific coverage matrix requires every deal to have a real status."""
    for row in rows:
        if unresolved_infrastructure(row):
            return False
        if row.get("identity_deferral") == UNRESOLVED_INFRASTRUCTURE:
            return False
        if row.get("canonical_status") is None:
            return False
    return True


def seconds_until_hourly_reset(now: float, buffer_s: int = HOURLY_RESET_BUFFER_S) -> float:
    nxt = (int(now // 3600) + 1) * 3600 + buffer_s
    return max(0.0, nxt - now)


def identity_proofs(row: dict) -> list[str]:
    """Affirmative historical-identity evidence (A/B/C). OpenFIGI NO_MATCH and
    Tiingo SYMBOL_NOT_FOUND/NO_HISTORY are neither negative nor affirmative."""
    proofs = []
    if row.get("openfigi_status") == "MATCHED":
        proofs.append("A_OPENFIGI_MATCHED")
    if row.get("tiingo_identity_verified"):
        proofs.append("B_TIINGO_NAME_AND_LISTING_WINDOW")
    if row.get("identity_basis") == REVIEWED_SEC_BASIS:
        proofs.append("C_REVIEWED_SEC_MAPPING")
    return proofs


def identity_veto(row: dict) -> Optional[str]:
    if row.get("openfigi_status") in FIGI_IDENTITY_VETO:
        return f"OPENFIGI_{row['openfigi_status']}"
    if row.get("tiingo_status") == "IDENTITY_AMBIGUOUS":
        return "TIINGO_IDENTITY_AMBIGUOUS"
    return None


def canonical_status(row: dict) -> tuple[Optional[str], Optional[str]]:
    """(status, identity_deferral_reason). Fixed order: infrastructure →
    veto → conflict → no raw history → no affirmative proof → print count.

    Unresolved provider/network failures return (None, UNRESOLVED_INFRASTRUCTURE).
    That is not a sixth canonical deal status and is not NO_PRICE_HISTORY.
    A run that still has one does not publish a scientific coverage matrix.
    """
    if unresolved_infrastructure(row):
        return None, UNRESOLVED_INFRASTRUCTURE
    proofs = identity_proofs(row)
    veto = identity_veto(row)
    # Proof C is contemporaneous SEC mapping. It overrides an OpenFIGI/Tiingo
    # uniqueness veto on the same ticker; it does not change price_reconcile_v2.
    if veto and "C_REVIEWED_SEC_MAPPING" not in proofs:
        return DEFERRED_IDENTITY, veto
    if row.get("material_conflicts", 0) > 0:
        return DEFERRED_PRICE_CONFLICT, None
    if row.get("tiingo_n", 0) == 0 and row.get("yahoo_n", 0) == 0:
        return NO_PRICE_HISTORY, None
    if not proofs:
        return DEFERRED_IDENTITY, DEFER_IDENTITY_UNCONFIRMED
    if row.get("combined_n", 0) >= MIN_PRINTS:
        return CANONICALLY_ADMITTED, None
    return INSUFFICIENT_CANONICAL_PRINTS, None


def admit_prints(row: dict) -> bool:
    """Prints enter the canonical manifest (and so the >=20-deal readiness
    count) only with no identity veto, no material conflict under
    price_reconcile_v2, and at least one affirmative identity proof."""
    return canonical_status(row)[0] in (CANONICALLY_ADMITTED,
                                        INSUFFICIENT_CANONICAL_PRINTS)


def cached_row_canonically_admitted(row: dict) -> bool:
    """Recompute admission. A stored canonical_status flag is not the rule."""
    status, _reason = canonical_status(row)
    return status == CANONICALLY_ADMITTED


def retained_cached_prints(old_prints: list, rows: list, refetched_ids: set) -> list:
    """Prior prints survive a resume only for deals that were not refetched
    and whose cached row is canonically admitted under the current rule.

    A non-admitted cached deal cannot contribute prints to the manifest or
    to deals_with_3plus_prints, even when the stored row still says admitted.
    """
    admitted_cached = {
        row.get("deal_id")
        for row in rows
        if row.get("deal_id") not in refetched_ids
        and cached_row_canonically_admitted(row)
    }
    return [p for p in old_prints if p.get("deal_id") in admitted_cached]


def _classify_deal(row: dict) -> str:
    if row.get("openfigi_status") == "AMBIGUOUS":
        return "SECURITY_IDENTITY_AMBIGUOUS"
    if row.get("openfigi_status") == "NAME_MISMATCH":
        return "SECURITY_IDENTITY_NAME_MISMATCH"
    if row.get("tiingo_status") == "IDENTITY_AMBIGUOUS":
        return "SECURITY_IDENTITY_AMBIGUOUS"
    if row.get("material_conflicts", 0) > 0:
        return "DEFER_PRICE_CONFLICT"
    if (row.get("tiingo_n", 0) or row.get("yahoo_n", 0)) and not identity_proofs(row):
        return DEFER_IDENTITY_UNCONFIRMED
    if row.get("openfigi_status") == "NO_MATCH":
        return "OPENFIGI_NO_MATCH"
    if row.get("tiingo_n", 0) >= 3 and row.get("yahoo_n", 0) >= 3 and row.get("material_conflicts", 0) == 0:
        return "MULTI_PROVIDER_CONFIRMED"
    if row.get("tiingo_n", 0) >= 3:
        return "TIINGO_COVERED" if row.get("yahoo_n", 0) == 0 else "TIINGO_COVERED"
    if row.get("yahoo_n", 0) >= 3 and row.get("tiingo_n", 0) == 0:
        return "YAHOO_ONLY"
    if row.get("tiingo_status") == "SYMBOL_NOT_FOUND":
        return "TIINGO_NO_SYMBOL"
    if row.get("tiingo_status") in ("NO_HISTORY", "ok") and row.get("tiingo_n", 0) == 0:
        return "TIINGO_NO_HISTORY"
    if row.get("tiingo_status") == "TRANSIENT_FAILURE":
        return "PROVIDER_TRANSIENT_FAILURE"
    if row.get("tiingo_n", 0) == 0 and row.get("yahoo_n", 0) == 0:
        return "NO_PUBLIC_PRICE_HISTORY"
    return "OTHER"


def main() -> int:
    presence = credential_presence()
    print(json.dumps({"credential_presence": presence}, indent=2))
    missing = missing_credential_names()
    if missing:
        print("CREDENTIAL_ENVIRONMENT_NOT_VISIBLE", file=sys.stderr)
        for name in missing:
            print(name, file=sys.stderr)
        return 3

    if not os.getenv("SEC_USER_AGENT"):
        print("SEC_USER_AGENT is not set", file=sys.stderr)
        return 2

    deals = json.loads(DEFAULT_DEAL_MANIFEST.read_text())["deals"]
    ticker_resolver = SecurityIdentityResolver(
        map_path=DEFAULT_TICKER_MAP, user_agent=os.environ["SEC_USER_AGENT"])
    figi = OpenFIGISecurityIdentityResolver()
    tiingo = TiingoEquityPriceProvider()
    yahoo = YahooEquityPriceProvider()
    # Dual fetch for reconciliation: run each provider independently
    orch_tiingo = PriceProviderOrchestrator(
        providers=[tiingo], resolver=ticker_resolver, pad_days=PAD_DAYS)
    orch_yahoo = PriceProviderOrchestrator(
        providers=[yahoo], resolver=ticker_resolver, pad_days=PAD_DAYS)

    prior_rows = {}
    conflict_samples = []
    historical_debug = None
    if OUT_MATRIX.exists():
        old_doc = json.loads(OUT_MATRIX.read_text())
        prior_rows = {r["deal_id"]: r for r in old_doc.get("deals") or []}
        old_meta = old_doc.get("meta") or {}
        conflict_samples = list(old_doc.get("conflict_samples") or [])
        # Side-ledger totals are historical/debug only. They are never added
        # to the scientific reconcile totals.
        if old_meta.get("historical_debug"):
            historical_debug = old_meta["historical_debug"]
        elif old_meta.get("reconcile_pre_retry"):
            historical_debug = {
                "label": "NOT_INCLUDED_IN_SCIENTIFIC_RECONCILE_TOTALS",
                "reconcile_pre_retry": old_meta.get("reconcile_pre_retry"),
                "note": (
                    "Side-ledger retained from an earlier acquisition pass. "
                    "It is not added to meta.reconcile."
                ),
            }

    rows = []
    all_obs = []
    deals_this_hour = 0
    hour_started = time.time()
    fetched_now = set()

    for d in deals:
        cached = prior_rows.get(d["deal_id"])
        if cached and row_cache_reusable(cached):
            rows.append(cached)
            continue

        if time.time() - hour_started >= 3600:
            deals_this_hour = 0
            hour_started = time.time()
        if deals_this_hour >= HOURLY_TIINGO_DEALS:
            wait = seconds_until_hourly_reset(time.time())
            print(f"TIINGO_HOURLY_BUDGET sleep {wait:.0f}s", file=sys.stderr, flush=True)
            time.sleep(wait)
            deals_this_hour = 0
            hour_started = time.time()

        ident, defer = ticker_resolver.resolve(d)
        fetched_now.add(d["deal_id"])
        figi_id = figi.resolve_deal(
            d, ticker=ident.ticker, exchange=ident.exchange)
        # One Tiingo fetch per deal (metadata + EOD). A second combined fetch
        # would double the hourly allocation without changing admission.
        attempt_429 = 0
        attempt_transient = 0
        while True:
            t_res = orch_tiingo.fetch_deal(d)
            decision = plan_tiingo_retry(
                t_res, attempt_429 if tiingo_hourly_limited(t_res) else attempt_transient)
            if decision == "accept":
                break
            if decision == "hourly_wait":
                attempt_429 += 1
                wait = seconds_until_hourly_reset(time.time())
                print(f"TIINGO_HTTP_429 {d['deal_id']} sleep {wait:.0f}s "
                      f"attempt {attempt_429}/{MAX_HOURLY_429_WAITS}",
                      file=sys.stderr, flush=True)
                time.sleep(wait)
                deals_this_hour = 0
                hour_started = time.time()
                continue
            if decision == "bounded_retry":
                attempt_transient += 1
                backoff = min(2 ** attempt_transient, 8)
                print(f"TIINGO_TRANSIENT {d['deal_id']} retry {attempt_transient}/"
                      f"{MAX_NON429_TRANSIENT_ATTEMPTS} sleep {backoff}s",
                      file=sys.stderr, flush=True)
                time.sleep(backoff)
                continue
            print(f"TIINGO_UNRESOLVED {d['deal_id']} status={t_res.get('status')}",
                  file=sys.stderr, flush=True)
            break
        deals_this_hour += 1
        y_res = orch_yahoo.fetch_deal(d)
        if t_res.get("status") == "ok":
            c_res = t_res
        elif t_res.get("status") == "IDENTITY_AMBIGUOUS":
            # Same veto as the orchestrator: do not fall through to Yahoo.
            c_res = {"provider": None, "observations": [], "n_prints": 0}
        else:
            c_res = y_res

        t_obs = t_res.get("observations") or []
        y_obs = y_res.get("observations") or []
        recon = reconcile_series(t_obs, y_obs, rule=THESIS_RECONCILE_RULE) if t_obs or y_obs else {
            "n_overlap": 0, "exact_match": 0, "tolerable_match": 0,
            "material_conflict": 0, "tiingo_only": 0, "yahoo_only": 0,
            "conflicts": [], "status": "N/A",
        }
        if recon.get("material_conflict", 0):
            for c in recon.get("conflicts", [])[:3]:
                conflict_samples.append({"deal_id": d["deal_id"], **c})

        row = {
            "deal_id": d["deal_id"],
            "target_cik": d.get("target_cik"),
            "target_name": d.get("target"),
            "announcement_date": (d.get("announcement_timestamp") or "")[:10],
            "resolution_date": (d.get("resolution_timestamp") or "")[:10],
            "resolution_type": d.get("resolution_type") or d.get("status"),
            "historical_ticker": ident.ticker,
            "identity_basis": ident.ticker_basis,
            "historical_exchange": ident.exchange,
            "openfigi_status": figi_id.mapping_status,
            "figi": figi_id.figi,
            "composite_figi": figi_id.composite_figi,
            "share_class_figi": figi_id.share_class_figi,
            "tiingo_status": t_res.get("status"),
            "tiingo_n": len(t_obs),
            "tiingo_identity_verified": any(
                t.get("identity_verified") for t in t_res.get("provider_trace") or []),
            "yahoo_status": y_res.get("status"),
            "yahoo_n": len(y_obs),
            "overlap_sessions": recon.get("n_overlap", 0),
            "exact_matches": recon.get("exact_match", 0),
            "tolerable_matches": recon.get("tolerable_match", 0),
            "material_conflicts": recon.get("material_conflict", 0),
            "reconcile_rule": THESIS_RECONCILE_RULE,
            "combined_provider": c_res.get("provider"),
            "combined_n": c_res.get("n_prints", len(c_res.get("observations") or [])),
        }
        row["final_coverage_status"] = _classify_deal(row)
        row["identity_proofs"] = identity_proofs(row)
        row["raw_provider_covered"] = max(row["tiingo_n"], row["yahoo_n"]) >= MIN_PRINTS
        row["canonical_status"], row["identity_deferral"] = canonical_status(row)
        row["prints_admitted"] = admit_prints(row)
        row["row_schema_version"] = ROW_SCHEMA_VERSION
        rows.append(row)
        # Canonical observations: combined orchestrator (Tiingo preferred),
        # only for deals that pass the identity + reconciliation admission rule.
        if row["prints_admitted"]:
            all_obs.extend(c_res.get("observations") or [])
        print(json.dumps({
            "deal_id": d["deal_id"],
            "tiingo_status": row["tiingo_status"],
            "tiingo_n": row["tiingo_n"],
            "yahoo_status": row["yahoo_status"],
            "yahoo_n": row["yahoo_n"],
            "canonical_status": row["canonical_status"],
        }), flush=True)

    if not run_is_complete(rows):
        incomplete = {
            "RUN_COMPLETE": "NO",
            "reason": (
                "unresolved infrastructure failure after bounded retry; "
                "scientific coverage matrix not published"
            ),
            "deals": [
                {"deal_id": r.get("deal_id"),
                 "tiingo_status": r.get("tiingo_status"),
                 "yahoo_status": r.get("yahoo_status"),
                 "identity_deferral": r.get("identity_deferral")}
                for r in rows
                if unresolved_infrastructure(r) or r.get("canonical_status") is None
            ],
        }
        INCOMPLETE_COVERAGE.write_text(json.dumps(incomplete, indent=2) + "\n")
        print("RUN_COMPLETE = NO", file=sys.stderr)
        print(f"wrote {INCOMPLETE_COVERAGE}", file=sys.stderr)
        return 4

    # Scientific totals are the per-deal fields. The pre-retry side ledger
    # is not added.
    recon_stats = reconcile_totals_from_rows(rows)

    kept_prints = []
    if DEFAULT_MANIFEST.exists():
        old_manifest = json.loads(DEFAULT_MANIFEST.read_text())
        kept_prints = retained_cached_prints(
            old_manifest.get("prints") or [], rows, fetched_now)

    meta_stub = {"RUN_COMPLETE": "YES", "reconcile_rule": THESIS_RECONCILE_RULE}
    if historical_debug:
        meta_stub["historical_debug"] = historical_debug
    write_normalized_manifest(all_obs, DEFAULT_MANIFEST, meta=meta_stub)
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    manifest["prints"] = kept_prints + manifest.get("prints", [])
    by_deal_prints = Counter(p["deal_id"] for p in manifest["prints"])
    n_3plus = sum(1 for n in by_deal_prints.values() if n >= MIN_PRINTS)
    meta = {
        "canonical_n": len(deals),
        "total_real_price_prints": len(manifest["prints"]),
        "deals_with_3plus_prints": n_3plus,
        "tiingo_deals_covered": sum(1 for r in rows if r["tiingo_n"] >= 3),
        "yahoo_deals_covered": sum(1 for r in rows if r["yahoo_n"] >= 3),
        "multi_provider_confirmed": sum(
            1 for r in rows if r["final_coverage_status"] == "MULTI_PROVIDER_CONFIRMED"),
        # Raw provider coverage is reported separately and never used for readiness.
        "raw_provider_covered": sum(1 for r in rows if r["raw_provider_covered"]),
        "canonically_admitted": sum(
            1 for r in rows if r["canonical_status"] == CANONICALLY_ADMITTED),
        "deferred_identity": sum(
            1 for r in rows if r["canonical_status"] == DEFERRED_IDENTITY),
        "deferred_price_conflict": sum(
            1 for r in rows if r["canonical_status"] == DEFERRED_PRICE_CONFLICT),
        "no_price_history": sum(
            1 for r in rows if r["canonical_status"] == NO_PRICE_HISTORY),
        "insufficient_canonical_prints": sum(
            1 for r in rows if r["canonical_status"] == INSUFFICIENT_CANONICAL_PRINTS),
        "identity_deferral_reasons": dict(Counter(
            r["identity_deferral"] for r in rows if r["identity_deferral"])),
        "uncovered_deals": sum(
            1 for r in rows if r["canonical_status"] != CANONICALLY_ADMITTED),
        "deals_not_admitted": sum(1 for r in rows if not r["prints_admitted"]),
        "reconcile_rule": THESIS_RECONCILE_RULE,
        "historical_price_data_ready": n_3plus >= 20,
        "crsp_status": CRSP_STATUS,
        "provider_chain": [p.name for p in default_providers()],
        "openfigi_matched": sum(1 for r in rows if r["openfigi_status"] == "MATCHED"),
        "openfigi_ambiguous": sum(1 for r in rows if r["openfigi_status"] == "AMBIGUOUS"),
        "openfigi_no_match": sum(1 for r in rows if r["openfigi_status"] == "NO_MATCH"),
        "openfigi_name_mismatch": sum(
            1 for r in rows if r["openfigi_status"] == "NAME_MISMATCH"),
        "tiingo_identity_verified": sum(
            1 for r in rows if r.get("tiingo_identity_verified")),
        "gap_class_counts": dict(Counter(r["final_coverage_status"] for r in rows)),
        "reconcile": dict(recon_stats),
        "RUN_COMPLETE": "YES",
        "tiingo_hourly_limited_remaining": sum(
            1 for r in rows if r.get("tiingo_status") == "TRANSIENT_FAILURE"),
    }
    if historical_debug:
        meta["historical_debug"] = historical_debug
    doc = {
        "schema_version": 1,
        "_doc": "Free thesis stack coverage matrix (OpenFIGI + Tiingo + Yahoo).",
        "meta": meta,
        "deals": rows,
        "conflict_samples": conflict_samples[:50],
    }
    OUT_MATRIX.write_text(json.dumps(doc, indent=2) + "\n")
    manifest["meta"] = meta
    DEFAULT_MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    OUT_AUDIT.write_text(json.dumps({"meta": meta, "deals": rows}, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    print(f"wrote {OUT_MATRIX}")
    print(f"wrote {DEFAULT_MANIFEST} ({len(manifest['prints'])} prints)")

    # Offline audit docs (no credentials required once matrix exists)
    from scripts.audit_free_price_coverage import main as audit_main
    audit_rc = audit_main()
    if audit_rc != 0:
        print("audit_free_price_coverage failed", file=sys.stderr)
        return audit_rc

    if n_3plus < 20:
        print("HISTORICAL_PRICE_DATA_READY = NO", file=sys.stderr)
        print("SPREAD_STRESS_BACKTEST_STATUS = BLOCKED_INSUFFICIENT_PRICE_HISTORY",
              file=sys.stderr)
        return 0

    print("HISTORICAL_PRICE_DATA_READY = YES", file=sys.stderr)
    print("PRICE_COVERAGE_READY = YES", file=sys.stderr)
    print("SPREAD_STRESS_V1_PANEL_VALID = SEE_DIAGNOSTIC", file=sys.stderr)
    print("THESIS_PRICE_DATA_READY_FOR_REVIEW = YES", file=sys.stderr)
    from scripts.freeze_thesis_price_cohort import main as freeze_main
    freeze_rc = freeze_main()
    if freeze_rc != 0:
        print("cohort freeze failed after readiness", file=sys.stderr)
        return freeze_rc
    # Free-thesis goal: stop before model / spread_stress execution.
    print("STOP — cohort frozen; do not execute backtest in this goal.",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
