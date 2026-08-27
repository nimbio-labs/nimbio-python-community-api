"""Conditional GETs: the ETag cache, ``If-None-Match``, and 304 replay.

The behaviour under test is transport-level and transparent, so most of these
assert on two things at once: what went out on the wire, and that what came
back is indistinguishable from a plain 200.
"""

import json as _json
import threading

import httpx
import pytest
import respx

from nimbio_community_api import (
    DEFAULT_CACHE_SIZE,
    AsyncNimbioClient,
    CacheStats,
    NimbioClient,
    PermissionDeniedError,
)
from nimbio_community_api._cache import ETagCache, cache_key

PROD = "https://api.nimbio.com"
STREAM = f"{PROD}/v1/events/stream"

GATE_BODY = {"latches": [{"latch_id": "L1", "latch_name": "Front",
                          "status": "closed"}]}


def _ok(body, etag="W/\"v1\""):
    headers = {"Cache-Control": "private, no-cache"}
    if etag is not None:
        headers["ETag"] = etag
    return httpx.Response(200, json=body, headers=headers)


def _not_modified(etag="W/\"v1\""):
    headers = {"Cache-Control": "private, no-cache"}
    if etag is not None:
        headers["ETag"] = etag
    return httpx.Response(304, headers=headers)


@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


# -- the wire ---------------------------------------------------------------- #

@respx.mock
def test_first_get_sends_no_conditional_header(client):
    route = respx.get(f"{PROD}/v1/community/gate-status").mock(
        return_value=_ok(GATE_BODY))
    client.community.gate_status()
    assert "if-none-match" not in {
        k.lower() for k in route.calls.last.request.headers}


@respx.mock
def test_second_get_sends_the_first_responses_etag(client):
    route = respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY, etag='W/"abc"'), _not_modified('W/"abc"')])
    client.community.gate_status()
    client.community.gate_status()
    assert route.calls[1].request.headers["if-none-match"] == 'W/"abc"'


@respx.mock
def test_304_returns_a_value_equal_to_the_200(client):
    respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY), _not_modified()])
    first = client.community.gate_status()
    second = client.community.gate_status()
    assert second == first
    assert second.latches[0].latch_name == "Front"
    # ...and is genuinely a different object, not the one we handed out before.
    assert second is not first
    assert second.latches[0] is not first.latches[0]
    assert second.raw is not first.raw


@respx.mock
def test_a_response_without_an_etag_is_never_stored(client):
    route = respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY, etag=None), _ok(GATE_BODY, etag=None)])
    client.community.gate_status()
    client.community.gate_status()
    assert "if-none-match" not in {
        k.lower() for k in route.calls[1].request.headers}
    assert client.cache_stats().entries == 0


@respx.mock
def test_a_route_that_stops_sending_etags_drops_its_entry(client):
    respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY), _ok(GATE_BODY, etag=None)])
    client.community.gate_status()
    assert client.cache_stats().entries == 1
    client.community.gate_status()
    assert client.cache_stats().entries == 0


@respx.mock
def test_304_may_restate_a_new_etag_and_it_is_adopted(client):
    route = respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY, etag='W/"one"'),
                     _not_modified('W/"two"'),
                     _not_modified('W/"two"')])
    client.community.gate_status()
    client.community.gate_status()
    client.community.gate_status()
    assert route.calls[1].request.headers["if-none-match"] == 'W/"one"'
    assert route.calls[2].request.headers["if-none-match"] == 'W/"two"'


# -- opt-out ------------------------------------------------------------------ #

@respx.mock
def test_cache_false_never_sends_the_header_or_stores(test_key):
    route = respx.get(f"{PROD}/v1/community/gate-status").mock(
        return_value=_ok(GATE_BODY))
    with NimbioClient(test_key, max_retries=0, cache=False) as c:
        c.community.gate_status()
        c.community.gate_status()
        assert "if-none-match" not in {
            k.lower() for k in route.calls[1].request.headers}
        assert c.cache_stats() == CacheStats(hits=0, misses=0, entries=0)


