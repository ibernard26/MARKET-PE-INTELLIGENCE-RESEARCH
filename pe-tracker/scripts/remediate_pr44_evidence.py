#!/usr/bin/env python3
"""Remediate PR #44 evidence without rerunning the 129-deal acquisition.

Refetches only overlapping deals (Tiingo and Yahoo) and Tiingo metadata for
currently admitted deals. Does not fit a model and does not run a backtest.

  cd pe-tracker
  python -m scripts.remediate_pr44_evidence
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit_free_price_coverage import main as audit_main  # noqa: E402
from scripts.freeze_thesis_price_cohort import main as freeze_main  # noqa: E402
from scripts.run_free_price_coverage import (  # noqa: E402
    CANONICALLY_ADMITTED,
    DEFERRED_IDENTITY,
    DEFERRED_PRICE_CONFLICT,
    INSUFFICIENT_CANONICAL_PRINTS,
    MAX_NON429_TRANSIENT_ATTEMPTS,
    MIN_PRINTS,
    NO_PRICE_HISTORY,
    ROW_SCHEMA_VERSION,
    THESIS_RECONCILE_RULE,
    UNRESOLVED_INFRASTRUCTURE,
    _classify_deal,
    admit_prints,
    canonical_status,
    identity_proofs,
    migrate_cached_row,
    plan_tiingo_retry,
    reconcile_totals_from_rows,
    seconds_until_hourly_reset,
    tiingo_hourly_limited,
)
from src.ingest.equity_prices.calendar_gate import filter_session_observations  # noqa: E402
from src.ingest.equity_prices.fetch import DEFAULT_DEAL_MANIFEST  # noqa: E402
from src.ingest.equity_prices.identity_evidence import (  # noqa: E402
    build_identity_evidence,
)
from src.ingest.equity_prices.pit_flags import annotate_prints, pit_summary  # noqa: E402
from src.ingest.equity_prices.reconciliation import (  # noqa: E402
    RECONCILE_RULES,
    reconcile_session_evidence,
    summarize_session_evidence,
)
from src.ingest.equity_prices.schema import ProviderStatus, SecurityIdentity  # noqa: E402
from src.ingest.equity_prices.tiingo import (  # noqa: E402
    TiingoEquityPriceProvider,
    tiingo_api_token_present,
)
from src.ingest.equity_prices.yahoo import YahooEquityPriceProvider  # noqa: E402
from src.ingest.target_prices import DEFAULT_MANIFEST  # noqa: E402
from src.model.logistic import MIN_CLASS_N  # noqa: E402
from src.model.spread_stress.panel_diagnostic import (  # noqa: E402
    diagnose_v1_panel,
    load_manifest_panel,
    pre_resolution_print_stats,
)

MATRIX = ROOT / "data" / "free_price_coverage_matrix.json"
AUDIT = ROOT / "data" / "free_price_fetch_audit.json"
EVIDENCE = ROOT / "data" / "price_reconcile_v2_evidence.json"
IDENTITY = ROOT / "data" / "tiingo_identity_evidence.json"
PIT = ROOT / "data" / "pit_ordering_diagnostics.json"
DIAGNOSTIC = ROOT / "data" / "spread_stress_v1_panel_diagnostic.json"
POSTMORTEM = ROOT / "docs" / "SPREAD_STRESS_V1_POSTMORTEM.md"
PAD_DAYS = 3
BREAK_LIKE = frozenset({"terminated", "withdrawn", "broken"})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n")


def _status_name(status) -> str:
    return status.value if isinstance(status, ProviderStatus) else str(status)


def _metadata_result(status, payload: dict) -> dict:
    name = _status_name(status)
    trace = []
    if name == "TRANSIENT_FAILURE" and isinstance(payload, dict):
        http = payload.get("http_status")
        trace.append({
            "http_status": http,
            "error": f"Tiingo meta HTTP {http}" if http else payload.get("error"),
        })
    return {"status": name, "provider_trace": trace, "payload": payload}


def _bounded_metadata(provider: TiingoEquityPriceProvider, symbol: str) -> tuple[str, dict]:
    attempt_429 = 0
    attempt_transient = 0
    while True:
        status, payload = provider.fetch_metadata(symbol)
        wrapped = _metadata_result(status, payload if isinstance(payload, dict) else {})
        prior = attempt_429 if tiingo_hourly_limited(wrapped) else attempt_transient
        decision = plan_tiingo_retry(wrapped, prior)
        if decision == "accept":
            return wrapped["status"], payload if isinstance(payload, dict) else {}
        if decision == "hourly_wait":
            attempt_429 += 1
            wait = seconds_until_hourly_reset(time.time())
            print(f"TIINGO_HTTP_429 metadata {symbol} sleep {wait:.0f}s",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
            continue
        if decision == "bounded_retry":
            attempt_transient += 1
            backoff = min(2 ** attempt_transient, 8)
            print(f"TIINGO_TRANSIENT metadata {symbol} sleep {backoff}s",
                  file=sys.stderr, flush=True)
            time.sleep(backoff)
            continue
        return wrapped["status"], payload if isinstance(payload, dict) else {}


def _history_to_res(result) -> dict:
    """Normalize a provider result. HTTP 429 stays on the trace, not inferred."""
    status = _status_name(result.status)
    error = result.error
    trace = {
        "provider": result.provider,
        "status": status,
        "error": error,
        "n_observations": len(result.observations or []),
    }
    if error and "HTTP 429" in str(error):
        trace["http_status"] = 429
    return {
        "status": status,
        "provider_trace": [trace],
        "observations": list(result.observations or []),
        "identity_verified": bool(result.identity_verified),
    }


def _deal_window(deal: dict) -> tuple[date, date, date, date]:
    """Same announce→resolution clip the coverage orchestrator uses."""
    ann = date.fromisoformat(deal["announcement_timestamp"][:10])
    res_s = deal.get("resolution_timestamp") or deal["announcement_timestamp"]
    res = date.fromisoformat(res_s[:10])
    return ann - timedelta(days=PAD_DAYS), res + timedelta(days=PAD_DAYS), ann, res


def _clip_observations(observations: list, ann: date, res: date) -> list:
    in_window = [
        obs for obs in observations
        if ann <= date.fromisoformat(obs.session_date) <= res
    ]
    ok, _bad = filter_session_observations(in_window)
    return ok


def _identity_from_coverage_row(row: dict, deal: dict) -> SecurityIdentity:
    """Refetch the ticker the live run already stored. Do not re-resolve it."""
    ann = (deal.get("announcement_timestamp") or "")[:10] or None
    res = (deal.get("resolution_timestamp") or "")[:10] or ann
    cik = deal.get("target_cik")
    ticker = (row.get("historical_ticker") or "").strip().upper() or None
    return SecurityIdentity(
        deal_id=deal["deal_id"],
        target_cik=int(cik) if cik is not None else None,
        target_name=deal.get("target") or row.get("target_name"),
        ticker=ticker,
        exchange=row.get("historical_exchange"),
        ticker_basis=row.get("identity_basis"),
        announcement_date=ann,
        resolution_date=res,
        identity_source="coverage_row_historical_ticker",
    )


def _bounded_history(provider, identity: SecurityIdentity, start: date, end: date, *,
                     hourly: bool, deal_id: str) -> dict:
    attempt_429 = 0
    attempt_transient = 0
    while True:
        res = _history_to_res(provider.fetch_history(identity, start, end))
        if not hourly:
            if res.get("status") != "TRANSIENT_FAILURE":
                return res
            if attempt_transient >= MAX_NON429_TRANSIENT_ATTEMPTS:
                return res
            attempt_transient += 1
            time.sleep(min(2 ** attempt_transient, 8))
            continue
        prior = attempt_429 if tiingo_hourly_limited(res) else attempt_transient
        decision = plan_tiingo_retry(res, prior)
        if decision == "accept":
            return res
        if decision == "hourly_wait":
            attempt_429 += 1
            wait = seconds_until_hourly_reset(time.time())
            print(f"TIINGO_HTTP_429 {deal_id} sleep {wait:.0f}s",
                  file=sys.stderr, flush=True)
            time.sleep(wait)
            continue
        if decision == "bounded_retry":
            attempt_transient += 1
            time.sleep(min(2 ** attempt_transient, 8))
            continue
        return res


def _recompute_meta(rows: list, prints: list, old_meta: dict,
                    historical_debug: dict) -> dict:
    by_deal = Counter(p["deal_id"] for p in prints)
    n_3 = sum(1 for n in by_deal.values() if n >= MIN_PRINTS)
    meta = {
        "canonical_n": old_meta.get("canonical_n"),
        "total_real_price_prints": len(prints),
        "deals_with_3plus_prints": n_3,
        "tiingo_deals_covered": sum(1 for r in rows if (r.get("tiingo_n") or 0) >= 3),
        "yahoo_deals_covered": sum(1 for r in rows if (r.get("yahoo_n") or 0) >= 3),
        "multi_provider_confirmed": sum(
            1 for r in rows if r.get("final_coverage_status") == "MULTI_PROVIDER_CONFIRMED"),
        "raw_provider_covered": sum(1 for r in rows if r.get("raw_provider_covered")),
        "canonically_admitted": sum(
            1 for r in rows if r.get("canonical_status") == CANONICALLY_ADMITTED),
        "deferred_identity": sum(
            1 for r in rows if r.get("canonical_status") == DEFERRED_IDENTITY),
        "deferred_price_conflict": sum(
            1 for r in rows if r.get("canonical_status") == DEFERRED_PRICE_CONFLICT),
        "no_price_history": sum(
            1 for r in rows if r.get("canonical_status") == NO_PRICE_HISTORY),
        "insufficient_canonical_prints": sum(
            1 for r in rows if r.get("canonical_status") == INSUFFICIENT_CANONICAL_PRINTS),
        "identity_deferral_reasons": dict(Counter(
            r["identity_deferral"] for r in rows if r.get("identity_deferral"))),
        "uncovered_deals": sum(
            1 for r in rows if r.get("canonical_status") != CANONICALLY_ADMITTED),
        "deals_not_admitted": sum(1 for r in rows if not r.get("prints_admitted")),
        "reconcile_rule": THESIS_RECONCILE_RULE,
        "historical_price_data_ready": n_3 >= 20,
        "crsp_status": old_meta.get("crsp_status"),
        "provider_chain": old_meta.get("provider_chain"),
        "openfigi_matched": sum(1 for r in rows if r.get("openfigi_status") == "MATCHED"),
        "openfigi_ambiguous": sum(1 for r in rows if r.get("openfigi_status") == "AMBIGUOUS"),
        "openfigi_no_match": sum(1 for r in rows if r.get("openfigi_status") == "NO_MATCH"),
        "openfigi_name_mismatch": sum(
            1 for r in rows if r.get("openfigi_status") == "NAME_MISMATCH"),
        "tiingo_identity_verified": sum(1 for r in rows if r.get("tiingo_identity_verified")),
        "gap_class_counts": dict(Counter(r.get("final_coverage_status") for r in rows)),
        "reconcile": reconcile_totals_from_rows(rows),
        "RUN_COMPLETE": "YES",
        "tiingo_hourly_limited_remaining": sum(
            1 for r in rows if r.get("tiingo_status") == "TRANSIENT_FAILURE"),
        "historical_debug": historical_debug,
        "overlap_deals_canonically_admitted": sum(
            1 for r in rows
            if (r.get("overlap_sessions") or 0) > 0
            and r.get("canonical_status") == CANONICALLY_ADMITTED),
        "overlap_deals_identity_deferred": sum(
            1 for r in rows
            if (r.get("overlap_sessions") or 0) > 0
            and r.get("canonical_status") == DEFERRED_IDENTITY),
        "admitted_deals_with_secondary_overlap": sum(
            1 for r in rows
            if r.get("canonical_status") == CANONICALLY_ADMITTED
            and (r.get("overlap_sessions") or 0) > 0),
    }
    return meta


def _apply_row_status(row: dict) -> None:
    row["identity_proofs"] = identity_proofs(row)
    row["final_coverage_status"] = _classify_deal(row)
    row["raw_provider_covered"] = max(row.get("tiingo_n") or 0, row.get("yahoo_n") or 0) >= MIN_PRINTS
    row["canonical_status"], row["identity_deferral"] = canonical_status(row)
    row["prints_admitted"] = admit_prints(row)
    row["reconcile_rule"] = THESIS_RECONCILE_RULE
    row["row_schema_version"] = ROW_SCHEMA_VERSION


def _write_postmortem(diag: dict, meta: dict) -> None:
    admitted = meta.get("canonically_admitted")
    body = f"""# spread_stress_v1 postmortem

