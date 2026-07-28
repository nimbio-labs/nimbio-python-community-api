"""Coverage for the hold-open + webhook surface and the webhook-signature
verifier (sync client; the async client shares the same endpoint registry)."""

import json as _json
import time

import httpx
import pytest
import respx

from nimbio_community_api import NimbioClient
from nimbio_community_api.webhooks import (
    WebhookSignatureError,
    compute_signature,
    construct_event,
    verify_signature,
)

PROD = "https://api.nimbio.com"


@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


def _body(route):
    return _json.loads(route.calls.last.request.content)


# -- hold opens --------------------------------------------------------------- #

@respx.mock
def test_hold_opens_read(client):
    respx.get(f"{PROD}/v1/community/hold-opens").mock(return_value=httpx.Response(
        200, json={"result": "ok", "hold_opens": {
            "l1": {"latch_id": "l1", "latch_name": "Front Gate",
                   "held_open": True, "manual": False, "disabled_until": None,
                   "events": [{"id": "e1"}], "recurring": [],
                   "timezone": "America/Los_Angeles"}}}))
    ho = client.community.hold_opens()
    latch = ho.latches["l1"]
    assert latch.held_open is True
    assert latch.manual is False
    assert latch.events == [{"id": "e1"}]


@respx.mock
def test_set_hold_open_sends_state(client):
    route = respx.put(f"{PROD}/v1/community/latches/l1/hold-open").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "latch_id": "l1", "manual": True,
            "held_open": True, "request_id": "r1"}))
    res = client.community.set_hold_open("l1", True)
    assert _body(route) == {"state": True}
    assert res.manual is True
    assert res.held_open is True
    assert not res.simulated


@respx.mock
def test_set_hold_open_simulated(client):
    respx.put(f"{PROD}/v1/community/latches/l1/hold-open").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "would_set": True, "latch_id": "l1",
            "request_id": "r1"}))
    res = client.community.set_hold_open("l1", True)
    assert res.simulated


@respx.mock
def test_add_and_remove_hold_open_event(client):
    add = respx.post(f"{PROD}/v1/community/latches/l1/hold-open/events").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "event_id": "e9", "latch_id": "l1",
            "request_id": "r1"}))
    added = client.community.add_hold_open_event(
        "l1", start="2026-08-01 09:00", end="2026-08-01 10:00")
    assert _body(add) == {"start": "2026-08-01 09:00", "end": "2026-08-01 10:00"}
    assert added.event_id == "e9"

    respx.delete(f"{PROD}/v1/community/latches/l1/hold-open/events/e9").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "removed": True, "request_id": "r2"}))
    removed = client.community.remove_hold_open_event("l1", "e9")
    assert removed.removed is True


# -- webhooks ------------------------------------------------------------------ #

@respx.mock
def test_webhook_event_types(client):
    respx.get(f"{PROD}/v1/community/webhook-events").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "events": ["sense_line.changed", "hold_open.changed"]}))
    events = client.community.webhook_event_types()
    assert "hold_open.changed" in events


