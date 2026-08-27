"""Coverage for the endpoints added in wave 3: guest links (including the list
read that returns working gate URLs), directory access codes, GuestView Entry
with its replace-the-whole-set eligible-latch write and its schedule windows,
and GuestView short codes.

Wire contracts are asserted once against the sync client (both clients consume
the same endpoint registry); the async client is exercised for the shapes where
a wrapper could realistically drift, and every new method is asserted present on
both at the bottom.

Two of these tests exist to keep a *docstring* honest rather than to check a
wrapper: `test_guest_link_list_returns_working_gate_links` fails the moment the
API stops listing `token`/`url`, which is when the secrecy warning would become
wrong, and `test_set_guest_view_entry_latches_replaces_the_whole_set` pins the
destructive-by-omission semantics the warning is about.
"""

import json as _json

import httpx
import pytest
import respx

from nimbio_community_api import (
    AsyncNimbioClient,
    ConflictError,
    NimbioClient,
    NotFoundError,
    PermissionDeniedError,
    models,
)

PROD = "https://api.nimbio.com"


@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


def _body(route):
    return _json.loads(route.calls.last.request.content)


def _params(route):
    return dict(route.calls.last.request.url.params)


# -- fixtures ----------------------------------------------------------------- #

_GUEST_LINK = {
    "community_id": 2585,
    "created_at": "2026-08-18T09:15:00+00:00",
    "created_by_account_id": "a1b2",
    "created_by_cm": True,
    "created_by_name": "Dana Lee",
    "expires_at": "2026-08-25T11:00:00+00:00",
    "guest_link_id": 4417,
    "key_id": "k1a2",
    "key_name": "Main Entrance",
    "last_used_at": "2026-08-19T14:02:11+00:00",
    "latches": [{"latch_id": "l1", "latch_name": "Main Entrance"}],
    "link_type": "limited_use",
    "max_uses": 6,
    "notify_on_use": False,
    "revoked": False,
    "state": "active",
    "subtitle": "Front gate access",
    "title": "Booking 8841 — Unit 4",
    "token": "Q1w2E3r4T5y6U7i8O9p0aA",
    "total_opens": 2,
    "url": "https://d.nimbio.com/l/Q1w2E3r4T5y6U7i8O9p0aA",
    "uses_consumed": 2,
}

_ACCESS_CODE = {
    "account_id": "a1",
    "api_managed": True,
    "code_length": 6,
    "code_masked": "******",
    "created_at": "2026-08-18T16:12:00+00:00",
    "directory_access_code_id": 412,
    "disabled": False,
    "expires_at": "2026-08-19T17:00:00+00:00",
    "has_schedule": False,
    "latch_ids": ["l1"],
    "latches": [{"id": "l1", "name": "Service Entrance"}],
    "owner_name": "Front Desk",
}

_GUEST_VIEW_ENTRY = {
    "allowed": True,
    "directory_viewing_enabled": True,
    "eligible_latches": [
        {"latch_id": "3f2a", "latch_name": "Front Gate"},
        {"latch_id": "9b7c", "latch_name": "Pool Gate"},
    ],
    "schedule": [
        {"days_of_the_week": "MTWHF", "end_time": "17:00", "latch_id": "3f2a",
         "latch_name": "Front Gate", "schedule_id": 41, "start_time": "09:00"},
        {"days_of_the_week": "SU", "end_time": "06:00", "latch_id": "9b7c",
         "latch_name": "Pool Gate", "schedule_id": 42, "start_time": "22:00"},
    ],
    "schedule_timezone": "latch_local",
}

_SHORT_CODE = {
    "community_id": 2585,
    "created_at": "2026-08-18T17:04:11+00:00",
    "disabled": False,
    "last_updated_datetime": "2026-08-18T17:04:11+00:00",
    "latch_id": "l1",
    "latch_name": "Main Entrance",
    "require_security_code": False,
    "short_code": "Kp7Rx2Q",
}


# -- guest links -------------------------------------------------------------- #

@respx.mock
def test_guest_link_list_returns_working_gate_links(client):
    """The whole reason the list docstring carries a password-grade warning.

    `token` and `url` come back from the LIST, not only from create, so a
    logged listing is a set of live gate links. If this ever stops being true
    the warning becomes wrong and should be revisited — hence the assertion.
    """
    respx.get(f"{PROD}/v1/community/guest-links").mock(
        return_value=httpx.Response(200, json={"result": "ok",
                                               "guest_links": [_GUEST_LINK]}))

    links = client.community.guest_links()
    assert [x.guest_link_id for x in links] == [4417]
    assert links[0].token == "Q1w2E3r4T5y6U7i8O9p0aA"
    assert links[0].url == "https://d.nimbio.com/l/Q1w2E3r4T5y6U7i8O9p0aA"


