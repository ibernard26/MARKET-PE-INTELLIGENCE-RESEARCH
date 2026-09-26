# Batch 8 — Reviewer packets (five unresolved deals)

**Status:** advisory only.  
**Canonical writes:** none.  
`sec_deal_manifest.json`, `EVENT_RULES`, and `fs_v1` were **not** modified.

**Corpus context (unchanged):** N = 24 reviewer-approved deals on `main`.  
**Batch 8 ingestion:** not authorized by this document.

**Locked classifiers used for scoring:**

| Contract | Rule |
|---|---|
| `EVENT_RULES` announcement | 8-K/A with Item **1.01**, or form **425** |
| `EVENT_RULES` closed | 8-K/A with Item **2.01**, or **25-NSE** / **15-12B** / **15-12G** |
| `EVENT_RULES` terminated | 8-K/A with Item **1.02** only |
| `EVENT_RULES` withdrawn | 8-K/A with Item **1.02** or **8.01**, or form **RW** |
| `fs_v1` consideration | cash → `offer_price`; stock → `exchange_ratio` × acquirer; mixed → cash + ratio × acquirer. No election/proration/VWAP fields. |

**Evidence method:** SEC EDGAR submissions metadata (`data.sec.gov`) + primary filing HTML on `www.sec.gov`, retrieved for this packet build. Accession numbers and Item tags are from EDGAR metadata unless noted as prose read from the filing body/exhibit.

**Disposition vocabulary (advisory):**

- **ADMIT** — under current locked rules, a reviewer can admit with the cited accessions and announcement-time terms.
- **EXCLUDE** — under current locked rules, the deal cannot be admitted without changing rules or fabricating a false simple consideration.
- **DEFER** — evidence is incomplete or a human must choose among rule-compliant interpretations before admission.

`CANONICAL_INGESTION_AUTHORIZED_BY_AGENT = NO`

---

## DEAL-KLAC-LRCX-2015

| Field | Value |
|---|---|
| Target / CIK | KLA-Tencor Corporation / **319201** |
| Acquirer | Lam Research Corporation |
| Valid-time announce (prose) | Agreement dated **2015-10-20** (Item 1.01 body) |
| EDGAR known_at (announce) | `2015-10-21T10:09:08` (naive; Z stripped per provider caveat) |

### 1. Announcement accession
`0001193125-15-348701` — Form **8-K**, items **1.01, 8.01, 9.01**, filed 2015-10-21.  
Archive: `https://www.sec.gov/Archives/edgar/data/319201/000119312515348701/`  
**EVENT_RULES announcement:** PASS (Item 1.01).

### 2. Terms accession
Same filing `0001193125-15-348701` (EX-2.1 merger agreement `d56926dex21.htm`; body `d56926d8k.htm`; press EX-99.1).

### 3. Original announcement-time consideration
**Not a single fixed cash price or fixed exchange ratio.**

From Item 1.01 / EX-2.1 / EX-99.1 (read from EDGAR HTML):

- **Mixed election (default):** $32.00 cash **plus** 0.5 Lam Research share.
- **Cash election:** $32.00 **plus** 0.5 × five-day **VWAP** of Lam Research (prorated).
- **Stock election:** economically inverse of the cash election using the same VWAP (prorated).
- Press framing: elections among all-cash / all-stock / mixed, **subject to proration**; illustrative headline values (e.g. ~$61.15 / ~1.0311×) are **VWAP-path dependent**, not a fixed `offer_price` + `exchange_ratio` pair.

### 4. Amendments and amendment dates
No separate merger-agreement amendment 8-K was required for this exclusion analysis. Deal ended by mutual termination (below).

### 5. Resolution accession
`0000319201-16-000095` — Form **8-K**, items **1.02, 8.01, 9.01**, filed 2016-10-06; acceptance `2016-10-06T10:38:26`.  
Archive: `https://www.sec.gov/Archives/edgar/data/319201/000031920116000095/`

