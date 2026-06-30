"""Unit tests for the exception hierarchy and status -> class mapping."""

import pytest

from nimbio_community_api import _exceptions as e


@pytest.mark.parametrize("status,code,expected", [
    (400, None, e.BadRequestError),
    (401, "unauthorized", e.AuthenticationError),
    (403, "open_denied", e.PermissionDeniedError),
    (403, "not_community_key", e.PermissionDeniedError),
    (404, "member_not_found", e.NotFoundError),
    (429, "rate_limited", e.RateLimitError),
    (504, "did_not_open", e.GateNotOpenedError),
    (502, "upstream_unavailable", e.UpstreamError),
    (503, None, e.UpstreamError),
    (500, None, e.ServerError),
    (418, None, e.APIError),  # unmapped 4xx -> base APIError
])
def test_exception_for_status_mapping(status, code, expected):
    assert e.exception_for(status, code) is expected


def test_did_not_open_code_wins_over_status():
    # The did_not_open *code* maps to GateNotOpenedError even off 504.
    assert e.exception_for(400, "did_not_open") is e.GateNotOpenedError


def test_api_error_attributes_and_str():
    err = e.APIError("Invalid API key", status_code=401, code="unauthorized",
                     request_id="r123", response={"x": 1},
                     headers={"X-Request-Id": "r123"})
    assert err.status_code == 401
    assert err.code == "unauthorized"
    assert err.message == "Invalid API key"
    assert err.request_id == "r123"
    assert err.response == {"x": 1}
    assert err.headers["X-Request-Id"] == "r123"
    s = str(err)
    assert "[401]" in s and "unauthorized" in s and "r123" in s


def test_api_error_str_minimal():
    err = e.APIError("boom", status_code=500)
    s = str(err)
    assert "[500]" in s and "boom" in s


def test_rate_limit_error_retry_after():
    err = e.RateLimitError("slow down", status_code=429, retry_after=30.0)
    assert err.retry_after == 30.0
    assert isinstance(err, e.APIError)


def test_hierarchy_is_catchable_as_base():
    err = e.PermissionDeniedError("nope", status_code=403)
    assert isinstance(err, e.APIError)
    assert isinstance(err, e.NimbioError)


def test_connection_and_timeout_errors():
    cause = ValueError("dns")
    conn = e.APIConnectionError("boom", cause=cause)
    assert conn.__cause__ is cause
    assert isinstance(conn, e.NimbioError)

    to = e.APITimeoutError(cause=cause)
    assert isinstance(to, e.APIConnectionError)
    assert to.__cause__ is cause


def test_config_error_is_nimbio_error():
    assert issubclass(e.NimbioConfigError, e.NimbioError)
