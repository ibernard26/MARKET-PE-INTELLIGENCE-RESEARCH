# Free thesis data stack — OpenFIGI + Tiingo + Yahoo

**ACTIVE** historical research stack for the thesis-data phase.

```
SEC EDGAR → deal identity
    → OpenFIGI (FIGI mapping)
    → Tiingo (primary EOD)
    → Yahoo (reconcile / fallback)
    → NormalizedEquityObservation
```

## Credential environment variables

| Variable | Role |
|---|---|
| `OPENFIGI_API_KEY` | OpenFIGI mapping |
| `TIINGO_API_TOKEN` | Tiingo EOD (`TIINGO_API_KEY` accepted as alias) |
| `SEC_USER_AGENT` | SEC company_tickers lookup |

Never commit values. Presence helpers return YES/NO only.

## CRSP freeze

| Flag | Value |
|---|---|
| CRSP_STATUS | `FROZEN_FUTURE_ROBUSTNESS_PROVIDER` |
| CRSP_ACTIVE_INGESTION | **NO** |
| CRSP_REQUIRED_FOR_THESIS | **NO** |

CRSP adapter/tests remain in-tree for future institutional replication.

## Provider precedence

1. Tiingo (when token present)
2. Yahoo
3. NO_HISTORY / CREDENTIALS_REQUIRED / DEFER

Yahoo observations are preserved for reconciliation. Conflicts are never averaged.

Reconciliation rule: `price_reconcile_v1` (`ABS_EPS=1e-4`, `REL_EPS=1e-6`).

## Commands

```bash
cd pe-tracker

# 1) Live smoke (exits 3 if credentials missing; never prints values)
python -m scripts.smoke_free_providers

# 2) Full 129-deal coverage + reconcile + audit docs
#    If ≥20 deals with ≥3 prints: freezes spread_stress_thesis_v1 cohort
#    Does NOT execute spread_stress / model fit
python -m scripts.run_free_price_coverage

# Offline regenerators (matrix must already exist):
python -m scripts.audit_free_price_coverage
python -m scripts.freeze_thesis_price_cohort   # gated on readiness
```

Writes:

- `data/free_price_coverage_matrix.json`
- `data/target_price_manifest.json` (normalized; license-safe free providers)
- `data/free_price_fetch_audit.json`
- `docs/TIINGO_YAHOO_PRICE_RECONCILIATION.md`
- `docs/HISTORICAL_PRICE_AVAILABILITY_BIAS_AUDIT.md`
- `data/spread_stress_thesis_v1_cohort.json` (only if gate passes)

## Gates

Keep ≥20 deals with ≥3 real prints. Do not auto-run `spread_stress` / model fit.

## Security-identity admission gate

Tickers get reused, especially across the 2014–2015 corpus. A ticker's prices
enter `target_price_manifest.json`, and so count toward the ≥20-deal readiness
gate, only when the ticker is shown to be the SEC target. The rule below was
fixed before any live provider data was seen.

- **Name rule** (`security_identity/name_match.names_agree`): drop legal-form
  and filler words. After that, one name's significant tokens must be a
  non-empty subset of the other's.
- **Tiingo:** the issuer name must agree with the SEC target name, and the
  listing interval `[startDate, endDate]` must cover the announcement date.
  Otherwise the result is `IDENTITY_AMBIGUOUS`, and no price call is made.
- **Orchestrator:** after `IDENTITY_AMBIGUOUS` it does **not** fall back to
  Yahoo on the same ticker.
- **OpenFIGI:** a single candidate whose name disagrees gives `NAME_MISMATCH`,
  never `MATCHED`.
- **Manifest admission** (`run_free_price_coverage.admit_prints`): prints are
  admitted only when there's no OpenFIGI `AMBIGUOUS`/`NAME_MISMATCH`, no Tiingo
  `IDENTITY_AMBIGUOUS`, and no material Tiingo/Yahoo conflict. OpenFIGI
  `NO_MATCH` is not negative evidence, because it's common for delisted names.
