# Batch 10 audit — autonomous SEC corpus expansion (revolution 2)

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
| START_MAIN_SHA | `dfcd462ca04b596072fe424945d6f884bfc47821` (Batch 9 merge) |
| START_N | 65 |
| START_Y0 | 46 |
| START_Y1 | 19 |
| START_CENSORED | 0 |

## Candidate process

| Field | Value |
|---|---|
| Selection | Outcome-blind EFTS chronological queue continuing past Batch 9 examined accessions |
| Candidates in frozen queue | 300 |
| Examined | 300 |
| Admitted (final) | 2 |
| Excluded | 257 |
| Deferred | 41 |

Accuracy > batch size: do not force 20.

## Admitted deals

| deal_id | target | acquirer | consideration | offer_price | resolution |
|---|---|---|---|---:|---|
| `DEAL-SABA-VECTOR-2015` | SABA SOFTWARE INC | Vector Capital | cash | 9.00 | closed |
| `DEAL-SUTRON-HACH-2015` | SUTRON CORP | Hach Company | cash | 8.50 | closed |

## Ending state (this branch, pre-merge)

| Field | Value |
|---|---|
| END_N | 67 |
| END_Y0 | 48 |
| END_Y1 | 19 |
| END_CENSORED | 0 |
| sample_prevalence (canonical Y1/N) | 19/67 ≈ 0.2836 (**not** a population break probability) |

## Ledgers

- `data/review/batch_2_candidate_queue.json`
- `data/review/batch_2_admission_ledger.json`

## Validation

- Live `SECEdgarProvider` ingest of the 2 new rows: accepted=2, quarantined=0, rejected=0
- Full suite + dbt: see PR checks

## Notes

- Prior Batch 9 examined accessions were skipped so the chronological stream advances.
- Many deferred rows remain acquirer-extraction failures (fail closed); they are not admitted.
