"""Build the Q3 2026 (Jul 1 - Sep 24) deal register from reviewed research rows.

Research-grade, NOT model-grade: terms come from press releases and wire copy
found by web search (most news hosts are blocked by the environment's network
policy, so pages could not be fetched and read in full). US-listed targets are
cross-checked against EDGAR metadata from data.sec.gov (form type, items,
acceptance time, accession) via scripts/verify_deals_sec.py. Nothing here is
written to the deals table or the SEC manifest; that needs a reviewer reading
the cited filings (see docs/HISTORICAL_DEAL_DATA_SOURCES.md).

Conventions: unknown values stay empty (never estimated); `verification` is
  sec_metadata_confirmed - EDGAR filing METADATA (form, 8-K items, acceptance
                   time, accession) matches the event; filing text NOT read
  (separate column filing_content_verified = yes only if the filing text was read;
   it is "no" on every row today because www.sec.gov is unreachable here)
  press_multi    - two or more independent press sources agree
  press_single   - one source; treat as provisional
  reported_only  - media report / non-binding; not a signed deal
Rows 050+ came from the ChatGPT staging package (see
data/public_mna_intelligence/2026-07-01_2026-09-24/) and were re-checked here
with EDGAR metadata or independent search before inclusion.
Run:  python scripts/build_deal_register_2026q3.py
"""
import csv
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "research" / "deal_register_2026Q3.csv"

FIELDS = [
    "deal_id", "window_event", "window_event_date", "target", "target_ticker", "acquirer",
    "sponsor", "deal_type", "consideration_type", "offer_terms", "headline_value",
    "value_basis", "premium", "announce_date", "announce_known_at_utc", "status_2026_09_24",
    "resolution_date", "expected_close", "sector", "geography", "sec_cik",
    "sec_announce_accession", "sec_resolution_accession", "verification", "filing_content_verified",
    "sources", "notes",
]

R = []


def add(**kw):
    row = {f: "" for f in FIELDS}
    row["filing_content_verified"] = "no"
    unknown = set(kw) - set(FIELDS)
    assert not unknown, unknown
    row.update(kw)
    R.append(row)


# ----------------------------------------------------------------- July 2026
add(deal_id="2026Q3-001", window_event="announced", window_event_date="2026-07-06",
    target="Crinetics Pharmaceuticals", target_ticker="CRNX", acquirer="Vertex Pharmaceuticals",
    deal_type="strategic", consideration_type="cash", offer_terms="$85.00/sh cash",
    headline_value="$10.0B equity (~$8.8B net of cash)", value_basis="equity",
    announce_date="2026-07-06", announce_known_at_utc="2026-07-06T21:17:19Z",
    status_2026_09_24="closed", resolution_date="2026-09-01",
    sector="biotech", geography="US", sec_cik="1658247",
    sec_announce_accession="0001140361-26-027642", sec_resolution_accession="0001140361-26-035195",
    verification="sec_metadata_confirmed",
    sources="https://www.biopharmadive.com/news/vertex-crinetics-acquire-deal-palsonify-acromegaly/824545/",
    notes="Closed: 8-K items 2.01/3.01 + Form 25-NSE on 2026-09-01; 15-12G 2026-09-11. FactSet roundup cites $9B (headline mismatch). $4.5B bridge (BofA/MS).")

add(deal_id="2026Q3-002", window_event="announced+terminated", window_event_date="2026-07-06",
    target="Element Solutions", target_ticker="ESI", acquirer="Solstice Advanced Materials",
    deal_type="strategic", consideration_type="mixed",
    offer_terms="$10.00 cash + 0.500 SOLS sh per ESI sh (implied ~$50.10; ~15% premium to 2026-07-02 close)",
    headline_value="~$14.5B incl. net debt", value_basis="enterprise",
    announce_date="2026-07-06", announce_known_at_utc="2026-07-06T13:13:10Z",
    status_2026_09_24="terminated", resolution_date="2026-08-27",
    sector="specialty chemicals", geography="US", sec_cik="1590714",
    sec_announce_accession="0001104659-26-080825", sec_resolution_accession="0001104659-26-102559",
    verification="sec_metadata_confirmed",
    sources="https://www.tradingview.com/news/tradingview:1db2d00a69fdf:0-solstice-to-acquire-element-solutions-in-stock-and-cash-deal-0-5-share-plus-10-per-share/; https://www.cnbc.com/2026/07/06/honeywell-spinoff-solstice-to-buy-element-solutions-for-14point5-billion.html; https://ir.elementsolutionsinc.com/Investors/news/news-details/2026/Element-Solutions-Announces-Mutual-Termination-of-Merger-Agreement-with-Solstice-Advanced-Materials/default.aspx",
    notes="BROKEN DEAL (positive class). Mutual termination, no fee either side, after shareholder conversations. 8-K items 1.01/1.02 accepted 2026-08-27. FactSet cites $12.2B (headline mismatch). Financing: initial $4.685B senior secured 364-day bridge term loan commitment (+ $1.0B backstop revolver, Goldman Sachs). known_at = earliest disclosure (ESI 8-K item 7.01 acc 0001104659-26-080612, 13:13:10Z); 1.01 8-K followed 21:18:48Z. Terms per reviewer correction 2026-09-24, corroborated by TradingView/CNBC.")

add(deal_id="2026Q3-003", window_event="announced", window_event_date="2026-07-06",
    target="Ultra Maritime", acquirer="Lockheed Martin", sponsor="Advent International (seller)",
    deal_type="strategic (sponsor exit)", consideration_type="cash", headline_value="$3.45B",
    value_basis="purchase price", announce_date="2026-07-06", status_2026_09_24="pending",
    sector="defense - undersea/ASW", geography="US",
    verification="press_multi",
    sources="https://news.lockheedmartin.com/2026-07-06-Lockheed-Martin-to-Acquire-Ultra-Maritime-Solutions; https://breakingdefense.com/2026/07/lockheed-martin-to-purchase-ultra-maritime-in-3-5b-deal/",
    notes="Tracked theme #2 (defense sub-tier). Expected close n/d.")

add(deal_id="2026Q3-004", window_event="announced", window_event_date="2026-07-20",
    target="WildFire Energy (private)", acquirer="Magnolia Oil & Gas (MGY)", deal_type="strategic",
    consideration_type="stock + debt assumption + cash",
    offer_terms="32.2M MGY Class A sh + assumption of $600M notes due 2029; remaining consideration funded with cash/debt/new equity",
    headline_value="~$4.06B incl. debt", value_basis="enterprise", announce_date="2026-07-20",
    announce_known_at_utc="2026-07-20T11:12:06Z",
    status_2026_09_24="likely closed 2026-09-14 per 8-K item 2.01 metadata (filing text unread - confirm before labeling)",
    sec_resolution_accession="0001104659-26-107498",
    expected_close="late Q3 2026", sector="upstream oil & gas (Eagle Ford)", geography="US",
    sec_cik="1698990", sec_announce_accession="0001104659-26-084859", verification="sec_metadata_confirmed",
    sources="https://www.businesswire.com/news/home/20260719614998/en/Magnolia-Oil-Gas-Announces-Acquisition-of-WildFire-Energy; https://www.worldoil.com/news/2026/7/20/magnolia-s-4-06-billion-wildfire-deal-creates-major-south-texas-position/; https://www.bloomberg.com/news/articles/2026-07-20/magnolia-oil-agrees-to-buy-wildfire-energy-in-4-1-billion-deal",
    notes="MGY 8-K items 1.01/2.03/3.02 accepted 2026-07-20T11:12:06Z (consistent with share issuance + debt). MGY 8-K items 1.01/2.01/2.03/3.02/7.01 accepted 2026-09-14T20:10:29Z - item 2.01 (completion of acquisition) indicates closing; resolution_date left blank until the filing text is read. Terms per reviewer correction 2026-09-24, corroborated by World Oil/Bloomberg. Private target.")