@respx.mock
def test_guest_link_repr_does_not_leak_the_token_or_url(client):
    """A link printed at a prompt or interpolated into a log line must not put
    a working gate in the scrollback. The attributes still read normally."""
    respx.get(f"{PROD}/v1/community/guest-links").mock(
        return_value=httpx.Response(200, json={"result": "ok",
                                               "guest_links": [_GUEST_LINK]}))

    link = client.community.guest_links()[0]
    text = repr(link)
    assert "Q1w2E3r4T5y6U7i8O9p0aA" not in text
    assert "d.nimbio.com" not in text
    # The identifying, non-secret fields are still there to debug with.
    assert "4417" in text
    assert "limited_use" in text


@respx.mock
def test_guest_links_sends_include_inactive_explicitly(client):
    route = respx.get(f"{PROD}/v1/community/guest-links").mock(
        return_value=httpx.Response(200, json={"result": "ok",
                                               "guest_links": []}))

    client.community.guest_links()
    assert _params(route) == {"include_inactive": "true"}

    client.community.guest_links(include_inactive=False)
    assert _params(route) == {"include_inactive": "false"}


@respx.mock
def test_guest_link_state_and_use_accounting(client):
    respx.get(f"{PROD}/v1/community/guest-links").mock(
        return_value=httpx.Response(200, json={"result": "ok", "guest_links": [
            _GUEST_LINK,
            {**_GUEST_LINK, "guest_link_id": 4418, "state": "spent",
             "uses_consumed": 6},
            {**_GUEST_LINK, "guest_link_id": 4419, "state": "upcoming",
             "link_type": "event", "max_uses": None},
        ]}))

    live, spent, upcoming = client.community.guest_links()
    assert live.active is True
    assert live.uses_remaining == 4
    assert live.latch_ids == ["l1"]

    # Not revoked, not expired — and still unusable. Only `state` knows.
    assert spent.revoked is False
    assert spent.active is False
    assert spent.uses_remaining == 0

    # An event link has unlimited opens inside its window.
    assert upcoming.active is False
    assert upcoming.uses_remaining is None


@respx.mock
def test_create_limited_use_guest_link(client):
    route = respx.post(f"{PROD}/v1/community/guest-links").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "b1c2", "guest_link": _GUEST_LINK}))

    link = client.community.create_guest_link(
        "limited_use", ["l1"], key_id="k1a2", max_uses=6,
        title="Booking 8841 — Unit 4", subtitle="Front gate access",
        expires_at="2026-08-25T11:00:00Z", notify_on_use=False)

    assert _body(route) == {
        "link_type": "limited_use", "latch_ids": ["l1"], "key_id": "k1a2",
        "title": "Booking 8841 — Unit 4", "subtitle": "Front gate access",
        "max_uses": 6, "expires_at": "2026-08-25T11:00:00Z",
        "notify_on_use": False,
    }
    assert link.url == "https://d.nimbio.com/l/Q1w2E3r4T5y6U7i8O9p0aA"
    assert link.request_id == "b1c2"


@respx.mock
def test_create_event_guest_link_sends_only_what_you_passed(client):
    """Optional fields are omitted rather than sent as null, so an event link's
    body never carries the limited-use knobs."""
    route = respx.post(f"{PROD}/v1/community/guest-links").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "guest_link": {**_GUEST_LINK, "link_type": "event",
                           "max_uses": None,
                           "window_start": "2026-08-20T18:00:00+00:00",
                           "window_end": "2026-08-20T23:00:00+00:00"}}))

    link = client.community.create_guest_link(
        "event", ["l1"], title="Rooftop party",
        window_start="2026-08-20 18:00", window_end="2026-08-20 23:00",
        extra_info="Buzz 4B")

    assert _body(route) == {
        "link_type": "event", "latch_ids": ["l1"], "title": "Rooftop party",
        "extra_info": "Buzz 4B",
        "window_start": "2026-08-20 18:00", "window_end": "2026-08-20 23:00",
    }
    assert link.window_end == "2026-08-20T23:00:00+00:00"
    assert link.uses_remaining is None


@respx.mock
def test_create_guest_link_conflict_raises(client):
    respx.post(f"{PROD}/v1/community/guest-links").mock(
        return_value=httpx.Response(409, json={"error": {
            "code": "window_too_long",
            "message": "Event window exceeds the community maximum of 8 hours",
        }}))

    with pytest.raises(ConflictError) as e:
        client.community.create_guest_link(
            "event", ["l1"], title="All weekend",
            window_start="2026-08-20 09:00", window_end="2026-08-22 09:00")
    assert e.value.code == "window_too_long"


@respx.mock
def test_revoke_guest_link_is_terminal(client):
    route = respx.delete(f"{PROD}/v1/community/guest-links/4417").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "b1c2",
            "guest_link": {**_GUEST_LINK, "revoked": True, "state": "revoked",
                           "revoked_datetime": "2026-08-20T10:00:00+00:00"}}))

    link = client.community.revoke_guest_link(4417)
    assert route.calls.last.request.url.path.endswith("/guest-links/4417")
    assert link.revoked is True
    assert link.state == "revoked"
    assert link.active is False
    assert link.revoked_datetime == "2026-08-20T10:00:00+00:00"