# -- mutation safety ---------------------------------------------------------- #

@respx.mock
def test_mutating_a_result_does_not_corrupt_a_later_cache_hit(client):
    respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY), _not_modified(), _not_modified()])
    first = client.community.gate_status()
    first.latches[0].latch_name = "VANDALISED"
    first.latches.clear()
    first.raw["latches"] = []

    second = client.community.gate_status()
    assert second.latches[0].latch_name == "Front"
    # And a mutation of the *cache hit* does not poison the hit after it —
    # the stored bytes are re-decoded every time, not handed out.
    second.raw["latches"][0]["latch_name"] = "ALSO VANDALISED"
    third = client.community.gate_status()
    assert third.latches[0].latch_name == "Front"


# -- scope: never for writes, never for the stream ----------------------------- #

@respx.mock
def test_non_get_methods_are_never_cached(client):
    route = respx.post(f"{PROD}/v1/community/messages").mock(
        return_value=httpx.Response(200, json={"result": "ok"},
                                    headers={"ETag": 'W/"post"'}))
    client.community.message("hi")
    client.community.message("hi")
    assert "if-none-match" not in {
        k.lower() for k in route.calls[1].request.headers}
    assert client.cache_stats() == CacheStats(hits=0, misses=0, entries=0)


def test_stream_path_is_explicitly_uncacheable():
    # Belt and braces: the SSE body carries no ETag anyway, but the exclusion
    # is stated rather than inferred.
    assert cache_key("GET", "/v1/events/stream", None) is None
    assert cache_key("GET", "/v1/community/gate-status", None) is not None


@respx.mock
def test_stream_events_sends_no_conditional_header(client):
    body = (b": open\n\nid: e1\nevent: sense_line.changed\n"
            b"data: " + _json.dumps(
                {"event": "sense_line.changed", "id": "e1",
                 "community_id": 5, "data": {"latch_id": "L1"}}).encode()
            + b"\n\n")
    route = respx.get(STREAM).mock(
        return_value=httpx.Response(200, content=body,
                                    headers={"ETag": 'W/"stream"'}))
    events = []
    for evt in client.community.stream_events(reconnect=False):
        events.append(evt)
    assert len(events) == 1
    assert "if-none-match" not in {
        k.lower() for k in route.calls.last.request.headers}
    assert client.cache_stats().entries == 0


# -- cache keys --------------------------------------------------------------- #

@respx.mock
def test_different_query_params_are_different_entries(client):
    p0 = respx.get(f"{PROD}/v1/community/access-logs", params={"page": "0"}).mock(
        side_effect=[_ok({"page": 0, "has_more": False, "logs": [{"key_name": "A"}]},
                         etag='W/"p0"'),
                     _not_modified('W/"p0"')])
    p1 = respx.get(f"{PROD}/v1/community/access-logs", params={"page": "1"}).mock(
        return_value=_ok({"page": 1, "has_more": False, "logs": [{"key_name": "B"}]},
                         etag='W/"p1"'))
    client.community.access_log(page=0)
    client.community.access_log(page=1)
    again = client.community.access_log(page=0)
    assert again.logs[0].key_name == "A"
    assert p0.calls[1].request.headers["if-none-match"] == 'W/"p0"'
    assert "if-none-match" not in {k.lower() for k in p1.calls.last.request.headers}
    assert client.cache_stats().entries == 2


def test_cache_key_is_order_insensitive_and_method_scoped():
    a = cache_key("GET", "/v1/x", {"b": 2, "a": 1})
    b = cache_key("GET", "/v1/x", {"a": 1, "b": 2})
    assert a == b
    assert cache_key("GET", "/v1/x", {"a": 1}) != cache_key("GET", "/v1/x", None)
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        assert cache_key(method, "/v1/x", None) is None