add(deal_id="2026Q3-005", window_event="rejected", window_event_date="2026-07-26",
    target="Brown-Forman", target_ticker="BF.B", acquirer="Sazerac", deal_type="unsolicited proposal",
    consideration_type="cash", offer_terms="$32.00/sh cash (non-binding, submitted 2026-05-01)",
    headline_value="~$15B", value_basis="equity", announce_date="2026-05-01",
    status_2026_09_24="rejected", resolution_date="2026-07-26", sector="spirits", geography="US",
    sec_cik="14693", verification="press_multi",
    sources="https://www.brown-forman.com/article/brown-forman-board-issues-statement-july-26-2026; https://www.bloomberg.com/news/articles/2026-07-26/brown-forman-says-it-rejected-sazerac-s-unsolicited-takeover-bid",
    notes="Board: 'not actionable'; Brown family (Wolf Pen Branch) majority of Class A opposed. NOT a July deal announcement despite some roundups listing it as July's largest. Brown-Forman 8-K 1.01 of 2026-09-21 is a $500M notes offering, unrelated.")

add(deal_id="2026Q3-006", window_event="announced", window_event_date="2026-07-27",
    target="Luxfer Holdings", target_ticker="LXFR", acquirer="Wynnchurch Capital affiliates",
    sponsor="Wynnchurch Capital", deal_type="take-private (LBO)", consideration_type="cash",
    offer_terms="$17.37/sh cash", premium="30.7% to 2026-04-28 close ($13.29)",
    announce_date="2026-07-27", announce_known_at_utc="2026-07-27T12:31:57Z",
    status_2026_09_24="pending", expected_close="before end-2026",
    sector="industrials - gas containment/materials", geography="US-listed (UK plc)", sec_cik="1096056",
    sec_announce_accession="0002077096-26-000223", verification="sec_metadata_confirmed",
    sources="https://www.businesswire.com/news/home/20260727527925/en/Luxfer-Enters-Into-Agreement-to-Be-Acquired-for-$17.37-Per-Share-in-All-Cash-Transaction",
    notes="No financing condition. DEFM14A on file.")

add(deal_id="2026Q3-007", window_event="announced", window_event_date="2026-07-30",
    target="MarketAxess", target_ticker="MKTX", acquirer="Intercontinental Exchange",
    deal_type="strategic", consideration_type="cash", offer_terms="$167.00/sh cash",
    headline_value="~$6.0B equity / ~$5.7B EV", value_basis="equity + EV",
    premium="33% to 2026-07-29 close", announce_date="2026-07-30",
    announce_known_at_utc="2026-07-30T11:44:54Z", status_2026_09_24="pending", expected_close="H1 2027",
    sector="market structure / fixed-income trading", geography="US", sec_cik="1278021",
    sec_announce_accession="0001193125-26-324933", verification="sec_metadata_confirmed",
    sources="https://ir.theice.com/press/news-details/2026/Intercontinental-Exchange-to-Acquire-MarketAxess-Creating-a-Premier-Fixed-Income-Marketplace/default.aspx; https://www.cnbc.com/2026/07/30/intercontinental-exchange-to-buy-marketaxess.html",
    notes="Debt-financed (bonds, term loan, CP). HSR + MKTX vote required.")

add(deal_id="2026Q3-008", window_event="closed", window_event_date="2026-07-31",
    target="SkyWater Technology", target_ticker="SKYT", acquirer="IonQ", deal_type="strategic",
    consideration_type="mixed", offer_terms="$15.00 cash + 0.4883 IONQ sh (collar-fixed at close)",
    headline_value="~$1.8B", value_basis="total consideration", status_2026_09_24="closed",
    resolution_date="2026-07-31", sector="semiconductor foundry / quantum", geography="US",
    sec_cik="1819974", sec_resolution_accession="0001193125-26-327137", verification="sec_metadata_confirmed",
    sources="https://www.nasdaq.com/press-release/ionq-completes-acquisition-skywater-technology-2026-07-31",
    notes="Announced pre-window (Jan 2026). FTC granted early termination 2026-07-31 (FTC chairman statement; per ChatGPT staging MNA-20260731-IONQ-SKYWATER and search summary; ftc.gov unreachable here).")

add(deal_id="2026Q3-009", window_event="announced", window_event_date="2026-07",
    target="Seattle Seahawks", acquirer="Khosla family-led group", deal_type="control sale",
    headline_value="$9.6B", status_2026_09_24="pending", sector="sports franchise", geography="US",
    verification="reported_only",
    sources="(FactSet July 2026 monthly review, via search summary; page not fetchable)",
    notes="Single secondary citation - VERIFY before use.")

add(deal_id="2026Q3-010", window_event="announced", window_event_date="2026-07",
    target="Argan (FR)", acquirer="WDP", deal_type="strategic (REIT combination)",
    headline_value="~$14.8B", status_2026_09_24="n/d", sector="logistics REIT", geography="Europe",
    verification="reported_only",
    sources="(Intellizence July 2026 top-10, via search summary; page not fetchable)",
    notes="Terms and structure not captured - GAP.")

# --------------------------------------------------------------- August 2026
add(deal_id="2026Q3-011", window_event="announced", window_event_date="2026-08-03",
    target="Lantheus Holdings", target_ticker="LNTH", acquirer="Curium US",
    deal_type="strategic", consideration_type="cash + CVR",
    offer_terms="$102.50/sh cash + CVR up to $12.00 (commercial milestones through 2030)",
    headline_value="up to ~$8.0B", value_basis="total incl. CVR", announce_date="2026-08-03",
    announce_known_at_utc="2026-08-03T12:37:46Z", status_2026_09_24="pending", expected_close="H1 2027",
    sector="radiopharma / diagnostics", geography="US", sec_cik="1521036",
    sec_announce_accession="0001193125-26-331138", verification="sec_metadata_confirmed",
    sources="https://investor.lantheus.com/news-releases/news-release-details/curium-announces-definitive-agreement-merge-lantheus",
    notes="known_at = first deal 8-K (7.01/8.01) 12:37Z; 1.01 8-K accepted 2026-08-04T01:00Z. Some roundups cite $7.5B (cash-only).")

add(deal_id="2026Q3-012", window_event="announced", window_event_date="2026-08-03",
    target="Integer Holdings", target_ticker="ITGR", acquirer="KKR affiliate", sponsor="KKR",
    deal_type="take-private (LBO)", consideration_type="cash", offer_terms="$127.00/sh cash",
    headline_value="~$5.7B EV", value_basis="enterprise",
    premium="51.8% to 2026-04-29 (pre-strategic-review); 28.8% to 30-day VWAP", announce_date="2026-08-03",
    announce_known_at_utc="2026-08-03T21:14:02Z", status_2026_09_24="pending", expected_close="by end-2026",
    sector="medtech contract manufacturing", geography="US", sec_cik="1114483",
    sec_announce_accession="0000950103-26-011881", verification="sec_metadata_confirmed",
    sources="https://investor.integer.net/news-events/press-releases/news-details/2026/Integer-to-Be-Acquired-by-KKR-in-Transaction-Valued-at-Approximately-5-7-Billion/default.aspx",
    notes="known_at = first DEFA14A; 1.01 8-K accepted 2026-08-04T20:32Z.")

add(deal_id="2026Q3-013", window_event="announced", window_event_date="2026-08-04",
    target="SEGRO plc", target_ticker="SGRO.L", acquirer="Prologis", deal_type="strategic (Rule 2.7)",
    consideration_type="stock (partial cash alternative)",
    offer_terms="0.0920 PLD sh per SGRO sh; partial cash alt = 258p + 0.0690 PLD sh (at fixed 1,031.7p)",
    headline_value="~GBP14B (~$18.8B per roundups)", value_basis="equity",
    announce_date="2026-08-04", status_2026_09_24="pending", expected_close="H1 2027",
    sector="logistics REIT", geography="UK", verification="press_multi",
    sources="https://www.prologis.com/insights-news/press-releases/prologis-announces-recommended-acquisition-segro-plc; https://www.slaughterandmay.com/recent-work/advising-segro-on-the-recommended-share-offer-by-prologis/",
    notes="Best and final after three proposals. SGRO may pay 2026 interim (<=10.14p) and final (<=22.56p) dividends.")

