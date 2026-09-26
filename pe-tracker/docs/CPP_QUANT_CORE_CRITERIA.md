# C++ quant-core criteria

C++ is **not** part of the current model architecture
(`break_logit_v1` / `fs_v1` / `event_driven_v1`).

## Required sequence before any native code

1. Python prototype
2. Statistical validation
3. Profiling
4. Identify a real bottleneck
5. Benchmark a native candidate against the Python baseline
6. **Only then** introduce C++ (or another native path)

Skipping steps for “quant aesthetics” is not allowed.

## Current decision

**C++ NOT JUSTIFIED YET.**

Measured on the synthetic benchmark suite (`python -m benchmarks.bench`,
performance-only synthetic data — see `benchmarks/bench.py`):

| Workload | Feature gen | Backtest | Portfolio agg | Covariance | Monte Carlo (50k paths) |
|---|---|---|---|---|---|
| 100    | 0.3 ms  | 0.3 ms  | 0.1 ms  | 0.4 ms  | 0.61 s |
| 1,000  | 1.9 ms  | 1.6 ms  | 0.6 ms  | 0.5 ms  | 5.20 s |
| 10,000 | 24 ms   | 21 ms   | 7 ms    | 4.5 ms  | 51.8 s |

Reading:
- Feature generation, backtest, portfolio aggregation and covariance are all
  **sub-30 ms even at 10,000 deals** — far below research latency needs.
- **Monte Carlo** is the only hotspot and only binds at large *synthetic* scale,
  not at current real book size.

## Potential future C++ candidates (after the sequence above)

- large Monte Carlo
- large-scale optimization
- high-throughput simulation
- performance-critical execution paths

## Not C++ candidates merely because they are quantitative

- SEC parsing
- logistic regression on tens/hundreds of deals
- dbt transformations
- research notebooks
- small portfolio calculations

## Explicit non-goals of this repository stage

- No CMake
- No C++ source files
- No pybind11

## Status

No C++ exists in this repository. This document is the gate: it must record
measured benchmark evidence before any native module is added.