@respx.mock
def test_webhook_crud(client):
    create = respx.post(f"{PROD}/v1/community/webhooks").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "r1",
            "webhook": {"webhook_id": "w1", "url": "https://x/y",
                        "events": ["sense_line.changed"], "secret": "whsec_abc"}}))
    created = client.community.create_webhook(
        "https://x/y", ["sense_line.changed"], description="HA")
    assert _body(create) == {"url": "https://x/y",
                             "events": ["sense_line.changed"],
                             "description": "HA"}
    assert created.secret == "whsec_abc"

    respx.get(f"{PROD}/v1/community/webhooks").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "webhooks": [{"webhook_id": "w1", "url": "https://x/y",
                                          "events": ["sense_line.changed"],
                                          "active": True, "disabled": False}]}))
    listed = client.community.webhooks()
    assert listed[0].webhook_id == "w1"
    assert listed[0].secret is None  # never listed

    update = respx.patch(f"{PROD}/v1/community/webhooks/w1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "webhook": {"webhook_id": "w1", "active": True},
            "request_id": "r2"}))
    updated = client.community.update_webhook("w1", active=True)
    assert _body(update) == {"active": True}
    assert updated.webhook.active is True

    respx.post(f"{PROD}/v1/community/webhooks/w1/rotate-secret").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "webhook_id": "w1", "secret": "whsec_new",
            "request_id": "r3"}))
    rotated = client.community.rotate_webhook_secret("w1")
    assert rotated.secret == "whsec_new"

    respx.post(f"{PROD}/v1/community/webhooks/w1/test").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "message": "Test delivery queued", "request_id": "r4"}))
    ping = client.community.test_webhook("w1")
    assert ping.result == "ok"

    respx.delete(f"{PROD}/v1/community/webhooks/w1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "webhook_id": "w1", "request_id": "r5"}))
    deleted = client.community.delete_webhook("w1")
    assert deleted.result == "ok"


# -- /v1/me capabilities --------------------------------------------------------- #

@respx.mock
def test_me_exposes_capabilities(client):
    respx.get(f"{PROD}/v1/me").mock(return_value=httpx.Response(200, json={
        "account_id": "a1",
        "key": {"api_key_id": "k1", "mode": "test", "type": "community",
                "community_id": "7",
                "capabilities": ["open", "gate_status", "hold_opens", "webhooks"]}}))
    me = client.me()
    assert me.key.type == "community"
    assert "hold_opens" in me.key.capabilities


@respx.mock
def test_gate_status_possible_statuses(client):
    respx.get(f"{PROD}/v1/community/gate-status").mock(
        return_value=httpx.Response(200, json={"latches": [{
            "latch_id": "l1", "latch_name": "Front Gate", "status": "Closed",
            "offline": False,
            "possible_statuses": [{"status": "Open", "transient": False},
                                  {"status": "Closed", "transient": False}]}]}))
    gs = client.community.gate_status()
    labels = {p.status for p in gs.latches[0].possible_statuses}
    assert labels == {"Open", "Closed"}


# -- signature verification ------------------------------------------------------ #

def test_verify_signature_roundtrip():
    secret = "whsec_test"
    body = b'{"event":"ping","data":{}}'
    ts = str(int(time.time()))
    sig = compute_signature(secret, ts, body)
    assert sig.startswith("sha256=")
    assert verify_signature(secret, ts, body, sig)
    # Tampered body fails.
    assert not verify_signature(secret, ts, body + b" ", sig)
    # Wrong secret fails.
    assert not verify_signature("whsec_other", ts, body, sig)


def test_verify_signature_replay_window():
    secret = "whsec_test"
    body = b"{}"
    old_ts = str(int(time.time()) - 3600)
    sig = compute_signature(secret, old_ts, body)
    # Outside tolerance -> rejected; tolerance disabled -> accepted.
    assert not verify_signature(secret, old_ts, body, sig)
    assert verify_signature(secret, old_ts, body, sig, tolerance_seconds=None)


def test_construct_event_verifies_and_decodes():
    secret = "whsec_test"
    envelope = {"event": "hold_open.changed", "id": "e1", "community_id": 7,
                "data": {"latch_id": "l1", "held_open": True}}
    body = _json.dumps(envelope).encode()
    ts = str(int(time.time()))
    sig = compute_signature(secret, ts, body)

    event = construct_event(body, sig, ts, secret)
    assert event["event"] == "hold_open.changed"
    assert event["data"]["held_open"] is True

    with pytest.raises(WebhookSignatureError):
        construct_event(body, sig, ts, "whsec_wrong")


# -- account surface --------------------------------------------------------- #

@respx.mock
def test_account_keys_parses_nested_latches(client):
    respx.get(f"{PROD}/v1/account/keys").mock(return_value=httpx.Response(
        200, json={"keys": [{
            "id": "k1", "name": "Home", "home": "123 Main St",
            "disabled": False, "hidden": False, "pending": False,
            "parent_name": "Maple Court Master",
            "latches": [{"id": "l1", "name": "Front Gate", "offline": False,
                         "location": "Entrance", "held_open": False}]}]}))
    keys = client.account.keys()
    assert keys[0].parent_name == "Maple Court Master"
    assert keys[0].latches[0].name == "Front Gate"


@respx.mock
def test_account_open_targets_key_and_latch(client):
    route = respx.post(f"{PROD}/v1/account/keys/k1/latches/l1/open").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "request_id": "r1"}))
    res = client.account.open("k1", "l1", note="hi")
    assert res.simulated
    assert _json.loads(route.calls.last.request.content) == {"note": "hi"}


@respx.mock
def test_me_usage_accepts_legacy_names(client):
    # Servers before the 2026-07 fix emitted only calls_this_minute etc.
    respx.get(f"{PROD}/v1/me").mock(return_value=httpx.Response(200, json={
        "account_id": "a1",
        "key": {"api_key_id": "k1", "mode": "test", "type": "account",
                "calls_this_minute": 2, "rate_limit_per_minute": 60,
                "calls_this_month": 9, "quota_per_month": 1000}}))
    me = client.me()
    assert me.key.minute_count == 2
    assert me.key.minute_limit == 60
    assert me.key.month_count == 9
    assert me.key.month_limit == 1000