add(deal_id="2026Q3-014", window_event="announced", window_event_date="2026-08-06",
    target="easyJet plc", target_ticker="EZJ.L", acquirer="Apollo (Eagle Bidco)", sponsor="Apollo",
    deal_type="take-private (Rule 2.7 scheme)", consideration_type="cash (unlisted-share alternative)",
    offer_terms="715p/sh cash", headline_value="~GBP5.7B (~$7.7B)", value_basis="equity",
    premium="81% to 394p close 2026-05-28 (pre-offer period)", announce_date="2026-08-06",
    status_2026_09_24="pending", expected_close="by end-Mar 2027",
    sector="airlines", geography="UK", verification="press_multi",
    sources="https://www.cnbc.com/2026/08/06/easyjet-apollo-castlelake-private-equity-budget-airline.html; https://www.easyjet.com/en/news/airline/article/acquisition-of-easyjet-updates",
    notes="Castlelake (final 690p) withdrew 2026-08-06. Scheme document deadline extended to 2026-10-15. Reuters (via ChatGPT staging) flags an EU airline-ownership execution issue - regulatory risk factor.")

add(deal_id="2026Q3-015", window_event="announced", window_event_date="2026-08-06",
    target="Beazer Homes USA", target_ticker="BZH", acquirer="Dream Finders Homes",
    deal_type="strategic (contested -> agreed)", consideration_type="cash", offer_terms="$33.50/sh cash",
    headline_value="~$2.2B", value_basis="enterprise", announce_date="2026-08-06",
    announce_known_at_utc="2026-08-07T10:10:15Z", status_2026_09_24="pending", expected_close="Q4 2026",
    sector="homebuilding", geography="US", sec_cik="915840",
    sec_announce_accession="0001104659-26-092299", verification="sec_metadata_confirmed",
    sources="https://investors.dreamfindershomes.com/news-events/press-releases/detail/65/dream-finders-homes-to-acquire-beazer-homes-creating",
    notes="Agreement dated 2026-08-06; $31.3M target break fee; DEFM14A 2026-09-15. OPEN QUESTION: new 8-K item 1.01 accepted 2026-09-18T20:05Z (acc 0001104659-26-108933) - content unreadable here (www.sec.gov blocked); may be an amendment.")

add(deal_id="2026Q3-016", window_event="announced", window_event_date="2026-08-10",
    target="Bowman Consulting Group", target_ticker="BWMN", acquirer="Bernhard Capital Partners",
    sponsor="Bernhard Capital Partners", deal_type="take-private (LBO)", consideration_type="cash",
    offer_terms="$43.00/sh cash", headline_value="~$1.0B EV", value_basis="enterprise",
    premium="58% to 2026-08-07 unaffected close; 57% to 30-day VWAP", announce_date="2026-08-10",
    announce_known_at_utc="2026-08-10T13:21:17Z", status_2026_09_24="pending", expected_close="Q4 2026",
    sector="engineering / infrastructure services", geography="US", sec_cik="1847590",
    sec_announce_accession="0001193125-26-341431", verification="sec_metadata_confirmed",
    sources="https://investors.bowman.com/news-releases/news-release-details/bowman-consulting-group-enters-definitive-agreement-be-acquired; https://bowman.com/news/bowman-consulting-group-announces-expiration-of-go-shop-period",
    notes="35-day go-shop expired 2026-09-13, 76 parties contacted, no proposals. Tracked theme #1 (grid/electrical services).")

add(deal_id="2026Q3-017", window_event="proposal", window_event_date="2026-08-13",
    target="Cleanaway Waste Management", target_ticker="CWY.AX", acquirer="EQT Infrastructure",
    sponsor="EQT", deal_type="take-private proposal (non-binding)", consideration_type="cash",
    offer_terms="A$3.13/sh cash (indicative)", headline_value="~A$9.4B EV (Bloomberg: ~$4.9B equity)",
    value_basis="enterprise", premium="32.1% to A$2.37 last close", announce_date="2026-08-13",
    status_2026_09_24="non-binding / exclusivity", sector="waste management", geography="Australia",
    verification="press_multi",
    sources="https://www.bloomberg.com/news/articles/2026-08-12/eqt-offers-to-buy-australia-s-cleanaway-waste-for-4-9-billion; https://www.fool.com.au/2026/09/14/cleanaway-waste-management-provides-eqt-bid-update/",
    notes="Board intends to recommend at >=A$3.13 subject to a scheme implementation deed; 9-week exclusivity; no binding deed as of mid-Sep. Tracked theme #5-adjacent (mandated recurring services).")

add(deal_id="2026Q3-018", window_event="announced", window_event_date="2026-08-13",
    target="Accelerant Holdings", target_ticker="ARX", acquirer="Thoma Bravo", sponsor="Thoma Bravo",
    deal_type="take-private (LBO)", consideration_type="cash", offer_terms="$20.25/sh cash (Class A and B)",
    headline_value=">$4B EV", value_basis="enterprise", premium="49% to 2026-08-12 close",
    announce_date="2026-08-13", announce_known_at_utc="2026-08-13T11:59:29Z",
    status_2026_09_24="pending", expected_close="H1 2027", sector="insurance risk exchange / insurtech",
    geography="US", sec_cik="1997350", sec_announce_accession="0001193125-26-349973",
    verification="sec_metadata_confirmed",
    sources="https://investor.accelerant.ai/news/news-details/2026/Accelerant-Enters-into-Definitive-Agreement-to-be-Acquired-by-Thoma-Bravo/default.aspx",
    notes="6% p.a. ticking fee if insurance-regulatory approvals delay close. known_at = first DEFA14A; 1.01 8-K accepted 2026-08-14T01:14Z.")

add(deal_id="2026Q3-019", window_event="blocked", window_event_date="2026-08-14",
    target="A-Paint Topco (Liquid Nails)", acquirer="Henkel", deal_type="strategic",
    consideration_type="cash", headline_value="$725M", value_basis="purchase price",
    announce_date="2025 (FTC suit Dec 2025)", status_2026_09_24="blocked (permanent injunction)",
    resolution_date="2026-08-14", sector="construction adhesives", geography="US",
    verification="press_multi",
    sources="https://www.cooley.com/news/insight/2026/2026-08-21-ftc-court-win-blocks-henkels-acquisition-of-liquid-nails; https://natlawreview.com/article/ftcs-new-litigation-strategy-sticks-court-blocks-henkels-725m-bid-for-liquid-nails",
    notes="BLOCKED, NOT YET A BREAK LABEL: SDNY permanent injunction 2026-08-14 (valid time); FTC public case summary dated 2026-08-17 (known time, per ChatGPT staging MNA-20260814-HENKEL-LIQUIDNAILS). Y=1 only after party termination/abandonment is verified - GAP. First win of FTC's federal-court-only strategy.")

add(deal_id="2026Q3-020", window_event="announced", window_event_date="2026-08-14",
    target="Harte Hanks", target_ticker="HHS", acquirer="Star Equity Holdings", deal_type="strategic",
    consideration_type="cash + preferred stock", offer_terms="$5.00/sh (cash + Star preferred)",
    headline_value="$38.4M", value_basis="equity", announce_date="2026-08-14",
    status_2026_09_24="pending", expected_close="before end-2026", sector="marketing services",
    geography="US", sec_cik="45919", sec_announce_accession="0000045919-26-000009",
    verification="sec_metadata_confirmed",
    sources="https://www.globenewswire.com/news-release/2026/08/14/3345329/0/en/star-equity-holdings-enters-into-merger-agreement-to-acquire-harte-hanks.html",
    notes="Press release 2026-08-14; Harte Hanks 1.01 8-K accepted 2026-08-19T20:17Z. Cash/preferred split n/d.")