@respx.mock
def test_revoking_another_communitys_link_is_a_404(client):
    respx.delete(f"{PROD}/v1/community/guest-links/9999").mock(
        return_value=httpx.Response(404, json={"error": {
            "code": "guest_link_not_found", "message": "Not found"}}))

    with pytest.raises(NotFoundError):
        client.community.revoke_guest_link(9999)


@respx.mock
def test_guest_link_logs_page_and_filter(client):
    route = respx.get(f"{PROD}/v1/community/guest-links/logs").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "limit": 50, "offset": 0, "logs": [{
                "client_ip": "203.0.113.7",
                "guest_link_id": 4417,
                "guest_link_log_id": 91002,
                "latch_id": "l1",
                "latch_name": "Main Entrance",
                "link_title": "Booking 8841 — Unit 4",
                "link_type": "limited_use",
                "log_datetime": "2026-08-19T14:02:11+00:00",
                "result": "opened",
                "use_number": 2,
                "user_agent": "Mozilla/5.0 (iPhone)",
            }]}))

    page = client.community.guest_link_logs(guest_link_id=4417, limit=25,
                                            offset=50)
    assert _params(route) == {"guest_link_id": "4417", "limit": "25",
                              "offset": "50"}
    assert len(page) == 1
    row = list(page)[0]
    assert row.opened is True
    assert row.client_ip == "203.0.113.7"
    assert row.user_agent.startswith("Mozilla/5.0")

    client.community.guest_link_logs()
    assert _params(route) == {"limit": "50", "offset": "0"}


@respx.mock
def test_guest_link_latch_exclusions_absence_is_permission(client):
    respx.get(f"{PROD}/v1/community/guest-links/latch-exclusions").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "excluded_latch_ids": {"event": ["l9"], "limited_use": []}}))

    ex = client.community.guest_link_latch_exclusions()
    assert ex.excluded_for("event") == ["l9"]
    assert ex.excluded_for("limited_use") == []
    assert ex.is_excluded("event", "l9") is True
    # Per link type: barred from event links, fine for limited-use ones.
    assert ex.is_excluded("limited_use", "l9") is False
    # A link type the server never mentioned means nothing is excluded.
    assert ex.excluded_for("some_future_type") == []
    assert ex.is_excluded("some_future_type", "l9") is False


# -- directory access codes --------------------------------------------------- #

@respx.mock
def test_access_codes_never_returns_the_pin(client):
    respx.get(f"{PROD}/v1/community/access-codes").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "feature_enabled": True,
            "access_codes": [_ACCESS_CODE,
                             {**_ACCESS_CODE, "directory_access_code_id": 413,
                              "api_managed": False, "owner_name": "Unit 4B"}]}))

    codes = client.community.access_codes()
    assert codes.feature_enabled is True
    assert len(codes) == 2
    assert [c.directory_access_code_id for c in codes] == [412, 413]
    assert codes.access_codes[0].code_masked == "******"
    assert codes.access_codes[0].code_length == 6
    assert not hasattr(codes.access_codes[0], "code")
    # The latch rows here use id/name rather than latch_id/latch_name.
    assert codes.access_codes[0].latches[0].latch_id == "l1"
    assert codes.access_codes[0].latches[0].latch_name == "Service Entrance"
    # Only the api_managed ones can be edited or deleted through this API.
    assert [c.directory_access_code_id for c in codes.api_managed] == [412]


@respx.mock
def test_create_access_code_returns_the_pin_once(client):
    route = respx.post(f"{PROD}/v1/community/access-codes").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "b1c2", "access_code": {
                "account_id": "a1", "code": "481502",
                "code_normalized": "481502",
                "directory_access_code_id": 412, "key_id": "k1",
                "latch_ids": ["l1"]}}))

    created = client.community.create_access_code(
        "481502", ["l1"], expires_in_hours=24,
        temporal={"days_of_the_week": "MTWHF", "start": "09:00",
                  "end": "17:00"})

    assert _body(route) == {
        "code": "481502", "latch_ids": ["l1"], "expires_in_hours": 24,
        "temporal": {"days_of_the_week": "MTWHF", "start": "09:00",
                     "end": "17:00"},
    }
    assert created.code == "481502"
    assert created.directory_access_code_id == 412
    # The one response that carries a live PIN must not print it.
    assert "481502" not in repr(created)


@respx.mock
def test_update_access_code_sends_only_what_you_passed(client):
    route = respx.patch(f"{PROD}/v1/community/access-codes/412").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "b1c2",
            "access_code": {"directory_access_code_id": 412,
                            "disabled": True}}))

    updated = client.community.update_access_code(412, disabled=True)
    assert _body(route) == {"disabled": True}
    assert updated.directory_access_code_id == 412
    assert updated.disabled is True

    client.community.update_access_code(412, latch_ids=["l1", "l2"],
                                        expires_in_days=7)
    assert _body(route) == {"latch_ids": ["l1", "l2"], "expires_in_days": 7}

    # The cutoff is recomputed from *now*, so re-sending one extends the code
    # rather than confirming the old value; the weekly window replaces.
    client.community.update_access_code(
        412, expires_in_hours=48,
        temporal={"days_of_the_week": "SU", "start": "10:00", "end": "14:00"})
    assert _body(route) == {
        "expires_in_hours": 48,
        "temporal": {"days_of_the_week": "SU", "start": "10:00",
                     "end": "14:00"},
    }


