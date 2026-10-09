# Commodity-exposure v2: first-pass labels (UNVALIDATED, research only)

**Status: not validated.** The labels and blinded packet below await the separate AI-assisted review, which is not independent human review (prereg §6). No agreement has been scored. **Do not use these labels in any model, feature, or the canonical DB.** No model fit, backtest, walk-forward, DB mutation, or feature integration was performed.

## Run provenance
| Item | Value |
|---|---|
| Code | commit `fd4f696` (implementation `60b29c9` + entity-resolution fix D1, see `COMMODITY_EXPOSURE_V2_DEVIATIONS.md`) |
| Rules hash | `rules_sha256` = `21812309b8442ef8b9ad821f341d282395bfb5bd2d0ed56f30f8539558cb6373` (also in `data/research/commodity_exposure_v2_run.json`) |
| SEC access | Live, 2026-10-09. The contact is supplied only via the runtime env var `SEC_CONTACT_EMAIL` and is not stored in the repo or any artifact. Requests are spaced ≥ 0.12 s. Already-downloaded v1 cache files were reused where available. |

## Artifacts
| Path | Contents |
|---|---|
| `data/research/commodity_exposure_v2_identities.csv` | Acquirer identity per deal: merger-filing accession, form, filing date, SEC acceptance (ET), parent/ultimate-parent quotes, PE signal + quote, matched registrant, current-vintage SIC (context only), and reason when unknown |
| `data/research/commodity_exposure_v2_labels.csv` | 258 party rows with producer / consumer / hedged. Each non-unknown cell carries accession, form, filing date, SEC acceptance timestamp (ET), document URL, Item, offset, and quote. |
| `data/research/commodity_exposure_v2_run.json` | Coverage, unknown rates, entity-resolution counts, rules hash, research-only flags |
| `data/research/commodity_exposure_v2_review_packet/` | **Blinded** review packet for the 20 preregistered validation deals: one `DEAL-*.md` per deal, plus `index.json`, `README.md` (criteria and instructions), and `response_template.csv`. It contains no first-pass labels. |

## Coverage (first pass, all 129 deals; descriptive)
- **`not_yet_reviewed`: 0.** All 258 rows are `labeled` or `unknown` with a reason.
- **Unknown share:** 74.0% of all 258 party rows.

| Party | labeled | unknown (share) | unknown reasons | producer yes | consumer yes | hedged yes / no_disclosed |
|---|---|---|---|---|---|---|
| target | 43 | 86 (66.7%) | 85 no qualifying disclosure; 1 no in-window annual report | 8 | 38 | 17 / 3 |
| acquirer | 24 | 105 (81.4%) | 44 PE buyer unresolved; 27 no unique SEC registrant; 4 not identified in merger filing; 30 no qualifying disclosure | 6 | 20 | 9 / 0 |

- **Per-flag unknown rate.**
  - Targets: producer 94.0%, consumer 70.5%, hedged 84.5%.
  - Acquirers: producer 95.3%, consumer 84.5%, hedged 93.0%.
- **By deal.** 53 of 129 deals have at least one labeled party: breaks 8/20, closes 45/109. This is descriptive only; no association was tested.
- **Comparison with v1.** v2 labels far fewer rows as exposed than v1 (target labeled 43 vs 84). This is expected from the stricter preregistered criteria. Whether the stricter rules are *accurate* is what the blinded review will test.

## Entity resolution (acquirers)
- **Resolved:** 54/129, all `strategic` deals.
  - Extraction methods across all 129 rows: 120 used a defined Parent/Buyer term and 2 used a merger-agreement party clause. 6 rows were resolved via the bidder-filed SEC header.
  - 53/54 are consistent with the manifest acquirer name. The exception is SUTRON-HACH, which resolved to Danaher Corporation: the merger agreement names Danaher as Parent, and Hach is a Danaher subsidiary.
- **Unknown PE buyers:** 44 `acquirer_pe_buyer_unresolved`. These are 22 manifest `take_private` deals plus 22 `strategic` deals whose merger filing shows sponsor/fund language. The sponsor's management company was never substituted.
- **Other unknown:**
  - 27 `acquirer_no_unique_sec_registrant`: foreign or private buyers, acquisition vehicles without sponsor language, ambiguous names.
  - 4 `acquirer_not_identified_in_merger_filing`. This includes APC-OXY: the manifest's announcement accession is a Chevron-filed 425 that conflicts with the manifest acquirer, so it was rejected.
- **Validation sample composition (identity only):** 8 of 20 acquirers resolved; 12 unknown.

## Scoring (to be run only after the reviewer's CSV exists)
```
python -m scripts.commodity_v2.score --review path/to/completed_response_template.csv
```
This writes `data/research/commodity_exposure_v2_agreement.json`, containing:
- **G1:** exact agreement on ≥ 18/20 deals.
- **G2:** shared-unknown rule. It needs ≥ 15 substantive cells and ≥ 0.85 agreement on them; otherwise `not_evaluable`, which fails.
- **G3:** κ ≥ 0.60 for each evaluable flag. Consumer is required.
- **Also reported:** per-flag agreement (overall and substantive), per-rater unknown rates, and disagreements.

## Known limitations
- **Merger-filing identity.**
  - Guarantor-only parties ("solely for certain limited purposes, Oracle Corporation") are not used, so CERN-ORCL is unknown.
  - Some sponsor deals labeled `strategic` in the manifest lack sponsor language near the Parent definition and are reported as `no_unique_sec_registrant` (e.g. CEC-APOLLO, BLYTH-CARLYL). They are unknown either way.
- **SIC** is current-vintage SEC metadata, not point-in-time. It is context only.
- **Packet section spans** come from heading heuristics. Some Item 7A spans are short when 7A cross-references Item 7. Reviewers should use the full-document URL when a span looks wrong.
- **Evidence scope** is the latest in-window annual report plus the latest subsequent pre-announcement 10-Q. 8-Ks are never exposure evidence.
- **Development tuning.** Development used the v1 sample, and rules were tuned in-sample there (`COMMODITY_EXPOSURE_V2_DEV_DRYRUN.md`).
