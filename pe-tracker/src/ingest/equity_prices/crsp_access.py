"""CRSP / WRDS access detection — never fabricate credentials or responses.

Supported modes (env-driven):

  CRSP_ACCESS_MODE=wrds|flat_file|none

WRDS:
  WRDS_USERNAME=…
  (password via WRDS_PASSWORD env, ~/.pgpass, or interactive wrds lib — never commit)

Flat file:
  CRSP_DATA_DIR=/licensed/path/…
  Optional table/file name overrides for CIZ / Flat File 2.0 layouts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_WRDS_DAILY_TABLE = "crsp.dsf_v2"
DEFAULT_WRDS_NAMES_TABLE = "crsp.stocknames_v2"
DEFAULT_WRDS_DELIST_TABLE = "crsp.dlstdt_v2"

# Local licensed store (gitignored). Raw vendor files must not land in Git.
DEFAULT_LICENSED_DIR = Path(__file__).resolve().parents[3] / "data" / "licensed" / "crsp"


@dataclass(frozen=True)
class CrspAccessConfig:
    """Resolved CRSP access posture for this process."""
    mode: str  # wrds | flat_file | none
    available: bool
    reason: str
    wrds_username: Optional[str] = None
    data_dir: Optional[Path] = None
    daily_table: str = DEFAULT_WRDS_DAILY_TABLE
    names_table: str = DEFAULT_WRDS_NAMES_TABLE
    delist_table: str = DEFAULT_WRDS_DELIST_TABLE
    schema_notes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "available": self.available,
            "reason": self.reason,
            "wrds_username": self.wrds_username,
            "data_dir": str(self.data_dir) if self.data_dir else None,
            "daily_table": self.daily_table,
            "names_table": self.names_table,
            "delist_table": self.delist_table,
            "schema_notes": list(self.schema_notes),
        }


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def detect_crsp_access(
        env: Optional[dict] = None,
        licensed_dir: Optional[Path] = None,
) -> CrspAccessConfig:
    """Inspect environment for legitimate CRSP access. Never invent credentials."""
    e = env if env is not None else os.environ
    mode_raw = (e.get("CRSP_ACCESS_MODE") or "").strip().lower()
    user = (e.get("WRDS_USERNAME") or "").strip() or None
    data_dir_s = (e.get("CRSP_DATA_DIR") or "").strip()
    data_dir = Path(data_dir_s) if data_dir_s else (licensed_dir or DEFAULT_LICENSED_DIR)
    daily = (e.get("CRSP_DAILY_TABLE") or DEFAULT_WRDS_DAILY_TABLE).strip()
    names = (e.get("CRSP_NAMES_TABLE") or DEFAULT_WRDS_NAMES_TABLE).strip()
    delist = (e.get("CRSP_DELIST_TABLE") or DEFAULT_WRDS_DELIST_TABLE).strip()
    notes = (
        "Table names are configurable; WRDS library layouts differ by subscription.",
        "Prefer current CRSP CIZ / Flat File 2.0 semantics when available.",
    )

    if mode_raw in ("", "auto"):
        if user:
            mode_raw = "wrds"
        elif data_dir_s and Path(data_dir_s).is_dir():
            mode_raw = "flat_file"
        else:
            mode_raw = "none"

    if mode_raw == "none":
        return CrspAccessConfig(
            mode="none", available=False,
            reason="CRSP_ACCESS_MODE=none or no WRDS_USERNAME / CRSP_DATA_DIR configured",
            daily_table=daily, names_table=names, delist_table=delist,
            schema_notes=notes,
        )

    if mode_raw == "wrds":
        if not user:
            return CrspAccessConfig(
                mode="wrds", available=False,
                reason="CRSP_ACCESS_MODE=wrds but WRDS_USERNAME is unset",
                daily_table=daily, names_table=names, delist_table=delist,
                schema_notes=notes,
            )
        # Presence of username is necessary but not sufficient; connection is
        # validated lazily by the adapter. Password must never be required in Git.
        return CrspAccessConfig(
            mode="wrds", available=True,
            reason="WRDS_USERNAME configured; connection validated on first query",
            wrds_username=user,
            daily_table=daily, names_table=names, delist_table=delist,
            schema_notes=notes,
        )

    if mode_raw == "flat_file":
        if not data_dir.is_dir():
            return CrspAccessConfig(
                mode="flat_file", available=False,
                reason=f"CRSP_DATA_DIR not found or not a directory: {data_dir}",
                data_dir=data_dir,
                daily_table=daily, names_table=names, delist_table=delist,
                schema_notes=notes,
            )
        return CrspAccessConfig(
            mode="flat_file", available=True,
            reason=f"licensed flat-file directory present: {data_dir}",
            data_dir=data_dir,
            daily_table=daily, names_table=names, delist_table=delist,
            schema_notes=notes,
        )

    return CrspAccessConfig(
        mode=mode_raw, available=False,
        reason=f"unknown CRSP_ACCESS_MODE={mode_raw!r}; use wrds|flat_file|none",
        wrds_username=user, data_dir=data_dir if data_dir_s else None,
        daily_table=daily, names_table=names, delist_table=delist,
        schema_notes=notes,
    )
