import httpx
import pytest
import respx

from nimbio_community_api import (
    AuthenticationError,
    GateNotOpenedError,
    NimbioClient,
    PermissionDeniedError,
    RateLimitError,
)

PROD = "https://api.nimbio.com"


@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


@respx.mock
def test_me(client):
    respx.get(f"{PROD}/v1/me").mock(return_value=httpx.Response(200, json={
        "account_id": "a1",
        "key": {"api_key_id": "k1", "prefix": "nimbio_test_ab12cd34",
                "name": "Integration", "mode": "test", "minute_limit": 60,
                "minute_count": 1, "month_limit": 10000, "month_count": 42},
    }))
    me = client.me()
    assert me.account_id == "a1"
    assert me.key.mode == "test"
    assert me.key.month_count == 42
    assert me.raw["key"]["name"] == "Integration"


@respx.mock
def test_health_does_not_raise_on_503(client):
    respx.get(f"{PROD}/healthz").mock(
        return_value=httpx.Response(503, json={"ok": False, "wamp": "disconnected"}))
    h = client.health()
    assert h.ok is False
    assert h.wamp == "disconnected"


@respx.mock
def test_health_unauthenticated(client):
    route = respx.get(f"{PROD}/healthz").mock(
        return_value=httpx.Response(200, json={"ok": True, "wamp": "connected"}))
    client.health()
    assert "authorization" not in {k.lower() for k in route.calls.last.request.headers}


@respx.mock
def test_gate_status(client):
    respx.get(f"{PROD}/v1/community/gate-status").mock(return_value=httpx.Response(
        200, json={"latches": [
            {"latch_id": "l1", "latch_name": "Front Gate", "status": "closed",
             "offline": False, "latch_status_current_message": "Closed"}]}))
    gs = client.community.gate_status()
    assert len(gs.latches) == 1
    assert gs.latches[0].latch_name == "Front Gate"
    assert gs.latches[0].offline is False


@respx.mock
def test_keys_list(client):
    respx.get(f"{PROD}/v1/community/keys").mock(return_value=httpx.Response(
        200, json={"result": "ok", "keys": [
            {"id": "k1", "name": "Front Gate Key", "disabled": False,
             "sharing": {"allow_subkeys": True}, "latches": [{"latch_id": "l1"}]}]}))
    keys = client.community.keys()
    assert keys[0].id == "k1"
    assert keys[0].sharing["allow_subkeys"] is True
    assert keys[0].latches[0]["latch_id"] == "l1"


@respx.mock
def test_open_sends_body_and_auth(client, test_key):
    route = respx.post(f"{PROD}/v1/community/latches/l1/open").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "would_open": True, "request_id": "r1",
            "latch_id": "l1"}))
    res = client.community.open("l1", note="hi")
    assert res.simulated is True
    assert res.request_id == "r1"
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {test_key}"
    import json
    assert json.loads(req.content) == {"note": "hi"}


@respx.mock
def test_open_denied_raises_permission(client):
    respx.post(f"{PROD}/v1/community/latches/l1/open").mock(
        return_value=httpx.Response(403, json={"error": {
            "code": "open_denied", "message": "Disabled", "request_id": "r9"}}))
    with pytest.raises(PermissionDeniedError) as ei:
        client.community.open("l1")
    assert ei.value.code == "open_denied"
    assert ei.value.request_id == "r9"
    assert ei.value.status_code == 403


@respx.mock
def test_did_not_open_raises_gate_error(client):
    respx.post(f"{PROD}/v1/community/latches/l1/open").mock(
        return_value=httpx.Response(504, json={"error": {
            "code": "did_not_open", "message": "no confirm", "request_id": "r9"}}))
    with pytest.raises(GateNotOpenedError):
        client.community.open("l1")


@respx.mock
def test_auth_error(client):
    respx.get(f"{PROD}/v1/me").mock(return_value=httpx.Response(401, json={
        "error": {"code": "unauthorized", "message": "Invalid API key"}}))
    with pytest.raises(AuthenticationError):
        client.me()


@respx.mock
def test_rate_limit_carries_retry_after(client):
    respx.get(f"{PROD}/v1/me").mock(return_value=httpx.Response(
        429, headers={"Retry-After": "12"},
        json={"error": {"code": "rate_limited", "message": "slow down"}}))
    with pytest.raises(RateLimitError) as ei:
        client.me()
    assert ei.value.retry_after == 12.0


@respx.mock
def test_member_management_roundtrip(client):
    respx.post(f"{PROD}/v1/community/members/4021/grant-keys").mock(
        return_value=httpx.Response(200, json={
            "result": "keys_granted", "request_id": "r1",
            "account_community_id": 4021,
            "granted": {"created": ["k1"], "enabled": [], "exists": []}}))
    res = client.community.grant_keys(4021, ["k1"])
    assert res.result == "keys_granted"
    assert res["granted"]["created"] == ["k1"]
    assert res.get("account_community_id") == 4021


@respx.mock
def test_access_log_pagination(client):
    respx.get(f"{PROD}/v1/community/access-logs", params={"page": "0"}).mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "page": 0, "has_more": True,
            "logs": [{"key_name": "A", "datetime": "t0"}]}))
    respx.get(f"{PROD}/v1/community/access-logs", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "page": 1, "has_more": False,
            "logs": [{"key_name": "B", "datetime": "t1"}]}))
    rows = list(client.community.iter_access_log())
    assert [r.key_name for r in rows] == ["A", "B"]


@respx.mock
def test_retry_then_success(test_key):
    c = NimbioClient(test_key, max_retries=2)
    route = respx.get(f"{PROD}/v1/me")
    route.side_effect = [
        httpx.Response(503, json={"error": {"code": "x", "message": "down"}}),
        httpx.Response(200, json={"account_id": "a1", "key": {}}),
    ]
    me = c.me()
    assert me.account_id == "a1"
    assert route.call_count == 2
    c.close()
