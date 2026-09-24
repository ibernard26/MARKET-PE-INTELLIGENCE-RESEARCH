# Q3 2026 Deal Research: July 1 – September 24, 2026

*Compiled 2026-09-24; updated the same day with ChatGPT's public-source package (see its section below). Structured data: `pe-tracker/data/research/deal_register_2026Q3.csv` (64 rows). SEC evidence: `pe-tracker/data/research/sec_filings_2026Q3.json`. To rebuild: `python scripts/build_deal_register_2026q3.py && python scripts/verify_deals_sec.py` (run from `pe-tracker/`).*

## How this was built
- **Search:** web search results with source links. Most news and wire sites (Reuters, Business Wire, PR Newswire, GlobeNewswire, Yahoo, FactSet, Intellizence, `www.sec.gov`) are **blocked by this environment's network policy**, so I couldn't open and read the pages themselves. Each fact is backed by the search results, with the cited URLs listed in the CSV.
- **SEC check:** `data.sec.gov` is reachable. For every US-listed target, I pulled the company's EDGAR filing list and matched the deal against it: 8-K item 1.01 (agreement signed), 1.02 (terminated) and 2.01 (completed), plus Form 25 or 15 (delisting). The earliest verified disclosure time (usually the SEC acceptance time, in UTC) is used as the deal's point-in-time `known_at`.
- **What the SEC check does and doesn't prove:** all 29 accession numbers cited in the register (across 25 rows) matched the expected company's EDGAR filing list. That confirms **filing metadata only**: form type, 8-K item numbers, acceptance time and accession. **No filing text was read** (`www.sec.gov` is blocked), so `filing_content_verified` is `no` on every row. The other 39 rows are verified by press only, or not verified at all.
- **Verification levels:**
  - `sec_metadata_confirmed`: 25 rows (EDGAR metadata matches the event; filing text not read)
  - `press_multi` (two or more sources agree): 26
  - `press_single`: 8
  - `reported_only`: 5 (listed in monthly roundups but not confirmed; don't use these without checking)
  - The separate column `filing_content_verified` is `no` on all 64 rows.
- **Missing values:** anything not found stays **blank or `n/d`**. Nothing is estimated.
- **Not loaded into the model:** these rows are **not** in the `deals` table, the bitemporal store or the SEC manifest. Their terms come from press coverage rather than a reviewer reading the filing, and the strategy contract requires the latter.
- **Research candidates only:** `reported_only` rows and regulator-only events (UK CMA and US FTC steps) stay as research and event candidates. They are never loaded into model data automatically.

## Scoreboard: deals that resolved in the window
| Outcome | Deal | Date | Evidence |
|---|---|---|---|
| **Terminated** | Getty / **Shutterstock**: Getty walked away rather than sell the editorial business the CMA required | 2026-07-07 | Shutterstock 8-K 1.02 (7/9) + press |
| **Terminated** | Solstice / **Element Solutions** (~$14.5B, cash + stock) | 2026-08-27 | 8-K 1.02, SEC |
| **Blocked** | Henkel / **Liquid Nails** ($725M): FTC won a permanent injunction in SDNY | 2026-08-14 | press (multiple) |
| **Terminated** | TOMI / Carbonium Core (micro-cap) | 2026-09-20 | press |
| **Rejected** | Sazerac's $32/sh proposal for **Brown-Forman** (made May 1) | 2026-07-26 | company statement |
| Closed | IonQ / **SkyWater** ($15 + 0.4883 IONQ) | 2026-07-31 | 8-K 2.01 + Form 25 |
| Closed | PIF/Silver Lake/Affinity / **Electronic Arts** ($210/sh, ~$55B) | 2026-08-04 | 8-K 2.01 + Form 25 |
| Closed | Vertex / **Crinetics** ($85/sh) | 2026-09-01 | 8-K 2.01 + Form 25 |
| Closed | Zymeworks / **Theravance** ($17 + CVR) | 2026-09-23 | 8-K 2.01 + Form 25 |
| Closed | eBay / **Depop** (from Etsy, ~$1.4B) | 2026-07-30 | press (multiple) |
| Closed | Ascension / **AmSurg** ($3.9B), after the FTC consent order with 7 surgery-center divestitures | late Aug | press (multiple) |
| Closed | Adena / **Fairfield Medical Center** (OhioHealth's earlier deal abandoned) | 2026-09-01 | press (multiple) |
| Closed | Williams / **Momentum Midstream** (up to $5.5B), 31 days from signing to close | 2026-09-03 | press + WMB 8-K |
| *Likely closed* | Magnolia / **WildFire Energy** (~$4.06B) | 2026-09-14 | MGY 8-K item 2.01 (metadata only; confirm from filing text) |
| **Contested** | Verisk / **AccuLynx** ($2.35B): Delaware court ordered Verisk to close; Verisk appealed 8/18 | 2026-08-07 | press (multiple) |

*SEC evidence in this table is filing metadata (form type and 8-K items). The filings' text was not read.*

Solstice/Element is the cleanest example for the break model: a large signed deal that broke with no regulatory block and no fee paid. The two sides called it off after hearing from shareholders, about seven weeks after signing.

## July
| Target | Acquirer | Terms | Value | Status |
|---|---|---|---|---|
| Crinetics (CRNX) | Vertex | $85.00 cash | $10.0B equity | **closed 9/1** |
| Element Solutions (ESI) | Solstice | $10.00 cash + 0.500 SOLS sh (~$50.10 implied); $4.685B bridge | ~$14.5B incl. net debt | **terminated 8/27** |
| Ultra Maritime | Lockheed Martin (from Advent) | cash | $3.45B | pending |
| WildFire Energy | Magnolia O&G | 32.2M MGY Class A sh + $600M notes assumed; rest cash/debt/new equity | ~$4.06B incl. debt | likely closed 9/14 (8-K 2.01 metadata) |
| Delivery Hero | Uber | €41.50 cash tender offer (agreement 7/16; offer document 8/27) | $14.8B equity | acceptance period ends 11/5 |
| Luxfer (LXFR) | Wynnchurch | $17.37 cash (+30.7%) | n/d | pending, close before YE26 |
| MarketAxess (MKTX) | ICE | $167.00 cash (+33%) | ~$6.0B equity | pending, H1 2027 |
| SkyWater (SKYT) | IonQ | $15 + 0.4883 IONQ | ~$1.8B | **closed 7/31** |
| *Seahawks; Argan* | *Khosla group; WDP* | – | *$9.6B; ~$14.8B* | *reported only* |

## August
| Target | Acquirer | Terms | Value | Status |
|---|---|---|---|---|
| Lantheus (LNTH) | Curium | $102.50 cash + CVR ≤$12 | up to ~$8.0B | pending, H1 2027 |
| Integer (ITGR) | **KKR** | $127.00 cash (+51.8%) | ~$5.7B EV | pending, YE26 |
| SEGRO | Prologis | 0.0920 PLD sh (+ partial cash alternative) | ~£14B | pending, H1 2027 |
| easyJet | **Apollo** | 715p cash (+81%) | ~£5.7B | pending, by Mar 2027 |
| Beazer (BZH) | Dream Finders | $33.50 cash | ~$2.2B | pending, Q4 |
| Bowman (BWMN) | **Bernhard Capital** | $43.00 cash (+58%) | ~$1.0B EV | pending; go-shop drew no bids |
| Cleanaway | **EQT** | A$3.13 (non-binding) | ~A$9.4B EV | exclusivity, no binding deed yet |
| Accelerant (ARX) | **Thoma Bravo** | $20.25 cash (+49%) | >$4B EV | pending, H1 2027 |
| Liquid Nails | Henkel | – | $725M | **blocked 8/14** |
| Harte Hanks (HHS) | Star Equity | $5.00 (cash + preferred) | $38.4M | pending |
| Ambros (private) | Werewolf (reverse merger) | stock + $150M PIPE | $500M pre-money | pending |
| First Eagle | Victory Capital (from **Genstar**) | $4.4B cash + $2.0B stock | ~$7.0B | pending |
| USI | Aon (from **KKR**) | cash | $17.0B | pending, Q4 |
| EA | PIF / **Silver Lake** / Affinity | $210 cash | ~$55B | **closed 8/4** |
| *OpenRouter; ATG* | *Stripe; MARI* | – | *>$8B; ~$6B* | *reported only* |

## September (through 9/24)
| Target | Acquirer | Terms | Value | Status |
|---|---|---|---|---|
| Birch Permian | Diversified Energy (from Elliott) | n/d | ~$1.8B | pending |
| Hugging Face | Nvidia | ~$11.9B + ~$1.0B retention (agreed 9/2; first disclosed 9/3) | ~$12.9B | pending, H1 2027 |
| Lincoln Bancorp | Equity Bancshares | cash + stock | $123.8M | pending |
| Eagle Financial (EFSI) | John Marshall Bancorp | stock (1.30x tangible book) | $253M | pending |
| Centerspace (CSR) | IRT | 3.800 IRT sh (fixed ratio) | ~$2.14B | pending |
| Convergent Genomics | Veracyte | n/d | n/d | – |
| Baldwin Group (BWIN) | Sequence + **Dell Family Office** | $32.50 cash | ~$7.7B | pending |
| Atome (majority stake) | Grab | n/d | n/d | – |
| Tallgrass crude assets | Enbridge | cash | $2.55B | n/d |
| Mistras (MG) | **H.I.G.** | $20.35 cash (+8–13% vs VWAP) | ~$866M EV | pending |
| WakeMed | Atrium Health | nonprofit combination | – | planned |
| SeaLink tourism | Journey Beyond (carve-out) | n/d | n/d | – |
| Dianomi | Taboola | n/d | n/d | – |
| ITM | Telix | $1.65B upfront + ≤$0.7B milestones | up to $2.35B | pending |
| Priority Tech (PRTH) | CEO-led group / **Searchlight** | $8.05 cash (+38%) | ~$1.6B EV | pending, H1 2027 |
| Carbonium Core | TOMI | – | – | **terminated 9/20** |
| Kobayashi Pharma | **CVC** (talks) | – | >¥500B | reported talks only |

**Pre-window deals with events in the window:**
- **Bio-Techne:** Merck KGaA's $73 offer won the shareholder vote on 9/23.
- **Paramount / WBD** (agreement signed 2026-02-27): the 12-state attorneys general suit settled on 9/21. The deal is **pending, with a close likely soon now the litigation is settled**. No primary source gives a dated close; an "early October" close appears only in press reports of an internal memo. A $0.25/share per-quarter ticking fee accrues if the deal hasn't closed by 9/30.
- **EQT / Intertek:** pending, with no event in the window.
- **Uber / Delivery Hero** is now listed under July: the agreement was signed 7/16. The 8/27 offer document and the boards' 9/2 recommendation are milestones, not the announcement.

## ChatGPT's public-source package: how it was integrated
The package had 33 event rows, mostly UK CMA and US FTC milestones. The original files are stored unchanged in `pe-tracker/data/public_mna_intelligence/2026-07-01_2026-09-24/staging_chatgpt/`. The row-by-row review is in `reconciliation.csv` next to them.
- **Its sources couldn't be opened here.** All 28 source URLs (gov.uk, ftc.gov, Reuters, company investor-relations sites) are blocked by this environment's network policy (proxy 403). So no row was accepted just because it cites a source. Each one was checked against SEC filing data or independent search.
- **Result:**
  - 3 confirmed by SEC filings (Getty/Shutterstock, Priority, Beretta/Ruger)
  - 16 corroborated by press
  - 4 corrected
  - 10 regulator-only rows that can't be verified here (ABF/Hovis, Danone/Huel, Seras/Enva, OCS/Mitie, ABP/Dovecote, GXO/Wincanton, two Paramount/WBD CMA steps). They're kept as events but not linked to any label.
- **Corrections:**
  - **IonQ/SkyWater** and **Williams/Momentum** had already **closed**; the package listed them as pending.
  - **Verisk:** the ruling date is 8/7, not 8/8, and the appeal was filed 8/18.
  - **Ascension/AmSurg:** closed after the consent order.
  - **Getty/Shutterstock:** the resolution date is the party's termination notice (7/7), not the CMA page (7/8).
- **Deals new to the register:**
  - Getty/Shutterstock, eBay/Depop, Williams/Momentum, Verisk/AccuLynx, Ascension/AmSurg, Adena/FMC
  - Nuveen/Schroders: completion scheduled for 10/1
  - Brink's/NCR Atleos, McCormick/Unilever Foods ($44.8B EV), KONE/TK Elevator (€29.4B; seller Vertical Topco I S.A., jointly controlled by Advent and Cinven), E.ON/OVO, Sky/ITV
  - Ingenia/Warburg and IDP/Blackstone: rejected proposals, never labels
  - Beretta/Ruger
- **Label rules applied** (the package's rules match the repo's strategy contract):
  - Clearance never means Y=0.
  - An injunction never means Y=1 until termination is verified (so Henkel stays unlabeled).
  - A rejected proposal is never a break.
  - When an event's valid date and known date differ, both are kept (Henkel 8/14 vs 8/17, ABP 9/17 vs 9/21, GXO 9/13 vs 9/23).

### Label candidates from the window (a reviewer must confirm before they become model rows)
| | Public target (usable by `break_logit_v1` once reviewed) | Private or nonprofit target (no spread features) |
|---|---|---|
| **Y=1 (broke)** | Element Solutions (8/27), Shutterstock (7/7) | TOMI/Carbonium (micro-cap; 9/20) |
| **Y=0 (closed)** | SkyWater (7/31), EA (8/4), Crinetics (9/1), Theravance (9/23) | Depop, AmSurg, Momentum, Fairfield MC; WildFire (likely 9/14, confirm) |
| **Censored (unresolved)** | everything else, including Henkel (blocked, not confirmed terminated), Verisk (on appeal), Schroders (completion scheduled 10/1 per press) and Paramount/WBD (settled, pending) | |

`MODEL_DATA_STATUS` is still **NO_REAL_LABELS**. None of these rows is in the canonical bitemporal store yet. The six public-target candidates (2 breaks, 4 closes) are what would be ingested first once a reviewer confirms terms against the filings. That is far below any sample size needed to fit a model.

## Links to the tracked themes
- **#1 Grid and electrical services:** Bowman / Bernhard Capital (58% premium; 76 parties contacted in the go-shop, no rival bid).
- **#2 Defense sub-tier suppliers:** Lockheed / Ultra Maritime (bought from Advent) is a large-cap deal rather than a sub-tier one, but it shows primes buying undersea capability.
- **#3 Carve-outs:** Kelsian SeaLink tourism, Tallgrass crude assets, and USI and First Eagle as sponsor exits.
- **#5 Mandated recurring services:** Mistras / H.I.G. (inspection) and Cleanaway / EQT (waste). Mistras's small premium is worth watching for a shareholder vote risk.
- **PE take-private activity:** 8 signed take-privates in the window (Luxfer, Integer, easyJet, Bowman, Accelerant, Baldwin, Mistras, Priority), plus the EA LBO closing. Premiums range from about 8% to 81%.

## Errors in secondary roundups, corrected here
| Claim | Correction |
|---|---|
| Sazerac–Brown-Forman is "July's largest deal" | The $32 bid was made May 1 and **rejected** July 26. It was never a signed deal. |
| Biogen–Apellis announced September 2026 | Announced March 31 and **closed in May**. Excluded. |
| Merck KGaA–Bio-Techne is an August deal | Announced **June 25**. Only the 9/23 vote is in the window. |
| Theravance deal announced August | Announced **June 29** and closed 9/23. |
| Priority Technology announced 9/22 | SEC acceptance is **9/21 11:40 UTC**. |
| Victory–First Eagle $6.4B | **~$7.0B** including $575M of assumed notes. |
| Solstice–Element $12.2B | **~$14.5B** including net debt (per the companies). |
| Uber–Delivery Hero announced with the 8/27 offer | Agreement signed **7/16** (UBER 8-K 1.01). 8/27 is the offer-document date. |
| Nvidia–Hugging Face announced 8/27 | 8/27 was an unconfirmed media report. Agreement dated **9/2**; first public disclosure **9/3** (8-K accepted 08:03:56 ET). |

## Gaps: what to ask ChatGPT or another source
Paste this and paste the answers back. I'll reconcile them against EDGAR where I can.

> For each deal below, give: the exact announcement date, the per-share terms or exchange ratio, the equity value and the enterprise value, the expected close date, the key conditions (regulatory approvals, shareholder vote, financing), and a primary-source URL (press release or SEC filing). If you're not sure, say so. Don't estimate.
> 1. ~~Solstice / Element per-share terms~~ (resolved 2026-09-24)
> 2. Magnolia / WildFire (July 20, 2026): confirm the closing date (8-K item 2.01 filed September 14, 2026). Terms resolved 2026-09-24
> 3. WDP / Argan (July 2026): structure, value and status
> 4. Seattle Seahawks sale (July 2026): buyer group, price, league approval status
> 5. Stripe / OpenRouter and MARI Group / Ambassador Theatre Group (August 2026): terms and whether signed
> 6. Henkel / Liquid Nails after the August 14, 2026 injunction: appealed or abandoned?
> 7. Baldwin Group / Sequence + DFO (September 14, 2026): expected close and conditions
> 8. John Marshall Bancorp / Eagle Financial (September 8, 2026): exchange ratio
> 9. Enbridge / Tallgrass crude assets (September 2026): exact date, buyer entity, status
> 10. Veracyte / Convergent Genomics, Grab / Atome, Taboola / Dianomi, Journey Beyond / SeaLink: prices
> 11. Beazer Homes 8-K filed September 18, 2026 (item 1.01) and Centerspace 8-K filed September 23, 2026 (item 1.01): what agreement or amendment each reports
> 12. Any US public-target M&A deal of $500M or more announced July 1 to September 24, 2026 that is missing from this list
> 13. Getty / Shutterstock: the per-share terms, and whether any termination fee was paid on the July 7, 2026 termination
> 14. OhioHealth / Fairfield Medical Center: the date the deal was abandoned
> 15. Ascension / AmSurg: the exact closing date
> 16. E.ON / OVO: the price. Sky / ITV: the signing date
> 18. Paramount / WBD: a primary-source closing date, if one is announced
> 17. Brink's / NCR Atleos: the outcome of the CMA Phase 1 review (deadline October 22, 2026)

## Access limits hit
- **Blocked sites:** `www.sec.gov` (filing text), `efts.sec.gov` (full-text search), all major wires and news sites, FactSet, Intellizence and stockanalysis.com. Allowing `www.sec.gov` alone would let the register's cited filings be read directly, which is what the manifest's reviewed-entry step needs. `data.sec.gov` works without a personal user-agent.
- **Perplexity:** there's no Perplexity connector in this session. Web search is the only general search tool available here.
