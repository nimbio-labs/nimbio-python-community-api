"""Account open history: the typed models and ``account.history`` /
``iter_history``, sync and async."""

import httpx
import pytest
import respx

from nimbio_community_api import AsyncNimbioClient, NimbioClient
from nimbio_community_api._exceptions import (
    APIError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
)
from nimbio_community_api.models import AccountOpen, OpenHistoryPage

PROD = "https://api.nimbio.com"
HISTORY = f"{PROD}/v1/account/history"

WINDOW = {"from": "2026-07-17T15:00:00+00:00", "to": "2026-10-15T15:00:00+00:00"}

MINE = {
    "id": 90210417,
    "opened_at": "2026-10-15T08:02:11-07:00",
    "key": {"id": "K1", "name": "Front Gate Key"},
    "latch": {"id": "L1", "name": "Front Gate"},
    "opened_by": {"is_you": True, "name": None},
    "guest_link": None,
    "open_type": "open",
    "result": "opened",
    "open_type_id": 1,
    "result_id": 1,
}

SHARED = {
    **MINE,
    "id": 90210300,
    "opened_at": "2026-10-14T18:30:00-07:00",
    "opened_by": {"is_you": False, "name": "Sam Lee"},
}

GUEST = {
    **MINE,
    "id": 90210201,
    "opened_at": "2026-10-13T10:00:00-07:00",
    "opened_by": {"is_you": False, "name": "Party Saturday"},
    "guest_link": {"id": 42, "label": "Party Saturday"},
    "open_type": "teleportation",  # a name this release does not know
    "open_type_id": 99,
}


def _page(opens, page=0, has_more=False, **window):
    return httpx.Response(200, json={"page": page, "has_more": has_more,
                                     **(window or WINDOW), "opens": opens})


def _err(status, code):
    return httpx.Response(status, json={"error": {"code": code, "message": code}})


# -- models ------------------------------------------------------------------ #

def test_own_open_parses_with_null_guest_link():
    row = AccountOpen.from_dict(MINE)
    assert row.id == 90210417
    assert row.opened_at == "2026-10-15T08:02:11-07:00"
    assert (row.key.id, row.key.name) == ("K1", "Front Gate Key")
    assert (row.latch.id, row.latch.name) == ("L1", "Front Gate")
    assert row.opened_by.is_you is True and row.opened_by.name is None
    assert row.guest_link is None
    assert (row.open_type, row.result) == ("open", "opened")
    assert (row.open_type_id, row.result_id) == (1, 1)
    assert row.raw is MINE


def test_someone_elses_open_names_them():
    row = AccountOpen.from_dict(SHARED)
    assert row.opened_by.is_you is False
    assert row.opened_by.name == "Sam Lee"


def test_guest_link_open_and_unknown_open_type_pass_through():
    row = AccountOpen.from_dict(GUEST)
    assert row.guest_link is not None
    assert (row.guest_link.id, row.guest_link.label) == (42, "Party Saturday")
    assert row.open_type == "teleportation"
    assert row.open_type_id == 99


def test_open_tolerates_garbage():
    row = AccountOpen.from_dict({"id": "abc", "key": "nope", "guest_link": "x",
                                 "open_type_id": "abc"})
    assert row.id is None
    assert row.key.id is None and row.latch.name is None
    assert row.opened_by.is_you is False
    assert row.guest_link is None and row.open_type_id is None
    assert AccountOpen.from_dict(None).opened_at is None


def test_page_parses_window_and_rows():
    page = OpenHistoryPage.from_dict({"page": 2, "has_more": True, **WINDOW,
                                      "opens": [MINE, SHARED]})
    assert page.page == 2 and page.has_more
    assert page.date_from == WINDOW["from"] and page.date_to == WINDOW["to"]
    assert len(page) == 2
    assert [o.opened_by.is_you for o in page] == [True, False]
    empty = OpenHistoryPage.from_dict({})
    assert empty.opens == [] and not empty.has_more and empty.page is None


# -- sync -------------------------------------------------------------------- #

@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


@respx.mock
def test_history_sends_only_page_by_default(client):
    route = respx.get(HISTORY).mock(return_value=_page([MINE]))
    page = client.account.history()
    assert dict(route.calls.last.request.url.params) == {"page": "0"}
    assert page.opens[0].key.id == "K1" and not page.has_more


