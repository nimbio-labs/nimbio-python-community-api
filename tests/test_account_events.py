"""Account-scoped directory call events: the typed models, the account SSE
stream (``account.stream_events``) and the history read
(``account.directory_calls`` / ``iter_directory_calls``), sync and async."""

import json as _json

import httpx
import pytest
import respx

from nimbio_community_api import AsyncNimbioClient, NimbioClient, _sse
from nimbio_community_api._exceptions import (
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)
from nimbio_community_api.models import (
    DirectoryCall,
    DirectoryCallEnded,
    DirectoryCallPage,
    DirectoryCallRinging,
    StreamEvent,
    StreamReset,
)

PROD = "https://api.nimbio.com"
STREAM = f"{PROD}/v1/account/events/stream"
COMMUNITY_STREAM = f"{PROD}/v1/events/stream"
CALLS = f"{PROD}/v1/account/directory-calls"

RINGING = {
    "directory_call_id": "c1",
    "placed_at": "2026-10-15T12:00:00+00:00",
    "answer_window_ends_at": "2026-10-15T12:09:00+00:00",
    "community": {"id": 123, "name": "Oak Grove"},
    "latch": {"id": "L1", "name": "Front Gate"},
    "called": {"type": "home", "home_id": "H1", "home_name": "12 Elm"},
    "arrived_via": "nfc",
    "caller": {"signed_in": True, "first_name": "Ada", "last_name": "Lovelace"},
}

ENDED = {
    "directory_call_id": "c1",
    "outcome": "opened",
    "ended_at": "2026-10-15T12:02:00+00:00",
    "ended_by": "callee",
    "answered_at": "2026-10-15T12:00:30+00:00",
    "answered_by_you": False,
    "answered_by_first_name": "Sam",
    "declined_by_you": True,
    "opened_by_you": False,
}


def _err(status, code):
    return httpx.Response(status, json={"error": {"code": code, "message": code}})


def _frame(i, etype="directory_call.ringing", data=None):
    body = {"event": etype, "id": f"a{i}", "account_id": "acct-1",
            "occurred_at": "2026-10-15T12:00:00+00:00",
            "data": RINGING if data is None else data}
    return f"id: a{i}\nevent: {etype}\ndata: {_json.dumps(body)}\n\n"


def _sse_bytes(*frames):
    return (": stream open\n\n" + "".join(frames)).encode()


# -- models ------------------------------------------------------------------- #

def test_ringing_full_caller():
    r = DirectoryCallRinging.from_dict(RINGING)
    assert r.directory_call_id == "c1"
    assert r.community.id == 123 and r.community.name == "Oak Grove"
    assert r.latch is not None and r.latch.name == "Front Gate"
    assert r.called.type == "home" and r.called.home_name == "12 Elm"
    assert r.arrived_via == "nfc"
    assert r.caller is not None and r.caller.signed_in is True
    assert r.caller.display_name == "Ada Lovelace"
    assert r.raw == RINGING


def test_ringing_anonymous_caller_and_no_latch():
    r = DirectoryCallRinging.from_dict({**RINGING, "caller": None, "latch": None,
                                        "called": {"type": "member",
                                                   "home_id": None,
                                                   "home_name": None}})
    assert r.caller is None
    assert r.latch is None
    assert r.called.type == "member" and r.called.home_id is None


@pytest.mark.parametrize("first,last,display", [
    ("Ada", None, "Ada"),
    (None, "Lovelace", "Lovelace"),
    (None, None, None),
])
def test_ringing_partial_caller_names(first, last, display):
    r = DirectoryCallRinging.from_dict(
        {**RINGING, "caller": {"signed_in": True, "first_name": first,
                               "last_name": last}})
    assert r.caller is not None
    assert (r.caller.first_name, r.caller.last_name) == (first, last)
    assert r.caller.display_name == display


def test_ringing_tolerates_garbage():
    r = DirectoryCallRinging.from_dict(None)
    assert r.directory_call_id is None and r.caller is None and r.latch is None
    assert r.community.id is None and r.called.type is None
    assert DirectoryCallRinging.from_dict(
        {"community": {"id": "nope"}, "caller": "x"}).caller is None


def test_ended_parses_and_keeps_unknown_outcome():
    e = DirectoryCallEnded.from_dict(ENDED)
    assert e.outcome == "opened" and e.ended_by == "callee"
    assert e.declined_by_you is True and e.opened_by_you is False
    assert e.answered_by_first_name == "Sam"
    future = DirectoryCallEnded.from_dict(
        {**ENDED, "outcome": "voicemail", "ended_by": "operator"})
    assert future.outcome == "voicemail"   # passed through, never rejected
    assert future.ended_by == "operator"


