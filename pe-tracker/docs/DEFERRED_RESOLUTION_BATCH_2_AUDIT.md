# Deferred-resolution batch 2 audit

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
| START_MAIN_SHA | `fd0a2c72102bec7b8ec6451a3b1110803f01ec5c` (batch 1 merge) |
| START_N | 89 |
| START_Y0 | 69 |
| START_Y1 | 20 |
| START_CENSORED | 0 |
| START_DEFERRED_PENDING | 166 |

## Deferred process

| Field | Value |
|---|---|
| Selection | Chronological deferred queue continuing past batch 1 decisions |
| Deferred examined (this revolution) | 39 |
| Skipped already decided | 48 |
| Admitted | 20 |
| Excluded | 7 |
| Still deferred (this revolution) | 12 |
| Remaining PENDING in queue | 127 |

## Yield by prior defer class (ADMITs)

| Prior class | ADMITs |
|---|---:|
| `ACQUIRER_EXTRACTION` | 10 |
| `AMBIGUOUS_RESOLUTION_EVENT` | 8 |
| `SEC_TRANSIENT_FAILURE` | 2 |

## Admitted deals

| deal_id | target | acquirer | consideration | offer_price | resolution | prior_class |
|---|---|---|---|---:|---|---|
| `DEAL-SIGMA-MERCK-2014` | SIGMA ALDRICH CORP | Merck KGaA | cash | 140.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-TIBCO-VISTA-2014` | TIBCO SOFTWARE INC | VISTA EQUITY PARTNERS | cash | 24.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-EINSTE-JAB-2014` | EINSTEIN NOAH RESTAURANT GROUP INC | JAB Holding Company | cash | 20.25 | closed | ACQUIRER_EXTRACTION |
| `DEAL-CLECO-COMO-2014` | CLECO CORP | COMO 1 L.P | cash | 55.37 | closed | ACQUIRER_EXTRACTION |
| `DEAL-DIGITA-INVEST-2014` | DIGITAL RIVER INC /DE | Siris Capital Group | cash | 26.0 | closed | SEC_TRANSIENT_FAILURE |
| `DEAL-CHYRON-VECTOR-2014` | ChyronHego Corp | Vector Capital | cash | 2.82 | closed | SEC_TRANSIENT_FAILURE |
| `DEAL-OPLINK-KOCH-2014` | OPLINK COMMUNICATIONS INC | KOCH INDUSTRIES | cash | 24.25 | closed | ACQUIRER_EXTRACTION |
| `DEAL-AVANIR-OTSUKA-2014` | AVANIR PHARMACEUTICALS, INC. | OTSUKA PHARMACEUTICAL | cash | 17.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-MICROF-FORTRE-2014` | MICROFINANCIAL INC | Fortress Investment Group LLC | cash | 10.2 | closed | ACQUIRER_EXTRACTION |
| `DEAL-PEERLE-MOBIUS-2014` | PEERLESS SYSTEMS CORP | Mobius Acquisition, LLC | cash | 7.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-SILICO-LATTIC-2015` | SILICON IMAGE INC | Lattice Semiconductor Corporation | cash | 7.3 | closed | ACQUIRER_EXTRACTION |
| `DEAL-ATHLON-ENCANA-2014` | Athlon Energy Inc. | ENCANA CORPORATION | cash | 58.5 | closed | ACQUIRER_EXTRACTION |
| `DEAL-ELECSY-LINDSA-2014` | ELECSYS CORP | Lindsay | cash | 17.5 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-ENTROP-MAXLIN-2015` | ENTROPIC COMMUNICATIONS INC | MaxLinear | mixed | 1.2 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-E2OPEN-INSIGH-2015` | E2open Inc | Insight | cash | 8.6 | closed | ACQUIRER_EXTRACTION |
| `DEAL-ORBITZ-EXPEDI-2015` | Orbitz Worldwide, Inc. | Expedia, Inc | cash | 12.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-SAPIEN-PUBLIC-2014` | SAPIENT CORP | PUBLICIS GROUPE S.A | cash | 25.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-RIVERB-PROJEC-2014` | Riverbed Technology, Inc. | PROJECT HOMESTAKE HOLDINGS | cash | 21.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-ADVENT-SSCTEC-2015` | ADVENT SOFTWARE INC /DE/ | SS&C Technologies | cash | 44.25 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-SALIX-VALEAN-2015` | SALIX PHARMACEUTICALS LTD | VALEANT PHARMACEUTICALS INTERNATIONAL | cash | 158.0 | closed | ACQUIRER_EXTRACTION |

## Excluded (this revolution)

| target | announcement_accession | reason |
|---|---|---|
| Eos Petro, Inc. | `0001445866-14-001151` | REPRESENTABILITY_FAIL: could not faithfully map consideration under fs_v1 (cash_vals=[], ratio_vals=[]) |
| Islet Sciences, Inc | `0001354488-14-004931` | REPRESENTABILITY_FAIL: could not faithfully map consideration under fs_v1 (cash_vals=[], ratio_vals=[]) |
| Cardigant Medical Inc. | `0001144204-14-062361` | announcement text lacks clear equity M&A language |
| Athlon Energy Inc. | `0001104659-14-078406` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| INTEGRATED ENERGY SOLUTIONS, INC. | `0001469709-14-000509` | announcement text lacks clear equity M&A language |
| MICROFINANCIAL INC | `0001047469-14-009992` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| Aldeyra Therapeutics, Inc.  (ALDX) | `0001193125-15-008866` | announcement text lacks clear equity M&A language |

## Ending state (this branch, pre-merge)

| Field | Value |
|---|---|
| END_N | 109 |
| END_Y0 | 89 |
| END_Y1 | 20 |
| END_CENSORED | 0 |
| sample_prevalence (canonical Y1/N) | 20/109 ≈ 0.1835 (**not** a population break probability) |

## Validation

- Live `SECEdgarProvider` ingest of the 20 new rows: accepted=20, quarantined=0, rejected=0
- Full suite + dbt: see PR checks