add(deal_id="2026Q3-021", window_event="announced", window_event_date="2026-08-20",
    target="Ambros Therapeutics (private)", acquirer="Werewolf Therapeutics (HOWL)",
    deal_type="reverse merger + $150M PIPE", consideration_type="stock",
    headline_value="Ambros $500M pre-money; Werewolf $47.5M", value_basis="pre-money",
    announce_date="2026-08-21", announce_known_at_utc="2026-08-20T20:06:14Z",
    status_2026_09_24="pending", expected_close="by Q1 2027", sector="biotech", geography="US",
    sec_cik="1785530", sec_announce_accession="0001193125-26-359185", verification="sec_metadata_confirmed",
    sources="https://www.globenewswire.com/news-release/2026/08/21/3349041/0/en/werewolf-therapeutics-and-ambros-therapeutics-announce-merger-agreement-and-concurrent-oversubscribed-150-million-private-placement.html",
    notes="Pro forma: Werewolf holders ~6.8%, Ambros ~71.7%, PIPE ~21.5%. Renamed Ambros (AMBX).")

add(deal_id="2026Q3-022", window_event="announced", window_event_date="2026-08-26",
    target="First Eagle Investments (private)", acquirer="Victory Capital (VCTR)",
    sponsor="Genstar Capital (seller)", deal_type="strategic (sponsor exit)",
    consideration_type="cash + stock", offer_terms="~$4.4B cash + ~$2.0B VCTR stock + $575M notes assumed",
    headline_value="~$7.0B", value_basis="total consideration", announce_date="2026-08-26",
    status_2026_09_24="pending", sector="asset management", geography="US",
    verification="press_multi",
    sources="https://ir.vcm.com/news/news-details/2026/Victory-Capital-to-Acquire-First-Eagle-Investments-Creating-a-571-Billion-Diversified-Global-Asset-Manager/default.aspx; https://www.bloomberg.com/news/articles/2026-08-26/victory-capital-agrees-to-buy-first-eagle-in-7-billion-deal",
    notes="Some roundups cite $6.4B (excludes assumed notes). Genstar ~14.6% of VCTR post-close, voting capped 4.9%.")

add(deal_id="2026Q3-023", window_event="announced (business combination agreement)", window_event_date="2026-07-16",
    target="Delivery Hero", target_ticker="DHER.DE", acquirer="Uber", deal_type="strategic tender offer",
    consideration_type="cash", offer_terms="EUR41.50/sh cash (min. acceptance 50% + 1 share incl. Uber's stake)",
    headline_value="$14.8B equity (100%)", value_basis="equity", premium="~108% to 2026-05-08 unaffected close",
    announce_date="2026-07-16", announce_known_at_utc="2026-07-16T10:35:59Z", status_2026_09_24="pending",
    expected_close="settlement H2 2027", sector="food delivery", geography="Germany",
    sec_cik="1543151", sec_announce_accession="0001552781-26-000382", verification="sec_metadata_confirmed",
    sources="https://www.sec.gov/Archives/edgar/data/1543151/000155278126000382/e26302_ex99-1.htm; https://investor.uber.com/news-events/news/press-release-details/2026/Uber-Publishes-Offer-Document-for-its-Takeover-Offer-for-Delivery-Hero/default.aspx; https://www.cnbc.com/2026/05/23/delivery-hero-confirms-takeover-offer-from-uber.html",
    notes="Definitive BCA 2026-07-16 (UBER 8-K items 1.01/2.03/7.01; EUR14.2B bridge signed same day). offer_document_published = 2026-08-27 (acceptance period 2026-08-27 to 2026-11-05) - a milestone, NOT the announcement. Boards recommended 2026-09-02; Prosus irrevocable (~17%). Earlier approach confirmed 2026-05-23 (CNBC) - proposal history only.")

add(deal_id="2026Q3-024", window_event="announced", window_event_date="2026-08-31",
    target="USI Insurance Services (private)", acquirer="Aon", sponsor="KKR (seller)",
    deal_type="strategic (sponsor exit)", consideration_type="cash",
    headline_value="$17.0B incl. net debt", value_basis="enterprise", announce_date="2026-08-31",
    status_2026_09_24="pending", expected_close="Q4 2026", sector="insurance brokerage",
    geography="US", verification="press_multi",
    sources="https://www.insurancejournal.com/news/national/2026/08/31/883334.htm; https://www.bloomberg.com/news/articles/2026-08-31/aon-agrees-to-buy-usi-insurance-from-kkr-in-17-billion-deal",
    notes="Signed 2026-08-30; debt-funded; $395M run-rate synergies; KKR ~3.4x balance-sheet MOIC (since 2017).")

add(deal_id="2026Q3-025", window_event="announced", window_event_date="2026-08",
    target="OpenRouter (private)", acquirer="Stripe", deal_type="strategic",
    headline_value=">$8B (reported valuation)", status_2026_09_24="n/d", sector="AI infrastructure",
    geography="US", verification="reported_only",
    sources="(FactSet/Intellizence August 2026 roundups, via search summary)",
    notes="Single secondary citation - VERIFY.")

add(deal_id="2026Q3-026", window_event="announced", window_event_date="2026-08",
    target="Ambassador Theatre Group", acquirer="MARI Group", deal_type="n/d",
    headline_value="~$6B (reported)", status_2026_09_24="n/d", sector="live entertainment",
    geography="UK", verification="reported_only",
    sources="(FactSet/Intellizence August 2026 roundups, via search summary)",
    notes="Single secondary citation - VERIFY.")

add(deal_id="2026Q3-027", window_event="closed", window_event_date="2026-08-04",
    target="Electronic Arts", target_ticker="EA", acquirer="PIF / Silver Lake / Affinity Partners",
    sponsor="Silver Lake; Affinity Partners; PIF", deal_type="take-private (LBO)",
    consideration_type="cash", offer_terms="$210.00/sh cash", headline_value="~$55B",
    value_basis="enterprise", announce_date="2025-09-29", status_2026_09_24="closed",
    resolution_date="2026-08-04", sector="video games", geography="US", sec_cik="712515",
    sec_resolution_accession="0001140361-26-031157", verification="sec_metadata_confirmed",
    sources="https://www.ea.com/news/ea-announces-completion-of-acquisition",
    notes="Largest LBO on record. 8-K 2.01 + Form 25-NSE 2026-08-04; 15-12G 2026-08-14.")

# ------------------------------------------------------------ September 2026
add(deal_id="2026Q3-028", window_event="announced", window_event_date="2026-09-02",
    target="Birch Permian Holdings (private)", acquirer="Diversified Energy",
    sponsor="Elliott (seller affiliates)", deal_type="strategic (sponsor exit)",
    headline_value="~$1.8B", announce_date="2026-09-02", status_2026_09_24="pending",
    sector="upstream oil & gas (Permian)", geography="US", verification="press_single",
    sources="https://www.ogj.com/general-interest/companies/news/55402758/diversified-energy-to-acquire-birch-permian-in-18-billion-deal")

add(deal_id="2026Q3-029", window_event="announced", window_event_date="2026-09-02",
    target="Hugging Face (private)", acquirer="Nvidia", deal_type="strategic",
    consideration_type="cash + equity retention",
    offer_terms="~$11.9B purchase price + up to ~$1.0B equity retention",
    headline_value="~$12.9B", value_basis="total incl. retention", announce_date="2026-09-02",
    announce_known_at_utc="2026-09-03T12:03:56Z", status_2026_09_24="pending", expected_close="H1 2027",
    sector="AI platform", geography="US", sec_cik="1045810", sec_announce_accession="0001045810-26-000078",
    verification="sec_metadata_confirmed",
    sources="https://blogs.nvidia.com/blog/nvidia-to-acquire-hugging-face/; https://www.cnbc.com/2026/09/03/nvidia-agrees-to-buy-hugging-face-for-almost-13-billion-ai-expansion.html",
    notes="Event (agreement) date 2026-09-02; known_at = earliest verified public disclosure: NVDA 8-K item 8.01 accepted 2026-09-03T12:03:56Z (= 08:03:56 ET), public announcement dated 2026-09-03. Media reports from 2026-08-27 were unconfirmed and are not used as known_at. Full EU/US/UK review likely.")