def test_from_event_reads_the_stream_payload():
    evt = StreamEvent(id="a1", type="directory_call.ended",
                      data={"event": "directory_call.ended", "id": "a1",
                            "account_id": "acct-1", "data": ENDED})
    assert DirectoryCallEnded.from_event(evt).outcome == "opened"
    assert DirectoryCallRinging.from_event(RINGING).directory_call_id == "c1"


def test_history_row_and_page():
    live = {**RINGING, "state": "ringing", "outcome": None, "ended_at": None,
            "ended_by": None, "answered_at": None, "answered_by_you": False,
            "answered_by_first_name": None, "declined_by_you": False,
            "opened_by_you": False, "caller": None}
    done = {**RINGING, **ENDED, "state": "ended", "outcome": "transferred"}
    page = DirectoryCallPage.from_dict(
        {"calls": [live, done], "next_before": "2026-10-15T11:00:00+00:00"})
    assert len(page) == 2 and page.has_more
    first, second = list(page)
    assert isinstance(first, DirectoryCall)
    assert first.state == "ringing" and first.outcome is None
    assert first.caller is None and first.ended_at is None
    assert second.outcome == "transferred"   # unknown outcome tolerated
    assert second.caller is not None and second.caller.first_name == "Ada"
    assert second.declined_by_you is True
    last = DirectoryCallPage.from_dict({"calls": [], "next_before": None})
    assert not last.has_more and len(last) == 0


# -- sync stream -------------------------------------------------------------- #

@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


@respx.mock
def test_account_stream_yields_events_on_the_account_route(client):
    route = respx.get(STREAM).mock(return_value=httpx.Response(
        200, headers={"content-type": "text/event-stream"},
        content=_sse_bytes(_frame(1), _frame(2, "directory_call.ended", ENDED))))
    community = respx.get(COMMUNITY_STREAM)
    got = list(client.account.stream_events(reconnect=False))
    assert route.called and not community.called
    assert [e.type for e in got] == ["directory_call.ringing",
                                     "directory_call.ended"]
    assert got[0].data["account_id"] == "acct-1"
    assert DirectoryCallRinging.from_event(got[0]).caller.first_name == "Ada"
    assert DirectoryCallEnded.from_event(got[1]).declined_by_you is True


@respx.mock
def test_account_stream_sends_filter_and_cursor(client):
    route = respx.get(STREAM).mock(return_value=httpx.Response(
        200, content=_sse_bytes(_frame(2))))
    list(client.account.stream_events(events=["directory_call.ringing"],
                                      last_event_id="a1", reconnect=False))
    params = dict(route.calls.last.request.url.params)
    assert params == {"events": "directory_call.ringing", "last_event_id": "a1"}


@respx.mock
def test_account_stream_resumes_after_drop_and_reset(client, monkeypatch):
    monkeypatch.setattr(_sse, "RECONNECT_BACKOFF_BASE", 0.0)
    reset = 'event: stream.reset\ndata: {"reason":"replay_unavailable"}\n\n'
    route = respx.get(STREAM).mock(side_effect=[
        httpx.Response(200, content=_sse_bytes(_frame(1))),
        httpx.Response(200, content=_sse_bytes(reset, _frame(5))),
        httpx.Response(200, content=_sse_bytes(_frame(6))),
    ])
    it = client.account.stream_events(last_event_id="a0")
    assert next(it).id == "a1"
    assert isinstance(next(it), StreamReset)
    assert next(it).id == "a5"
    assert next(it).id == "a6"
    it.close()
    cursors = [dict(c.request.url.params).get("last_event_id")
               for c in route.calls]
    assert cursors == ["a0", "a1", "a5"]


@respx.mock
def test_account_stream_ignores_revoked_frame_then_raises_on_reconnect(
        client, monkeypatch):
    monkeypatch.setattr(_sse, "RECONNECT_BACKOFF_BASE", 0.0)
    revoked = ('event: stream.revoked\n'
               'data: {"event":"stream.revoked","code":"forbidden"}\n\n')
    respx.get(STREAM).mock(side_effect=[
        httpx.Response(200, content=_sse_bytes(_frame(1), revoked)),
        _err(403, "forbidden"),
    ])
    it = client.account.stream_events()
    assert next(it).id == "a1"
    with pytest.raises(PermissionDeniedError):
        next(it)


@pytest.mark.parametrize("status,code,error", [
    (403, "not_account_key", PermissionDeniedError),
    (404, "feature_not_enabled", NotFoundError),
    (429, "stream_limit", RateLimitError),
    (400, "unknown_event_type", BadRequestError),
])
@respx.mock
def test_account_stream_error_mapping(client, status, code, error):
    respx.get(STREAM).mock(return_value=_err(status, code))
    with pytest.raises(error) as ei:
        next(client.account.stream_events())
    assert ei.value.code == code


# -- sync history ------------------------------------------------------------- #

