# Geopolitical research report (read-only)

**Module:** `RESEARCH_STAGING_NOT_A_MODEL_FEATURE`  
**Models:** NON-EXECUTABLE FOR LIVE TRADING AND UNVALIDATED FOR EMPIRICAL PREDICTION  
**Synthetic values:** none

## Resolved deal outcomes

Source `pe-tracker/data/sec_deal_manifest.json`, N = 129.

| Outcome | N |
|---|---:|
| closed | 109 |
| terminated | 19 |
| withdrawn | 1 |

_Reviewer-curated corpus; sample prevalence is not a population break rate (docs/SAMPLING_FRAME.md)._

## Deal coverage and missingness

| Field | Present | Missing |
|---|---:|---:|
| announcement_timestamp | 129 | 0 |
| announcement_accession | 129 | 0 |
| terms_accession | 129 | 0 |
| offer_price | 119 | 10 |
| exchange_ratio | 21 | 108 |
| resolution_timestamp | 129 | 0 |
| resolution_accession | 129 | 0 |
| resolution_type | 129 | 0 |
| deal_type | 129 | 0 |
| consideration_type | 129 | 0 |
| target_cik | 129 | 0 |

## Historical sample composition

deal_type: {'strategic': 107, 'take_private': 22}  
consideration_type: {'cash': 108, 'mixed': 11, 'stock': 10}  
first_walkforward_v1 cohort: {'in_frozen_cohort_N62': 62, 'outside_cohort': 67}

## Verified geopolitical event timeline

## Geopolitical exposure by sector

**No validated event→deal exposure links.**

## Source verification & coverage

| Status | Clusters |
|---|---:|
| VERIFIED_PRIMARY | 1 |
| CORROBORATED_SECONDARY | 0 |
| ATTRIBUTED_CLAIM | 13 |
| UNCONFIRMED | 37 |
| DISPUTED | 1 |
| RETRACTED | 0 |

Corpus sector coverage: {'manifest_deals': 129, 'manifest_deals_with_research_sector_label': 4, 'manifest_deals_without_sector': 125, 'note': 'Sector exists only as free text in the research-only 2026Q3 register; it is not mapped to the controlled SECTORS vocabulary automatically.'}

## Reserved model charts

| Chart | Model | Status |
|---|---|---|
| Ranked deal-break probabilities | break_logit_v1 | NOT AVAILABLE — MODEL NOT EXECUTED |
| ROC and precision–recall curves | break_logit_v1 | NOT AVAILABLE — MODEL NOT EXECUTED |
| Probability calibration | break_logit_v1 | NOT AVAILABLE — MODEL NOT EXECUTED |
| Walk-forward performance against baselines | break_logit_v1 | NOT AVAILABLE — MODEL NOT EXECUTED |
| Expected-value sensitivity | break_logit_v1 | NOT AVAILABLE — MODEL NOT EXECUTED |
| Time-varying close/break/continue probabilities | break_hazard_v1 | NOT AVAILABLE — MODEL NOT EXECUTED |
| Competing-risk cumulative incidence | break_hazard_v1 | NOT AVAILABLE — MODEL NOT EXECUTED |
| Event-driven changes in estimated break risk | break_hazard_v1 | NOT AVAILABLE — MODEL NOT EXECUTED |
| Risk by forecast horizon | break_hazard_v1 | NOT AVAILABLE — MODEL NOT EXECUTED |
