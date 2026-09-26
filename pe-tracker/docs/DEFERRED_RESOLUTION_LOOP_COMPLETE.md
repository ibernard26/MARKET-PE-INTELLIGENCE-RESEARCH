# DEFERRED_RESOLUTION_LOOP_COMPLETE

**DEFERRED_RESOLUTION_LOOP_COMPLETE = YES**

Stop condition: **A** — 3 deferred-resolution revolutions complete.

## Starting

| Field | Value |
|---|---|
| MAIN_SHA | `1c477c8fa47c70ba6b27fe99a05beb2aea5e0a1d` |
| N | 69 |
| Y0 | 50 |
| Y1 | 19 |
| CENSORED | 0 |
| DEFERRED | 214 unique |

## Revolutions

| Rev | Examined | ADMIT | EXCLUDE | DEFER | PR | Merge SHA | Ending N | Ending Y0 | Ending Y1 | pytest | dbt | SEC ingest |
|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|---|---|
| 1 | 48 | 20 | 10 | 18 | #27 | `fd0a2c7` | 89 | 69 | 20 | PASS | PASS | 20/0/0 |
| 2 | 39 | 20 | 7 | 12 | #28 | `1088fcb` | 109 | 89 | 20 | PASS | PASS | 20/0/0 |
| 3 | 41 | 20 | 3 | 19 | #29 | `263ef78` | 129 | 109 | 20 | PASS | PASS | 20/0/0 |

## Final

| Field | Value |
|---|---|
| FINAL_MAIN_SHA | `263ef78ed31a128797f1a9d596964ba8e613a648` |
| FINAL_N | 129 |
| FINAL_Y0 | 109 |
| FINAL_Y1 | 20 (terminated=19, withdrawn=1) |
| FINAL_CENSORED | 0 |
| FINAL_DEFERRED | PENDING=86, DEFER=49, EXCLUDE=19; unique backlog 214 → 135 unresolved |

## Contract flags

| Flag | Value |
|---|---|
| EVENT_RULES_CHANGED | NO |
| FS_V1_CHANGED | NO |
| BREAK_LOGIT_V1_CHANGED | NO |
| REAL_MODEL_FIT_EXECUTED | NO |
| WALK_FORWARD_EXECUTED | NO |
| CALIBRATION_EXECUTED | NO |
| HYPERPARAMETER_TUNING | NO |
| execution_authorized | false |
| first_walkforward_v1 | frozen at N=62 |

## Newly admitted deals (60)