@respx.mock
def test_update_access_code_a_resident_made_is_a_404(client):
    respx.patch(f"{PROD}/v1/community/access-codes/413").mock(
        return_value=httpx.Response(404, json={"error": {
            "code": "access_code_not_found", "message": "Not found"}}))

    with pytest.raises(NotFoundError):
        client.community.update_access_code(413, disabled=True)


@respx.mock
def test_delete_access_code(client):
    route = respx.delete(f"{PROD}/v1/community/access-codes/412").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "b1c2",
            "directory_access_code_id": 412}))

    deleted = client.community.delete_access_code(412)
    assert route.calls.last.request.url.path.endswith("/access-codes/412")
    assert deleted.directory_access_code_id == 412
    assert deleted.simulated is False


@respx.mock
def test_delete_access_code_test_mode_is_simulated(client):
    respx.delete(f"{PROD}/v1/community/access-codes/412").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "directory_access_code_id": 412}))

    assert client.community.delete_access_code(412).simulated is True


@respx.mock
def test_access_code_eligible_latches_is_the_allowlist(client):
    respx.get(f"{PROD}/v1/community/access-codes/eligible-latches").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "feature_enabled": True,
            "latches": [{"latch_id": "l1", "latch_name": "Service Entrance"}]}))

    eligible = client.community.access_code_eligible_latches()
    assert eligible.feature_enabled is True
    assert len(eligible) == 1
    assert eligible.latch_ids == ["l1"]
    assert [x.latch_name for x in eligible] == ["Service Entrance"]


@respx.mock
def test_access_code_writes_are_403_when_the_feature_is_off(client):
    respx.post(f"{PROD}/v1/community/access-codes").mock(
        return_value=httpx.Response(403, json={"error": {
            "code": "access_codes_disabled",
            "message": "Directory access codes are disabled"}}))

    with pytest.raises(PermissionDeniedError) as e:
        client.community.create_access_code("481502", ["l1"])
    assert e.value.code == "access_codes_disabled"


@respx.mock
def test_access_code_logs_mask_the_entered_digits(client):
    route = respx.get(f"{PROD}/v1/community/access-codes/logs").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "limit": 50, "offset": 0, "logs": [{
                "account_id": "a1",
                "client_ip": "203.0.113.9",
                "code_entered_masked": "****",
                "directory_access_code_id": 412,
                "directory_access_code_log_id": 9001,
                "latch_id": "l1",
                "log_datetime": "2026-08-18T17:04:11+00:00",
                "owner_name": "Front Desk",
                "result": "opened",
            }]}))

    page = client.community.access_code_logs(limit=10, offset=20)
    assert _params(route) == {"limit": "10", "offset": "20"}
    row = list(page)[0]
    assert row.code_entered_masked == "****"
    assert row.opened is True
    assert row.directory_access_code_id == 412
    assert row.client_ip == "203.0.113.9"


# -- GuestView Entry ---------------------------------------------------------- #

@respx.mock
def test_guest_view_entry_read(client):
    respx.get(f"{PROD}/v1/community/guest-view-entry").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "guest_view_entry": _GUEST_VIEW_ENTRY}))

    entry = client.community.guest_view_entry()
    assert entry.allowed is True
    assert entry.directory_viewing_enabled is True
    assert entry.latch_ids == ["3f2a", "9b7c"]
    assert entry.schedule_timezone == "latch_local"
    assert [w.schedule_id for w in entry.schedule_for("3f2a")] == [41]
    # A latch with no windows is guest-accessible at ANY hour, not closed.
    assert entry.schedule_for("never-scheduled") == []
    assert entry.created_schedule_ids == []


@respx.mock
def test_guest_view_entry_window_midnight_rule_matches_quiet_hours(client):
    """Windows here wrap past midnight as ONE window — the quiet-hours rule,
    not the key-schedule / hold-open one that needs two."""
    respx.get(f"{PROD}/v1/community/guest-view-entry").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "guest_view_entry": _GUEST_VIEW_ENTRY}))

    entry = client.community.guest_view_entry()
    weekday, overnight = entry.schedule
    assert weekday.wraps_midnight is False
    assert weekday.all_day is False
    assert overnight.wraps_midnight is True   # 22:00 -> 06:00, one window
    assert overnight.days_of_the_week == "SU"  # S is Saturday, U is Sunday


@respx.mock
def test_set_guest_view_entry_enabled_is_a_setter_not_a_toggle(client):
    route = respx.put(f"{PROD}/v1/community/guest-view-entry").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "b1c2",
            "guest_view_entry": {**_GUEST_VIEW_ENTRY, "allowed": False}}))

    entry = client.community.set_guest_view_entry_enabled(False)
    assert _body(route) == {"allowed": False}
    assert entry.allowed is False
    # Switching off leaves the configuration intact, so switching back on
    # restores it — that is why suspending guest access is safe.
    assert entry.latch_ids == ["3f2a", "9b7c"]
    assert len(entry.schedule) == 2


