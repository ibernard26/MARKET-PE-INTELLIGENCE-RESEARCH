# Deferred-resolution batch 3 audit

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
| first_walkforward_v1 | frozen at N=62 |

## Starting state

| Field | Value |
|---|---|
| START_MAIN_SHA | `1088fcbe79d08fc7175f6cab9a0de2ce1715dd2a` (batch 2 merge) |
| START_N | 109 |
| START_Y0 | 89 |
| START_Y1 | 20 |
| START_CENSORED | 0 |
| START_DEFERRED_PENDING | 127 |

## Deferred process

| Field | Value |
|---|---|
| Selection | Chronological deferred queue continuing past batches 1–2 |
| Deferred examined (this revolution) | 41 |
| Skipped already decided | 87 |
| Admitted | 20 |
| Excluded | 3 |
| Still deferred (this revolution) | 19 |
| Remaining PENDING in queue | 86 |

## Yield by prior defer class (ADMITs)

| Prior class | ADMITs |
|---|---:|
| `ACQUIRER_EXTRACTION` | 10 |
| `AMBIGUOUS_RESOLUTION_EVENT` | 10 |

## Admitted deals

| deal_id | target | acquirer | consideration | offer_price | resolution | prior_class |
|---|---|---|---|---:|---|---|
| `DEAL-INFORM-ITALIC-2015` | INFORMATICA CORP | Italics Inc | cash | 48.75 | closed | ACQUIRER_EXTRACTION |
| `DEAL-EXCEL-BLACKS-2015` | Excel Trust, Inc. | Blackstone | cash | 15.85 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-DOVER-WEBSTE-2015` | DOVER SADDLERY INC | Webster Capital | cash | 8.5 | closed | ACQUIRER_EXTRACTION |
| `DEAL-PROCER-FRANCI-2015` | PROCERA NETWORKS, INC. | Francisco Partners | cash | 11.5 | closed | ACQUIRER_EXTRACTION |
| `DEAL-OMNIVI-HUA-2015` | OMNIVISION TECHNOLOGIES INC | HUA CAPITAL MANAGEMENT | cash | 29.75 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-BORDER-PITNEY-2015` | Borderfree, Inc. | Pitney Bowes Inc | cash | 14.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-QUALIT-FUNDS-2015` | QUALITY DISTRIBUTION INC | Apax Partners | cash | 16.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-ANN-ASCENA-2015` | ANN INC. | ASCENA RETAIL GROUP | cash | 50.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-FRISCH-NRD-2015` | FRISCHS RESTAURANTS INC | NRD Partners I, L.P | cash | 34.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-OM-APOLLO-2015` | OM GROUP INC | Apollo | cash | 34.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-NAUGAT-LIBERT-2015` | Naugatuck Valley Financial Corp | Liberty | cash | 11.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-INTEGR-UPHILL-2015` | INTEGRATED SILICON SOLUTION INC | Uphill Investment Co | cash | 21.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-COAST-LKQ-2015` | COAST DISTRIBUTION SYSTEM INC | LKQ CORPORATION | cash | 5.5 | closed | ACQUIRER_EXTRACTION |
| `DEAL-REMY-BORGWA-2015` | REMY INTERNATIONAL, INC. | BorgWarner Inc | cash | 29.5 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-STJUDE-SJM-2015` | ST JUDE MEDICAL INC | SJM International | cash | 63.5 | closed | ACQUIRER_EXTRACTION |
| `DEAL-TECUMS-MUELLE-2015` | TECUMSEH PRODUCTS CO | MUELLER | cash | 5.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-STEINE-CATTER-2015` | STEINER LEISURE Ltd | CATTERTON | cash | 65.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-BLYTH-CARLYL-2015` | BLYTH INC | The Carlyle Group | cash | 6.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-STRATE-BLACKS-2015` | STRATEGIC HOTELS & RESORTS, INC | BLACKSTONE | cash | 14.25 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-BIOMED-BLACKS-2015` | BioMed Realty Trust Inc | BLACKSTONE | cash | 23.75 | closed | AMBIGUOUS_RESOLUTION_EVENT |

## Excluded (this revolution)

| target | announcement_accession | reason |
|---|---|---|
| Clean Coal Technologies Inc.  (NSGP) | `0001185185-15-001565` | announcement text lacks clear equity M&A language |
| MUELLER INDUSTRIES INC  (MLI) | `0001140361-15-030477` | DUPLICATE_TRANSACTION: inverse/same economic pair already admitted |
| MUELLER INDUSTRIES INC  (MLI) | `0001140361-15-030477` | DUPLICATE_TRANSACTION: inverse/same economic pair |

## Ending state (this branch, pre-merge)

| Field | Value |
|---|---|
| END_N | 129 |
| END_Y0 | 109 |
| END_Y1 | 20 |
| END_CENSORED | 0 |
| sample_prevalence (canonical Y1/N) | 20/129 ≈ 0.1550 (**not** a population break probability) |

## Validation

- Live `SECEdgarProvider` ingest of the 20 new rows: accepted=20, quarantined=0, rejected=0
- Full suite + dbt: see PR checks