add(deal_id="2026Q3-030", window_event="announced", window_event_date="2026-09-03",
    target="Lincoln Bancorp (private)", acquirer="Equity Bancshares (EQBK)", deal_type="bank merger",
    consideration_type="cash + stock", headline_value="$123.8M", value_basis="deal value",
    announce_date="2026-09-03", status_2026_09_24="pending", expected_close="Q4 2026",
    sector="banking (US community)", geography="US", verification="press_multi",
    sources="https://www.equitybank.com/articles/equity-bancshares-inc-and-lincoln-bancorp-announce-plans-to-merge/; http://bankingjournal.aba.com/2026/09/proposed-bank-acquisitions-announced-in-three-states/",
    notes="Target ~$1.7B assets.")

add(deal_id="2026Q3-031", window_event="announced", window_event_date="2026-09-08",
    target="Eagle Financial Services", target_ticker="EFSI", acquirer="John Marshall Bancorp (JMSB)",
    deal_type="bank merger", consideration_type="stock", headline_value="$253M",
    value_basis="deal value", premium="130% of tangible book (price/TBV)", announce_date="2026-09-08",
    announce_known_at_utc="2026-09-08T12:45:26Z", status_2026_09_24="pending", expected_close="Q1 2027",
    sector="banking (US community)", geography="US", sec_cik="880641",
    sec_announce_accession="0001193125-26-384457", verification="sec_metadata_confirmed",
    sources="http://bankingjournal.aba.com/2026/09/proposed-bank-acquisitions-announced-in-three-states/",
    notes="Exchange ratio n/d - GAP. Target ~$1.8B assets (Bank of Clarke).")

add(deal_id="2026Q3-032", window_event="announced", window_event_date="2026-09-09",
    target="Centerspace", target_ticker="CSR", acquirer="Independence Realty Trust (IRT)",
    deal_type="strategic (REIT all-stock)", consideration_type="stock",
    offer_terms="3.800 IRT sh per CSR sh (fixed)", headline_value="~$2.14B (combined EV ~$8.1B)",
    value_basis="deal value / combined EV", announce_date="2026-09-09",
    announce_known_at_utc="2026-09-09T10:49:06Z", status_2026_09_24="pending",
    expected_close="as early as end-Q4 2026", sector="multifamily REIT", geography="US",
    sec_cik="798359", sec_announce_accession="0001140361-26-035986", verification="sec_metadata_confirmed",
    sources="https://www.businesswire.com/news/home/20260909840602/en/Independence-Realty-Trust-and-Centerspace-to-Merge-in-%248.1-Billion-Combination; https://www.insidearbitrage.com/2026/09/independence-realty-trust-to-acquire-centerspace-for-2-14-billion/",
    notes="Pro forma IRT ~78% / CSR ~22%. OPEN QUESTION: new 8-K item 1.01 accepted 2026-09-23T21:16Z (acc 0001140361-26-037453) - content unreadable here; possibly an amendment.")

add(deal_id="2026Q3-033", window_event="announced", window_event_date="2026-09-10",
    target="Convergent Genomics (private)", acquirer="Veracyte (VCYT)", deal_type="strategic",
    announce_date="2026-09-10", status_2026_09_24="n/d", sector="diagnostics", geography="US",
    verification="press_single", sources="https://www.sec.gov/Archives/edgar/data/0001384101/000138410126000049/vcyt-20260910.htm",
    notes="Terms not captured - GAP.")

add(deal_id="2026Q3-034", window_event="announced", window_event_date="2026-09-14",
    target="The Baldwin Group", target_ticker="BWIN", acquirer="Sequence Holdings + Dell Family Office",
    sponsor="Sequence Holdings; DFO Management", deal_type="take-private", consideration_type="cash",
    offer_terms="$32.50/sh cash", headline_value="~$7.7B", value_basis="enterprise (reported)",
    premium="88% to 2026-06-17 unaffected close (reported)", announce_date="2026-09-14",
    announce_known_at_utc="2026-09-14T13:19:14Z", status_2026_09_24="pending",
    sector="insurance distribution", geography="US", sec_cik="1781755",
    sec_announce_accession="0000950103-26-013874", verification="sec_metadata_confirmed",
    sources="https://baldwin.com/news/the-baldwin-group-to-go-private-through-majority-investment-by-sequence-holdings-and-dell-family-office/; https://www.insidearbitrage.com/2026/09/sequence-holdings-and-dell-family-office-to-take-the-baldwin-group-private-for-7-70-billion/",
    notes="Expected close n/d - GAP. Shareholder-fairness investigations announced.")

add(deal_id="2026Q3-035", window_event="announced", window_event_date="2026-09-15",
    target="Atome Financial (majority stake)", acquirer="Grab Holdings", deal_type="strategic",
    announce_date="2026-09-15", status_2026_09_24="n/d", sector="fintech", geography="Southeast Asia",
    verification="press_single",
    sources="https://www.sec.gov/Archives/edgar/data/0001855612/000185561226000133/a6-kxatometransactionannou.htm",
    notes="Terms not captured - GAP.")

add(deal_id="2026Q3-036", window_event="announced", window_event_date="2026-09-15",
    target="Tallgrass crude assets", acquirer="Enbridge", deal_type="asset acquisition",
    consideration_type="cash", headline_value="$2.55B", announce_date="2026-09 (mid)",
    status_2026_09_24="n/d", sector="midstream", geography="US", verification="press_single",
    sources="https://okenergytoday.com/2026/09/tallgrass-energy-sold-in-2-5-billion-deal-to-enbridge/",
    notes="Exact date and status n/d - VERIFY.")

add(deal_id="2026Q3-037", window_event="announced", window_event_date="2026-09-18",
    target="Mistras Group", target_ticker="MG", acquirer="H.I.G. Capital (Athena Purchaser)",
    sponsor="H.I.G. Capital", deal_type="take-private (LBO)", consideration_type="cash",
    offer_terms="$20.35/sh cash", headline_value="~$866M EV", value_basis="enterprise",
    premium="~8% / ~13% to 30- / 90-day VWAP", announce_date="2026-09-18",
    announce_known_at_utc="2026-09-18T20:05:33Z", status_2026_09_24="pending",
    expected_close="late 2026 / early 2027", sector="industrial asset-integrity testing",
    geography="US", sec_cik="1436126", sec_announce_accession="0001140361-26-037107",
    verification="sec_metadata_confirmed",
    sources="https://www.globenewswire.com/news-release/2026/09/18/3364639/12235/en/mistras-group-inc-enters-into-definitive-agreement-to-be-acquired-by-h-i-g-capital-for-20-35-per-share-in-cash.html",
    notes="Agreement dated 2026-09-17. Thin premium vs VWAP - watch for holder pushback. Tracked theme #5-adjacent (mandated inspection).")

add(deal_id="2026Q3-038", window_event="announced", window_event_date="2026-09-18",
    target="WakeMed (nonprofit)", acquirer="Atrium Health (Advocate Health)",
    deal_type="nonprofit health-system combination", announce_date="2026-09-18",
    status_2026_09_24="planned", sector="health systems", geography="US", verification="press_single",
    sources="https://healthtechmagazine.net/article/2026/09/mergers-and-acquisitions-overview-notable-healthcare-ma-activity-2026",
    notes="No price (nonprofit).")

add(deal_id="2026Q3-039", window_event="announced", window_event_date="2026-09-19",
    target="Kelsian SeaLink tourism portfolio", acquirer="Journey Beyond", deal_type="carve-out",
    announce_date="2026-09-19", status_2026_09_24="n/d", sector="tourism", geography="Australia",
    verification="press_single", sources="(search summary, 2026-09-19)",
    notes="Tracked theme #3 (carve-outs). Terms not captured - GAP.")

add(deal_id="2026Q3-040", window_event="announced", window_event_date="2026-09-20",
    target="Dianomi", acquirer="Taboola", deal_type="strategic", announce_date="2026-09-20",
    status_2026_09_24="n/d", sector="adtech", geography="UK", verification="press_single",
    sources="(search summary, 2026-09-20)", notes="Terms not captured - GAP.")