@respx.mock
def test_set_guest_view_entry_latches_replaces_the_whole_set(client):
    """The destructive-by-omission write, pinned.

    Sending one latch does not ADD it: the omitted latch loses eligibility and
    its schedule windows are deleted with it. The read-modify-write the
    docstring insists on is the second half of this test.
    """
    route = respx.put(
        f"{PROD}/v1/community/guest-view-entry/eligible-latches").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "guest_view_entry": {
                **_GUEST_VIEW_ENTRY,
                "eligible_latches": [{"latch_id": "3f2a",
                                      "latch_name": "Front Gate"}],
                "schedule": [_GUEST_VIEW_ENTRY["schedule"][0]]}}))

    after = client.community.set_guest_view_entry_latches(["3f2a"])
    assert _body(route) == {"latch_ids": ["3f2a"]}
    # The Pool Gate is gone, and so is its overnight window.
    assert after.latch_ids == ["3f2a"]
    assert [w.schedule_id for w in after.schedule] == [41]
    assert after.schedule_for("9b7c") == []

    # The safe idiom: read, modify the list you were given, send it back.
    respx.get(f"{PROD}/v1/community/guest-view-entry").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "guest_view_entry": _GUEST_VIEW_ENTRY}))
    entry = client.community.guest_view_entry()
    client.community.set_guest_view_entry_latches(entry.latch_ids + ["c3d4"])
    assert _body(route) == {"latch_ids": ["3f2a", "9b7c", "c3d4"]}


@respx.mock
def test_set_guest_view_entry_latches_empty_removes_every_gate(client):
    route = respx.put(
        f"{PROD}/v1/community/guest-view-entry/eligible-latches").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "guest_view_entry": {
                **_GUEST_VIEW_ENTRY, "eligible_latches": [], "schedule": []}}))

    after = client.community.set_guest_view_entry_latches([])
    assert _body(route) == {"latch_ids": []}
    assert after.latch_ids == []


@respx.mock
def test_set_guest_view_entry_latches_requires_the_feature_on(client):
    respx.put(f"{PROD}/v1/community/guest-view-entry/eligible-latches").mock(
        return_value=httpx.Response(403, json={"error": {
            "code": "guest_view_entry_disabled",
            "message": "GuestView Entry is disabled"}}))

    with pytest.raises(PermissionDeniedError) as e:
        client.community.set_guest_view_entry_latches(["3f2a"])
    assert e.value.code == "guest_view_entry_disabled"


@respx.mock
def test_guest_view_entry_logs_identify_visitors(client):
    route = respx.get(f"{PROD}/v1/community/guest-view-entry/logs").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "has_more": False, "limit": 50, "offset": 0,
            "logs": [{
                "account_id": "a1b2",
                "client_ip": "203.0.113.9",
                "first_name": "Dana",
                "guest_view_entry_log_id": 918,
                "last_name": "Lee",
                "latch_id": "3f2a",
                "latch_name": "Front Gate",
                "log_datetime": "2026-08-18T17:04:11+00:00",
                "phone": "+15551234567",
                "result": "opened",
            }]}))

    page = client.community.guest_view_entry_logs(success=True, limit=10)
    assert _params(route) == {"limit": "10", "offset": "0", "success": "true"}
    assert page.has_more is False
    row = list(page)[0]
    assert row.opened is True
    assert (row.first_name, row.last_name, row.phone) == (
        "Dana", "Lee", "+15551234567")

    client.community.guest_view_entry_logs(success=False)
    assert _params(route)["success"] == "false"

    # Omitted entirely means everything — not "false".
    client.community.guest_view_entry_logs()
    assert "success" not in _params(route)


@respx.mock
def test_add_guest_view_entry_schedule(client):
    route = respx.post(f"{PROD}/v1/community/guest-view-entry/schedule").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "b1c2",
            "created_schedule_ids": [41, 43],
            "guest_view_entry": _GUEST_VIEW_ENTRY}))

    entry = client.community.add_guest_view_entry_schedule(
        ["3f2a", "9b7c"], "MTWHF", start_time="09:00", end_time="17:00")

    assert _body(route) == {"latch_ids": ["3f2a", "9b7c"],
                            "days_of_the_week": "MTWHF",
                            "start_time": "09:00", "end_time": "17:00"}
    assert entry.created_schedule_ids == [41, 43]
    assert entry.allowed is True


@respx.mock
def test_add_guest_view_entry_schedule_omits_unset_times(client):
    route = respx.post(f"{PROD}/v1/community/guest-view-entry/schedule").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "created_schedule_ids": [44],
            "guest_view_entry": _GUEST_VIEW_ENTRY}))

    client.community.add_guest_view_entry_schedule(["3f2a"], "SU",
                                                   start_time="22:00")
    assert _body(route) == {"latch_ids": ["3f2a"], "days_of_the_week": "SU",
                            "start_time": "22:00"}


