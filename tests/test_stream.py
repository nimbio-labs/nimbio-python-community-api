"""Coverage for the live event stream: the SSE parser, frame→model mapping,
and the sync/async ``stream_events`` consumers (reconnect, resume cursor,
reset handling, error mapping)."""

import json as _json

import httpx
import pytest
import respx

from nimbio_community_api import AsyncNimbioClient, NimbioClient, _sse
from nimbio_community_api._exceptions import (
    APIConnectionError,
    PermissionDeniedError,
    RateLimitError,
)
from nimbio_community_api.models import StreamEvent, StreamReset

PROD = "https://api.nimbio.com"
STREAM = f"{PROD}/v1/events/stream"


def _sse_bytes(*frames, comments_first=True):
    out = ": stream open\n\n" if comments_first else ""
    for f in frames:
        if "id" in f:
            out += f"id: {f['id']}\n"
        out += f"event: {f['event']}\ndata: {_json.dumps(f['data'])}\n\n"
    return out.encode()


def _evt_frame(i, etype="sense_line.changed"):
    return {"id": f"e{i}", "event": etype,
            "data": {"event": etype, "id": f"e{i}", "community_id": 5,
                     "occurred_at": "2026-07-31T12:00:00+00:00",
                     "data": {"latch_id": "L1", "n": i}}}


# -- parser ------------------------------------------------------------------- #

def test_sse_parser_assembles_frames_and_skips_comments():
    p = _sse.SSEParser()
    assert p.feed(": ping") is None
    assert p.feed("") is None          # blank after comment: no frame
    assert p.feed("id: e1") is None
    assert p.feed("event: sense_line.changed") is None
    assert p.feed("data: {\"a\":1}") is None
    frame = p.feed("")
    assert frame == {"id": "e1", "event": "sense_line.changed",
                     "data": '{"a":1}'}
    # Parser state resets after dispatch.
    assert p.feed("") is None


def test_sse_parser_multiline_data_and_no_space():
    p = _sse.SSEParser()
    p.feed("event:x")            # no space after colon
    p.feed("id:e9")
    p.feed("data: line1")
    p.feed("data: line2")
    frame = p.feed("")
    assert frame["data"] == "line1\nline2"
    assert frame["event"] == "x"
    assert frame["id"] == "e9"


def test_frame_to_model_variants():
    ok = _sse.frame_to_model({"id": "e1", "event": "open.succeeded",
                              "data": '{"data":{"latch_id":"L"}}'})
    assert isinstance(ok, StreamEvent)
    assert ok.payload == {"latch_id": "L"}

    reset = _sse.frame_to_model({"id": None, "event": "stream.reset",
                                 "data": '{"reason":"replay_unavailable"}'})
    assert isinstance(reset, StreamReset)
    assert reset.reason == "replay_unavailable"

    bad_reset = _sse.frame_to_model({"id": None, "event": "stream.reset",
                                     "data": "not json"})
    assert isinstance(bad_reset, StreamReset)
    assert bad_reset.reason is None

    assert _sse.frame_to_model({"id": None, "event": "x", "data": "{}"}) is None
    assert _sse.frame_to_model({"id": "e", "event": None, "data": "{}"}) is None
    assert _sse.frame_to_model({"id": "e", "event": "x", "data": "bad"}) is None
    empty = _sse.frame_to_model({"id": "e", "event": "x", "data": ""})
    assert isinstance(empty, StreamEvent) and empty.data == {}
    listy = _sse.frame_to_model({"id": "e", "event": "x", "data": "[1]"})
    assert isinstance(listy, StreamEvent) and listy.data == {}


def test_stream_params_and_backoff():
    assert _sse.stream_params(None, None) == {}
    assert _sse.stream_params(["a", "b"], "e1") == {
        "events": "a,b", "last_event_id": "e1"}
    assert _sse.backoff_delay(0) == 0.5
    assert _sse.backoff_delay(10) == _sse.RECONNECT_BACKOFF_MAX


# -- sync consumer ------------------------------------------------------------ #

@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


@respx.mock
def test_stream_yields_events_single_connection(client):
    respx.get(STREAM).mock(return_value=httpx.Response(
        200, headers={"content-type": "text/event-stream"},
        content=_sse_bytes(_evt_frame(1), _evt_frame(2, "hold_open.changed"))))
    got = list(client.community.stream_events(reconnect=False))
    assert [e.id for e in got] == ["e1", "e2"]
    assert got[1].type == "hold_open.changed"
    assert got[0].payload["latch_id"] == "L1"


@respx.mock
def test_stream_sends_filter_and_cursor(client):
    route = respx.get(STREAM).mock(return_value=httpx.Response(
        200, content=_sse_bytes(_evt_frame(2))))
    list(client.community.stream_events(
        events=["sense_line.changed", "hold_open.changed"],
        last_event_id="e1", reconnect=False))
    params = dict(route.calls.last.request.url.params)
    assert params["events"] == "sense_line.changed,hold_open.changed"
    assert params["last_event_id"] == "e1"


