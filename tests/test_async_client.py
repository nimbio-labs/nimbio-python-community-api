import json as _json

import httpx
import pytest
import respx

from nimbio_community_api import (
    APIConnectionError,
    APITimeoutError,
    AsyncNimbioClient,
    GateNotOpenedError,
    PermissionDeniedError,
    UpstreamError,
)

PROD = "https://api.nimbio.com"


@respx.mock
async def test_async_me(test_key):
    respx.get(f"{PROD}/v1/me").mock(return_value=httpx.Response(200, json={
        "account_id": "a1", "key": {"mode": "test"}}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        me = await client.me()
        assert me.account_id == "a1"
        assert me.key.mode == "test"


@respx.mock
async def test_async_open_simulated(test_key):
    respx.post(f"{PROD}/v1/community/latches/l1/open").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "request_id": "r1", "latch_id": "l1"}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        res = await client.community.open("l1", note="x")
        assert res.simulated is True


@respx.mock
async def test_async_permission_error(test_key):
    respx.get(f"{PROD}/v1/community/members").mock(
        return_value=httpx.Response(403, json={"error": {
            "code": "not_community_key",
            "message": "This API key is not bound to a community"}}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        with pytest.raises(PermissionDeniedError) as ei:
            await client.community.members()
        assert ei.value.code == "not_community_key"


@respx.mock
async def test_async_iter_access_log(test_key):
    respx.get(f"{PROD}/v1/community/access-logs", params={"page": "0"}).mock(
        return_value=httpx.Response(200, json={
            "page": 0, "has_more": True, "logs": [{"key_name": "A"}]}))
    respx.get(f"{PROD}/v1/community/access-logs", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json={
            "page": 1, "has_more": False, "logs": [{"key_name": "B"}]}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        names = [row.key_name async for row in client.community.iter_access_log()]
        assert names == ["A", "B"]


@respx.mock
async def test_async_health_no_raise_on_503(test_key):
    respx.get(f"{PROD}/healthz").mock(
        return_value=httpx.Response(503, json={"ok": False, "wamp": "disconnected"}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        h = await client.health()
        assert h.ok is False and h.wamp == "disconnected"


@respx.mock
async def test_async_health_unauthenticated(test_key):
    route = respx.get(f"{PROD}/healthz").mock(
        return_value=httpx.Response(200, json={"ok": True, "wamp": "connected"}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        await client.health()
    assert "authorization" not in {
        k.lower() for k in route.calls.last.request.headers}


@respx.mock
async def test_async_gate_not_opened(test_key):
    respx.post(f"{PROD}/v1/community/latches/l1/open").mock(
        return_value=httpx.Response(504, json={"error": {
            "code": "did_not_open", "message": "no confirm", "request_id": "r9"}}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        with pytest.raises(GateNotOpenedError):
            await client.community.open("l1")


@respx.mock
async def test_async_writes_send_bodies(test_key):
    msg = respx.post(f"{PROD}/v1/community/messages").mock(
        return_value=httpx.Response(200, json={"result": "sent", "request_id": "r"}))
    grant = respx.post(f"{PROD}/v1/community/members/4021/grant-keys").mock(
        return_value=httpx.Response(200, json={"result": "keys_granted",
                                               "request_id": "r"}))
    revoke = respx.post(f"{PROD}/v1/community/members/4021/revoke-keys").mock(
        return_value=httpx.Response(200, json={"result": "keys_revoked",
                                               "request_id": "r"}))
    disable = respx.post(f"{PROD}/v1/community/members/4021/keys-disabled").mock(
        return_value=httpx.Response(200, json={"result": "keys_disabled",
                                               "request_id": "r"}))
    add = respx.post(f"{PROD}/v1/community/members").mock(
        return_value=httpx.Response(201, json={"result": "member_added",
                                               "request_id": "r"}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        assert (await client.community.message("hi")).result == "sent"
        assert (await client.community.grant_keys(4021, ["k1"])).result == "keys_granted"
        assert (await client.community.revoke_keys(4021, ["k1"])).result == "keys_revoked"
        assert (await client.community.set_keys_disabled(
            4021, ["k1"], False)).result == "keys_disabled"
        added = await client.community.add_member("+1555", ["k1"])
        assert added.result == "member_added"

    assert _json.loads(msg.calls.last.request.content) == {"message": "hi"}
    assert _json.loads(grant.calls.last.request.content) == {"key_ids": ["k1"]}
    assert _json.loads(revoke.calls.last.request.content) == {
        "key_ids": ["k1"], "remove_member": False}
    assert _json.loads(disable.calls.last.request.content) == {
        "key_ids": ["k1"], "disabled": False}
    assert _json.loads(add.calls.last.request.content) == {
        "phone_number": "+1555", "key_ids": ["k1"]}


@respx.mock
async def test_async_reads(test_key):
    respx.get(f"{PROD}/v1/community/gate-status").mock(
        return_value=httpx.Response(200, json={"latches": [{"latch_id": "l1"}]}))
    respx.get(f"{PROD}/v1/community/key-statuses").mock(
        return_value=httpx.Response(200, json={"keys": [{"id": "k1"}],
                                               "hold_opens": {}}))
    respx.get(f"{PROD}/v1/community/keys").mock(
        return_value=httpx.Response(200, json={"keys": [{"id": "k1", "name": "F"}]}))
    respx.get(f"{PROD}/v1/community/members/5/access-logs").mock(
        return_value=httpx.Response(200, json={"window": "last_30", "logs": []}))
    respx.get(f"{PROD}/v1/community/gate-status-log").mock(
        return_value=httpx.Response(200, json={"page": 0, "has_more": False,
                                               "logs": [{"state": "open"}]}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        assert (await client.community.gate_status()).latches[0].latch_id == "l1"
        assert (await client.community.key_statuses()).keys[0]["id"] == "k1"
        assert (await client.community.keys())[0].id == "k1"
        assert (await client.community.member_access_logs(5)).window == "last_30"
        glog = await client.community.gate_status_log()
        assert glog.logs[0].state == "open"


@respx.mock
async def test_async_iter_gate_status_log(test_key):
    respx.get(f"{PROD}/v1/community/gate-status-log", params={"page": "0"}).mock(
        return_value=httpx.Response(200, json={
            "page": 0, "has_more": True, "logs": [{"state": "open"}]}))
    respx.get(f"{PROD}/v1/community/gate-status-log", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json={
            "page": 1, "has_more": False, "logs": [{"state": "closed"}]}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        states = [r.state async for r in client.community.iter_gate_status_log()]
        assert states == ["open", "closed"]


@respx.mock
async def test_async_retry_then_success(test_key):
    route = respx.get(f"{PROD}/v1/me")
    route.side_effect = [
        httpx.Response(503, json={"error": {"code": "x", "message": "down"}}),
        httpx.Response(200, json={"account_id": "a1", "key": {}}),
    ]
    async with AsyncNimbioClient(test_key, max_retries=2) as client:
        me = await client.me()
        assert me.account_id == "a1"
    assert route.call_count == 2


@respx.mock
async def test_async_retry_exhausted(test_key):
    route = respx.get(f"{PROD}/v1/me")
    route.side_effect = [
        httpx.Response(503, json={"error": {"code": "x", "message": "down"}}),
        httpx.Response(503, json={"error": {"code": "x", "message": "down"}}),
    ]
    async with AsyncNimbioClient(test_key, max_retries=1) as client:
        with pytest.raises(UpstreamError):
            await client.me()
    assert route.call_count == 2


@respx.mock
async def test_async_connection_error(test_key):
    respx.get(f"{PROD}/v1/me").mock(side_effect=httpx.ConnectError("x"))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        with pytest.raises(APIConnectionError):
            await client.me()


@respx.mock
async def test_async_timeout_error(test_key):
    respx.get(f"{PROD}/v1/me").mock(side_effect=httpx.ReadTimeout("x"))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        with pytest.raises(APITimeoutError):
            await client.me()


@respx.mock
async def test_async_health_connection_error(test_key):
    respx.get(f"{PROD}/healthz").mock(side_effect=httpx.ConnectError("x"))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        with pytest.raises(APIConnectionError):
            await client.health()


@respx.mock
async def test_async_health_timeout(test_key):
    respx.get(f"{PROD}/healthz").mock(side_effect=httpx.ReadTimeout("slow"))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        with pytest.raises(APITimeoutError):
            await client.health()


@respx.mock
async def test_async_byo_http_client_not_closed(test_key):
    http = httpx.AsyncClient()
    client = AsyncNimbioClient(test_key, http_client=http, max_retries=0)
    respx.get(f"{PROD}/v1/me").mock(
        return_value=httpx.Response(200, json={"account_id": "a1", "key": {}}))
    await client.me()
    await client.aclose()
    assert http.is_closed is False
    await http.aclose()
