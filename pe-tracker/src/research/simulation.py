"""Monte Carlo simulation of correlated deal-break outcomes.

Each deal either closes or breaks. Breaks are correlated through a single common
factor (a Gaussian copula): a deal breaks on a path when its latent draw falls
below its own break threshold, so raising the factor correlation `rho` makes
breaks cluster — the common-cause tail that ordinary covariance misses.

Vectorized with NumPy; runs are fully reproducible from `seed`. No scipy: the
per-deal normal thresholds use the standard library's NormalDist.inv_cdf.

VaR / Expected Shortfall are reported as positive loss magnitudes at a
confidence level, with the usual small-sample caveats left to the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

_NORM = NormalDist()


@dataclass
class SimPosition:
    deal_id: str
    p_break: float               # probability the deal breaks
    downside_notional: float     # loss (>0) realized if it breaks
    upside_notional: float = 0.0 # gain realized if it closes (spread captured)


def simulate_portfolio(positions: list[SimPosition], n_paths: int = 100_000,
                       rho: float = 0.15, seed: int = 12345) -> dict:
    """Simulate portfolio P&L across `n_paths`. Returns the P&L array and risk
    stats. `rho` in [0,1) is the common-factor loading (0 = independent breaks).
    """
    if not positions:
        return {"pnl": np.zeros(n_paths), "mean": 0.0, "n_paths": n_paths}
    if not 0.0 <= rho < 1.0:
        raise ValueError("rho must be in [0, 1)")

    rng = np.random.default_rng(seed)
    m = len(positions)

    p = np.array([pos.p_break for pos in positions])
    down = np.array([pos.downside_notional for pos in positions])
    up = np.array([pos.upside_notional for pos in positions])
    # break when latent < threshold; P(Z < inv_cdf(p)) = p
    thresh = np.array([_NORM.inv_cdf(min(max(pi, 1e-9), 1 - 1e-9)) for pi in p])

    common = rng.standard_normal((n_paths, 1))
    idio = rng.standard_normal((n_paths, m))
    latent = np.sqrt(rho) * common + np.sqrt(1.0 - rho) * idio   # corr(latent_i, latent_j)=rho

    broke = latent < thresh                       # (n_paths, m) boolean
    pnl_mat = np.where(broke, -down, up)          # loss on break, gain on close
    pnl = pnl_mat.sum(axis=1)

    return {
        "pnl": pnl,
        "n_paths": n_paths,
        "rho": rho,
        "seed": seed,
        "mean": float(pnl.mean()),
        "std": float(pnl.std(ddof=1)) if n_paths > 1 else 0.0,
        "mean_break_count": float(broke.sum(axis=1).mean()),
    }


def value_at_risk(pnl: np.ndarray, level: float = 0.95) -> float:
    """Loss (positive) not exceeded with probability `level`."""
    q = np.quantile(pnl, 1.0 - level)     # left-tail P&L quantile (usually negative)
    return float(max(-q, 0.0))


def expected_shortfall(pnl: np.ndarray, level: float = 0.95) -> float:
    """Mean loss (positive) in the worst (1-level) tail."""
    q = np.quantile(pnl, 1.0 - level)
    tail = pnl[pnl <= q]
    if tail.size == 0:
        return float(max(-q, 0.0))
    return float(max(-tail.mean(), 0.0))


def risk_report(positions: list[SimPosition], n_paths: int = 100_000,
                rho: float = 0.15, seed: int = 12345, level: float = 0.95) -> dict:
    """Convenience: simulate and summarize VaR/ES plus loss percentiles."""
    sim = simulate_portfolio(positions, n_paths=n_paths, rho=rho, seed=seed)
    pnl = sim["pnl"]
    pct = {f"p{int(x*100)}": float(np.quantile(pnl, x)) for x in (0.01, 0.05, 0.50, 0.95, 0.99)}
    return {
        "n_paths": n_paths, "rho": rho, "seed": seed, "level": level,
        "mean_pnl": sim["mean"], "std_pnl": sim["std"],
        "mean_break_count": sim["mean_break_count"],
        "VaR": value_at_risk(pnl, level),
        "ES": expected_shortfall(pnl, level),
        "pnl_percentiles": pct,
    }
