# Deferred backlog baseline

**As of main** `1c477c8fa47c70ba6b27fe99a05beb2aea5e0a1d`  
**Canonical corpus:** N=69 (Y0=50, Y1=19, censored=0)  
**Unique deferred:** **214** (ledger cross-dup skips: 0)  
**Chronological range:** 2014-01-09 → 2016-10-11

## Counts by primary resolution class

| Class | N | Notes |
|---|---:|---|
| `ACQUIRER_EXTRACTION` | 123 | retryable — improve primary-doc party parsing |
| `AMBIGUOUS_RESOLUTION_EVENT` | 67 | retryable — literal EVENT_RULES timeline |
| `SEC_TRANSIENT_FAILURE` | 23 | retryable — bounded backoff + cache |
| `TERMS_EXTRACTION` | 1 | retryable / may become REPRESENTABILITY_FAIL |

## Source batch mix

| Original batch | Deferred unique |
|---:|---:|
| 1 | 95 |
| 2 | 41 |
| 3 | 78 |

## Retry posture

| Bucket | N |
|---|---:|
| Likely machine-retryable | 214 |
| Likely permanent under locked rules | 0 |
| Other / mixed | 0 |

## Artifact

Normalized queue: `pe-tracker/data/review/deferred_resolution_queue.json`

## Contract

EVENT_RULES / fs_v1 / break_logit_v1 unchanged.  
`execution_authorized=false`. first_walkforward_v1 frozen at N=62.  
REAL MODEL FIT / WALK-FORWARD / CALIBRATION / TUNING = NO.
