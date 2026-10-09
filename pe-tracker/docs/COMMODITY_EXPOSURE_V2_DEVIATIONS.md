# Commodity-exposure v2: deviations log

All deviations from `docs/PREREG_COMMODITY_EXPOSURE_COVERAGE_v2.md` and from the implementation frozen in commit `60b29c9` are recorded here. They are listed in the order they occurred.

## D1. Entity-resolution extraction mechanics fixed after the first live run (before any v2 labeling)
**When**
- The first live `resolve` run, using the frozen `60b29c9` code, made 298 SEC requests with the owner-authorized contact supplied via `SEC_CONTACT_EMAIL` at runtime.
- It resolved only 17/129 acquirers. 64 were "not identified in merger filing", even for plain strategic deals (Cisco, AMD, Salesforce, Oracle).
- It also produced wrong identities:
  - **APC-OXY → Chevron.** The manifest announcement accession is a Chevron-filed 425.
  - **REYNOL-IMPERI and DOVER-WEBSTE.** Each was resolved to the **target itself**.

**What was inspected**
- Only identity-resolution output (identities CSV, merger-filing text) was inspected, for all 129 deals, which includes the v2 validation sample.
- **No exposure labels had been generated**, and labeling rules (`rules.py`) were not changed. `git diff 60b29c9 -- pe-tracker/scripts/commodity_v2/rules.py` is empty.

**Changes (`entities.py`)**: these are mechanical parsing/safety fixes within prereg §2. No new identity sources were added beyond those named in §2 (the merger filing and its SEC header).
1. **Spaced quotes.** Defined-term parsing tolerates spaced quotes (`(“ Parent ”)`), Parent definitions without an entity-type clause, and longer jurisdiction clauses.
2. **Party clauses.** When no Parent-type term exists, the acquirer is taken as the first merger-agreement party that is neither the target nor a merger sub. This covers short-name definitions such as `(“AMD”)`.
3. **SEC header filer.** For bidder-filed merger filings (425, SC TO-T/TO-C, SC 14D1), the filing's SEC header `FILED BY`/`FILER` CIK (≠ target) is used. This is accepted only when consistent with the manifest acquirer name, which rejects APC-OXY → Chevron.
4. **Defined terms.** Defined terms ("Parent", "Buyer", "Company", …) and bare suffixes are never used as entity names.
   - Name variants strip leading list items, e.g. "Company, Microsoft Corporation" → "Microsoft Corporation".
   - "Holdings Inc" was removed from the suffix list. Stripping it had collapsed "Dover Saddlery Holdings, Inc" onto the target.
5. **Target exclusion.** **The target's own CIK is never accepted as the acquirer.**
6. **Small caps.** Small-caps splits ("T APESTRY , I NC .") are normalized for identity extraction only.
7. **Wholly-owned clause.** The ultimate-parent search skips "wholly owned subsidiary of Parent"-type clauses and searches 3,000 chars instead of 400.
8. **PE signal.** It now also recognizes "Fund/Capital/Partners … L.P." names and "Parent … affiliates of / controlled by / owned by … Capital/Partners/Equity/Fund/Management".
   - Case-sensitive guards prevent matches such as "owned by the Minority Limited Partners" or third-party voting-agreement holders.

**New output column.** `identity_note` explains rejected header identities.

**Effect (acquirers)**

| Outcome | Before | After |
|---|---|---|
| resolved | 17 | 54 |
| pe_buyer_unresolved | 17 | 44 |
| no_unique_sec_registrant | 31 | 27 |
| not_identified | 64 | 4 |

All fixes have unit tests in `tests/test_commodity_exposure_v2.py`.

**Known remaining limitation.** A guarantor party ("solely for certain limited purposes, Oracle Corporation") is not treated as the acquirer. CERN-ORCL therefore stays `acquirer_no_unique_sec_registrant`. The same applies to sponsor deals the manifest calls `strategic` without sponsor language near the Parent definition (e.g. CEC-APOLLO, BLYTH-CARLYL). Their reason is `acquirer_no_unique_sec_registrant` rather than `acquirer_pe_buyer_unresolved`, but **either way they are `unknown`, and no sponsor identity is substituted**.
