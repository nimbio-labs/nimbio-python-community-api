import httpx
import pytest
import respx

from nimbio_community_api import AsyncNimbioClient, PermissionDeniedError

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
