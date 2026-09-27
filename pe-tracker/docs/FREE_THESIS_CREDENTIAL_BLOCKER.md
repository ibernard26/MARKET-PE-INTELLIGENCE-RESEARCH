# Free thesis stack — credential blocker

**Status:** `CREDENTIAL_ENVIRONMENT_NOT_VISIBLE`  
**As of main:** `d6b23b4417daea959411df7b0dbf0c45d4f905bd` (update on each recheck)

## Missing environment variables (names only)

| Variable | Present in this cloud-agent VM |
|---|---|
| `OPENFIGI_API_KEY` | **NO** |
| `TIINGO_API_TOKEN` | **NO** |

`SEC_USER_AGENT` is present. API egress to OpenFIGI/Tiingo hosts works.

## Why live phases are stopped

Auto-advance rule: **failed gate → stop dependent phase**.

Without both secrets, these phases cannot run:

1. OpenFIGI live smoke  
2. Tiingo live smoke  
3. Full 129-deal coverage  
4. Reconciliation / bias audit from live matrix  
5. Readiness / cohort freeze  

Architecture + offline scripts are already on `main` (PRs #37–#39).

## How to unblock (Cloud Agent)

1. Cursor → Cloud Agents → Secrets for this environment.  
2. Add **Runtime Secrets** or **Environment Variables** named exactly:
   - `OPENFIGI_API_KEY`
   - `TIINGO_API_TOKEN`  
   (Not Build Secrets — those do not reach the running agent.)  
3. **Start a new agent** on `main` (existing pods do not pick up secrets added after boot).  
4. Run:

```bash
cd pe-tracker
python -m scripts.smoke_free_providers && python -m scripts.run_free_price_coverage
```

Or:

```bash
python -m scripts.resume_free_thesis_stack
```

## Scientific invariants (unchanged)

- No synthetic / interpolated / forward-filled prices  
- Gate ≥20 deals with ≥3 real prints  
- CRSP = `FROZEN_FUTURE_ROBUSTNESS_PROVIDER`  
- Free-thesis goal stops before model / `spread_stress` execution  
- Never print, log, commit, or serialize credential values  

## Resume checklist when secrets appear

- [ ] `OPENFIGI_LIVE_TEST = PASS`  
- [ ] `TIINGO_LIVE_TEST = PASS`  
- [ ] `data/free_price_coverage_matrix.json` written  
- [ ] Reconciliation + bias audit docs regenerated  
- [ ] `DEALS_WITH_3PLUS_PRINTS` recomputed  
- [ ] If ≥20: freeze `spread_stress_thesis_v1` cohort; **stop** before backtest  
