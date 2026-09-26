# Batch 11 audit — autonomous SEC corpus expansion (revolution 3)

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
| START_MAIN_SHA | `be04642b9f63754992acf085e63857ce1b6ad3be` (Batch 10 merge) |
| START_N | 67 |
| START_Y0 | 48 |
| START_Y1 | 19 |
| START_CENSORED | 0 |

## Candidate process

| Field | Value |
|---|---|
| Selection | Outcome-blind EFTS chronological queue continuing past Batches 9–10 examined accessions |
| Candidates in frozen queue | 350 |
| Examined | 350 |
| Admitted (final) | 2 |
| Excluded | 270 |
| Deferred | 78 |

Accuracy > batch size: do not force 20.

## Admitted deals

| deal_id | target | acquirer | consideration | offer_price | resolution |
|---|---|---|---|---:|---|
| `DEAL-SCIQUE-ACCEL-2016` | SCIQUEST INC | Accel-KKR | cash | 17.75 | closed |
| `DEAL-IMPRIV-THOMA-2016` | Imprivata Inc | Thoma Bravo | cash | 19.25 | closed |

## Ending state (this branch, pre-merge)

| Field | Value |
|---|---|
| END_N | 69 |
| END_Y0 | 50 |
| END_Y1 | 19 |
| END_CENSORED | 0 |
| sample_prevalence (canonical Y1/N) | 19/69 ≈ 0.2754 (**not** a population break probability) |

## Ledgers

- `data/review/batch_3_candidate_queue.json`
- `data/review/batch_3_admission_ledger.json`

## Validation

- Live `SECEdgarProvider` ingest of the 2 new rows: accepted=2, quarantined=0, rejected=0
- Full suite + dbt: see PR checks
