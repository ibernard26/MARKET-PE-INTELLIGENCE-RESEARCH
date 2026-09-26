"""Non-destructive model-cohort abstraction.

Canonical deals remain in the SQLite store regardless of whether they belong
to any particular probability experiment. A ModelCohort is a read-only
membership list that selects which deal_ids are admissible for one experiment.

This module provides the mechanism only. It does not hard-code Batch 8 or any
other outcome-enriched packet, and it never mutates canonical tables.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


class CohortError(ValueError):
    """Raised when a cohort specification is invalid."""


@dataclass(frozen=True)
class ModelCohort:
    """Immutable cohort specification for one model experiment."""

    cohort_id: str
    cohort_version: str
    description: str
    selection_method: str
    outcome_blind: bool
    probability_calibration_eligible: bool
    deal_ids: tuple[str, ...]
    created_from_code_commit: str

    @staticmethod
    def from_ids(
        cohort_id: str,
        cohort_version: str,
        description: str,
        selection_method: str,
        outcome_blind: bool,
        probability_calibration_eligible: bool,
        deal_ids: Iterable[str],
        created_from_code_commit: str,
    ) -> "ModelCohort":
        """Build a cohort with deterministically sorted unique deal_ids."""
        ids = tuple(sorted({str(d) for d in deal_ids}))
        return ModelCohort(
            cohort_id=cohort_id,
            cohort_version=cohort_version,
            description=description,
            selection_method=selection_method,
            outcome_blind=bool(outcome_blind),
            probability_calibration_eligible=bool(probability_calibration_eligible),
            deal_ids=ids,
            created_from_code_commit=created_from_code_commit,
        )

    def validate(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """Validate identity, uniqueness, ordering, and optional store membership."""
        if not self.cohort_id:
            raise CohortError("cohort_id required")
        if not self.cohort_version:
            raise CohortError("cohort_version required")
        if not self.selection_method:
            raise CohortError("selection_method required")
        if not self.created_from_code_commit:
            raise CohortError("created_from_code_commit required")
        if len(self.deal_ids) != len(set(self.deal_ids)):
            raise CohortError("deal_ids must be unique")
        if tuple(sorted(self.deal_ids)) != self.deal_ids:
            raise CohortError("deal_ids must be deterministically sorted")
        if conn is not None:
            present = {r[0] for r in conn.execute("SELECT deal_id FROM deals")}
            unknown = [d for d in self.deal_ids if d not in present]
            if unknown:
                raise CohortError(f"unknown deal_ids not in canonical store: {unknown}")

    def membership(self) -> Sequence[str]:
        """Return the immutable sorted membership tuple."""
        return self.deal_ids