@respx.mock
def test_directory_calls_sends_limit_and_before(client):
    route = respx.get(CALLS).mock(return_value=httpx.Response(
        200, json={"calls": [{**RINGING, "state": "ringing"}],
                   "next_before": None}))
    page = client.account.directory_calls()
    assert dict(route.calls.last.request.url.params) == {"limit": "20"}
    assert page.calls[0].directory_call_id == "c1" and not page.has_more

    client.account.directory_calls(limit=5, before="2026-10-01T00:00:00Z")
    assert dict(route.calls.last.request.url.params) == {
        "limit": "5", "before": "2026-10-01T00:00:00Z"}


@respx.mock
def test_iter_directory_calls_walks_the_cursor(client):
    route = respx.get(CALLS).mock(side_effect=[
        httpx.Response(200, json={"calls": [{**RINGING, "directory_call_id": "c3"},
                                            {**RINGING, "directory_call_id": "c2"}],
                                  "next_before": "t2"}),
        httpx.Response(200, json={"calls": [{**RINGING, "directory_call_id": "c1"}],
                                  "next_before": None}),
    ])
    ids = [c.directory_call_id for c in client.account.iter_directory_calls(limit=2)]
    assert ids == ["c3", "c2", "c1"]
    assert "before" not in dict(route.calls[0].request.url.params)
    assert dict(route.calls[1].request.url.params)["before"] == "t2"


@pytest.mark.parametrize("status,code,error", [
    (403, "not_account_key", PermissionDeniedError),
    (404, "feature_not_enabled", NotFoundError),
])
@respx.mock
def test_directory_calls_error_mapping(client, status, code, error):
    respx.get(CALLS).mock(return_value=_err(status, code))
    with pytest.raises(error) as ei:
        client.account.directory_calls()
    assert ei.value.code == code


@respx.mock
def test_iter_directory_calls_stops_on_a_stuck_cursor(client):
    stuck = httpx.Response(200, json={"calls": [{**RINGING, "directory_call_id": "c1"}],
                                      "next_before": "t1"})
    route = respx.get(CALLS).mock(side_effect=[stuck, stuck, stuck])
    ids = [c.directory_call_id for c in client.account.iter_directory_calls(before="t1")]
    assert ids == ["c1"]
    assert route.call_count == 1


# -- async -------------------------------------------------------------------- #

@pytest.mark.asyncio
@respx.mock
async def test_async_account_stream_resumes(test_key, monkeypatch):
    monkeypatch.setattr(_sse, "RECONNECT_BACKOFF_BASE", 0.0)
    route = respx.get(STREAM).mock(side_effect=[
        httpx.Response(200, content=_sse_bytes(_frame(1))),
        httpx.Response(200, content=_sse_bytes(_frame(2, "directory_call.ended",
                                                      ENDED))),
    ])
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        it = client.account.stream_events(events=["directory_call.ringing",
                                                  "directory_call.ended"])
        assert (await it.__anext__()).id == "a1"
        ended = await it.__anext__()
        await it.aclose()
    assert DirectoryCallEnded.from_event(ended).outcome == "opened"
    second = dict(route.calls[1].request.url.params)
    assert second == {"events": "directory_call.ringing,directory_call.ended",
                      "last_event_id": "a1"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,error", [
    (403, "not_account_key", PermissionDeniedError),
    (404, "feature_not_enabled", NotFoundError),
])
@respx.mock
async def test_async_account_stream_error_mapping(test_key, status, code, error):
    respx.get(STREAM).mock(return_value=_err(status, code))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        with pytest.raises(error):
            await client.account.stream_events().__anext__()


@pytest.mark.asyncio
@respx.mock
async def test_async_directory_calls_and_iter(test_key):
    respx.get(CALLS).mock(side_effect=[
        httpx.Response(200, json={"calls": [{**RINGING, "directory_call_id": "c2"}],
                                  "next_before": "t2"}),
        httpx.Response(200, json={"calls": [{**RINGING, "directory_call_id": "c1",
                                             "caller": None}],
                                  "next_before": None}),
        _err(404, "feature_not_enabled"),
    ])
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        ids = [c.directory_call_id
               async for c in client.account.iter_directory_calls(limit=1)]
        assert ids == ["c2", "c1"]
        with pytest.raises(NotFoundError):
            await client.account.directory_calls()


@pytest.mark.asyncio
@respx.mock
async def test_async_iter_directory_calls_stops_on_an_empty_page(test_key):
    route = respx.get(CALLS).mock(side_effect=[
        httpx.Response(200, json={"calls": [], "next_before": "t9"}),
        httpx.Response(200, json={"calls": [], "next_before": "t9"}),
    ])
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        ids = [c.directory_call_id async for c in client.account.iter_directory_calls()]
    assert ids == []
    assert route.call_count == 1
