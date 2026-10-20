# Commodity-exposure v2: development dry-run notes (DEVELOPMENT ONLY, not v2 results)

These notes describe tuning the v2 rule implementation (prereg §1) on the **v1 20-deal sample**. That sample is designated development-only in `docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v2.md` §4.
- **No network.** The dry-run (`python -m scripts.commodity_v2.run devrun ...`) ran offline against the local v1 SEC cache, with no new SEC requests.
- **v1 identities and filings.** It used the v1 identity resolution and v1 evidence filings. Merger-filing entity resolution was **not** exercised here, because no merger filings exist in the v1 cache.
- **Not v2 results.**
  - The v2 validation sample was never inspected.
  - No numbers here are v2 results, and none count toward any v2 gate.
- **In-sample and circular.** These figures are optimistic:
  - the rules were tuned on these very rows;
  - the comparison reference is v1 pass B, which was written by the same assistant that wrote the v2 rules.

## What changed during development
The regex mechanics for §1 were developed iteratively on this sample. The final implementation is frozen at the implementation commit.

| Area | Change | Motivating v1 dev cases |
|---|---|---|
| **Consumer: input vocabulary** | Drops bare "energy" and "power". Also drops bare "paper" (commercial paper); "paperboard" and "pulp" are kept. | CHNG/UNH "time and energy"; MDLA, MNTV "market power"; COP "commercial paper" |
| **Consumer: proximity** | Requires an input-to-cost proximity tie: *cost/price of … X*, *X … costs/prices*, *purchases of / we purchase/use … X* | Athlon regulatory-cost sentence |
| **Consumer: own cost** | Also requires an own-cost tie: our costs/margins, cost of sales, raw materials, input/operating costs, higher/increased costs | GNW macro "fluctuating oil and commodity prices" |
| **Consumer: sell side** | Sell-side exclusion: realized/sales prices, our production/reserves, *decline in … prices*, *prices decline*, *oil/gas industry/companies/properties*, *we produce*. A strong buy-side marker (raw materials, purchases of, prices we pay, input costs, feedstock) overrides it. | CXO, COP, Encana |
| **Consumer: producer guard** | Party-level guard: when the party is a producer, a consumer sentence must carry a strong buy-side marker | Athlon "commodity derivative contracts … oil and natural gas prices" |
| **Consumer: impact words** | Include "impact(s)" and "affect", alongside increase, volatility, fluctuation, adverse and inflation | Tecumseh "most significant cost … impacts" |
| **Consumer: investment exclusion** | Investment/portfolio/credit contexts are excluded | GNW energy portfolio |
| **Factor lists** | "including"/"such as" followed by ≥4 commas, plus ≥2 semicolons, ≥3 bullets and >700 chars, are all excluded | QUALIT, IRBT/AMZN list sentences |
| **Producer** | Requires the filer as subject of produce/extract/mine/drill/refine a named commodity, or *producer/refiner/miner of*, or *our … production/proved reserves*. Raise/process/grow is allowed for meat/poultry/grain/livestock. Transport/purchase/supplier/cost-of contexts are excluded inside the match. | Tecumseh (steel buyer), Quality Distribution (crude transporter), Hillshire "We raise turkeys" (v1 miss) |
| **Hedged** | Requires a derivative term within 160 chars of a commodity term plus an affirmative usage verb. Excludes "no well-established market for hedging" and "may … hedge" alone. Commodity-specific "does not use … hedge" gives `no_disclosed`. | Blackstone FSOC text; Kroger commodity derivatives (kept) |

## Dev-sample figures (v2 rules vs v1 pass A vs v1 pass B; 40 party rows × 3 flags)
| Flag | v1 pass A yes | v1 pass B yes | v2 yes | v2 = pass B (of 40) |
|---|---|---|---|---|
| producer | 7 | 6 | 6 | 40 |
| consumer | 23 | 10 | 11 | 39 |
| hedged | 11 | 8 | 10 | 38 |

**Consumer**
- v1 had **13 consumer false hits** (pass A yes, pass B unknown). The v2 rules remove **12 of 13**.
- The remaining one is QUALIT-FUNDS (Quality Distribution): "significant increases in diesel fuel costs could materially and adversely affect our results". This is a genuine input-cost statement under the v2 criteria. The v1 pass-B "unknown" was the more conservative judgment.

**Producer**
- Both v1 producer false hits are removed (Tecumseh, Quality Distribution).
- The v1 producer miss (Hillshire) is fixed.

**Hedged**
- v2 says `yes` where v1 pass B said unknown in two places:
  - Athlon: "We have entered into oil derivative contracts";
  - Kroger 7A: "derivative financial instruments … adverse fluctuations in commodity prices".
- v1 analysis attributed both pass-B unknowns to packet truncation. The v2 rule outcome is defensible in both.
- The Blackstone FSOC false hit is removed.

**Overall**
- Deal-level exact match with v1 pass B on the 3 v2 flags is **17/20**. For comparison, v1 pass A vs pass B on the same 3 flags was 8/20.
- Substantive cells (either side non-unknown): 27, with agreement on them 24/27.
- **These are in-sample development numbers and must not be read as an estimate of v2 validation performance.**

## Not exercised in development
- **Merger-filing entity resolution.** Only unit tests with synthetic merger-agreement text were run; no merger filings are cached. Its first real use is the production run.
- **SEC acceptance-timestamp chronology on live data.** This is unit-tested. The v1 cache has acceptance timestamps in the submissions JSON, but the dev run used v1 plan entries.