The canonical historical-price coverage gate passed with {admitted} admitted deals.
The existing spread_stress_v1 panel was not executable because its feature-time
construction collides with date-only resolution timestamps, and the admitted
cohort also contains only one break-like outcome. No model fit or backtest was
performed.

This note does not define `spread_stress_v2` and does not change the v1
feature-time rule.

## Coverage gate passed

`PRICE_COVERAGE_READY = {diag['PRICE_COVERAGE_READY']}`.

The readiness population is `CANONICALLY_ADMITTED` deals with at least 3 raw
closes (`close_field_used = close`). That gate is separate from whether the
v1 panel constructor can turn those closes into labeled rows.

## v1 panel construction failed

`SPREAD_STRESS_V1_PANEL_VALID = {diag['SPREAD_STRESS_V1_PANEL_VALID']}`.

`build_spread_stress_panel` selects the last print at or before the cutoff and
then requires `feature_time < resolution_time`. It does not look for an earlier
print after that comparison fails.

## Why date-only resolution timestamps collide with 16:00 closes

SEC resolution timestamps in this corpus are mostly calendar dates. Ingest
normalizes a date-only timestamp to midnight (`00:00:00`). Tiingo session
closes are stamped `16:00` America/New_York. A resolution-day close is therefore
later than the stored resolution instant, and the selected feature time fails
`feature_time < resolution_time`.