| Rev | deal_id | target | acquirer | resolution | prior_class |
|---:|---|---|---|---|---|
| 1 | `DEAL-MATERI-NEW-2014` | MATERIAL SCIENCES CORP | New Star Metals | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 1 | `DEAL-AMERIC-HIGLAS-2014` | AMERICAN PACIFIC CORP | H.I.G. LAS VEGAS | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-BEAM-SUNTOR-2014` | BEAM INC | Suntory | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 1 | `DEAL-CEC-APOLLO-2014` | CEC ENTERTAINMENT INC | Apollo Global Management | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-AMCOL-IMERYS-2014` | AMCOL INTERNATIONAL CORP | IMERYS SA | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-COLE-AMERIC-2014` | Cole Credit Property Trust Inc | American Realty Capital Properties | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-DFC-LONE-2014` | DFC GLOBAL CORP. | Lone Star Funds | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 1 | `DEAL-ZYGO-AMETEK-2014` | ZYGO CORP | AMETEK | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-POKERT-MULTIM-2014` | POKERTEK, INC. | MULTIMEDIA GAMES | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-BARRY-MRGB-2014` | BARRY R G CORP /OH/ | MRGB HOLD CO | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-MKTG-AEGIS-2014` | 'mktg, inc.' | Aegis Lifestyle | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-HILLSH-TYSON-2014` | Hillshire Brands Co | TYSON FOODS | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-VITACO-KROGER-2014` | Vitacost.com, Inc. | Kroger | closed | SEC_TRANSIENT_FAILURE |
| 1 | `DEAL-LORILL-IMPERI-2014` | LORILLARD, INC. | Imperial | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-REYNOL-IMPERI-2014` | REYNOLDS AMERICAN INC | Imperial | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-SYMMET-TECOST-2014` | Symmetry Medical Inc. | TECOSTAR HOLDINGS | withdrawn | AMBIGUOUS_RESOLUTION_EVENT |
| 1 | `DEAL-INTERM-ROCHE-2014` | INTERMUNE INC | Roche | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-BOLT-TELEDY-2014` | BOLT TECHNOLOGY CORP | Teledyne | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-TRW-ZFFRIE-2014` | TRW AUTOMOTIVE HOLDINGS CORP | ZF Friedrichshafen | closed | ACQUIRER_EXTRACTION |
| 1 | `DEAL-TAMINC-EASTMA-2014` | TAMINCO Corp | Eastman Chemical Company | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 2 | `DEAL-SIGMA-MERCK-2014` | SIGMA ALDRICH CORP | Merck KGaA | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 2 | `DEAL-TIBCO-VISTA-2014` | TIBCO SOFTWARE INC | VISTA EQUITY PARTNERS | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 2 | `DEAL-EINSTE-JAB-2014` | EINSTEIN NOAH RESTAURANT GROUP INC | JAB Holding Company | closed | ACQUIRER_EXTRACTION |
| 2 | `DEAL-CLECO-COMO-2014` | CLECO CORP | COMO 1 L.P | closed | ACQUIRER_EXTRACTION |
| 2 | `DEAL-DIGITA-INVEST-2014` | DIGITAL RIVER INC /DE | Siris Capital Group | closed | SEC_TRANSIENT_FAILURE |
| 2 | `DEAL-CHYRON-VECTOR-2014` | ChyronHego Corp | Vector Capital | closed | SEC_TRANSIENT_FAILURE |
| 2 | `DEAL-OPLINK-KOCH-2014` | OPLINK COMMUNICATIONS INC | KOCH INDUSTRIES | closed | ACQUIRER_EXTRACTION |
| 2 | `DEAL-AVANIR-OTSUKA-2014` | AVANIR PHARMACEUTICALS, INC. | OTSUKA PHARMACEUTICAL | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 2 | `DEAL-MICROF-FORTRE-2014` | MICROFINANCIAL INC | Fortress Investment Group LLC | closed | ACQUIRER_EXTRACTION |
| 2 | `DEAL-PEERLE-MOBIUS-2014` | PEERLESS SYSTEMS CORP | Mobius Acquisition, LLC | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 2 | `DEAL-SILICO-LATTIC-2015` | SILICON IMAGE INC | Lattice Semiconductor Corporation | closed | ACQUIRER_EXTRACTION |
| 2 | `DEAL-ATHLON-ENCANA-2014` | Athlon Energy Inc. | ENCANA CORPORATION | closed | ACQUIRER_EXTRACTION |
| 2 | `DEAL-ELECSY-LINDSA-2014` | ELECSYS CORP | Lindsay | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 2 | `DEAL-ENTROP-MAXLIN-2015` | ENTROPIC COMMUNICATIONS INC | MaxLinear | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 2 | `DEAL-E2OPEN-INSIGH-2015` | E2open Inc | Insight | closed | ACQUIRER_EXTRACTION |
| 2 | `DEAL-ORBITZ-EXPEDI-2015` | Orbitz Worldwide, Inc. | Expedia, Inc | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 2 | `DEAL-SAPIEN-PUBLIC-2014` | SAPIENT CORP | PUBLICIS GROUPE S.A | closed | ACQUIRER_EXTRACTION |
| 2 | `DEAL-RIVERB-PROJEC-2014` | Riverbed Technology, Inc. | PROJECT HOMESTAKE HOLDINGS | closed | ACQUIRER_EXTRACTION |
| 2 | `DEAL-ADVENT-SSCTEC-2015` | ADVENT SOFTWARE INC /DE/ | SS&C Technologies | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 2 | `DEAL-SALIX-VALEAN-2015` | SALIX PHARMACEUTICALS LTD | VALEANT PHARMACEUTICALS INTERNATION | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-INFORM-ITALIC-2015` | INFORMATICA CORP | Italics Inc | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-EXCEL-BLACKS-2015` | Excel Trust, Inc. | Blackstone | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 3 | `DEAL-DOVER-WEBSTE-2015` | DOVER SADDLERY INC | Webster Capital | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-PROCER-FRANCI-2015` | PROCERA NETWORKS, INC. | Francisco Partners | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-OMNIVI-HUA-2015` | OMNIVISION TECHNOLOGIES INC | HUA CAPITAL MANAGEMENT | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 3 | `DEAL-BORDER-PITNEY-2015` | Borderfree, Inc. | Pitney Bowes Inc | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-QUALIT-FUNDS-2015` | QUALITY DISTRIBUTION INC | Apax Partners | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 3 | `DEAL-ANN-ASCENA-2015` | ANN INC. | ASCENA RETAIL GROUP | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-FRISCH-NRD-2015` | FRISCHS RESTAURANTS INC | NRD Partners I, L.P | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 3 | `DEAL-OM-APOLLO-2015` | OM GROUP INC | Apollo | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-NAUGAT-LIBERT-2015` | Naugatuck Valley Financial Corp | Liberty | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-INTEGR-UPHILL-2015` | INTEGRATED SILICON SOLUTION INC | Uphill Investment Co | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-COAST-LKQ-2015` | COAST DISTRIBUTION SYSTEM INC | LKQ CORPORATION | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-REMY-BORGWA-2015` | REMY INTERNATIONAL, INC. | BorgWarner Inc | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 3 | `DEAL-STJUDE-SJM-2015` | ST JUDE MEDICAL INC | SJM International | closed | ACQUIRER_EXTRACTION |
| 3 | `DEAL-TECUMS-MUELLE-2015` | TECUMSEH PRODUCTS CO | MUELLER | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 3 | `DEAL-STEINE-CATTER-2015` | STEINER LEISURE Ltd | CATTERTON | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 3 | `DEAL-BLYTH-CARLYL-2015` | BLYTH INC | The Carlyle Group | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 3 | `DEAL-STRATE-BLACKS-2015` | STRATEGIC HOTELS & RESORTS, INC | BLACKSTONE | closed | AMBIGUOUS_RESOLUTION_EVENT |
| 3 | `DEAL-BIOMED-BLACKS-2015` | BioMed Realty Trust Inc | BLACKSTONE | closed | AMBIGUOUS_RESOLUTION_EVENT |

## Newly excluded (ledger)

| Rev | announcement_accession | reason |
|---:|---|---|
| 1 | `0001104659-14-006023` | REPRESENTABILITY_FAIL: could not faithfully map consideration under fs_v1 (cash_vals=[], ratio_vals= |
| 1 | `0001213900-14-001050` | announcement text lacks clear equity M&A language |
| 1 | `0001193125-14-071339` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| 1 | `0001193125-14-083388` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| 1 | `0001193125-14-104806` | announcement text lacks clear equity M&A language |
| 1 | `0001580695-14-000243` | announcement text lacks clear equity M&A language |
| 1 | `0001193125-14-195206` | REPRESENTABILITY_FAIL: could not faithfully map consideration under fs_v1 (cash_vals=[], ratio_vals= |
| 1 | `0001415889-14-001541` | announcement text lacks clear equity M&A language |
| 1 | `0001193125-14-236294` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| 1 | `0000912593-14-000069` | party inversion: extracted acquirer is the acquiree in 'will acquire' prose |
| 2 | `0001445866-14-001151` | REPRESENTABILITY_FAIL: could not faithfully map consideration under fs_v1 (cash_vals=[], ratio_vals= |
| 2 | `0001354488-14-004931` | REPRESENTABILITY_FAIL: could not faithfully map consideration under fs_v1 (cash_vals=[], ratio_vals= |
| 2 | `0001144204-14-062361` | announcement text lacks clear equity M&A language |
| 2 | `0001104659-14-078406` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| 2 | `0001469709-14-000509` | announcement text lacks clear equity M&A language |
| 2 | `0001047469-14-009992` | DUPLICATE_TRANSACTION: target_cik already in canonical corpus or batch |
| 2 | `0001193125-15-008866` | announcement text lacks clear equity M&A language |
| 3 | `0001185185-15-001565` | announcement text lacks clear equity M&A language |
| 3 | `0001140361-15-030477` | DUPLICATE_TRANSACTION: inverse/same economic pair already admitted |
| 3 | `0001140361-15-030477` | DUPLICATE_TRANSACTION: inverse/same economic pair |

## Unresolved deferred categories (PENDING+DEFER)

| Class | N |
|---|---:|
| `ACQUIRER_EXTRACTION` | 84 |
| `AMBIGUOUS_RESOLUTION_EVENT` | 42 |
| `SEC_TRANSIENT_FAILURE` | 8 |
| `TERMS_EXTRACTION` | 1 |

## Top remaining engineering bottlenecks

1. **ACQUIRER_EXTRACTION** — dominant residual; needs deeper EX-2.1 / Form 425 party parsing without guessing.
2. **AMBIGUOUS_RESOLUTION_EVENT** — mixed close/terminate timelines remain fail-closed DEFER when later break follows earlier close.
3. **SEC_TRANSIENT_FAILURE** — reduced via cache/backoff; some filings still unavailable after bounded retries.
4. **TERMS_EXTRACTION** — EV/aggregate misreads guarded; non-fs_v1 consideration still EXCLUDE.

See `DEFERRED_BACKLOG_REMAINDER.md`. Fresh large-scale EFTS scanning remains paused (PENDING ≥ 50).