@respx.mock
def test_remove_guest_view_entry_schedule_widens_access(client):
    route = respx.delete(
        f"{PROD}/v1/community/guest-view-entry/schedule/42").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "removed_schedule_id": 42,
            "guest_view_entry": {**_GUEST_VIEW_ENTRY,
                                 "schedule": [
                                     _GUEST_VIEW_ENTRY["schedule"][0]]}}))

    entry = client.community.remove_guest_view_entry_schedule(42)
    assert route.calls.last.request.url.path.endswith("/schedule/42")
    assert entry.removed_schedule_id == 42
    # The Pool Gate lost its last window, so it is now open to guests at ANY
    # hour — removing a window widens access.
    assert entry.schedule_for("9b7c") == []
    assert "9b7c" in entry.latch_ids


# -- GuestView short codes ---------------------------------------------------- #

@respx.mock
def test_short_codes_list(client):
    respx.get(f"{PROD}/v1/community/short-codes").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "short_codes": [
                _SHORT_CODE,
                {**_SHORT_CODE, "short_code": "Zz9Qw1E", "latch_id": None,
                 "latch_name": None}]}))

    codes = client.community.short_codes()
    assert [c.short_code for c in codes] == ["Kp7Rx2Q", "Zz9Qw1E"]
    assert codes[0].latch_id == "l1"
    assert codes[0].latch_name == "Main Entrance"
    # None = routes to the directory without preselecting a gate.
    assert codes[1].latch_id is None


@respx.mock
def test_create_short_code_server_generated_and_claimed(client):
    route = respx.post(f"{PROD}/v1/community/short-codes").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "b1c2",
            "short_code": _SHORT_CODE}))

    generated = client.community.create_short_code()
    assert _body(route) == {}
    assert generated.short_code == "Kp7Rx2Q"

    client.community.create_short_code(code="Kp7Rx2Q", latch_id="l1")
    assert _body(route) == {"code": "Kp7Rx2Q", "latch_id": "l1"}


@respx.mock
def test_claiming_a_taken_short_code_is_a_409(client):
    respx.post(f"{PROD}/v1/community/short-codes").mock(
        return_value=httpx.Response(409, json={"error": {
            "code": "short_code_taken",
            "message": "That short code is already in use"}}))

    with pytest.raises(ConflictError) as e:
        client.community.create_short_code(code="kp7rx2q")
    assert e.value.code == "short_code_taken"


@respx.mock
def test_assign_short_code_repoints_it(client):
    route = respx.put(f"{PROD}/v1/community/short-codes/Kp7Rx2Q").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "b1c2",
            "short_code": {**_SHORT_CODE, "latch_id": "l2",
                           "latch_name": "Service Entrance"}}))

    moved = client.community.assign_short_code("Kp7Rx2Q", "l2")
    assert route.calls.last.request.url.path.endswith("/short-codes/Kp7Rx2Q")
    assert _body(route) == {"latch_id": "l2"}
    # Exclusive: l1 has silently lost this code.
    assert moved.latch_id == "l2"
    assert moved.latch_name == "Service Entrance"


@respx.mock
def test_assign_unknown_or_foreign_short_code_is_a_404(client):
    respx.put(f"{PROD}/v1/community/short-codes/someone-elses").mock(
        return_value=httpx.Response(404, json={"error": {
            "code": "short_code_not_found", "message": "Not found"}}))

    with pytest.raises(NotFoundError) as e:
        client.community.assign_short_code("someone-elses", "l2")
    assert e.value.code == "short_code_not_found"


# -- models ------------------------------------------------------------------- #

def test_models_tolerate_an_empty_or_odd_payload():
    """Every wave-3 model is a tolerant dataclass: a missing or wrong-typed
    payload must degrade to empty rather than raise."""
    assert models.GuestLink.from_dict(None).guest_link_id is None
    assert models.GuestLink.from_dict({}).latch_ids == []
    assert models.GuestLinkLogPage.from_dict({}).logs == []
    assert models.GuestLinkLatchExclusions.from_dict(
        {"excluded_latch_ids": "nope"}).by_type == {}
    assert models.AccessCodes.from_dict({}).feature_enabled is False
    assert models.AccessCodeCreated.from_dict({}).code is None
    assert models.AccessCodeDeleted.from_dict({}).simulated is False
    assert models.AccessCodeEligibleLatches.from_dict({}).latch_ids == []
    assert models.AccessCodeLogPage.from_dict({}).logs == []
    assert models.GuestViewEntry.from_dict({}).allowed is False
    assert models.GuestViewEntryLogPage.from_dict({}).has_more is False
    assert models.ShortCode.from_dict({}).short_code is None
    assert models.NamedLatch.from_dict({}).latch_id is None
    w = models.GuestViewEntrySchedule.from_dict({})
    assert w.all_day is True and w.wraps_midnight is False


