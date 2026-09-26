# Deferred-resolution batch 1 audit

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
| START_MAIN_SHA | `1c477c8fa47c70ba6b27fe99a05beb2aea5e0a1d` |
| START_N | 69 |
| START_Y0 | 50 |
| START_Y1 | 19 |
| START_CENSORED | 0 |
| START_DEFERRED | 214 |

## Deferred process

| Field | Value |
|---|---|
| Selection | Chronological `deferred_resolution_queue.json` (batches 1–3 deferred) |
| Deferred examined | 48 |
| Admitted | 20 |
| Excluded | 10 |
| Still deferred (this revolution) | 18 |

Accuracy > throughput: stopped at 20 ADMITs after 48 examined (≤75).

## Yield by prior defer class (ADMITs)

| Prior class | ADMITs |
|---|---:|
| `ACQUIRER_EXTRACTION` | 14 |
| `AMBIGUOUS_RESOLUTION_EVENT` | 5 |
| `SEC_TRANSIENT_FAILURE` | 1 |

## Admitted deals

| deal_id | target | acquirer | consideration | offer_price | resolution | prior_class |
|---|---|---|---|---:|---|---|
| `DEAL-MATERI-NEW-2014` | MATERIAL SCIENCES CORP | New Star Metals | cash | 12.75 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-AMERIC-HIGLAS-2014` | AMERICAN PACIFIC CORP | H.I.G. LAS VEGAS | cash | 46.5 | closed | ACQUIRER_EXTRACTION |
| `DEAL-BEAM-SUNTOR-2014` | BEAM INC | Suntory | cash | 83.5 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-CEC-APOLLO-2014` | CEC ENTERTAINMENT INC | Apollo Global Management | cash | 54.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-AMCOL-IMERYS-2014` | AMCOL INTERNATIONAL CORP | IMERYS SA | cash | 41.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-COLE-AMERIC-2014` | Cole Credit Property Trust Inc | American Realty Capital Properties | cash | 7.25 | closed | ACQUIRER_EXTRACTION |
| `DEAL-DFC-LONE-2014` | DFC GLOBAL CORP. | Lone Star Funds | cash | 9.5 | closed | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-ZYGO-AMETEK-2014` | ZYGO CORP | AMETEK | cash | 19.25 | closed | ACQUIRER_EXTRACTION |
| `DEAL-POKERT-MULTIM-2014` | POKERTEK, INC. | MULTIMEDIA GAMES | cash | 1.35 | closed | ACQUIRER_EXTRACTION |
| `DEAL-BARRY-MRGB-2014` | BARRY R G CORP /OH/ | MRGB HOLD CO | cash | 19.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-MKTG-AEGIS-2014` | 'mktg, inc.' | Aegis Lifestyle | cash | 2.8 | closed | ACQUIRER_EXTRACTION |
| `DEAL-HILLSH-TYSON-2014` | Hillshire Brands Co | TYSON FOODS | cash | 63.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-VITACO-KROGER-2014` | Vitacost.com, Inc. | Kroger | cash | 8.0 | closed | SEC_TRANSIENT_FAILURE |
| `DEAL-LORILL-IMPERI-2014` | LORILLARD, INC. | Imperial | cash | 68.88 | closed | ACQUIRER_EXTRACTION |
| `DEAL-REYNOL-IMPERI-2014` | REYNOLDS AMERICAN INC | Imperial | cash | 68.88 | closed | ACQUIRER_EXTRACTION |
| `DEAL-SYMMET-TECOST-2014` | Symmetry Medical Inc. | TECOSTAR HOLDINGS | cash | 7.5 | withdrawn | AMBIGUOUS_RESOLUTION_EVENT |
| `DEAL-INTERM-ROCHE-2014` | INTERMUNE INC | Roche | cash | 74.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-BOLT-TELEDY-2014` | BOLT TECHNOLOGY CORP | Teledyne | cash | 22.0 | closed | ACQUIRER_EXTRACTION |
| `DEAL-TRW-ZFFRIE-2014` | TRW AUTOMOTIVE HOLDINGS CORP | ZF Friedrichshafen | cash | 105.6 | closed | ACQUIRER_EXTRACTION |
| `DEAL-TAMINC-EASTMA-2014` | TAMINCO Corp | Eastman Chemical Company | cash | 26.0 | closed | AMBIGUOUS_RESOLUTION_EVENT |

## Excluded (this revolution)

| target | announcement_accession | reason |
|---|---|---|
| ARTHROCARE CORP | `0001104659-14-006023` | REPRESENTABILITY_FAIL: could not faithfully map consideration under fs_v1 (cash_vals=[], ratio_vals=[]) |
| Excel Corp | `0001213900-14-001050` | announcement text lacks clear equity M&A language |
| AMCOL INTERNATIONAL CORP | `0001193125-14-071339` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| AMCOL INTERNATIONAL CORP | `0001193125-14-083388` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| Alphatec Holdings, Inc.  (ATEC) | `0001193125-14-104806` | announcement text lacks clear equity M&A language |
| Vertex Energy Inc.  (VTNR) | `0001580695-14-000243` | announcement text lacks clear equity M&A language |
| TELIK INC | `0001193125-14-195206` | REPRESENTABILITY_FAIL: could not faithfully map consideration under fs_v1 (cash_vals=[], ratio_vals=[]) |
| Marathon Patent Group, Inc.  (MARA) | `0001415889-14-001541` | announcement text lacks clear equity M&A language |
| DFC GLOBAL CORP. | `0001193125-14-236294` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| SUN COMMUNITIES INC  (SUI) | `0000912593-14-000069` | party inversion: extracted acquirer is the acquiree in 'will acquire' prose |

## Ending state (this branch, pre-merge)

| Field | Value |
|---|---|
| END_N | 89 |
| END_Y0 | 69 |
| END_Y1 | 20 |
| END_CENSORED | 0 |
| sample_prevalence (canonical Y1/N) | 20/89 ≈ 0.2247 (**not** a population break probability) |

## Engineering notes

- SEC fetch: bounded retry + on-disk cache (`data/review/_sec_cache/`).
- Acquirer: multi-source extraction; reject shell/role words and verb residue.
- Resolution: 5y post-announcement window; later close may supersede earlier break;
  later break after earlier close → DEFER (contradictory).
- Duplicate `target_cik` excluded within revolution.

## Ledgers

- `data/review/deferred_resolution_queue.json`
- `data/review/deferred_resolution_batch_1_ledger.json`
- `docs/DEFERRED_BACKLOG_BASELINE.md`

## Validation

- Live `SECEdgarProvider` ingest of the 20 new rows: accepted=20, quarantined=0, rejected=0
- Full suite + dbt: see PR checks
