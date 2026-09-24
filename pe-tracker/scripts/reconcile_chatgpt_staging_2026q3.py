"""Reconcile the ChatGPT staging package against this repo's own verification.

Input : data/public_mna_intelligence/2026-07-01_2026-09-24/staging_chatgpt/public_mna_events.csv
        (kept byte-for-byte as delivered, for provenance)
Output: data/public_mna_intelligence/2026-07-01_2026-09-24/reconciliation.csv

Every staging source URL (gov.uk, ftc.gov, reuters.com, issuer IR) was
unreachable from this environment (proxy 403), so no staging row is upgraded on
the strength of its own URL. Rows are instead checked against EDGAR metadata
(data.sec.gov) or independent search results, and linked to the deal register.
Label candidates follow the repo contract: Y=1 only for a verified termination
of a SIGNED deal, Y=0 only for verified completion; clearances, injunctions and
rejected proposals are never labels by themselves.
Run:  python scripts/reconcile_chatgpt_staging_2026q3.py
"""
import csv
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "data" / "public_mna_intelligence" / "2026-07-01_2026-09-24"
STAGING = BASE / "staging_chatgpt" / "public_mna_events.csv"
OUT = BASE / "reconciliation.csv"

# record_id -> (status, register_deal_id, label_candidate_after_review, note)
REVIEW = {
 "MNA-20260708-GETTY-SSTK": ("confirmed_sec_metadata", "2026Q3-050", "Y1_CANDIDATE",
    "Termination confirmed: Getty notice 2026-07-07; Shutterstock 8-K item 1.02 accepted 2026-07-09T10:03Z. Resolution date is 07-07 (party), not 07-08 (CMA page)."),
 "MNA-20260708-EON-OVO-ITC": ("corroborated_press", "2026Q3-060", "NONE", "Deal signed 2026-05-11 (E.ON release)."),
 "MNA-20260714-ABF-HOVIS": ("unverified_source_unreachable", "", "NONE", "Regulator-only event; completion not checked."),
 "MNA-20260715-EBAY-DEPOP-CLEAR": ("corroborated_press", "2026Q3-051", "NONE", "Clearance is not a label."),
 "MNA-20260715-DANONE-HUEL-LAUNCH": ("unverified_source_unreachable", "", "NONE", "Regulator-only event."),
 "MNA-20260721-MCCORMICK-UNILEVER-ITC": ("corroborated_press", "2026Q3-058", "NONE", "Deal announced 2026-03-31, ~$44.8B EV."),
 "MNA-20260723-SKY-ITV": ("corroborated_press", "2026Q3-061", "NONE", "Up to GBP1.6B carve-out."),
 "MNA-20260730-EBAY-DEPOP-CLOSE": ("corroborated_press", "2026Q3-051", "Y0_CANDIDATE_PRIVATE_TARGET",
    "Completion corroborated (~$1.4B incl. adjustments). Private target: no spread features for break_logit_v1."),
 "MNA-20260731-IONQ-SKYWATER": ("corrected", "2026Q3-008", "NONE",
    "Staging state 'pending' is stale: deal CLOSED same day 2026-07-31 (SKYT 8-K 2.01 + Form 25). The Y=0 comes from the close, not the FTC event."),
 "MNA-20260803-WILLIAMS-MOMENTUM": ("corrected", "2026Q3-052", "Y0_CANDIDATE_PRIVATE_TARGET",
    "Staging says pending; deal CLOSED 2026-09-03 (Williams release, WMB 8-K 8.01)."),
 "MNA-20260806-APOLLO-EASYJET": ("corroborated_press", "2026Q3-014", "NONE", "Matches register."),
 "MNA-20260806-PARAMOUNT-WBD-CLEAR": ("unverified_source_unreachable", "2026Q3-047", "NONE", "Clearance is not a label."),
 "MNA-20260808-VERISK-ACCULYNX": ("corrected", "2026Q3-053", "NONE",
    "Ruling dated 2026-08-07 (08-08 is the report date); Verisk appealed 2026-08-18. Unresolved."),
 "MNA-20260813-SERAS-ENVA-CLEAR": ("unverified_source_unreachable", "", "NONE", "Regulator-only event."),
 "MNA-20260814-HENKEL-LIQUIDNAILS": ("corroborated_press", "2026Q3-019", "NONE_UNTIL_TERMINATION_VERIFIED",
    "Injunction 08-14 (valid) vs FTC summary 08-17 (known) kept distinct. Not Y=1 until abandonment verified."),
 "MNA-20260817-PARAMOUNT-WBD-CMA-CLOSE": ("unverified_source_unreachable", "2026Q3-047", "NONE", "Regulatory case closure is not a label."),
 "MNA-20260820-DANONE-HUEL-CLEAR": ("unverified_source_unreachable", "", "NONE", "Regulator-only event."),
 "MNA-20260825-ASCENSION-AMSURG": ("corrected", "2026Q3-054", "Y0_CANDIDATE_PRIVATE_TARGET",
    "Beyond staging: Ascension CLOSED within days of the 08-25 consent order (exact date n/d)."),
 "MNA-20260826-BRINKS-NCR": ("corroborated_press", "2026Q3-057", "NONE", "Deal announced 2026-02-26 ($30 + 0.1574 BCO)."),
 "MNA-20260901-ADENA-FMC": ("corroborated_press", "2026Q3-055", "Y0_CANDIDATE_NONPROFIT",
    "Adena release says it finalized the acquisition 2026-09-01. Earlier OhioHealth/FMC deal abandoned (separate record; date n/d)."),
 "MNA-20260902-EON-OVO-LAUNCH": ("corroborated_press", "2026Q3-060", "NONE", ""),
 "MNA-20260903-SERAS-ENVA-CLOSE": ("unverified_source_unreachable", "", "NONE", "Regulator-only event."),
 "MNA-20260915-OCS-MITIE": ("unverified_source_unreachable", "", "NONE", "Regulator-only event; deal terms not captured."),
 "MNA-20260916-MCCORMICK-UNILEVER-LAUNCH": ("corroborated_press", "2026Q3-058", "NONE", ""),
 "MNA-20260916-BERETTA-RUGER": ("confirmed_sec_metadata", "2026Q3-064", "NONE",
    "Ruger 8-K items 1.01/1.02/3.03 accepted 2026-09-16T20:45Z consistent with the consent; content unread."),
 "MNA-20260917-ABP-DOVECOTE": ("unverified_source_unreachable", "", "NONE", "IEO 09-17 (valid) vs page 09-21 (known) kept distinct."),
 "MNA-20260921-PRIORITY-TAKEPRIVATE": ("confirmed_sec_metadata", "2026Q3-042", "NONE",
    "PRTH 8-K item 1.01 accepted 2026-09-21T11:40:34Z; matches staging terms."),
 "MNA-20260921-PARAMOUNT-WBD-STATES": ("corroborated_press", "2026Q3-047", "NONE", "Settlement confirmed by CNBC/CNN/Variety."),
 "MNA-20260921-INGENIA-WARBURG": ("corroborated_press", "2026Q3-062", "NEVER_LABEL_PROPOSAL", "Rejected proposal."),
 "MNA-20260922-IDP-BLACKSTONE": ("corroborated_press", "2026Q3-063", "NEVER_LABEL_PROPOSAL", "Rejected proposal."),
 "MNA-20260922-KONE-TKE": ("corroborated_press", "2026Q3-059", "NONE", "Deal announced 2026-04-29, EUR29.4B."),
 "MNA-20260922-SCHRODERS-NUVEEN": ("corroborated_press", "2026Q3-056", "NONE_UNTIL_COMPLETION",
    "Court hearing 2026-09-29; completion 2026-10-01 scheduled, not yet occurred."),
 "MNA-20260923-GXO-WINCANTON-CLOSECASE": ("unverified_source_unreachable", "", "NONE",
    "Remedy divestiture 09-13 (valid) vs CMA summary 09-23 (known) kept distinct; not the original deal's close."),
}
FIELDS_ADD = ["reconciliation_status", "register_deal_id", "label_candidate_after_review", "reconciliation_note"]


def main():
    rows = list(csv.DictReader(STAGING.open()))
    missing = {r["record_id"] for r in rows} ^ set(REVIEW)
    assert not missing, f"unreviewed or unknown records: {missing}"
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["record_id", "deal_key", "event_date", "known_at_date",
                                          "event_type", "source_url"] + FIELDS_ADD)
        w.writeheader()
        for r in rows:
            st, reg, lab, note = REVIEW[r["record_id"]]
            w.writerow({k: r[k] for k in ("record_id", "deal_key", "event_date", "known_at_date",
                                          "event_type", "source_url")}
                       | dict(zip(FIELDS_ADD, (st, reg, lab, note))))
    print(f"reconciled {len(rows)} staging rows -> {OUT}")


if __name__ == "__main__":
    main()