# -- bounds ------------------------------------------------------------------- #

@respx.mock
def test_lru_evicts_at_the_bound(test_key):
    routes = {}
    for page in range(3):
        routes[page] = respx.get(f"{PROD}/v1/community/access-logs",
                                 params={"page": str(page)}).mock(
            return_value=_ok({"page": page, "has_more": False, "logs": []},
                             etag=f'W/"p{page}"'))
    with NimbioClient(test_key, max_retries=0, cache_size=2) as c:
        c.community.access_log(page=0)
        c.community.access_log(page=1)
        c.community.access_log(page=2)
        assert c.cache_stats().entries == 2
        # page 0 was the least recently used, so it is the one that went.
        c.community.access_log(page=0)
        assert "if-none-match" not in {
            k.lower() for k in routes[0].calls.last.request.headers}
        # page 2 is still held.
        c.community.access_log(page=2)
        assert routes[2].calls.last.request.headers["if-none-match"] == 'W/"p2"'


@respx.mock
def test_a_hit_refreshes_recency(test_key):
    def _page(page):
        return _ok({"page": page, "has_more": False, "logs": []},
                   etag=f'W/"p{page}"')

    routes = {}
    for page in (1, 9):
        routes[page] = respx.get(f"{PROD}/v1/community/access-logs",
                                 params={"page": str(page)}).mock(
            side_effect=lambda req, page=page: _page(page))
    # Page 0's second read is a 304 — the point of the test is that a *hit*
    # refreshes recency, not just a store.
    routes[0] = respx.get(f"{PROD}/v1/community/access-logs",
                          params={"page": "0"}).mock(
        side_effect=[_page(0), _not_modified('W/"p0"'), _not_modified('W/"p0"')])
    with NimbioClient(test_key, max_retries=0, cache_size=2) as c:
        c.community.access_log(page=0)
        c.community.access_log(page=1)
        c.community.access_log(page=0)   # touches page 0: it becomes newest
        c.community.access_log(page=9)   # so page 1 is what gets evicted
        c.community.access_log(page=0)
        c.community.access_log(page=1)
        assert routes[0].calls.last.request.headers["if-none-match"] == 'W/"p0"'
        assert "if-none-match" not in {
            k.lower() for k in routes[1].calls.last.request.headers}


def test_cache_size_has_a_floor_of_one():
    assert ETagCache(0).max_entries == 1
    assert ETagCache(-5).max_entries == 1
    assert ETagCache().max_entries == DEFAULT_CACHE_SIZE


# -- stats -------------------------------------------------------------------- #

@respx.mock
def test_stats_report_what_actually_happened(client):
    respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY), _not_modified(), _not_modified()])
    assert client.cache_stats() == CacheStats(hits=0, misses=0, entries=0)
    client.community.gate_status()
    assert client.cache_stats() == CacheStats(hits=0, misses=1, entries=1)
    client.community.gate_status()
    client.community.gate_status()
    assert client.cache_stats() == CacheStats(hits=2, misses=1, entries=1)


@respx.mock
def test_an_error_counts_as_a_miss_and_drops_the_entry(client):
    respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY),
                     httpx.Response(403, json={"error": {
                         "code": "not_community_key", "message": "nope"}})])
    client.community.gate_status()
    with pytest.raises(PermissionDeniedError):
        client.community.gate_status()
    assert client.cache_stats() == CacheStats(hits=0, misses=2, entries=0)


# -- the eviction race -------------------------------------------------------- #

@respx.mock
def test_a_304_with_no_stored_body_re_asks_unconditionally(client):
    route = respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY), _not_modified(), _ok(GATE_BODY)])
    client.community.gate_status()
    # Simulate another thread evicting the entry after the conditional header
    # went out but before the 304 came back.
    client._cache._entries.clear()
    result = client.community.gate_status()
    assert result.latches[0].latch_name == "Front"
    assert len(route.calls) == 3
    assert "if-none-match" not in {
        k.lower() for k in route.calls[2].request.headers}


