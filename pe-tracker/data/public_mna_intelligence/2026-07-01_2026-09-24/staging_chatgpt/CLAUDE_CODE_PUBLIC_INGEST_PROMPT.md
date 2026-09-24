# Claude Code — Public M&A Backfill Without SEC/EDGAR Dependency

Repository: `ibernard26/MARKET-PE-INTELLIGENCE-RESEARCH`

Use the supplied staging files to build a public-source M&A/event backfill covering **2026-07-01 through 2026-09-24 inclusive**.

Create: `pe-tracker/data/public_mna_intelligence/2026-07-01_2026-09-24/`

Do not require `data.sec.gov` or `www.sec.gov`. Fetch the public URLs already supplied in the CSV/JSON. Prefer primary sources in this order: GOV.UK CMA, FTC, issuer/acquirer IR, then Reuters as a secondary fallback.

## Hard constraints
1. Staging rows are NOT canonical model-training rows.
2. Verify every source URL before canonical ingestion.
3. Capture the source publication/update date exactly as exposed.
4. Never invent time-of-day. Use the repo's conservative date normalization only when the source is date-only.
5. Preserve `event_date != known_at_date` when applicable.
6. Quarantine unavailable or contradictory records.
7. Do not auto-train.

## Label contract
- `Y=1`: signed deal definitively terminated/broken/withdrawn.
- `Y=0`: signed deal definitively completed/closed.
- pending: censored.

Never map regulatory clearance to `Y=0`, regulatory challenge to `Y=1`, a rejected preliminary offer to `Y=1`, or a court injunction directly to `Y=1` without verified termination.

## High-value records
- eBay/Depop completion: https://investors.ebayinc.com/investor-news/press-release-details/2026/eBay-Completes-Acquisition-of-Depop/default.aspx
- Getty/Shutterstock abandonment: https://www.gov.uk/cma-cases/getty-images-slash-shutterstock-merger-inquiry
- Henkel/Liquid Nails block: https://www.ftc.gov/legal-library/browse/cases-proceedings/henkel-paint
- Priority take-private: https://ir.prioritycommerce.com/news-releases/news-release-details/priority-technology-holdings-inc-announces-definitive-agreement
- GXO/Wincanton remedy closure: https://www.gov.uk/cma-cases/gxo-slash-wincanton-merger-inquiry

## Provider design
If the existing `HistoricalDealProvider` requires a full deal record, do not fake missing fields for regulatory-only events. Add the smallest staging/regulator-event provider necessary to attach sourced events to an existing canonical deal. Keep proposal history separate from signed deals.

Suggested event classes: `regulatory_inquiry_opened`, `invitation_to_comment`, `phase1_clearance`, `phase2_clearance`, `clearance_with_remedies`, `initial_enforcement_order`, `consent_order`, `court_injunction`, `early_termination_review`, `merger_abandoned`, `remedy_divestiture_completed`.

Suggested proposal states: `proposal`, `revised_proposal`, `proposal_rejected`, `definitive_agreement`, `pending_signed_deal`, `closed`, `terminated`. `proposal_rejected` must never become a positive break label.

## Tests
Add tests proving: date-only sources do not get invented intraday times; valid time can precede known time; rejected proposals cannot become `Y=1`; regulatory clearance cannot become `Y=0`; blocked deals require termination verification before `Y=1`; primary issuer completion can become a close candidate; unavailable sources are quarantined; event ingestion is idempotent; provenance URL/source/date are preserved.

## Report back
Report reachable URLs, rows upgraded from secondary to primary sources, quarantined rows, canonical deals/events added, new real labeled rows eligible for `break_logit_v1`, updated `MODEL_DATA_STATUS`, and remaining gaps. Do not merge automatically.