add(deal_id="2026Q3-041", window_event="announced", window_event_date="2026-09-20",
    target="ITM Isotope Technologies Munich (private)", acquirer="Telix Pharmaceuticals",
    deal_type="strategic", consideration_type="cash (+ milestones)",
    offer_terms="$1.65B upfront (cash-free/debt-free) + up to $0.70B milestones",
    headline_value="up to $2.35B", value_basis="total incl. milestones", announce_date="2026-09-20",
    status_2026_09_24="pending", sector="radiopharma", geography="Germany / Australia",
    verification="press_multi",
    sources="https://www.bloomberg.com/news/articles/2026-09-20/telix-to-buy-isotope-maker-itm-in-deal-worth-up-to-2-35-billion",
    notes="Milestones tied to ITM-11 approvals and sales.")

add(deal_id="2026Q3-042", window_event="announced", window_event_date="2026-09-21",
    target="Priority Technology Holdings", target_ticker="PRTH",
    acquirer="Investor group led by CEO Thomas Priore", sponsor="Searchlight Capital (equity)",
    deal_type="take-private (MBO)", consideration_type="cash", offer_terms="$8.05/sh cash",
    headline_value="~$1.6B EV", value_basis="enterprise",
    premium="38% to 2026-09-18 close; 65% to 2025-11-07 (pre-proposal)", announce_date="2026-09-21",
    announce_known_at_utc="2026-09-21T11:40:34Z", status_2026_09_24="pending", expected_close="H1 2027",
    sector="payments", geography="US", sec_cik="1653558",
    sec_announce_accession="0001213900-26-101651", verification="sec_metadata_confirmed",
    sources="https://ir.prioritycommerce.com/news-releases/news-release-details/priority-technology-holdings-inc-announces-definitive-agreement; https://www.businesswire.com/news/home/20260920050170/en/Priority-Technology-Holdings-Inc.-Announces-Definitive-Agreement-with-Investor-Group-Led-by-Chairman-and-CEO-Thomas-Priore-to-Take-Company-Private",
    notes="Special-committee process; no financing condition; needs majority-of-unaffiliated vote + regulatory approvals (issuer IR per ChatGPT staging MNA-20260921-PRIORITY-TAKEPRIVATE). Several roundups say 2026-09-22; SEC acceptance is 2026-09-21 11:40 UTC.")

add(deal_id="2026Q3-043", window_event="terminated", window_event_date="2026-09-20",
    target="Carbonium Core", acquirer="TOMI Environmental Solutions (TOMZ)", deal_type="merger",
    announce_date="2026-06-28", status_2026_09_24="terminated", resolution_date="2026-09-20",
    sector="environmental tech", geography="US", verification="press_multi",
    sources="https://www.globenewswire.com/news-release/2026/09/21/3365883/34752/en/tomi-environmental-solutions-announces-mutual-termination-of-merger-agreement-with-carbonium-core.html",
    notes="BROKEN DEAL. Mutual termination approved by TOMI board 2026-09-20; announced 2026-09-21. Micro-cap.")

add(deal_id="2026Q3-044", window_event="reported (talks)", window_event_date="2026-09-24",
    target="Kobayashi Pharmaceutical", acquirer="CVC + Nippon Sangyo Suishin Kiko (reported)",
    sponsor="CVC", deal_type="take-private talks", headline_value=">JPY500B (~$3.2B)",
    status_2026_09_24="talks only", sector="consumer health", geography="Japan",
    verification="reported_only",
    sources="https://www.bloomberg.com/news/articles/2026-09-24/kobayashi-in-3-2-billion-buyout-talks-after-red-yeast-scandal",
    notes="Not a signed deal.")

# ------------------------------------ pre-window deals with in-window milestones
add(deal_id="2026Q3-045", window_event="milestone (holder vote)", window_event_date="2026-09-23",
    target="Bio-Techne", target_ticker="TECH", acquirer="Merck KGaA", deal_type="strategic",
    consideration_type="cash", offer_terms="$73.00/sh cash", headline_value="~$11.3B EV",
    value_basis="enterprise", announce_date="2026-06-25", announce_known_at_utc="2026-06-25T12:21:30Z",
    status_2026_09_24="pending (shareholders approved 2026-09-23)", expected_close="late 2026 / early 2027",
    sector="life-science tools", geography="US", sec_cik="842023",
    sec_announce_accession="0001999371-26-013527", verification="sec_metadata_confirmed",
    sources="https://investors.bio-techne.com/news/detail/535/merck-kgaa-darmstadt-germany-agrees-to-acquire-bio-techne-strengthening-leadership-position-in-fast-growing-life-sciences-markets",
    notes="Announced pre-window (some roundups list it under August). Remaining: regulatory approvals.")

add(deal_id="2026Q3-046", window_event="closed", window_event_date="2026-09-23",
    target="Theravance Biopharma", target_ticker="TBPH", acquirer="Zymeworks", deal_type="strategic",
    consideration_type="cash + CVR", offer_terms="$17.00/sh cash + CVR (80% of ampreloxetine net proceeds, 10y)",
    headline_value="~$929M", value_basis="equity", announce_date="2026-06-29",
    announce_known_at_utc="2026-06-29T10:30:58Z", status_2026_09_24="closed", resolution_date="2026-09-23",
    sector="biopharma", geography="US", sec_cik="1583107",
    sec_announce_accession="0001104659-26-078453", sec_resolution_accession="0001104659-26-109979",
    verification="sec_metadata_confirmed",
    sources="https://investor.theravance.com/news-releases/news-release-details/theravance-biopharma-enters-definitive-agreement-be-acquired",
    notes="Closed: 8-K 2.01 + Form 25-NSE 2026-09-23.")

add(deal_id="2026Q3-047", window_event="milestone (state AG settlement)", window_event_date="2026-09-21",
    target="Warner Bros. Discovery", target_ticker="WBD", acquirer="Paramount Skydance", deal_type="strategic",
    consideration_type="cash", offer_terms="$31.00/sh cash (+$0.25/sh per quarter ticking fee if not closed by 2026-09-30)",
    headline_value="~$110-111B", value_basis="enterprise", announce_date="2026-02-27",
    announce_known_at_utc="2026-02-27T22:06:16Z",
    status_2026_09_24="pending - near-term after litigation settlement (no dated primary-source close)",
    sector="media", geography="US", sec_cik="1437107", sec_announce_accession="0001437107-26-000018",
    verification="sec_metadata_confirmed",
    sources="https://www.sec.gov/Archives/edgar/data/1437107/000143710726000018/exhibit991.htm; https://www.cnbc.com/2026/09/21/paramount-reaches-settlement-over-warner-bros-merger.html; https://www.cnn.com/2026/09/21/media/paramount-wbd-settlement-cnn-ellison-bonta-lawsuit",
    notes="Definitive agreement 2026-02-27 (WBD 8-K items 1.01/1.02 accepted 22:06:16Z; PSKY 8-K 1.01 2026-03-02). 12-state AG suit (filed July) settled 2026-09-21: 30+ films/yr, studios run separately, news independence board, no divestitures. HSR expired; EC cleared July; UK CMA Phase 1 clearance 2026-08-06, case closed 2026-08-17 (ChatGPT staging). Close timing: press reports an internal memo expecting close by early October - NOT a primary-source date; treat as pending/near-term.")

add(deal_id="2026Q3-048", window_event="pending (no in-window event found)", window_event_date="",
    target="Intertek Group", target_ticker="ITRK.L", acquirer="EQT (Isotope Bidco)", sponsor="EQT",
    deal_type="take-private (Rule 2.7)", consideration_type="cash",
    offer_terms="GBP60.00 cash + 107.7p FY25 final dividend", headline_value="~GBP9.3B equity / GBP10.7B EV",
    value_basis="equity + EV", announce_date="2026-06-18", status_2026_09_24="pending",
    sector="testing, inspection & certification", geography="UK", verification="press_multi",
    sources="https://www.intertek.com/siteassets/investors/offer/rule-2.7-announcement-dated-18-june-2026.pdf",
    notes="Carried as open pending deal; completion timing n/d - GAP.")