### 6. SEC Item number for resolution
**Item 1.02** — Termination Agreement dated **2016-10-05** between KLA-Tencor and Lam Research; no termination fees.

### 7. Point-in-time implications
- Announcement known_at = acceptance of `0001193125-15-348701`.
- Even at announcement time, the economic offer is an **election + proration + VWAP** object.
- Collapsing that object into a single `offer_price` / `exchange_ratio` would invent a false announcement-time state for `fs_v1` (affects `pct_spread`, `annualized_spread`, `is_all_cash`, mixed `offer_value`).

### 8. Faithful under current `fs_v1`?
**NO.** `fs_v1` has no fields for elections, proration, or VWAP cash-election mechanics.

### 9. Current `EVENT_RULES` classify resolution?
**YES — terminated** via Item **1.02**.

### 10. Unresolved ambiguity
Whether any future schema could encode elections is out of scope. Under **locked** `fs_v1`, representation is impossible without fabrication.

### 11. Recommended disposition
**EXCLUDE**

---

## DEAL-AKRX-FRESENIUS-2017

| Field | Value |
|---|---|
| Target / CIK | Akorn, Inc. / **3116** |
| Acquirer | Fresenius Kabi AG (Fresenius SE & Co. KGaA for limited purposes) |
| Valid-time announce (prose) | Merger Agreement dated **2017-04-24** |
| EDGAR known_at (announce) | `2017-04-24T17:16:28` |

### 1. Announcement accession
`0000950157-17-000499` — Form **8-K**, items **1.01, 2.02, 5.03, 8.01, 9.01**, filed 2017-04-24.  
Archive: `https://www.sec.gov/Archives/edgar/data/3116/000095015717000499/`  
**EVENT_RULES announcement:** PASS (Item 1.01).

### 2. Terms accession
Same filing `0000950157-17-000499` (body `form8k.htm`; EX-2.1 `ex2-1.htm`).

### 3. Original announcement-time consideration
**All cash $34.00 per share** (Item 1.01 body and EX-2.1 “Merger Consideration”).  
`fs_v1`: `consideration_type=cash`, `offer_price=34.00`.

### 4. Amendments and amendment dates
No admitted amendment that restores a target Item **1.02** termination filing. Later Akorn 8-Ks in 2018 discuss dispute / possible termination under **Item 8.01** only (see below).

### 5. Resolution accession
**None that satisfy locked `terminated`.**

Candidate dispute / status 8-Ks (Item **8.01**, not 1.02), target CIK 3116:

| Filing date | Accession | Items (EDGAR) | Role |
|---|---|---|---|
| 2018-04-23 | `0000950157-18-000454` | 8.01, 9.01 | Press / forward-looking language about circumstances that could give rise to termination |
| 2018-04-23 | `0000950157-18-000456` | 8.01, 9.01 | Same class |
| 2018-10-01 | `0000950157-18-001017` | 8.01, 9.01 | Same class |

Submissions scan over 2017-04-01 → 2019-06-01: **zero** target 8-K with Item **1.02**.

### 6. SEC Item number for resolution
**Missing for `terminated`.** Available filings are **Item 8.01**, not Item 1.02.

### 7. Point-in-time implications
- Announcement-time cash terms are clean and representable.
- Outcome label cannot be written through `SECEdgarProvider` as `terminated` without a verified Item 1.02 accession.
- Treating Item 8.01 “seeking / possible termination / litigation” language as the resolution event would change event semantics.
- Re-labeling as `withdrawn` (which allows Item 8.01) is a **human rule-application decision**, not something this packet authorizes.

### 8. Faithful under current `fs_v1`?
**YES** for announcement terms (cash $34.00).  
Blocked on **resolution provenance**, not feature schema.

### 9. Current `EVENT_RULES` classify resolution?
**NO for `terminated`** (requires Item 1.02).  
**Not automatically `withdrawn`** without explicit reviewer authorization that a specific Item 8.01 filing is the withdrawal event.

### 10. Unresolved ambiguity
Whether Fresenius-side filings, court judgments, or a particular Akorn Item 8.01 should be treated as `withdrawn` under locked rules. Agent must not equate Item 8.01 dispute text with Item 1.02 termination.