`normalize_as_of` expands a bare date to end-of-day only when the stored value
is still 10 characters. Once the event has been normalized to midnight, the
clock time is kept and the same-day 16:00 close is not strictly before it.

`SPREAD_STRESS_V1_BLOCK_REASON = {diag['SPREAD_STRESS_V1_BLOCK_REASON']}`.

Panel rows excluded for `feature_not_before_resolution`:
{diag['PANEL_ROWS_EXCLUDED_FEATURE_NOT_BEFORE_RESOLUTION']}.

Prints strictly before the stored resolution instant:
{diag['PRE_RESOLUTION_PRINTS_AVAILABLE']}.

Deals with at least 3 such prints:
{diag['DEALS_WITH_3PLUS_PRE_RESOLUTION_PRINTS']}.

Those counts show that pre-resolution closes exist. They are not a replacement
feature rule.

## Why last-pre-resolution-print is not an acceptable retroactive fix

Choosing the last print strictly before the resolution timestamp would use the
outcome time to decide which observation is the feature. That is future
information in the feature-time selection process. This remediation does not
do that, and it does not rename the modified rule `spread_stress_v1`.

## Class imbalance

The admitted cohort is {diag['admitted_closed']} closed and
{diag['admitted_break_like']} break-like. `MIN_CLASS_N` remains {MIN_CLASS_N}.
The existing v1 panel result is {diag['panel_rows_labeled']} labeled row
(pos={diag['panel_n_pos']}, neg={diag['panel_n_neg']}). Even a timestamp
correction would leave a single break-like outcome, which cannot clear
`MIN_CLASS_N`. The minimum is not lowered.

