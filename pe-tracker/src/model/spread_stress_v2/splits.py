"""Deal-grouped expanding walk-forward splits for spread_stress_v2.

At cutoff c:
  train = deals whose label is known strictly before c (resolved < c, not censored)
  test  = deals announced in [c, next cutoff)
A deal announced before c but unresolved at c is in neither (censored at c —
never a negative). Grouping is by deal_id, so every snapshot of a deal lands
on exactly one side; `assert_disjoint` enforces it.
"""
from __future__ import annotations

from datetime import date


class SplitLeakError(AssertionError):
    pass


def annual_cutoffs(first_year: int, last_year: int) -> list[date]:
    return [date(y, 1, 1) for y in range(first_year, last_year + 1)]


def _d(ts: str | None) -> date | None:
    return date.fromisoformat(ts[:10]) if ts else None


def fold(deals: list[dict], cutoff: date, next_cutoff: date) -> dict:
    train, test = [], []
    for d in deals:
        ann, res = _d(d["announcement_timestamp"]), _d(d.get("resolution_timestamp"))
        if d.get("label") is not None and res is not None and res < cutoff:
            train.append(d["deal_id"])
        elif ann is not None and cutoff <= ann < next_cutoff:
            test.append(d["deal_id"])
    out = {"cutoff": cutoff.isoformat(), "next_cutoff": next_cutoff.isoformat(),
           "train": sorted(train), "test": sorted(test)}
    assert_disjoint(out)
    return out


def assert_disjoint(f: dict) -> None:
    both = set(f["train"]) & set(f["test"])
    if both:
        raise SplitLeakError(f"deals on both sides of {f['cutoff']}: {sorted(both)}")


def walk_forward(deals: list[dict], cutoffs: list[date]) -> list[dict]:
    return [fold(deals, c, n) for c, n in zip(cutoffs, cutoffs[1:])]