### 11. Recommended disposition
**EXCLUDE** under current `EVENT_RULES` as written for `terminated`.  
(If Isaiah later authorizes a specific `withdrawn` + Item 8.01 accession, that would be a new human decision — still not ingestion authority from this packet.)

---

## DEAL-LLTC-ADI-2016

| Field | Value |
|---|---|
| Target / CIK | Linear Technology Corporation / **791907** |
| Acquirer | Analog Devices, Inc. |
| Valid-time announce (prose) | Merger Agreement dated **2016-07-26** (Item 8.01 body) |
| Close valid time (prose) | Merger completed **2017-03-10** (Item 2.01) |

### 1. Announcement accession
**No target Item 1.01** appears in EDGAR submissions for this merger window.

Rule-compliant announcement candidates are **Form 425** filings on 2016-07-26, e.g.:

- `0001193125-16-658273` — Form **425**, acceptance `2016-07-26T17:08:37`

Same-day target **8-K** `0001193125-16-658272` is items **8.01, 9.01** only (press release + “entered into Merger Agreement” under Other Events — **not** Item 1.01).

**EVENT_RULES announcement:** PASS **if** a Form **425** is used as `announcement_accession`; FAIL if the 8.01-only 8-K is used as the announcement event.

### 2. Terms accession
Recommended citation for reviewer-read terms:

- `0001193125-16-658272` EX-99.1 (joint press release: **$46.00 cash + 0.2321 ADI share**), and/or
- Closing 8-K Item 2.01 confirmation of the same pair (below).

`terms_accession` is not Item-validated by the provider, but a human must still accept the prose source.

### 3. Original announcement-time consideration
**Mixed:** `$46.00` cash **+** exchange ratio **`0.2321`** ADI share per LLTC share.  
`fs_v1`: `consideration_type=mixed`, `offer_price=46.00`, `exchange_ratio=0.2321`.

### 4. Amendments and amendment dates
No amendment that changes the $46.00 / 0.2321 pair was required for close; closing 8-K restates the same consideration.

### 5. Resolution accession
`0001193125-17-078946` — Form **8-K**, items include **2.01**, filed 2017-03-10; acceptance `2017-03-10T17:09:02`.  
Also Form **25-NSE** `0001354457-17-000054` (2017-03-10) and **15-12G** `0001193125-17-088491` (2017-03-20).

### 6. SEC Item number for resolution
**Item 2.01** (completion). Supporting **25-NSE** / **15-12G** also satisfy `closed`.

### 7. Point-in-time implications
- Feature time should be the knowable announcement instant from the chosen **425** (or later of valid/known times per pipeline rules).
- Absence of Item 1.01 means the definitive-agreement 8-K path used for most corpus deals is missing; terms come from 425 / 8.01 press / closing restatement.
- Closing restates consideration identical to the press release — good for consistency, but does not create announcement-time Item 1.01.

### 8. Faithful under current `fs_v1`?
**YES** — fixed mixed cash + ratio, no elections.

### 9. Current `EVENT_RULES` classify resolution?
**YES — closed** via Item **2.01** (and/or 25-NSE / 15-12G).

### 10. Unresolved ambiguity
Human must accept:

1. Form **425** as the announcement event (no Item 1.01), and  
2. Terms read from EX-99.1 / closing Item 2.01 rather than an Item 1.01 exhibit.

### 11. Recommended disposition
**DEFER** (awaiting reviewer sign-off on announcement/terms provenance).

---

## DEAL-RAD-WBA-2015

| Field | Value |
|---|---|
| Target / CIK | Rite Aid Corporation / **84129** |
| Acquirer | Walgreens Boots Alliance, Inc. |
| Valid-time announce (prose) | Merger Agreement dated **2015-10-27** |
| EDGAR known_at (announce) | `2015-10-29T06:09:17` |