## What was not run

- `SPREAD_STRESS_V1_EXECUTED = {diag['SPREAD_STRESS_V1_EXECUTED']}`
- `SPREAD_STRESS_V1_MODEL_FIT = {diag['SPREAD_STRESS_V1_MODEL_FIT']}`
- No walk-forward prediction was produced.
- No economic backtest was run.
- No calibration was run.

The harness status `BLOCKED_INSUFFICIENT_PRICE_HISTORY` is the pre-existing
gate string. On this corpus it is not a finding that historical prices are
missing. The coverage gate passed. The panel rule then removed rows because of
the timestamp collision, and the class counts are below `MIN_CLASS_N`.

## What a later version has to freeze first

A future spread-stress version needs an independently frozen feature-time
policy, written down before any execution on this cohort. That policy is not
designed here. Same-day closes on date-only announcements and resolutions stay
flagged `ANNOUNCEMENT_DAY_ORDERING_AMBIGUOUS` and
`RESOLUTION_DAY_ORDERING_AMBIGUOUS`. Raw prints remain in the manifest.
"""
    POSTMORTEM.write_text(body)


def apply_offline() -> int:
    """PIT flags, v1 panel diagnostic, cohort fingerprint. No provider calls.

    Does not rewrite reconciliation totals and does not invent identity evidence.
    """
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    sec = json.loads(DEFAULT_DEAL_MANIFEST.read_text())
    matrix = json.loads(MATRIX.read_text())
    deals_by_id = {d["deal_id"]: d for d in sec["deals"]}
    prints = annotate_prints(manifest.get("prints") or [], deals_by_id)
    if len(prints) != len(manifest.get("prints") or []):
        print("PIT annotation changed the print count", file=sys.stderr)
        return 4
    manifest["prints"] = prints
    _write(DEFAULT_MANIFEST, manifest)
    pit_doc = pit_summary(sec["deals"], prints)
    pit_doc["schema_version"] = 1
    _write(PIT, pit_doc)
    pre_n, pre_deals = pre_resolution_print_stats(prints, deals_by_id)
    panel = load_manifest_panel(prints, sec["deals"])
    meta = matrix.get("meta") or {}
    rows = matrix.get("deals") or []
    admitted_rows = [r for r in rows if r.get("canonical_status") == CANONICALLY_ADMITTED]
    closed = break_like = 0
    for row in admitted_rows:
        kind = (deals_by_id[row["deal_id"]].get("resolution_type") or "").lower()
        if kind in BREAK_LIKE:
            break_like += 1
        elif kind == "closed":
            closed += 1
    diag = diagnose_v1_panel(
        panel,
        price_coverage_ready=bool(meta.get("historical_price_data_ready")),
        pre_resolution_prints=pre_n,
        deals_with_3plus_pre_resolution_prints=pre_deals,
    )
    diag["admitted_closed"] = closed
    diag["admitted_break_like"] = break_like
    diag["MIN_CLASS_N"] = MIN_CLASS_N
    diag["labeled_deal_ids"] = [r["deal_id"] for r in panel.get("rows") or []]
    diag["collision_deal_ids"] = [
        r["deal_id"] for r in panel.get("excluded") or []
        if r.get("reason") == "feature_not_before_resolution"
    ]
    _write(DIAGNOSTIC, diag)
    _write_postmortem(diag, meta)
    freeze_rc = freeze_main()
    if freeze_rc != 0:
        return freeze_rc
    return audit_main()


def main() -> int:
    if "--offline-only" in sys.argv:
        return apply_offline()
    if not tiingo_api_token_present():
        print("CREDENTIAL_ENVIRONMENT_NOT_VISIBLE", file=sys.stderr)
        print("TIINGO_API_TOKEN", file=sys.stderr)
        return 3
    os.environ.setdefault(
        "SEC_USER_AGENT",
        "MARKET-PE-INTELLIGENCE research (ibernard26; reconcile remediation)",
    )

    matrix = json.loads(MATRIX.read_text())
    manifest = json.loads(DEFAULT_MANIFEST.read_text())
    sec = json.loads(DEFAULT_DEAL_MANIFEST.read_text())
    deals_by_id = {d["deal_id"]: d for d in sec["deals"]}
    rows = [dict(r) for r in matrix["deals"]]
    old_meta = matrix.get("meta") or {}
    retrieved_at = _now()

    before_counts = {}
    for row in rows:
        if (row.get("overlap_sessions") or 0) > 0:
            before_counts[row["deal_id"]] = {
                "overlap_sessions": row.get("overlap_sessions"),
                "exact_matches": row.get("exact_matches"),
                "tolerable_matches": row.get("tolerable_matches"),
                "material_conflicts": row.get("material_conflicts"),
            }

    historical_debug = {
        "label": "NOT_INCLUDED_IN_SCIENTIFIC_RECONCILE_TOTALS",
        "reconcile_pre_retry": old_meta.get("reconcile_pre_retry")
        or (old_meta.get("historical_debug") or {}).get("reconcile_pre_retry"),
        "prior_headline_reconcile": old_meta.get("reconcile"),
        "per_deal_counts_before_session_evidence": before_counts,
        "note": (
            "Side-ledger and pre-evidence per-deal counts from the live "
            "acquisition. Scientific meta.reconcile is the sum of per-deal "
            "fields after session evidence. This object is not added to those totals."
        ),
    }

    overlap_ids = [r["deal_id"] for r in rows if (r.get("overlap_sessions") or 0) > 0]
    admitted_ids = [r["deal_id"] for r in rows
                    if r.get("canonical_status") == CANONICALLY_ADMITTED]
    print(json.dumps({
        "overlap_deals": len(overlap_ids),
        "admitted_deals_for_identity_refresh": len(admitted_ids),
    }), flush=True)

    tiingo = TiingoEquityPriceProvider()
    yahoo = YahooEquityPriceProvider()

    sessions: list[dict] = []
    refetched_counts: dict[str, dict] = {}
    for deal_id in overlap_ids:
        deal = deals_by_id[deal_id]
        identity = _identity_from_coverage_row(
            next(r for r in rows if r["deal_id"] == deal_id), deal)
        if not identity.resolved():
            print(json.dumps({
                "RUN_COMPLETE": "NO",
                "deal_id": deal_id,
                "reason": "overlapping deal has no stored historical ticker",
            }), file=sys.stderr)
            return 4
        start, end, ann, res = _deal_window(deal)
        t_res = _bounded_history(
            tiingo, identity, start, end, hourly=True, deal_id=deal_id)
        y_res = _bounded_history(
            yahoo, identity, start, end, hourly=False, deal_id=deal_id)
        t_obs = _clip_observations(t_res.get("observations") or [], ann, res)
        y_obs = _clip_observations(y_res.get("observations") or [], ann, res)
        if t_res.get("status") != "AVAILABLE" or y_res.get("status") != "AVAILABLE" or not t_obs or not y_obs:
            print(json.dumps({
                "RUN_COMPLETE": "NO",
                "deal_id": deal_id,
                "tiingo_status": t_res.get("status"),
                "yahoo_status": y_res.get("status"),
                "tiingo_n": len(t_obs),
                "yahoo_n": len(y_obs),
                "reason": "overlap refetch did not return both raw series",
            }), file=sys.stderr)
            return 4
        refetched_counts[deal_id] = {
            "tiingo_n": len(t_obs),
            "yahoo_n": len(y_obs),
            "tiingo_identity_verified": bool(t_res.get("identity_verified")),
        }
        deal_sessions = reconcile_session_evidence(
            t_obs, y_obs, deal_id=deal_id, rule=THESIS_RECONCILE_RULE)
        if not deal_sessions:
            print(json.dumps({
                "RUN_COMPLETE": "NO",
                "deal_id": deal_id,
                "reason": "refetch produced no overlapping sessions",
                "tiingo_n": len(t_obs),
                "yahoo_n": len(y_obs),
            }), file=sys.stderr)
            return 4
        sessions.extend(deal_sessions)
        print(json.dumps({
            "deal_id": deal_id, "overlap_sessions": len(deal_sessions),
        }), flush=True)

    per_deal, evidence_totals = summarize_session_evidence(sessions)
    by_evidence = {r["deal_id"]: r for r in per_deal}
    if set(by_evidence) != set(overlap_ids):
        print("session evidence deal set != overlapping deals", file=sys.stderr)
        return 4

    abs_eps, rel_eps = RECONCILE_RULES[THESIS_RECONCILE_RULE]
    evidence_doc = {
        "schema_version": 1,
        "rule_version": THESIS_RECONCILE_RULE,
        "abs_eps": abs_eps,
        "rel_eps": rel_eps,
        "comparison": "raw_close_vs_raw_close",
        "adjusted_close_used": False,
        "averaged": False,
        "retrieved_at": retrieved_at,
        "per_deal": per_deal,
        "totals": evidence_totals,
        "sessions": sessions,
    }

    identity_records = []
    proof_b_failures = []
    rows_by_id = {r["deal_id"]: r for r in rows}
    for deal_id in admitted_ids:
        row = rows_by_id[deal_id]
        symbol = row.get("historical_ticker")
        status, meta = _bounded_metadata(tiingo, symbol)
        if status != "AVAILABLE":
            print(json.dumps({
                "RUN_COMPLETE": "NO",
                "deal_id": deal_id,
                "tiingo_metadata_status": status,
                "reason": "identity refresh did not return Tiingo metadata",
            }), file=sys.stderr)
            return 4
        record = build_identity_evidence(
            deal_id=deal_id,
            canonical_target_name=row.get("target_name"),
            historical_ticker=symbol,
            announcement_date=row.get("announcement_date"),
            tiingo_meta=meta,
            retrieved_at=retrieved_at,
            openfigi_status=row.get("openfigi_status"),
            figi=row.get("figi"),
            composite_figi=row.get("composite_figi"),
            share_class_figi=row.get("share_class_figi"),
            prior_proofs=row.get("identity_proofs") or [],
        )
        identity_records.append(record)
        row["tiingo_identity_verified"] = bool(record["proof_B_earned"])
        if not record["proof_B_earned"]:
            proof_b_failures.append(deal_id)
        _apply_row_status(row)
        print(json.dumps({
            "deal_id": deal_id,
            "proof_B_earned": record["proof_B_earned"],
            "canonical_status": row["canonical_status"],
        }), flush=True)

    for row in rows:
        if row["deal_id"] in by_evidence:
            ev = by_evidence[row["deal_id"]]
            counts = refetched_counts[row["deal_id"]]
            row["overlap_sessions"] = ev["overlap_sessions"]
            row["exact_matches"] = ev["exact_matches"]
            row["tolerable_matches"] = ev["tolerable_matches"]
            row["material_conflicts"] = ev["material_conflicts"]
            row["tiingo_n"] = counts["tiingo_n"]
            row["yahoo_n"] = counts["yahoo_n"]
            row["tiingo_status"] = "ok"
            row["yahoo_status"] = "ok"
            # Overlap deals stay identity-deferred when OpenFIGI vetoes them.
            # Do not promote tiingo_identity_verified from a price refetch;
            # proof B for admitted deals is recomputed from metadata below.
            row["row_migration"] = "refetched_session_evidence_price_reconcile_v2"
            _apply_row_status(row)
            continue
        if row.get("row_schema_version") == ROW_SCHEMA_VERSION and row.get("exact_matches") is not None:
            continue
        migrated = migrate_cached_row(row)
        row.clear()
        row.update(migrated)

    dropped = [r["deal_id"] for r in rows if not r.get("prints_admitted")]
    prints = [p for p in manifest.get("prints") or [] if p.get("deal_id") not in set(dropped)]
    prints = annotate_prints(prints, deals_by_id)
    # Admitted prints only. Identity failures are removed above.
    admitted_now = {r["deal_id"] for r in rows if r.get("prints_admitted")}
    prints = [p for p in prints if p["deal_id"] in admitted_now]
    if not proof_b_failures and len(prints) != len(manifest.get("prints") or []):
        print(json.dumps({
            "RUN_COMPLETE": "NO",
            "reason": "print count changed without a proof B failure",
            "before": len(manifest.get("prints") or []),
            "after": len(prints),
        }), file=sys.stderr)
        return 4

    meta = _recompute_meta(rows, prints, old_meta, historical_debug)
    if meta["reconcile"] != {
        "overlap_sessions": evidence_totals["overlap_sessions"]
        + sum((r.get("overlap_sessions") or 0) for r in rows if r["deal_id"] not in by_evidence),
        "exact": evidence_totals["exact"]
        + sum(int(r["exact_matches"]) for r in rows if r["deal_id"] not in by_evidence),
        "tolerable": evidence_totals["tolerable"]
        + sum(int(r["tolerable_matches"]) for r in rows if r["deal_id"] not in by_evidence),
        "conflict": evidence_totals["conflict"]
        + sum(int(r["material_conflicts"]) for r in rows if r["deal_id"] not in by_evidence),
    }:
        print("per-deal reconcile totals != evidence plus non-overlap rows", file=sys.stderr)
        return 4

    matrix_doc = {
        "schema_version": matrix.get("schema_version", 1),
        "_doc": matrix.get("_doc"),
        "meta": meta,
        "deals": rows,
        "conflict_samples": [
            {
                "deal_id": s["deal_id"],
                "session_date": s["session_date"],
                "primary_close": s["tiingo_raw_close"],
                "secondary_close": s["yahoo_raw_close"],
                "classification": s["classification"],
            }
            for s in sessions if s["classification"] == "MATERIAL_CONFLICT"
        ][:50],
    }
    manifest_doc = {
        "schema_version": manifest.get("schema_version", 2),
        "_doc": manifest.get("_doc"),
        "meta": meta,
        "prints": prints,
    }
    identity_doc = {
        "schema_version": 1,
        "provider": "tiingo",
        "credential_stored": False,
        "deals_revalidated": len(identity_records),
        "proof_B_failures": proof_b_failures,
        "deals": identity_records,
    }
    pit_doc = pit_summary(sec["deals"], prints)
    pit_doc["schema_version"] = 1

    _write(EVIDENCE, evidence_doc)
    _write(IDENTITY, identity_doc)
    _write(PIT, pit_doc)
    _write(MATRIX, matrix_doc)
    _write(AUDIT, {"meta": meta, "deals": rows})
    _write(DEFAULT_MANIFEST, manifest_doc)

    pre_n, pre_deals = pre_resolution_print_stats(prints, deals_by_id)
    panel = load_manifest_panel(prints, sec["deals"])
    admitted_rows = [r for r in rows if r.get("canonical_status") == CANONICALLY_ADMITTED]
    closed = break_like = 0
    for row in admitted_rows:
        kind = (deals_by_id[row["deal_id"]].get("resolution_type") or "").lower()
        if kind in BREAK_LIKE:
            break_like += 1
        elif kind == "closed":
            closed += 1
    diag = diagnose_v1_panel(
        panel,
        price_coverage_ready=bool(meta["historical_price_data_ready"]),
        pre_resolution_prints=pre_n,
        deals_with_3plus_pre_resolution_prints=pre_deals,
    )
    diag["admitted_closed"] = closed
    diag["admitted_break_like"] = break_like
    diag["MIN_CLASS_N"] = MIN_CLASS_N
    diag["labeled_deal_ids"] = [r["deal_id"] for r in panel.get("rows") or []]
    diag["collision_deal_ids"] = [
        r["deal_id"] for r in panel.get("excluded") or []
        if r.get("reason") == "feature_not_before_resolution"
    ]
    _write(DIAGNOSTIC, diag)
    _write_postmortem(diag, meta)

    freeze_rc = freeze_main()
    if freeze_rc != 0:
        print("cohort freeze failed", file=sys.stderr)
        return freeze_rc
    audit_rc = audit_main()
    if audit_rc != 0:
        print("audit doc write failed", file=sys.stderr)
        return audit_rc

    print(json.dumps({
        "RUN_COMPLETE": "YES",
        "CANONICAL_N": meta["canonical_n"],
        "CANONICALLY_ADMITTED": meta["canonically_admitted"],
        "TOTAL_REAL_PRICE_PRINTS": meta["total_real_price_prints"],
        "PROOF_B_FAILURES": proof_b_failures,
        "RECONCILE": meta["reconcile"],
        "ADMITTED_DEALS_WITH_SECONDARY_OVERLAP": meta["admitted_deals_with_secondary_overlap"],
        "SPREAD_STRESS_V1_BLOCK_REASON": diag["SPREAD_STRESS_V1_BLOCK_REASON"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
