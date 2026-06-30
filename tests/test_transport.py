"""Transport-level behavior: headers, params, retries, network errors, BYO client."""

import httpx
import pytest
import respx

from nimbio_community_api import (
    APIConnectionError,
    APITimeoutError,
    NimbioClient,
    UpstreamError,
)
from nimbio_community_api._base import BaseClient, endpoints

PROD = "https://api.nimbio.com"


@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


# -- headers ---------------------------------------------------------------- #

@respx.mock
def test_default_headers_present(client, test_key):
    route = respx.get(f"{PROD}/v1/me").mock(
        return_value=httpx.Response(200, json={"account_id": "a1", "key": {}}))
    client.me()
    headers = route.calls.last.request.headers
    assert headers["authorization"] == f"Bearer {test_key}"
    assert headers["accept"] == "application/json"
    assert "nimbio-community-api-python/" in headers["user-agent"]


@respx.mock
def test_custom_default_headers_merge(test_key):
    c = NimbioClient(test_key, max_retries=0,
                     default_headers={"X-Trace": "abc"})
    route = respx.get(f"{PROD}/v1/me").mock(
        return_value=httpx.Response(200, json={"account_id": "a1", "key": {}}))
    c.me()
    assert route.calls.last.request.headers["x-trace"] == "abc"
    c.close()


@respx.mock
def test_content_type_set_only_on_json_body(client):
    open_route = respx.post(f"{PROD}/v1/community/latches/l1/open").mock(
        return_value=httpx.Response(200, json={"result": "simulated"}))
    get_route = respx.get(f"{PROD}/v1/community/members").mock(
        return_value=httpx.Response(200, json={}))
    client.community.open("l1")
    client.community.members()
    assert open_route.calls.last.request.headers["content-type"] == "application/json"
    assert "content-type" not in {
        k.lower() for k in get_route.calls.last.request.headers}


# -- params ----------------------------------------------------------------- #

@respx.mock
def test_none_params_dropped(client):
    # window=last_30 is sent; the endpoint never sends None-valued params.
    route = respx.get(
        f"{PROD}/v1/community/members/5/access-logs").mock(
        return_value=httpx.Response(200, json={"result": "ok"}))
    client.community.member_access_logs(5, window="30_60")
    assert route.calls.last.request.url.params["window"] == "30_60"


def test_prepare_drops_none_params(test_key):
    c = NimbioClient(test_key)
    prepared = c._prepare("GET", "/x", params={"a": 1, "b": None})
    assert prepared.params == {"a": 1}
    # All-None params collapse to None (no query string).
    assert c._prepare("GET", "/x", params={"b": None}).params is None
    c.close()


# -- url encoding ----------------------------------------------------------- #

@respx.mock
def test_latch_id_is_url_encoded(client):
    route = respx.post(f"{PROD}/v1/community/latches/a%2Fb%20c/open").mock(
        return_value=httpx.Response(200, json={"result": "simulated"}))
    client.community.open("a/b c")
    assert route.called


# -- retries ---------------------------------------------------------------- #

@respx.mock
def test_retry_exhausted_raises(test_key):
    c = NimbioClient(test_key, max_retries=1)
    route = respx.get(f"{PROD}/v1/me")
    route.side_effect = [
        httpx.Response(503, json={"error": {"code": "x", "message": "down"}}),
        httpx.Response(503, json={"error": {"code": "x", "message": "down"}}),
    ]
    with pytest.raises(UpstreamError):
        c.me()
    assert route.call_count == 2  # original + 1 retry, then give up
    c.close()


@respx.mock
def test_no_retry_on_4xx(test_key):
    c = NimbioClient(test_key, max_retries=3)
    route = respx.get(f"{PROD}/v1/me").mock(
        return_value=httpx.Response(400, json={"error": {"code": "bad",
                                                          "message": "x"}}))
    from nimbio_community_api import BadRequestError
    with pytest.raises(BadRequestError):
        c.me()
    assert route.call_count == 1  # 400 is not retried
    c.close()


def test_should_retry_policy(test_key):
    c = NimbioClient(test_key, max_retries=2)
    assert c._should_retry(503, 0) is True
    assert c._should_retry(429, 1) is True
    assert c._should_retry(503, 2) is False   # attempts exhausted
    assert c._should_retry(404, 0) is False   # not retryable
    assert c._should_retry(200, 0) is False
    c.close()


def test_retry_delay_honors_retry_after(test_key):
    c = NimbioClient(test_key)
    assert c._retry_delay(0, {"retry-after": "7"}) == 7.0
    # Falls back to exponential backoff when no header.
    assert c._retry_delay(0, {}) == 0.5
    assert c._retry_delay(1, {}) == 1.0
    assert c._retry_delay(2, None) == 2.0
    c.close()