@respx.mock
def test_history_forwards_from_to_key_id_and_page(client):
    route = respx.get(HISTORY).mock(return_value=_page([], page=3))
    client.account.history(date_from="2026-10-01", date_to="2026-10-15T00:00:00Z",
                           key_id="K1", page=3)
    assert dict(route.calls.last.request.url.params) == {
        "from": "2026-10-01", "to": "2026-10-15T00:00:00Z",
        "key_id": "K1", "page": "3"}


@respx.mock
def test_iter_history_walks_pages_and_pins_the_window(client):
    route = respx.get(HISTORY).mock(side_effect=[
        _page([MINE, SHARED], page=0, has_more=True),
        _page([GUEST], page=1, has_more=False),
    ])
    rows = list(client.account.iter_history(key_id="K1"))
    assert [r.id for r in rows] == [90210417, 90210300, 90210201]
    assert [r.opened_at for r in rows] == [
        MINE["opened_at"], SHARED["opened_at"], GUEST["opened_at"]]
    assert dict(route.calls[0].request.url.params) == {"page": "0", "key_id": "K1"}
    # The second page reuses the window the first one echoed.
    assert dict(route.calls[1].request.url.params) == {
        "page": "1", "key_id": "K1", **WINDOW}


@respx.mock
def test_iter_history_keeps_a_caller_window_and_start_page(client):
    route = respx.get(HISTORY).mock(side_effect=[
        _page([MINE], page=4, has_more=True),
        _page([MINE], page=5, has_more=False),
    ])
    list(client.account.iter_history(date_from="2026-10-01", start_page=4))
    second = dict(route.calls[1].request.url.params)
    assert second["from"] == "2026-10-01" and second["page"] == "5"
    assert second["to"] == WINDOW["to"]


@respx.mock
def test_iter_history_stops_on_an_empty_page_even_if_has_more(client):
    route = respx.get(HISTORY).mock(side_effect=[
        _page([], has_more=True),
        _page([], has_more=True),
    ])
    assert list(client.account.iter_history()) == []
    assert route.call_count == 1


@pytest.mark.parametrize("status,code,error", [
    (404, "key_not_found", NotFoundError),
    (404, "feature_not_enabled", NotFoundError),
    (403, "not_account_key", PermissionDeniedError),
    (403, "oauth_not_permitted", PermissionDeniedError),
    (400, "invalid_window", BadRequestError),
])
@respx.mock
def test_history_error_mapping(client, status, code, error):
    respx.get(HISTORY).mock(return_value=_err(status, code))
    with pytest.raises(error) as ei:
        client.account.history()
    assert ei.value.code == code


@respx.mock
def test_history_bad_datetime_is_a_422(client):
    respx.get(HISTORY).mock(return_value=_err(422, "invalid_datetime"))
    with pytest.raises(APIError) as ei:
        client.account.history(date_from="yesterday")
    assert ei.value.status_code == 422
    assert ei.value.code == "invalid_datetime"


# -- async ------------------------------------------------------------------- #

@pytest.mark.asyncio
@respx.mock
async def test_async_history_and_iter(test_key):
    route = respx.get(HISTORY).mock(side_effect=[
        _page([MINE], page=0, has_more=True),
        _page([GUEST], page=1, has_more=False),
        _page([SHARED], page=7),
        _err(404, "key_not_found"),
    ])
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        rows = [r async for r in client.account.iter_history()]
        assert [r.opened_by.is_you for r in rows] == [True, False]
        assert rows[1].guest_link is not None
        assert dict(route.calls[1].request.url.params) == {"page": "1", **WINDOW}

        page = await client.account.history(date_from="2026-10-01",
                                            date_to="2026-10-02",
                                            key_id="K9", page=7)
        assert dict(route.calls[2].request.url.params) == {
            "from": "2026-10-01", "to": "2026-10-02", "key_id": "K9", "page": "7"}
        assert page.opens[0].opened_by.name == "Sam Lee"

        with pytest.raises(NotFoundError):
            await client.account.history(key_id="not-mine")


@pytest.mark.asyncio
@respx.mock
async def test_async_iter_history_stops_on_an_empty_page(test_key):
    route = respx.get(HISTORY).mock(side_effect=[
        _page([], has_more=True),
        _page([], has_more=True),
    ])
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        rows = [r async for r in client.account.iter_history()]
    assert rows == []
    assert route.call_count == 1
