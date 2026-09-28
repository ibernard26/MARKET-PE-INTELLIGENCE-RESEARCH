"""Smoke-test connectivity semantics. Does not call live providers.

The corpus resolver is covered separately: an ambiguous OpenFIGI payload
must still be DEFER_SECURITY_IDENTITY_AMBIGUOUS.
"""
import pytest

from scripts.smoke_free_providers import (
    OPENFIGI_CONNECTIVITY_FAIL,
    OPENFIGI_CONNECTIVITY_OK,
    openfigi_connectivity_ok,
)


@pytest.mark.parametrize("status", sorted(OPENFIGI_CONNECTIVITY_OK))
def test_valid_mapping_response_is_connectivity_pass(status):
    assert openfigi_connectivity_ok(status) is True


@pytest.mark.parametrize("status", sorted(OPENFIGI_CONNECTIVITY_FAIL))
def test_infrastructure_failure_is_connectivity_fail(status):
    assert openfigi_connectivity_ok(status) is False


def test_pass_and_fail_sets_do_not_overlap():
    assert OPENFIGI_CONNECTIVITY_OK.isdisjoint(OPENFIGI_CONNECTIVITY_FAIL)


def test_tiingo_hourly_limit_is_not_a_price_outcome():
    from scripts.run_free_price_coverage import (
        seconds_until_hourly_reset,
        tiingo_hourly_limited,
    )
    assert tiingo_hourly_limited({
        "status": "TRANSIENT_FAILURE",
        "provider_trace": [{"error": "Tiingo meta HTTP 429"}],
    }) is True
    assert tiingo_hourly_limited({
        "status": "ok",
        "provider_trace": [{"error": None}],
    }) is False
    assert tiingo_hourly_limited({"status": "NO_HISTORY"}) is False
    # 12:00:00 UTC + 120s buffer → 3600+120
    assert seconds_until_hourly_reset(0) == 3720
    assert seconds_until_hourly_reset(3600) == 3720