### 1. Announcement accession
`0001104659-15-073813` — Form **8-K**, items **1.01, 9.01**, filed 2015-10-29.  
Archive: `https://www.sec.gov/Archives/edgar/data/84129/000110465915073813/`  
**EVENT_RULES announcement:** PASS (Item 1.01).

### 2. Terms accession
Same filing `0001104659-15-073813`.

### 3. Original announcement-time consideration
**All cash $9.00 per share** (Item 1.01: “Per Share Merger Consideration”).  
`fs_v1`: `consideration_type=cash`, `offer_price=9.00`.

### 4. Amendments and amendment dates

| Date (prose / filing) | Accession | What changed |
|---|---|---|
| 2016-12-19 / filed 2016-12-20 | `0001104659-16-162913` (items 1.01, 7.01, 9.01) | **Asset Purchase Agreement** (store divestiture remedy structure with Fred’s / WBA involvement) — **not** a restatement of per-share merger cash as the announcement feature |
| 2017-01-29 / filed 2017-01-30 | `0001104659-17-004997` (items 1.01, 8.01, 9.01) | **Amendment No. 1** to Merger Agreement: **$9.00 → $7.00** per share (with divestiture-linked downward adjustment, floor **$6.50**) |
| 2017-06-28 / filed 2017-06-29 | `0001104659-17-042360` (items 1.01, 1.02, …) | Same 8-K: (a) **Item 1.02** terminates the WBA merger; (b) **Item 1.01** enters a **new** WBA Asset Purchase Agreement for 2,186 stores (~$5.175B) |

### 5. Resolution accession
`0001104659-17-042360` — Form **8-K**, includes Item **1.02**, filed 2017-06-29; acceptance `2017-06-29T08:55:55`.  
Archive: `https://www.sec.gov/Archives/edgar/data/84129/000110465917042360/`

### 6. SEC Item number for resolution
**Item 1.02** — Merger Termination Agreement dated **2017-06-28**; WBA pays **$325,000,000** termination fee.  
(Do not confuse with same-day Item 1.01 store APA.)

### 7. Point-in-time implications
- Locked PIT feature construction uses announcement knowable time → **$9.00**, not the later $7.00 amendment.
- Label y=1 from Item 1.02 termination of the **merger** agreement.
- Concurrent/related store APAs are separate contracts; they must not overwrite announcement merger terms or be treated as the resolution of the merger unless the reviewer redesigns the deal object.

### 8. Faithful under current `fs_v1`?
**YES** for announcement-time cash $9.00.

### 9. Current `EVENT_RULES` classify resolution?
**YES — terminated** via Item **1.02**.

### 10. Unresolved ambiguity
Human must explicitly confirm:

1. Announcement-time feature price = **$9.00** (ignore post-announce amendment for `feature_as_of`), and  
2. Resolution is the **merger** Item 1.02, not the June 2017 store APA Item 1.01.

### 11. Recommended disposition
**DEFER** (PIT / multi-agreement identity sign-off).

---

## DEAL-IRBT-AMZN-2022

| Field | Value |
|---|---|
| Target / CIK | iRobot Corporation / **1159167** |
| Acquirer | Amazon.com, Inc. |
| Valid-time announce (prose) | Merger Agreement dated **2022-08-04** (Item 1.01; filing 2022-08-05) |
| EDGAR known_at (announce) | `2022-08-05T08:15:41` |

### 1. Announcement accession
`0001193125-22-213174` — Form **8-K**, items **1.01, 5.03, 8.01, 9.01**, filed 2022-08-05.  
Archive: `https://www.sec.gov/Archives/edgar/data/1159167/000119312522213174/`  
**EVENT_RULES announcement:** PASS (Item 1.01).

### 2. Terms accession
Same filing `0001193125-22-213174` (EX-2.1; body states **$61.00** cash per share).

### 3. Original announcement-time consideration
**All cash $61.00 per share.**  
`fs_v1`: `consideration_type=cash`, `offer_price=61.00`.

### 4. Amendments and amendment dates

