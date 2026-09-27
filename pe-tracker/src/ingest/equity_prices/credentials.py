"""Credential presence checks — never return or log secret values."""
from __future__ import annotations

import os
from typing import Optional

from ..security_identity.openfigi import ENV_KEY as OPENFIGI_ENV, openfigi_api_key_present
from .tiingo import ENV_TOKEN as TIINGO_ENV, tiingo_api_token_present


def credential_presence(env: Optional[dict] = None) -> dict:
    """Return YES/NO presence flags only (no values, no lengths)."""
    return {
        "OPENFIGI_API_KEY_PRESENT": (
            "YES" if openfigi_api_key_present(env) else "NO"),
        "TIINGO_API_TOKEN_PRESENT": (
            "YES" if tiingo_api_token_present(env) else "NO"),
        "OPENFIGI_ENV_NAME": OPENFIGI_ENV,
        "TIINGO_ENV_NAME": TIINGO_ENV,
    }


def missing_credential_names(env: Optional[dict] = None) -> list[str]:
    e = env if env is not None else os.environ
    missing = []
    if not openfigi_api_key_present(e):
        missing.append(OPENFIGI_ENV)
    if not tiingo_api_token_present(e):
        missing.append(TIINGO_ENV)
    return missing
