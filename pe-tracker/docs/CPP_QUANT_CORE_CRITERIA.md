# C++ Quant-Core Criteria

This project is **Python-first**. C++ will only be introduced when profiling
demonstrates a genuine, sustained computational bottleneck that vectorized Python
(NumPy/pandas) and SQL/DuckDB cannot meet. C++ is not introduced on intuition,
and it is not introduced by this work.

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
  **sub-30 ms even at 10,000 deals** — orders of magnitude below any research
  latency requirement. No case for C++.
- **Monte Carlo is the only hotspot** and it scales ~linearly in
  `positions × paths`. At the *real* book size (single-digit deals × 50k paths)
  it runs in well under a second. It only becomes material at large synthetic
  scale (10k positions × 50k paths ≈ 52 s).

So the bottleneck candidate is identified (Monte Carlo), but it does not yet
bind at real research scale, and it is not yet exhausted in Python.

## Explicit triggers for reconsidering

C++ (or another native path) should be reconsidered when **any** of these hold,
and only after the Python-level path has first been vectorized/optimized:

1. Monte Carlo at **10^6+ paths** on a realistic book becomes materially slow
   (e.g. interactive research iteration exceeds a few seconds and blocks work).
2. Large-portfolio simulation (thousands of correlated names × 10^6 paths)
   dominates end-to-end runtime.
3. Matrix operations (covariance/factor models) can no longer meet research
   latency after NumPy-level optimization.
4. Event simulation reaches **millions of observations/events** per run.
5. Execution / order-book modeling is introduced (fine-grained, loop-heavy).
6. Profiling shows **Python interpreter overhead remains the bottleneck after
   vectorization** (i.e. the work is genuinely CPU-bound in Python, not I/O or
   already in NumPy C).

Before any of the above triggers C++, first try: larger NumPy batch sizes,
`float32` where precision allows, chunked/streamed path generation, and
`numpy`-native reductions. Reach for native code only if those are exhausted.

## Proposed future architecture (not built yet)

```
Python research / orchestration
        |
        v
C++ quant-core
        |
        +-- simulation
        +-- portfolio math
        +-- pricing
        +-- risk
        +-- execution simulation
```

Likely interface options when the time comes: **pybind11** for in-process calls,
**Apache Arrow / Parquet** for zero-copy data hand-off, or a clearly defined
service/API boundary. The Python simulation module (`src/research/simulation.py`)
is deliberately written behind a small, stable function surface so a native
implementation could be swapped in without changing callers.

## Status

No C++ exists in this repository. This document is the gate: it must record
measured benchmark evidence before any native module is added.
