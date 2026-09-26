# Batch 9 audit — autonomous SEC corpus expansion (revolution 1)

## Contract flags

| Flag | Value |
|---|---|
| REAL MODEL FIT | NO |
| WALK-FORWARD | NO |
| CALIBRATION | NO |
| EVENT_RULES CHANGED | NO |
| FS_V1 CHANGED | NO |
| BREAK_LOGIT_V1 CHANGED | NO |
| HYPERPARAMETER_TUNING | NO |
| `execution_authorized` | false (unchanged) |

## Starting state

| Field | Value |
|---|---|
| START_MAIN_SHA | `e629d227d40a8b65fa5ef4cccb93097204d07f45` |
| START_N | 62 |
| START_Y0 | 43 |
| START_Y1 | 19 |
| START_CENSORED | 0 |

## Candidate process

| Field | Value |
|---|---|
| Selection | Outcome-blind EFTS chronological queue (`batch_1_candidate_queue.json`) |
| Queries | target-side equity M&A language + per-share consideration (no outcome terms) |
| Candidates in frozen queue | 400 |
| Examined | 400 |
| Admitted (final) | 3 |
| Excluded | 302 (+ post-filter demotions logged as DEFER) |
| Deferred | 93 (+ post-filter) |

Accuracy > batch size: stop at clean ADMITs rather than force 20.

## Admitted deals

| deal_id | target | acquirer | consideration | offer_price | resolution |
|---|---|---|---|---:|---|
| `DEAL-VOCUS-GTCR-2014` | Vocus, Inc. | GTCR Beltsville Holdings, LLC | cash | 18.00 | closed |
| `DEAL-COBRA-MONOMO-2014` | COBRA ELECTRONICS CORP | Monomoy Capital Partners | cash | 4.30 | closed |
| `DEAL-ANNIE-GENERA-2014` | Annie's, Inc. | General Mills | cash | 46.00 | closed |

## Ending state (this branch, pre-merge)

| Field | Value |
|---|---|
| END_N | 65 |
| END_Y0 | 46 |
| END_Y1 | 19 |
| END_CENSORED | 0 |
| sample_prevalence (canonical Y1/N) | 19/65 ≈ 0.2923 (**not** a population break probability) |

## Ledgers

- `data/review/batch_1_candidate_queue.json`
- `data/review/batch_1_admission_ledger.json`

## Validation

- Live `SECEdgarProvider` ingest of the 3 new rows: accepted=3, quarantined=0, rejected=0
- Full suite + dbt: see PR checks / commit notes

## Notes

- Fail-closed demotions included party-inversion (acquirer-side filings), dirty acquirer strings, cash `offer_price<=1`, and ambiguous close+terminate same-filing cases.
- Deferred deals are not terminal; they remain eligible for later revolutions if evidence improves or extraction is strengthened without weakening locked rules.