# -- concurrency -------------------------------------------------------------- #

def test_cache_is_safe_under_concurrent_access():
    cache = ETagCache(16)

    def hammer(n):
        for i in range(200):
            key = f"GET /v1/x/{(n * 7 + i) % 40}"
            cache.store(key, f'W/"{i}"', b'{"n":1}')
            cache.etag_for(key)
            cache.hit(key)
            cache.stats()

    threads = [threading.Thread(target=hammer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert cache.stats().entries <= 16


# -- async parity ------------------------------------------------------------- #

@respx.mock
async def test_async_304_returns_an_equal_value(test_key):
    route = respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY, etag='W/"a"'), _not_modified('W/"a"')])
    async with AsyncNimbioClient(test_key, max_retries=0) as c:
        first = await c.community.gate_status()
        second = await c.community.gate_status()
    assert second == first
    assert second is not first
    assert route.calls[1].request.headers["if-none-match"] == 'W/"a"'


@respx.mock
async def test_async_mutation_does_not_corrupt_a_later_hit(test_key):
    respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY), _not_modified(), _not_modified()])
    async with AsyncNimbioClient(test_key, max_retries=0) as c:
        first = await c.community.gate_status()
        first.latches[0].latch_name = "VANDALISED"
        second = await c.community.gate_status()
        assert second.latches[0].latch_name == "Front"
        assert c.cache_stats() == CacheStats(hits=1, misses=1, entries=1)


@respx.mock
async def test_async_cache_false_never_sends_the_header(test_key):
    route = respx.get(f"{PROD}/v1/community/gate-status").mock(
        return_value=_ok(GATE_BODY))
    async with AsyncNimbioClient(test_key, max_retries=0, cache=False) as c:
        await c.community.gate_status()
        await c.community.gate_status()
    assert "if-none-match" not in {
        k.lower() for k in route.calls[1].request.headers}


@respx.mock
async def test_async_non_get_is_never_cached(test_key):
    route = respx.post(f"{PROD}/v1/community/latches/l1/open").mock(
        return_value=httpx.Response(200, json={"result": "simulated"},
                                    headers={"ETag": 'W/"open"'}))
    async with AsyncNimbioClient(test_key, max_retries=0) as c:
        await c.community.open("l1")
        await c.community.open("l1")
        assert c.cache_stats() == CacheStats(hits=0, misses=0, entries=0)
    assert "if-none-match" not in {
        k.lower() for k in route.calls[1].request.headers}


@respx.mock
async def test_async_304_with_no_stored_body_re_asks_unconditionally(test_key):
    route = respx.get(f"{PROD}/v1/community/gate-status").mock(
        side_effect=[_ok(GATE_BODY), _not_modified(), _ok(GATE_BODY)])
    async with AsyncNimbioClient(test_key, max_retries=0) as c:
        await c.community.gate_status()
        c._cache._entries.clear()
        result = await c.community.gate_status()
    assert result.latches[0].latch_name == "Front"
    assert len(route.calls) == 3


@respx.mock
async def test_async_stream_events_sends_no_conditional_header(test_key):
    body = (b": open\n\nid: e1\nevent: sense_line.changed\n"
            b"data: " + _json.dumps(
                {"event": "sense_line.changed", "id": "e1",
                 "community_id": 5, "data": {"latch_id": "L1"}}).encode()
            + b"\n\n")
    route = respx.get(STREAM).mock(
        return_value=httpx.Response(200, content=body,
                                    headers={"ETag": 'W/"stream"'}))
    async with AsyncNimbioClient(test_key, max_retries=0) as c:
        events = [e async for e in c.community.stream_events(reconnect=False)]
    assert len(events) == 1
    assert "if-none-match" not in {
        k.lower() for k in route.calls.last.request.headers}