add(deal_id="2026Q3-049", window_event="milestone (go-shop expired)", window_event_date="2026-09-13",
    target="Bowman Consulting Group", target_ticker="BWMN", acquirer="Bernhard Capital Partners",
    status_2026_09_24="pending", verification="press_multi",
    sources="https://bowman.com/news/bowman-consulting-group-announces-expiration-of-go-shop-period",
    notes="Milestone row for 2026Q3-016 (no superior proposal).")


# ------------- added from the ChatGPT staging package, re-verified 2026-09-24
add(deal_id="2026Q3-050", window_event="terminated", window_event_date="2026-07-07",
    target="Shutterstock", target_ticker="SSTK", acquirer="Getty Images Holdings (GETY)",
    deal_type="strategic merger", consideration_type="mixed (cash/stock election)",
    announce_date="2025-01 (pre-window)", status_2026_09_24="terminated", resolution_date="2026-07-07",
    sector="stock imagery / content licensing", geography="US / UK", sec_cik="1549346",
    sec_resolution_accession="0001140361-26-028035", verification="sec_metadata_confirmed",
    sources="https://www.gov.uk/cma-cases/getty-images-slash-shutterstock-merger-inquiry; https://www.morningstar.com/news/alliance-news/1782908390072304000/getty-terminates-shutterstock-merger-over-uk-competition-conditions; https://www.tradingview.com/news/tradingview:654ec45e79dc2:0-shutterstock-getty-images-merger-agreement-terminated-after-cma-condition-deal-expires-july-7-2026/",
    notes="BROKEN DEAL (regulatory-driven). Getty delivered written termination notice 2026-07-07 after declining the CMA-required sale of Shutterstock's editorial business; CMA recorded abandonment 2026-07-08; Shutterstock 8-K item 1.02 accepted 2026-07-09T10:03Z (Getty 8-K 8.01 2026-07-07T10:05Z, acc 0001213900-26-075721). Termination fee paid: n/d (agreement had $40M/$32.7M fee provisions) - GAP. Per-share terms n/d - GAP.")

add(deal_id="2026Q3-051", window_event="closed", window_event_date="2026-07-30",
    target="Depop (from Etsy)", acquirer="eBay", sponsor="", deal_type="strategic carve-out",
    consideration_type="cash", headline_value="~$1.4B at close ($1.2B price + ~$0.2B adjustments/interest)",
    value_basis="cash paid", announce_date="2026-02 (agreement 2026-02-15, public 2026-02-18)",
    status_2026_09_24="closed", resolution_date="2026-07-30", sector="online resale marketplace",
    geography="UK / US", verification="press_multi",
    sources="https://investors.ebayinc.com/investor-news/press-release-details/2026/eBay-Completes-Acquisition-of-Depop/default.aspx; https://www.marketscreener.com/news/ebay-inc-completed-the-acquisition-of-depop-limited-from-etsy-inc--ce7f50dad189ff27; https://www.cnbc.com/2026/02/18/ebay-buying-depop-etsy.html",
    notes="CMA Phase 1 clearance 2026-07-15. Private target (carve-out from Etsy) - no target spread, so not usable for break_logit_v1 features. Tracked theme #3 (carve-outs).")

add(deal_id="2026Q3-052", window_event="announced+closed", window_event_date="2026-08-03",
    target="Momentum Midstream (private)", acquirer="Williams Companies (WMB)", deal_type="strategic",
    consideration_type="cash + stock", offer_terms="~$3.5B cash/debt + ~$2.0B WMB equity",
    headline_value="up to $5.5B", value_basis="total consideration", announce_date="2026-08-03",
    status_2026_09_24="closed", resolution_date="2026-09-03", sector="midstream (Haynesville gas)",
    geography="US", sec_cik="107263", verification="press_multi",
    sources="https://www.williams.com/2026/08/03/williams-delivers-strong-second-quarter-2026-results-announces-strategic-acquisition-of-momentum-midstream-connecting-haynesville-to-gulf-coast-lng-and-power-demand/; https://www.williams.com/2026/09/03/williams-completes-acquisition-of-momentum-midstream/",
    notes="ChatGPT staging had this as pending; it CLOSED 2026-09-03 (Williams release; WMB 8-K item 8.01 accepted 2026-09-03T20:21Z). Announced with Q2 earnings (8-K 2.02 2026-08-03), no separate 1.01. Signed-to-close in 31 days.")

add(deal_id="2026Q3-053", window_event="litigation (specific performance)", window_event_date="2026-08-07",
    target="AccuLynx (private)", acquirer="Verisk Analytics (VRSK)", deal_type="strategic",
    headline_value="$2.35B", value_basis="deal value", announce_date="2025 (pre-window)",
    status_2026_09_24="contested - buyer ordered to close; appeal filed 2026-08-18",
    sector="insurance/roofing software", geography="US", sec_cik="1442145",
    verification="press_multi",
    sources="https://www.insurancejournal.com/news/east/2026/08/11/880962.htm; https://www.hsfkramer.com/insights/2026-08/verisk-analytics-v-acculynx-sorry-you-actually-do-have-to-comply-with-that-second-request; https://courts.delaware.gov/opinions/download.aspx?id=399420",
    notes="Del. Chancery (2026-08-07) held Verisk's Dec-2025 termination invalid (its willful conduct caused the FTC-clearance condition to fail) and ordered specific performance; Verisk appealed 2026-08-18 (VRSK 8-K 8.01 same day). NOT a resolved label either way. Buyer-walk risk case study.")

add(deal_id="2026Q3-054", window_event="closed", window_event_date="2026-08-25",
    target="AmSurg (private)", acquirer="Ascension Health", deal_type="strategic",
    consideration_type="cash", headline_value="$3.9B", announce_date="pre-window",
    status_2026_09_24="closed", resolution_date="2026-08 (days after 2026-08-25; exact date n/d)",
    sector="ambulatory surgery centers", geography="US", verification="press_multi",
    sources="https://www.ftc.gov/news-events/news/press-releases/2026/08/ftc-approves-final-consent-order-ascension-health-amsurg-deal; https://www.healthcaredive.com/news/ascension-closes-acquisition-amsurg-following-ftc-scrutiny/822070/",
    notes="FTC final consent order 2026-08-25 requires 7 ASC divestitures (6 to SC Affiliates, 1 to Florida Gastroenterology Center). Close followed within days. Private target.")

add(deal_id="2026Q3-055", window_event="closed", window_event_date="2026-09-01",
    target="Fairfield Medical Center (nonprofit)", acquirer="Adena Health", deal_type="nonprofit hospital acquisition",
    announce_date="2026-09-01", status_2026_09_24="closed", resolution_date="2026-09-01",
    sector="hospitals", geography="US (Ohio)", verification="press_multi",
    sources="https://www.ftc.gov/news-events/news/press-releases/2026/09/statement-regarding-fairfield-medical-centers-sale-adena-health; https://www.adena.org/articles/adena-health-finalizes-acquisition-of-fairfield-medical-center",
    notes="Earlier OhioHealth/FMC proposal ABANDONED after FTC staff concerns (abandonment date n/d - GAP); treat as a separate deal record. ChatGPT flagged completion wording as needing party confirmation - Adena's own release says 'finalizes acquisition'.")

add(deal_id="2026Q3-056", window_event="milestone (approvals; close scheduled)", window_event_date="2026-09-22",
    target="Schroders plc", target_ticker="SDR.L", acquirer="Nuveen", deal_type="strategic (scheme)",
    headline_value="~GBP9.9B", value_basis="equity", announce_date="2026-02-12",
    status_2026_09_24="pending - court sanction hearing 2026-09-29, completion 2026-10-01",
    expected_close="2026-10-01", sector="asset management", geography="UK", verification="press_multi",
    sources="https://www.scottishfinancialnews.com/articles/nuveen-completes-ps99bn-schroders-takeover-on-october-1; https://fxnewsgroup.com/forex-news/institutional/schroders-nuveen-confirm-receipt-of-antitrust-and-regulatory-approvals-for-9-9bn-deal/",
    notes="All antitrust/regulatory approvals received. Label stays censored until completion is confirmed.")