# -- network errors --------------------------------------------------------- #

@respx.mock
def test_connection_error_wrapped(client):
    respx.get(f"{PROD}/v1/me").mock(side_effect=httpx.ConnectError("no route"))
    with pytest.raises(APIConnectionError):
        client.me()


@respx.mock
def test_timeout_wrapped(client):
    respx.get(f"{PROD}/v1/me").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(APITimeoutError):
        client.me()


@respx.mock
def test_health_connection_error_wrapped(client):
    respx.get(f"{PROD}/healthz").mock(side_effect=httpx.ConnectError("x"))
    with pytest.raises(APIConnectionError):
        client.health()


@respx.mock
def test_health_timeout_wrapped(client):
    respx.get(f"{PROD}/healthz").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(APITimeoutError):
        client.health()


@respx.mock
def test_sync_context_manager_closes(test_key):
    respx.get(f"{PROD}/v1/me").mock(
        return_value=httpx.Response(200, json={"account_id": "a1", "key": {}}))
    with NimbioClient(test_key, max_retries=0) as client:
        inner = client._http
        assert client.me().account_id == "a1"
    assert inner.is_closed is True


@respx.mock
def test_non_numeric_retry_after_is_ignored(client):
    from nimbio_community_api import RateLimitError
    respx.get(f"{PROD}/v1/me").mock(return_value=httpx.Response(
        429, headers={"Retry-After": "soon"},
        json={"error": {"code": "rate_limited", "message": "slow"}}))
    with pytest.raises(RateLimitError) as ei:
        client.me()
    assert ei.value.retry_after is None


# -- decode / parse internals ----------------------------------------------- #

def test_decode_non_json_body(test_key):
    c = NimbioClient(test_key)
    decoded = c._decode(502, b"<html>Bad Gateway</html>", {})
    assert decoded["_raw_text"] == "<html>Bad Gateway</html>"
    assert c._decode(200, b"", {}) is None
    c.close()


def test_parse_non_json_error_surfaces_text(test_key):
    c = NimbioClient(test_key)
    from nimbio_community_api import UpstreamError as UE
    with pytest.raises(UE) as ei:
        c._parse(502, {"_raw_text": "Bad Gateway"}, {})
    assert "Bad Gateway" in ei.value.message
    c.close()


def test_parse_empty_2xx_returns_dict(test_key):
    c = NimbioClient(test_key)
    assert c._parse(204, None, {}) == {}
    c.close()


def test_parse_non_dict_error_body(test_key):
    # An error response whose JSON body is not an object (list/scalar/None).
    c = NimbioClient(test_key)
    from nimbio_community_api import ServerError
    with pytest.raises(ServerError) as ei:
        c._parse(500, ["weird"], {})
    assert ei.value.message == "HTTP 500"
    assert ei.value.code is None
    c.close()


# -- bring your own http client --------------------------------------------- #

@respx.mock
def test_byo_http_client_not_closed_by_client(test_key):
    http = httpx.Client()
    c = NimbioClient(test_key, http_client=http, max_retries=0)
    respx.get(f"{PROD}/v1/me").mock(
        return_value=httpx.Response(200, json={"account_id": "a1", "key": {}}))
    c.me()
    c.close()
    assert http.is_closed is False  # we don't own it
    http.close()


def test_owned_http_client_closed(test_key):
    c = NimbioClient(test_key)
    inner = c._http
    c.close()
    assert inner.is_closed is True


# -- repr does not leak the key --------------------------------------------- #

def test_repr_hides_key():
    c = NimbioClient("nimbio_live_supersecretvalue00", environment="dev")
    r = repr(c)
    assert "supersecret" not in r
    assert "api.nimbio.dev" in r and "live" in r
    c.close()


# -- endpoints registry is the single source of truth ----------------------- #

def test_endpoints_specs_shape():
    method, path, params, json, parser = endpoints.open(
        "l1", note="hi", idempotency_key="k")
    assert method == "POST"
    assert path == "/v1/community/latches/l1/open"
    assert json == {"note": "hi", "idempotency_key": "k"}
    assert callable(parser)

    # Optional body fields omitted when not provided.
    _, _, _, body, _ = endpoints.open("l1")
    assert body == {}

    _, _, params, _, _ = endpoints.access_log(page=3)
    assert params == {"page": 3}


def test_base_client_is_abstract_enough(test_key):
    # BaseClient holds config but has no transport; subclasses add _request.
    base = BaseClient(test_key, environment="dev")
    assert base.base_url == "https://api.nimbio.dev"
    assert base.mode == "test"
    assert not hasattr(base, "_request")
