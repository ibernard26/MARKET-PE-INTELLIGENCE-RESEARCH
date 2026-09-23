"""Benchmark smoke test: the harness runs at tiny scale and is clearly synthetic."""
from benchmarks import bench


def test_bench_runs_and_is_synthetic():
    rows = bench.run_all(scales=(20,), mc_paths=1_000)
    assert len(rows) == 1
    r = rows[0]
    assert r["synthetic"] is True
    for k in ("feature_generation_s", "backtest_s", "portfolio_aggregation_s",
              "covariance_s", "monte_carlo_s"):
        assert r[k] >= 0.0


def test_synthetic_marker_present():
    assert bench.SYNTHETIC is True