@respx.mock
def test_stream_reconnects_and_resumes_from_last_id(client, monkeypatch):
    monkeypatch.setattr(_sse, "RECONNECT_BACKOFF_BASE", 0.0)
    route = respx.get(STREAM).mock(side_effect=[
        httpx.Response(200, content=_sse_bytes(_evt_frame(1))),
        httpx.Response(200, content=_sse_bytes(_evt_frame(2))),
    ])
    it = client.community.stream_events()
    assert next(it).id == "e1"
    assert next(it).id == "e2"  # first connection ended; auto-reconnected
    it.close()
    assert route.call_count == 2
    second = dict(route.calls[1].request.url.params)
    assert second["last_event_id"] == "e1"


@respx.mock
def test_stream_reset_clears_cursor_and_is_yielded(client, monkeypatch):
    monkeypatch.setattr(_sse, "RECONNECT_BACKOFF_BASE", 0.0)
    reset_bytes = (b"event: stream.reset\n"
                   b'data: {"reason":"replay_unavailable"}\n\n')
    route = respx.get(STREAM).mock(side_effect=[
        httpx.Response(200, content=reset_bytes + _sse_bytes(
            _evt_frame(3), comments_first=False)),
        httpx.Response(200, content=_sse_bytes(_evt_frame(4))),
    ])
    it = client.community.stream_events(last_event_id="expired")
    first = next(it)
    assert isinstance(first, StreamReset)
    assert next(it).id == "e3"
    assert next(it).id == "e4"
    it.close()
    # After the reset the cursor restarted from e3, not "expired".
    assert dict(route.calls[1].request.url.params)["last_event_id"] == "e3"


@respx.mock
def test_stream_http_errors_raise(client):
    respx.get(STREAM).mock(return_value=httpx.Response(
        429, json={"error": {"code": "stream_limit",
                             "message": "At most 3 concurrent event streams per key"}}))
    with pytest.raises(RateLimitError) as ei:
        next(client.community.stream_events())
    assert ei.value.code == "stream_limit"

    respx.get(STREAM).mock(return_value=httpx.Response(
        403, json={"error": {"code": "not_community_key", "message": "no"}}))
    with pytest.raises(PermissionDeniedError):
        next(client.community.stream_events())


@respx.mock
def test_stream_transport_error_raises_without_reconnect(client):
    respx.get(STREAM).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(APIConnectionError):
        next(client.community.stream_events(reconnect=False))


@respx.mock
def test_stream_transport_error_reconnects(client, monkeypatch):
    monkeypatch.setattr(_sse, "RECONNECT_BACKOFF_BASE", 0.0)
    respx.get(STREAM).mock(side_effect=[
        httpx.ConnectError("boom"),
        httpx.Response(200, content=_sse_bytes(_evt_frame(1))),
    ])
    it = client.community.stream_events()
    assert next(it).id == "e1"
    it.close()


# -- async consumer ----------------------------------------------------------- #

@pytest.mark.asyncio
@respx.mock
async def test_async_stream_yields_and_reconnects(test_key, monkeypatch):
    monkeypatch.setattr(_sse, "RECONNECT_BACKOFF_BASE", 0.0)
    route = respx.get(STREAM).mock(side_effect=[
        httpx.Response(200, content=_sse_bytes(_evt_frame(1))),
        httpx.Response(200, content=_sse_bytes(_evt_frame(2))),
    ])
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        it = client.community.stream_events()
        assert (await it.__anext__()).id == "e1"
        assert (await it.__anext__()).id == "e2"
        await it.aclose()
    assert dict(route.calls[1].request.url.params)["last_event_id"] == "e1"


@pytest.mark.asyncio
@respx.mock
async def test_async_stream_errors_raise(test_key):
    respx.get(STREAM).mock(return_value=httpx.Response(
        429, json={"error": {"code": "stream_limit", "message": "cap"}}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        with pytest.raises(RateLimitError):
            await client.community.stream_events().__anext__()


@pytest.mark.asyncio
@respx.mock
async def test_async_stream_transport_error_no_reconnect(test_key):
    respx.get(STREAM).mock(side_effect=httpx.ConnectError("boom"))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        with pytest.raises(APIConnectionError):
            await client.community.stream_events(reconnect=False).__anext__()


@pytest.mark.asyncio
@respx.mock
async def test_async_stream_single_connection_ends(test_key):
    respx.get(STREAM).mock(return_value=httpx.Response(
        200, content=_sse_bytes(_evt_frame(1))))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        got = [e async for e in client.community.stream_events(reconnect=False)]
    assert [e.id for e in got] == ["e1"]