| Date | Accession | What changed |
|---|---|---|
| 2023-07-24 / filed 2023-07-25 | `0001193125-23-192862` (items 1.01, 2.03, 8.01, 9.01) | Amendment to Merger Agreement: consideration reduced **$61.00 → $51.75** cash per share; also credit-facility Item 1.01 content in same filing |
| Other 1.01 8-Ks (2022-11-02, 2023-01-20) | `0001159167-22-000060`, `0001159167-23-000004` | Financing / other definitive agreements — do not redefine announcement merger cash without reviewer mapping |

### 5. Resolution accession
`0001193125-24-017523` — Form **8-K**, items include **1.02**, filed 2024-01-29; acceptance `2024-01-29T08:36:01`.  
Archive: `https://www.sec.gov/Archives/edgar/data/1159167/000119312524017523/`

### 6. SEC Item number for resolution
**Item 1.02** — mutual termination effective with Termination Agreement; Amazon pays **$94,000,000** Parent Termination Fee.  
(Same 8-K also has Item 1.01 cross-reference to the termination disclosure — resolution classifier remains **1.02**.)

### 7. Point-in-time implications
- Announcement-time features use **$61.00**, not the July 2023 **$51.75** amendment.
- Using $51.75 at announcement feature time would be lookahead / wrong valid-time state.
- Label y=1 from January 2024 Item 1.02.

### 8. Faithful under current `fs_v1`?
**YES** for announcement-time cash $61.00.

### 9. Current `EVENT_RULES` classify resolution?
**YES — terminated** via Item **1.02**.

### 10. Unresolved ambiguity
Human must confirm announcement-time price **$61.00** for `fs_v1` rows and that the July 2023 amendment is a later state update only (not the announcement snapshot).

### 11. Recommended disposition
**DEFER** (PIT price-path sign-off).

---

## Five-row summary

| Deal ID | `fs_v1` representable? | `EVENT_RULES` resolution | Advisory disposition | Human approval required? |
|---|---|---|---|---|
| DEAL-KLAC-LRCX-2015 | **NO** (election / proration / VWAP) | **PASS** terminated (1.02) | **EXCLUDE** | **YES** — confirm exclusion (do not invent a single price/ratio) |
| DEAL-AKRX-FRESENIUS-2017 | **YES** (cash $34) | **FAIL** terminated (no target 1.02); 8.01 ≠ 1.02 | **EXCLUDE** | **YES** — confirm exclusion, or separately authorize any `withdrawn`+8.01 theory |
| DEAL-LLTC-ADI-2016 | **YES** (mixed $46 + 0.2321) | **PASS** closed (2.01); announce needs **425** | **DEFER** | **YES** — accept 425 announcement + terms without Item 1.01 |
| DEAL-RAD-WBA-2015 | **YES** (cash $9 at announce) | **PASS** terminated (1.02) | **DEFER** | **YES** — confirm PIT $9 (not $7) and merger 1.02 vs store APA |
| DEAL-IRBT-AMZN-2022 | **YES** (cash $61 at announce) | **PASS** terminated (1.02) | **DEFER** | **YES** — confirm PIT $61 (not amended $51.75) |

### Decisions that require human approval

All five. None of these deals may be added to `sec_deal_manifest.json` from this packet alone.

Specifically:

1. **KLAC** — approve **EXCLUDE** (or redesign schema; not authorized here).  
2. **AKRX** — approve **EXCLUDE** under locked termination rules, or issue a separate written authorization if a named Item 8.01/`withdrawn` path should be used.  
3. **LLTC** — approve or reject Form 425 + press/close terms without Item 1.01.  
4. **RAD** — approve announcement-time **$9.00** and merger Item 1.02 as the labeled outcome.  
5. **IRBT** — approve announcement-time **$61.00** despite later **$51.75** amendment.

`BATCH8_READY_FOR_INGESTION = NO`  
`CANONICAL_INGESTION_AUTHORIZED_BY_AGENT = NO`  
`REAL MODEL FIT: NO` · `WALK-FORWARD: NO` · `CALIBRATION: NO`