add(deal_id="2026Q3-057", window_event="milestone (CMA Phase 1 launched 2026-08-26)", window_event_date="2026-08-26",
    target="NCR Atleos", target_ticker="NATL", acquirer="Brink's (BCO)", deal_type="strategic",
    consideration_type="cash + stock", offer_terms="$30.00 cash + 0.1574 BCO sh (implied $50.40 at 2026-02-25)",
    headline_value="~$6.6B incl. debt", value_basis="enterprise", premium="24% to prior-day close",
    announce_date="2026-02-26", status_2026_09_24="pending (both holder votes passed 2026-06-30)",
    expected_close="Q1 2027", sector="ATM / cash infrastructure", geography="US", sec_cik="1974138",
    verification="press_multi",
    sources="https://investors.brinks.com/news-releases/news-release-details/brinks-acquire-ncr-atleos-66-billion-creating-leading-financial; https://www.gov.uk/cma-cases/the-brinks-company-slash-ncr-atleos-corporation-merger-inquiry",
    notes="CMA Phase 1 decision deadline 2026-10-22 (ChatGPT staging).")

add(deal_id="2026Q3-058", window_event="milestone (CMA Phase 1 launched 2026-09-16)", window_event_date="2026-09-16",
    target="Unilever Foods (carve-out)", acquirer="McCormick (MKC)", deal_type="Reverse Morris Trust",
    consideration_type="stock + $15.7B cash to Unilever", headline_value="~$44.8B EV (Unilever Foods)",
    value_basis="enterprise", announce_date="2026-03-31", status_2026_09_24="pending",
    sector="food / flavours", geography="Global", sec_cik="63754", verification="press_multi",
    sources="https://www.unilever.com/news/press-and-media/press-releases/2026/unilever-announces-the-combination-of-unilever-foods-with-mccormick/; https://www.gov.uk/cma-cases/mccormick-slash-unilever-merger-inquiry",
    notes="Pro forma: Unilever holders ~55.1%, MKC holders ~35.0%, Unilever ~9.9%. CMA invitation to comment 2026-07-21; Phase 1 deadline 2026-11-11. Tracked theme #3 (carve-outs).")

add(deal_id="2026Q3-059", window_event="milestone (CMA invitation to comment 2026-09-22)", window_event_date="2026-09-22",
    target="TK Elevator", acquirer="KONE",
    sponsor="Vertical Topco I S.A. (seller; jointly controlled by Advent and Cinven)", deal_type="strategic (sponsor exit)",
    consideration_type="cash + stock", offer_terms="EUR5B cash + up to 270M new KONE B shares",
    headline_value="EUR29.4B (~$34.4B)", value_basis="enterprise", announce_date="2026-04-29",
    status_2026_09_24="pending", sector="elevators & escalators", geography="Europe", verification="press_multi",
    sources="https://www.kone.com/global/en/newsroom/releases/2026/inside-information--kone-and-tke-to-combine--creating-a-world-class-company-in-the-elevator-and-escalator-industry-2026-04-29.html; https://peinsights.substack.com/p/advent-and-cinven-exit-tke-in-294bn; https://www.gov.uk/cma-cases/kone-slash-tk-elevator-merger-inquiry",
    notes="Largest pending deal touched in window by a regulator step. Heavy antitrust exposure (EU/UK/US). Seller per KONE release: Vertical Topco I S.A., receiving EUR5B cash + up to 270M KONE B shares at completion (no earlier than Q2 2027 per reporting).")

add(deal_id="2026Q3-060", window_event="milestone (CMA Phase 1 launched 2026-09-02)", window_event_date="2026-09-02",
    target="OVO Energy (retail business)", acquirer="E.ON", deal_type="strategic",
    announce_date="2026-05-11", status_2026_09_24="pending", expected_close="H2 2026",
    sector="energy retail", geography="UK", verification="press_multi",
    sources="https://www.eon.com/en/about-us/media/press-release/2026/eon-announces-acquisition-of-uk-energy-supplier-ovo.html; https://www.gov.uk/cma-cases/eon-slash-ovo-merger-inquiry",
    notes="CMA invitation to comment 2026-07-08; Phase 1 deadline 2026-10-28. OVO Home Services sold separately to Hometree. Price n/d - GAP.")

add(deal_id="2026Q3-061", window_event="milestone (CMA invitation to comment 2026-07-23)", window_event_date="2026-07-23",
    target="ITV Media & Entertainment", acquirer="Sky (Comcast)", deal_type="carve-out",
    consideration_type="cash + asset", offer_terms="GBP1.2B cash + Love Productions (~GBP200M) + earn-out up to GBP200M",
    headline_value="up to GBP1.6B", value_basis="total consideration", announce_date="2026-07 (pre-ITC)",
    status_2026_09_24="pending (CMA review)", sector="broadcasting / streaming", geography="UK",
    verification="press_multi",
    sources="https://www.cityam.com/sky-and-itv-mount-defence-of-1-6bn-merger-as-regulators-probe-deal/; https://www.gov.uk/cma-cases/sky-slash-itv-merger-inquiry",
    notes="Exact signing date n/d - GAP. Tracked theme #3 (carve-outs).")

add(deal_id="2026Q3-062", window_event="rejected", window_event_date="2026-09-21",
    target="Ingenia Communities", target_ticker="INA.AX", acquirer="Warburg Pincus", sponsor="Warburg Pincus",
    deal_type="unsolicited proposal (revised)", consideration_type="cash",
    offer_terms="A$5.05/sh (revised from A$4.75)", headline_value="~A$2.06B (~$1.47B)",
    status_2026_09_24="rejected", resolution_date="2026-09-21", sector="residential communities / REIT",
    geography="Australia", verification="press_multi",
    sources="https://www.bloomberg.com/news/articles/2026-09-20/ingenia-rejects-new-1-5-billion-warburg-pincus-takeover-bid; https://grafa.com/en/news/australia/ingenia-communities-rejects-revised-5-05-takeover-bid-from-warburg",
    notes="PROPOSAL HISTORY ONLY - never a break label. Conditional on Ingenia not proceeding with its Peet acquisition.")

add(deal_id="2026Q3-063", window_event="rejected", window_event_date="2026-09-22",
    target="IDP Education", target_ticker="IEL.AX", acquirer="Blackstone", sponsor="Blackstone",
    deal_type="unsolicited proposal (revised)", consideration_type="cash",
    offer_terms="A$2.50/sh (revised from A$2.30; submitted 2026-09-09)", headline_value="~A$694.7M (~$494M)",
    premium="56% to 2026-09-08 close", status_2026_09_24="rejected", resolution_date="2026-09-22",
    sector="education services", geography="Australia", verification="press_multi",
    sources="https://www.marketscreener.com/news/idp-education-rejects-blackstone-s-takeover-proposal-ce785ad9d98ef02d; https://grafa.com/en/news/australia/idp-education-rejects-2-50-blackstone-takeover-offer",
    notes="PROPOSAL HISTORY ONLY - never a break label. Board called it 'highly opportunistic'.")

add(deal_id="2026Q3-064", window_event="milestone (FTC proposed consent)", window_event_date="2026-09-16",
    target="Sturm, Ruger & Co. (minority stake)", target_ticker="RGR", acquirer="Beretta Holding",
    deal_type="minority stock purchase", status_2026_09_24="pending - behavioural remedy",
    sector="firearms", geography="US", sec_cik="95029", verification="press_single",
    sources="https://www.ftc.gov/legal-library/browse/cases-proceedings/berettaruger",
    notes="FTC proposed consent addresses board/governance entanglement (per ChatGPT staging; ftc.gov unreachable). Ruger 8-K items 1.01/1.02/3.03 accepted 2026-09-16T20:45Z (acc 0001174947-26-000877) and a Schedule 13D/A 2026-09-17 - consistent, content unread. Not a whole-company merger label.")


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ids = [r["deal_id"] for r in R]
    assert len(ids) == len(set(ids)), "duplicate deal_id"
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(R)
    print(f"wrote {len(R)} rows -> {OUT}")


if __name__ == "__main__":
    main()
