# Deferred backlog remainder

After **3** deferred-resolution revolutions (canonical N=129).

## Queue status

| Status | N |
|---|---:|
| `PENDING` | 86 |
| `ADMIT` | 60 |
| `DEFER` | 49 |
| `EXCLUDE` | 19 |

Remaining machine-candidates: PENDING=86 (plus this-loop DEFER rows that may retry with further extractor work).

## Engineering bottlenecks (by frequency among unresolved)

Ranked by remaining deferred/pending primary class (not investment attractiveness):

| Bottleneck class | Remaining N | Suggested code-path (no scientific-rule change) |
|---|---:|---|
| `ACQUIRER_EXTRACTION` | 84 | Improve Item 1.01 / EX-2.1 party parsing; PE sponsor whitelist; strip clause residue |
| `AMBIGUOUS_RESOLUTION_EVENT` | 42 | Prose-aware timeline only if Item tags insufficient; keep fail-closed mixed close/break |
| `SEC_TRANSIENT_FAILURE` | 8 | Stronger cache + resume; do not exclude solely for 503 |
| `TERMS_EXTRACTION` | 1 | Announcement-time consideration patterns; reject EV/aggregate misreads (≥$400/share) |

## Top residual reason strings (this-loop DEFERs)

| Reason prefix | N |
|---|---:|
| `acquirer validation: missing acquirer` | 28 |
| `contradictory resolution filings in-window (close present and later te` | 7 |
| `acquirer validation: acquirer token equals target token (likely filer≠` | 4 |
| `acquirer validation: acquirer string contains verb/boilerplate residue` | 2 |
| `acquirer validation: acquirer lacks entity form: 'the MVP Present as a` | 1 |
| `acquirer validation: acquirer lacks entity form: 'TPG'` | 1 |
| `acquirer validation: acquirer lacks entity form: 'institutional invest` | 1 |
| `same-day announcement and close (likely non-standard / internalization` | 1 |
| `acquirer validation: acquirer lacks entity form: 'EnerNOC Worcester'` | 1 |
| `acquirer validation: acquirer is a shell/role word: 'CONSORTIUM'` | 1 |
| `acquirer validation: acquirer lacks entity form: 'FORTUNE BRANDS HOME ` | 1 |
| `acquirer/price fail` | 1 |

## Locked contracts (unchanged)

EVENT_RULES / fs_v1 / break_logit_v1 unchanged.  
`execution_authorized=false`. first_walkforward_v1 frozen at N=62.  
REAL MODEL FIT / WALK-FORWARD / CALIBRATION / TUNING = NO.

Fresh large-scale EFTS scanning remains deferred until PENDING backlog is
materially reduced (<50) or judged non-machine-resolvable under locked rules.