def test_a_test_key_write_reports_itself_as_simulated():
    """Every wave-3 write is side-effecting — minting a gate link, a PIN, or a
    permission change — so each result has to say when nothing happened."""
    for model in (models.GuestLink, models.AccessCode, models.AccessCodeCreated,
                  models.AccessCodeDeleted, models.GuestViewEntry,
                  models.ShortCode):
        assert model.from_dict({"result": "simulated"}).simulated is True
        assert model.from_dict({"result": "ok"}).simulated is False


def test_guest_link_uses_remaining_never_goes_negative():
    """A link the server reports as over-consumed reads 0, not a negative."""
    link = models.GuestLink.from_dict({"max_uses": 2, "uses_consumed": 5})
    assert link.uses_remaining == 0


def test_short_code_envelope_and_bare_row_both_parse():
    """`short_code` names both the envelope key and a scalar field, so the
    shape has to decide which one is in hand."""
    bare = models.ShortCode.from_dict(_SHORT_CODE)
    enveloped = models.ShortCode.from_dict({"result": "simulated",
                                            "short_code": _SHORT_CODE})
    assert bare.short_code == enveloped.short_code == "Kp7Rx2Q"
    assert bare.simulated is False
    assert enveloped.simulated is True


def test_guest_link_constants_cover_the_states_the_server_reports():
    from nimbio_community_api import GUEST_LINK_STATES, GUEST_LINK_TYPES

    assert set(GUEST_LINK_TYPES) == {"event", "limited_use"}
    assert set(GUEST_LINK_STATES) == {
        "active", "upcoming", "expired", "spent", "revoked", "feature_disabled"}
    # The `active` property must agree with the constant it stands for.
    assert models.GuestLink.from_dict(
        {"state": GUEST_LINK_STATES[0]}).active is True


# -- both clients ------------------------------------------------------------- #

WAVE3_METHODS = (
    "guest_links",
    "create_guest_link",
    "revoke_guest_link",
    "guest_link_logs",
    "guest_link_latch_exclusions",
    "access_codes",
    "create_access_code",
    "update_access_code",
    "delete_access_code",
    "access_code_eligible_latches",
    "access_code_logs",
    "guest_view_entry",
    "set_guest_view_entry_enabled",
    "set_guest_view_entry_latches",
    "guest_view_entry_logs",
    "add_guest_view_entry_schedule",
    "remove_guest_view_entry_schedule",
    "short_codes",
    "create_short_code",
    "assign_short_code",
)


def test_both_clients_expose_every_wave3_method():
    """The two clients must not drift: a method that lands on only one of them
    is a silent gap for half the users."""
    sync_community = NimbioClient("nimbio_test_x").community
    async_community = AsyncNimbioClient("nimbio_test_x").community
    for name in WAVE3_METHODS:
        assert hasattr(sync_community, name), f"sync client missing {name}"
        assert hasattr(async_community, name), f"async client missing {name}"


@respx.mock
async def test_async_guest_links_family(test_key):
    list_route = respx.get(f"{PROD}/v1/community/guest-links").mock(
        return_value=httpx.Response(200, json={"result": "ok",
                                               "guest_links": [_GUEST_LINK]}))
    create_route = respx.post(f"{PROD}/v1/community/guest-links").mock(
        return_value=httpx.Response(200, json={"result": "ok",
                                               "guest_link": _GUEST_LINK}))
    respx.delete(f"{PROD}/v1/community/guest-links/4417").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "guest_link": {**_GUEST_LINK, "revoked": True,
                           "state": "revoked"}}))
    logs_route = respx.get(f"{PROD}/v1/community/guest-links/logs").mock(
        return_value=httpx.Response(200, json={"result": "ok", "limit": 50,
                                               "offset": 0, "logs": []}))
    respx.get(f"{PROD}/v1/community/guest-links/latch-exclusions").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "excluded_latch_ids": {"event": ["l9"], "limited_use": []}}))

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        links = await client.community.guest_links(include_inactive=False)
        assert _params(list_route) == {"include_inactive": "false"}
        # The async list leaks exactly as much as the sync one does.
        assert links[0].token == "Q1w2E3r4T5y6U7i8O9p0aA"

        created = await client.community.create_guest_link(
            "limited_use", ["l1"], max_uses=6)
        assert _body(create_route) == {"link_type": "limited_use",
                                       "latch_ids": ["l1"], "max_uses": 6}
        assert created.url.endswith("Q1w2E3r4T5y6U7i8O9p0aA")

        revoked = await client.community.revoke_guest_link(4417)
        assert revoked.state == "revoked"

        page = await client.community.guest_link_logs(limit=5)
        assert _params(logs_route) == {"limit": "5", "offset": "0"}
        assert len(page) == 0

        ex = await client.community.guest_link_latch_exclusions()
        assert ex.is_excluded("event", "l9") is True


