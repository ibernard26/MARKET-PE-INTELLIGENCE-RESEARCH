# Q3 2026 Deal Research: July 1 – September 24, 2026

*Compiled 2026-09-24. Structured data: `pe-tracker/data/research/deal_register_2026Q3.csv` (49 rows). SEC evidence: `pe-tracker/data/research/sec_filings_2026Q3.json`. To rebuild: `python scripts/build_deal_register_2026q3.py && python scripts/verify_deals_sec.py` (run from `pe-tracker/`).*

## How this was built
- **Search:** web search results with source links. Most news and wire sites (Reuters, Business Wire, PR Newswire, GlobeNewswire, Yahoo, FactSet, Intellizence, `www.sec.gov`) are **blocked by this environment's network policy**, so I couldn't open and read the pages themselves. Each fact is backed by the search results, with the cited URLs listed in the CSV.
- **SEC check:** `data.sec.gov` is reachable. For every US-listed target, I pulled the company's EDGAR filing list and matched the deal against it: 8-K item 1.01 (agreement signed), 1.02 (terminated) and 2.01 (completed), plus Form 25 or 15 (delisting). The SEC acceptance time is used as the deal's point-in-time `known_at`. All 20 cited accession numbers matched EDGAR.
- **Verification levels:**
  - `sec_confirmed`: 20 rows
  - `press_multi` (two or more sources agree): 16
  - `press_single`: 8
  - `reported_only`: 5 (listed in monthly roundups but not confirmed; don't use these without checking)
- **Missing values:** anything not found stays **blank or `n/d`**. Nothing is estimated.
- **Not loaded into the model:** these rows are **not** in the `deals` table or the SEC manifest. Their terms come from press coverage rather than a reviewer reading the filing, and the strategy contract requires the latter.

## Scoreboard: deals that resolved in the window
| Outcome | Deal | Date | Evidence |
|---|---|---|---|
| **Terminated** | Solstice / **Element Solutions** (~$14.5B, cash + stock) | 2026-08-27 | 8-K 1.02, SEC |
| **Blocked** | Henkel / **Liquid Nails** ($725M): FTC won a permanent injunction in SDNY | 2026-08-14 | press (multiple) |
| **Terminated** | TOMI / Carbonium Core (micro-cap) | 2026-09-20 | press |
| **Rejected** | Sazerac's $32/sh proposal for **Brown-Forman** (made May 1) | 2026-07-26 | company statement |
| Closed | IonQ / **SkyWater** ($15 + 0.4883 IONQ) | 2026-07-31 | 8-K 2.01 + Form 25 |
| Closed | PIF/Silver Lake/Affinity / **Electronic Arts** ($210/sh, ~$55B) | 2026-08-04 | 8-K 2.01 + Form 25 |
| Closed | Vertex / **Crinetics** ($85/sh) | 2026-09-01 | 8-K 2.01 + Form 25 |
| Closed | Zymeworks / **Theravance** ($17 + CVR) | 2026-09-23 | 8-K 2.01 + Form 25 |

Solstice/Element is the cleanest example for the break model: a large signed deal that broke with no regulatory block and no fee paid. The two sides called it off after hearing from shareholders, about seven weeks after signing.

## July
| Target | Acquirer | Terms | Value | Status |
|---|---|---|---|---|
| Crinetics (CRNX) | Vertex | $85.00 cash | $10.0B equity | **closed 9/1** |
| Element Solutions (ESI) | Solstice | cash + stock | ~$14.5B incl. net debt | **terminated 8/27** |
| Ultra Maritime | Lockheed Martin (from Advent) | cash | $3.45B | pending |
| WildFire Energy | Magnolia O&G | n/d | n/d | pending |
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
| Delivery Hero | Uber | €41.50 cash offer (launched 8/27) | $14.8B | acceptance period ends 11/5 |
| USI | Aon (from **KKR**) | cash | $17.0B | pending, Q4 |
| EA | PIF / **Silver Lake** / Affinity | $210 cash | ~$55B | **closed 8/4** |
| *OpenRouter; ATG* | *Stripe; MARI* | – | *>$8B; ~$6B* | *reported only* |

## September (through 9/24)
| Target | Acquirer | Terms | Value | Status |
|---|---|---|---|---|
| Birch Permian | Diversified Energy (from Elliott) | n/d | ~$1.8B | pending |
| Hugging Face | Nvidia | ~$11.9B + ~$1.0B retention | ~$12.9B | pending, H1 2027 |
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
- **Paramount / WBD:** the 12-state attorneys general suit settled on 9/21. Close is expected around early October. A $0.25 per quarter ticking fee starts accruing after 9/30.
- **EQT / Intertek:** pending, with no event in the window.
- **Uber / Delivery Hero:** the tender offer launched 8/27, and Delivery Hero's boards recommended it on 9/2.

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

## Gaps: what to ask ChatGPT or another source
Paste this and paste the answers back. I'll reconcile them against EDGAR where I can.

> For each deal below, give: the exact announcement date, the per-share terms or exchange ratio, the equity value and the enterprise value, the expected close date, the key conditions (regulatory approvals, shareholder vote, financing), and a primary-source URL (press release or SEC filing). If you're not sure, say so. Don't estimate.
> 1. Solstice Advanced Materials / Element Solutions (July 6, 2026): the per-share cash + stock terms
> 2. Magnolia Oil & Gas / WildFire Energy (July 20, 2026): price and structure
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

## Access limits hit
- **Blocked sites:** `www.sec.gov` (filing text), `efts.sec.gov` (full-text search), all major wires and news sites, FactSet, Intellizence and stockanalysis.com. Allowing `www.sec.gov` alone would let the register's cited filings be read directly, which is what the manifest's reviewed-entry step needs. `data.sec.gov` works without a personal user-agent.
- **Perplexity:** there's no Perplexity connector in this session. Web search is the only general search tool available here.
