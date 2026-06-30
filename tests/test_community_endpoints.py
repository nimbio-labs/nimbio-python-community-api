"""Per-endpoint coverage for the sync community surface: request + response."""

import json as _json

import httpx
import pytest
import respx

from nimbio_community_api import NimbioClient

PROD = "https://api.nimbio.com"


@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


def _body(route):
    return _json.loads(route.calls.last.request.content)


# -- reads ------------------------------------------------------------------ #

@respx.mock
def test_members(client):
    respx.get(f"{PROD}/v1/community/members").mock(return_value=httpx.Response(
        200, json={"accepted": [{"account_community_id": 1, "first_name": "Dana",
                                 "last_name": "Lee", "phone_number": "+1555"}],
                   "unaccepted": [], "removed": []}))
    members = client.community.members()
    assert members.accepted[0].full_name == "Dana Lee"
    assert members.unaccepted == []


@respx.mock
def test_key_statuses(client):
    respx.get(f"{PROD}/v1/community/key-statuses").mock(return_value=httpx.Response(
        200, json={"keys": [{"id": "k1", "name": "Front"}],
                   "hold_opens": {"k1": {"until": "later"}}}))
    ks = client.community.key_statuses()
    assert ks.keys[0]["id"] == "k1"
    assert ks.hold_opens["k1"]["until"] == "later"


# -- writes ----------------------------------------------------------------- #

@respx.mock
def test_open_live_opened(client):
    respx.post(f"{PROD}/v1/community/latches/l1/open").mock(
        return_value=httpx.Response(200, json={
            "result": "opened", "request_id": "r1", "key_log_id": 9001}))
    res = client.community.open("l1")
    assert res.opened is True
    assert res.key_log_id == 9001


@respx.mock
def test_message_body_and_result(client):
    route = respx.post(f"{PROD}/v1/community/messages").mock(
        return_value=httpx.Response(200, json={"result": "sent", "request_id": "r1"}))
    res = client.community.message("Pool closed Thursday")
    assert _body(route) == {"message": "Pool closed Thursday"}
    assert res.result == "sent"


@respx.mock
def test_add_member_body_and_201(client):
    route = respx.post(f"{PROD}/v1/community/members").mock(
        return_value=httpx.Response(201, json={
            "result": "member_added", "request_id": "r1",
            "account_community_id": 4021, "account_id": "a1",
            "keys": [{"key_id": "k1"}]}))
    res = client.community.add_member("+15551234567", ["k1", "k2"])
    assert _body(route) == {"phone_number": "+15551234567", "key_ids": ["k1", "k2"]}
    assert res.result == "member_added"
    assert res["account_community_id"] == 4021


@respx.mock
def test_grant_keys_body(client):
    route = respx.post(f"{PROD}/v1/community/members/4021/grant-keys").mock(
        return_value=httpx.Response(200, json={"result": "keys_granted",
                                               "request_id": "r1"}))
    client.community.grant_keys(4021, ["k1"])
    assert _body(route) == {"key_ids": ["k1"]}


@respx.mock
def test_revoke_keys_body_with_remove(client):
    route = respx.post(f"{PROD}/v1/community/members/4021/revoke-keys").mock(
        return_value=httpx.Response(200, json={"result": "keys_revoked",
                                               "request_id": "r1"}))
    client.community.revoke_keys(4021, ["k1"], remove_member=True)
    assert _body(route) == {"key_ids": ["k1"], "remove_member": True}


@respx.mock
def test_revoke_keys_default_remove_false(client):
    route = respx.post(f"{PROD}/v1/community/members/4021/revoke-keys").mock(
        return_value=httpx.Response(200, json={"result": "keys_revoked",
                                               "request_id": "r1"}))
    client.community.revoke_keys(4021, ["k1"])
    assert _body(route)["remove_member"] is False


@respx.mock
def test_set_keys_disabled_body(client):
    route = respx.post(f"{PROD}/v1/community/members/4021/keys-disabled").mock(
        return_value=httpx.Response(200, json={"result": "keys_disabled",
                                               "request_id": "r1"}))
    res = client.community.set_keys_disabled(4021, ["k1"], disabled=True)
    assert _body(route) == {"key_ids": ["k1"], "disabled": True}
    assert res.result == "keys_disabled"


# -- logs ------------------------------------------------------------------- #

@respx.mock
def test_member_access_logs_window(client):
    route = respx.get(f"{PROD}/v1/community/members/4021/access-logs").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "account_community_id": 4021, "window": "60_90",
            "truncated": False, "logs": [{"key_name": "Front"}]}))
    page = client.community.member_access_logs(4021, window="60_90")
    assert route.calls.last.request.url.params["window"] == "60_90"
    assert page.window == "60_90"
    assert page.logs[0].key_name == "Front"


@respx.mock
def test_gate_status_log_page(client):
    respx.get(f"{PROD}/v1/community/gate-status-log").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "page": 0, "has_more": False, "logs": [
                {"datetime": "t", "latch_name": "Gate", "status_label": "Opened",
                 "sense_line": 1, "state": "open"}]}))
    page = client.community.gate_status_log()
    assert page.logs[0].state == "open"


@respx.mock
def test_iter_gate_status_log_walks_pages(client):
    respx.get(f"{PROD}/v1/community/gate-status-log", params={"page": "0"}).mock(
        return_value=httpx.Response(200, json={
            "page": 0, "has_more": True, "logs": [{"state": "open"}]}))
    respx.get(f"{PROD}/v1/community/gate-status-log", params={"page": "1"}).mock(
        return_value=httpx.Response(200, json={
            "page": 1, "has_more": False, "logs": [{"state": "closed"}]}))
    states = [row.state for row in client.community.iter_gate_status_log()]
    assert states == ["open", "closed"]


@respx.mock
def test_iter_access_log_single_page(client):
    respx.get(f"{PROD}/v1/community/access-logs", params={"page": "0"}).mock(
        return_value=httpx.Response(200, json={
            "page": 0, "has_more": False, "logs": [{"key_name": "A"}]}))
    rows = list(client.community.iter_access_log())
    assert [r.key_name for r in rows] == ["A"]


@respx.mock
def test_iter_access_log_empty(client):
    respx.get(f"{PROD}/v1/community/access-logs", params={"page": "0"}).mock(
        return_value=httpx.Response(200, json={"page": 0, "has_more": False,
                                               "logs": []}))
    assert list(client.community.iter_access_log()) == []