@respx.mock
async def test_async_access_codes_family(test_key):
    respx.get(f"{PROD}/v1/community/access-codes").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "feature_enabled": True,
            "access_codes": [_ACCESS_CODE]}))
    create_route = respx.post(f"{PROD}/v1/community/access-codes").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "access_code": {"code": "481502",
                            "directory_access_code_id": 412,
                            "latch_ids": ["l1"]}}))
    patch_route = respx.patch(f"{PROD}/v1/community/access-codes/412").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "access_code": {"directory_access_code_id": 412,
                            "disabled": True}}))
    respx.delete(f"{PROD}/v1/community/access-codes/412").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "directory_access_code_id": 412}))
    respx.get(f"{PROD}/v1/community/access-codes/eligible-latches").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "feature_enabled": True,
            "latches": [{"latch_id": "l1", "latch_name": "Service"}]}))
    logs_route = respx.get(f"{PROD}/v1/community/access-codes/logs").mock(
        return_value=httpx.Response(200, json={"result": "ok", "limit": 50,
                                               "offset": 0, "logs": []}))

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        codes = await client.community.access_codes()
        assert codes.access_codes[0].code_masked == "******"

        created = await client.community.create_access_code(
            "481502", ["l1"], expires_in_days=7)
        assert _body(create_route) == {"code": "481502", "latch_ids": ["l1"],
                                       "expires_in_days": 7}
        assert created.code == "481502"

        updated = await client.community.update_access_code(412, disabled=True)
        assert _body(patch_route) == {"disabled": True}
        assert updated.disabled is True

        assert (await client.community.delete_access_code(
            412)).directory_access_code_id == 412
        assert (await
                client.community.access_code_eligible_latches()).latch_ids == ["l1"]

        await client.community.access_code_logs(offset=100)
        assert _params(logs_route) == {"limit": "50", "offset": "100"}


@respx.mock
async def test_async_guest_view_entry_and_short_codes(test_key):
    respx.get(f"{PROD}/v1/community/guest-view-entry").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "guest_view_entry": _GUEST_VIEW_ENTRY}))
    enabled_route = respx.put(f"{PROD}/v1/community/guest-view-entry").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "guest_view_entry": {**_GUEST_VIEW_ENTRY, "allowed": False}}))
    latches_route = respx.put(
        f"{PROD}/v1/community/guest-view-entry/eligible-latches").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "guest_view_entry": {
                **_GUEST_VIEW_ENTRY,
                "eligible_latches": [{"latch_id": "3f2a",
                                      "latch_name": "Front Gate"}],
                "schedule": [_GUEST_VIEW_ENTRY["schedule"][0]]}}))
    logs_route = respx.get(f"{PROD}/v1/community/guest-view-entry/logs").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "has_more": True, "limit": 50, "offset": 0,
            "logs": []}))
    schedule_route = respx.post(
        f"{PROD}/v1/community/guest-view-entry/schedule").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "created_schedule_ids": [41],
            "guest_view_entry": _GUEST_VIEW_ENTRY}))
    respx.delete(f"{PROD}/v1/community/guest-view-entry/schedule/42").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "removed_schedule_id": 42,
            "guest_view_entry": _GUEST_VIEW_ENTRY}))
    respx.get(f"{PROD}/v1/community/short-codes").mock(
        return_value=httpx.Response(200, json={"result": "ok",
                                               "short_codes": [_SHORT_CODE]}))
    create_code_route = respx.post(f"{PROD}/v1/community/short-codes").mock(
        return_value=httpx.Response(200, json={"result": "ok",
                                               "short_code": _SHORT_CODE}))
    assign_route = respx.put(f"{PROD}/v1/community/short-codes/Kp7Rx2Q").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "short_code": {**_SHORT_CODE, "latch_id": "l2"}}))

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        entry = await client.community.guest_view_entry()
        assert entry.latch_ids == ["3f2a", "9b7c"]

        off = await client.community.set_guest_view_entry_enabled(False)
        assert _body(enabled_route) == {"allowed": False}
        assert off.allowed is False

        # Read-modify-write: the whole set goes back, not just the new gate.
        narrowed = await client.community.set_guest_view_entry_latches(
            entry.latch_ids)
        assert _body(latches_route) == {"latch_ids": ["3f2a", "9b7c"]}
        assert narrowed.schedule_for("9b7c") == []

        page = await client.community.guest_view_entry_logs(success=True)
        assert _params(logs_route)["success"] == "true"
        assert page.has_more is True

        added = await client.community.add_guest_view_entry_schedule(
            ["3f2a"], "MTWHF", start_time="09:00", end_time="17:00")
        assert _body(schedule_route) == {
            "latch_ids": ["3f2a"], "days_of_the_week": "MTWHF",
            "start_time": "09:00", "end_time": "17:00"}
        assert added.created_schedule_ids == [41]

        removed = await client.community.remove_guest_view_entry_schedule(42)
        assert removed.removed_schedule_id == 42

        assert [c.short_code for c in
                await client.community.short_codes()] == ["Kp7Rx2Q"]

        await client.community.create_short_code(latch_id="l1")
        assert _body(create_code_route) == {"latch_id": "l1"}

        moved = await client.community.assign_short_code("Kp7Rx2Q", "l2")
        assert _body(assign_route) == {"latch_id": "l2"}
        assert moved.latch_id == "l2"
