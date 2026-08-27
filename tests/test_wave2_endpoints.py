"""Coverage for the endpoints added in wave 2: community settings (read +
all-or-nothing patch), the homes/units roster including the resident-detaching
delete, the member move-out date, and the four per-manager member-open
notification endpoints with their quiet-hours windows.

Wire contracts are asserted once against the sync client (both clients consume
the same endpoint registry); the async client is exercised for the shapes where
a wrapper could realistically drift, and every new method is asserted present on
both at the bottom.
"""

import json as _json

import httpx
import pytest
import respx

from nimbio_community_api import (
    APIError,
    AsyncNimbioClient,
    ConflictError,
    NimbioClient,
    NotFoundError,
    PermissionDeniedError,
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


# -- community settings ------------------------------------------------------- #

_SETTINGS = {
    "result": "ok",
    "community_id": 2585,
    "settings": {
        "allow_directory_viewing": True,
        "allow_directory_access_codes": False,
        "is_new_member_request_home_enabled": True,
        "limited_use_links_members_only": False,
        "limited_use_links_require_account": True,
        "event_keys_require_account": False,
        "event_keys_override": "inherit",
        "member_terminology_option_id": None,
        "member_term_custom": "Tenant",
        "member_term_custom_plural": "Tenants",
        "member_icon": "person",
        "home_terminology_option_id": 12,
        "home_term_custom": None,
        "home_term_custom_plural": None,
        "home_icon": None,
    },
    "read_only": {
        "allow_hold_opens": True,
        "is_open_log_history_enabled": False,
        "allow_guest_view_entry": False,
        "event_keys_enabled": True,
        "community_type": 3,
    },
    "terminology": {
        "member": {"singular": "Tenant", "plural": "Tenants", "icon": "person"},
        "home": {"singular": "Suite", "plural": "Suites", "icon": "home"},
    },
    "terminology_options": {
        "member": [{"terminology_option_id": 7, "label_singular": "Resident",
                    "label_plural": "Residents", "icon": "person"}],
        "home": [{"terminology_option_id": 12, "label_singular": "Suite",
                  "label_plural": "Suites", "icon": "home"}],
    },
}


@respx.mock
def test_settings_reads_both_halves_of_the_configuration(client):
    respx.get(f"{PROD}/v1/community/settings").mock(
        return_value=httpx.Response(200, json=_SETTINGS))

    s = client.community.settings()
    assert s.community_id == 2585
    assert s.setting("event_keys_override") == "inherit"
    assert s.setting("member_term_custom") == "Tenant"
    assert s.terminology["home"]["plural"] == "Suites"
    assert s.terminology_options["home"][0]["terminology_option_id"] == 12
    # A read applied nothing, so there is nothing to report as changed.
    assert s.changed == []


@respx.mock
def test_read_only_flags_are_how_you_learn_a_feature_is_off(client):
    """The point of the read: without it the only way to discover a gated
    family is off is to call it and interpret a 403. An unknown flag reads
    False — a server that has never heard of it cannot have it switched on."""
    respx.get(f"{PROD}/v1/community/settings").mock(
        return_value=httpx.Response(200, json=_SETTINGS))

    s = client.community.settings()
    assert s.feature("allow_hold_opens") is True
    assert s.feature("is_open_log_history_enabled") is False
    # The resolved answer for event keys, not the settable override.
    assert s.feature("event_keys_enabled") is True
    assert s.setting("event_keys_override") == "inherit"
    assert s.feature("a_flag_this_release_never_heard_of") is False


@respx.mock
def test_update_settings_sends_only_the_keys_you_pass(client):
    route = respx.patch(f"{PROD}/v1/community/settings").mock(
        return_value=httpx.Response(200, json={
            **_SETTINGS, "changed": ["allow_directory_viewing"],
            "request_id": "r1"}))

    result = client.community.update_settings(
        {"allow_directory_viewing": True})
    assert _body(route) == {"settings": {"allow_directory_viewing": True}}
    # `changed` is what was applied, which is not necessarily what was sent.
    assert result.changed == ["allow_directory_viewing"]
    assert result.request_id == "r1"


@respx.mock
def test_update_settings_rejects_an_unknown_key_and_applies_nothing(client):
    """The patch is validated whole before anything is written, so one bad key
    means the whole batch applies nothing — and an unknown key is rejected by
    name rather than silently dropped."""
    respx.patch(f"{PROD}/v1/community/settings").mock(
        return_value=httpx.Response(422, json={"error": {
            "code": "invalid_setting",
            "message": "Unknown setting 'allow_everything'. Settable: …",
            "request_id": "r1"}}))

    with pytest.raises(APIError) as e:
        client.community.update_settings({
            "allow_directory_viewing": False,   # valid
            "allow_everything": True,           # not a setting
        })
    assert e.value.status_code == 422
    assert e.value.code == "invalid_setting"
    assert "allow_everything" in e.value.message


@respx.mock
def test_update_settings_refuses_a_provisioned_read_only_flag(client):
    """`allow_hold_opens` and friends are Nimbio-side provisioning decisions,
    reported on the read so you can detect them and never set them."""
    respx.patch(f"{PROD}/v1/community/settings").mock(
        return_value=httpx.Response(422, json={"error": {
            "code": "invalid_setting",
            "message": "'allow_hold_opens' is provisioned by Nimbio — "
                       "contact support",
            "request_id": "r1"}}))

    with pytest.raises(APIError) as e:
        client.community.update_settings({"allow_hold_opens": True})
    assert e.value.code == "invalid_setting"


@respx.mock
def test_update_settings_simulates_on_a_test_key(client):
    """A test key validates the whole patch and returns the community's
    UNCHANGED settings, so nothing here reads as applied."""
    respx.patch(f"{PROD}/v1/community/settings").mock(
        return_value=httpx.Response(200, json={
            **_SETTINGS, "result": "simulated", "request_id": "r1"}))

    result = client.community.update_settings({"member_term_custom": "Owner"})
    assert result.simulated is True
    assert result.setting("member_term_custom") == "Tenant"
    assert result.changed == []


# -- homes / units roster ----------------------------------------------------- #

_HOME = {
    "home_id": "h1", "name": None, "address": "12 Elm St, Unit 3",
    "owner_occupied": False, "hidden": False, "home_phone": None,
    "home_email": None, "owner_name": None,
    "created_datetime": "2026-08-18T17:04:11+00:00", "member_count": 2,
}

_RESIDENT = {
    "account_community_id": 4021, "account_id": "a1", "first_name": "Dana",
    "last_name": "Lee", "phone_numbers": ["+1 555 123 4567"],
    "accepted": True, "move_out_date": "2026-12-31",
}


@respx.mock
def test_homes_asks_for_the_whole_roster_by_default(client):
    """include_hidden defaults to true — a roster sync wants every unit, not
    only the ones the portal lists."""
    route = respx.get(f"{PROD}/v1/community/homes").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "homes": [_HOME, {**_HOME, "home_id": "h2",
                                              "hidden": True}]}))

    homes = client.community.homes()
    assert _params(route) == {"include_hidden": "true"}
    assert [h.home_id for h in homes] == ["h1", "h2"]
    assert homes[0].address == "12 Elm St, Unit 3"
    assert homes[0].member_count == 2
    assert homes[1].hidden is True
    # The list read reports counts, not people.
    assert homes[0].members == []


@respx.mock
def test_homes_can_ask_for_the_portal_s_narrower_list(client):
    route = respx.get(f"{PROD}/v1/community/homes").mock(
        return_value=httpx.Response(200, json={"result": "ok", "homes": []}))

    assert client.community.homes(include_hidden=False) == []
    assert _params(route) == {"include_hidden": "false"}


@respx.mock
def test_add_home_returns_the_full_resource(client):
    """The created home comes back whole, so a roster sync can record it
    without a follow-up read."""
    route = respx.post(f"{PROD}/v1/community/homes").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "home": _HOME, "request_id": "r1"}))

    home = client.community.add_home("12 Elm St, Unit 3")
    assert _body(route) == {"home_address": "12 Elm St, Unit 3"}
    assert home.home_id == "h1"
    assert home.created_datetime == "2026-08-18T17:04:11+00:00"
    assert home.request_id == "r1"
    assert home.simulated is False


@respx.mock
def test_add_home_creates_nothing_on_a_test_key(client):
    """A test key validates the address; there is no home, and the model does
    not invent an id for one."""
    respx.post(f"{PROD}/v1/community/homes").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated",
            "would_create": {"address": "12 Elm St, Unit 3"},
            "request_id": "r1"}))

    home = client.community.add_home("12 Elm St, Unit 3")
    assert home.simulated is True
    assert home.home_id is None
    assert home.raw["would_create"]["address"] == "12 Elm St, Unit 3"


@respx.mock
def test_home_lists_the_residents_attached_to_it(client):
    """The single read is the only one carrying people — and it is what tells
    you what remove_home() would detach."""
    respx.get(f"{PROD}/v1/community/homes/h1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "home": {**_HOME, "members": [_RESIDENT]}}))

    home = client.community.home("h1")
    assert home.home_id == "h1"
    assert len(home.members) == 1
    resident = home.members[0]
    assert resident.account_community_id == 4021
    assert resident.first_name == "Dana"
    assert resident.move_out_date == "2026-12-31"
    assert resident.accepted is True


@respx.mock
def test_home_from_another_community_is_a_404(client):
    respx.get(f"{PROD}/v1/community/homes/hX").mock(
        return_value=httpx.Response(404, json={"error": {
            "code": "home_not_found",
            "message": "Home not found for this community"}}))

    with pytest.raises(NotFoundError) as e:
        client.community.home("hX")
    assert e.value.code == "home_not_found"


@respx.mock
def test_update_home_sends_only_the_fields_you_named(client):
    route = respx.patch(f"{PROD}/v1/community/homes/h1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "home": {**_HOME, "owner_occupied": True},
            "request_id": "r1"}))

    home = client.community.update_home("h1", owner_occupied=True)
    assert _body(route) == {"owner_occupied": True}
    assert home.owner_occupied is True

    # Correcting an address leaves the flags alone rather than resetting them.
    client.community.update_home("h1", home_address="12 Elm St, Unit 3A")
    assert _body(route) == {"home_address": "12 Elm St, Unit 3A"}


@respx.mock
def test_update_home_hidden_is_a_setter_not_a_toggle(client):
    """Sending hidden=True twice leaves the home hidden, so a retry is safe —
    which is the whole reason this is false/true rather than the portal's
    one-way hide."""
    route = respx.patch(f"{PROD}/v1/community/homes/h1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "home": {**_HOME, "hidden": True}}))

    assert client.community.update_home("h1", hidden=True).hidden is True
    assert _body(route) == {"hidden": True}
    assert client.community.update_home("h1", hidden=True).hidden is True
    assert _body(route) == {"hidden": True}

    # False is a real value, not "unset" — it must survive to the wire, or
    # un-hiding would silently do nothing.
    client.community.update_home("h1", hidden=False, owner_occupied=False)
    assert _body(route) == {"owner_occupied": False, "hidden": False}
    assert route.call_count == 3


@respx.mock
def test_update_home_refuses_to_hide_an_occupied_unit(client):
    respx.patch(f"{PROD}/v1/community/homes/h1").mock(
        return_value=httpx.Response(409, json={"error": {
            "code": "home_occupied",
            "message": "Home still has residents attached"}}))

    with pytest.raises(ConflictError) as e:
        client.community.update_home("h1", hidden=True)
    assert e.value.code == "home_occupied"


@respx.mock
def test_remove_home_reports_how_many_residents_it_detached(client):
    """The destructive call in this wave: the residents stay members and keep
    their keys, but lose their unit, and nothing restores it. The count is the
    only record of what happened."""
    respx.delete(f"{PROD}/v1/community/homes/h1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "home_id": "h1", "deleted": True,
            "detached_member_count": 2, "request_id": "r1"}))

    removed = client.community.remove_home("h1")
    assert removed.deleted is True
    assert removed.detached_member_count == 2
    assert removed.home_id == "h1"
    assert removed.simulated is False


@respx.mock
def test_remove_home_on_a_test_key_reports_the_blast_radius_it_avoided(client):
    """A test key answers with the count it WOULD have detached and deletes
    nothing — so `deleted` must not read True."""
    respx.delete(f"{PROD}/v1/community/homes/h1").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "home_id": "h1",
            "would_detach_member_count": 2, "request_id": "r1"}))

    removed = client.community.remove_home("h1")
    assert removed.simulated is True
    assert removed.deleted is False
    assert removed.detached_member_count == 2


@respx.mock
def test_set_move_out_date_records_a_date(client):
    route = respx.put(f"{PROD}/v1/community/members/4021/move-out-date").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "account_community_id": 4021,
            "move_out_date": "2026-12-31", "request_id": "r1"}))

    result = client.community.set_move_out_date(4021, "2026-12-31")
    assert _body(route) == {"move_out_date": "2026-12-31"}
    assert result.move_out_date == "2026-12-31"
    assert result.account_community_id == 4021


@respx.mock
def test_set_move_out_date_sends_null_to_clear_rather_than_omitting_it(client):
    """An absent field is a 422 on this endpoint, so clearing has to send an
    explicit null — omitting it would be an error, not a no-op."""
    route = respx.put(f"{PROD}/v1/community/members/4021/move-out-date").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "account_community_id": 4021,
            "move_out_date": None}))

    result = client.community.set_move_out_date(4021, None)
    assert _body(route) == {"move_out_date": None}
    assert result.move_out_date is None


@respx.mock
def test_set_move_out_date_simulates_on_a_test_key(client):
    """A test key validates the date and stores nothing, echoing the value it
    would have written under `would_set`."""
    respx.put(f"{PROD}/v1/community/members/4021/move-out-date").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "account_community_id": 4021,
            "would_set": "2026-12-31", "request_id": "r1"}))

    result = client.community.set_move_out_date(4021, "2026-12-31")
    assert result.simulated is True
    assert result.move_out_date == "2026-12-31"


@respx.mock
def test_set_move_out_date_for_another_community_s_member_is_a_404(client):
    respx.put(f"{PROD}/v1/community/members/9999/move-out-date").mock(
        return_value=httpx.Response(404, json={"error": {
            "code": "member_not_found",
            "message": "Member not found in this community"}}))

    with pytest.raises(NotFoundError):
        client.community.set_move_out_date(9999, "2026-12-31")


# -- my member-open notification settings ------------------------------------- #

_QUIET = {"quiet_hours_id": 41, "days_of_the_week": "MTWHF",
          "start_time": "22:00", "end_time": "06:00"}

_NOTIFICATIONS = {"result": "ok", "enabled": True, "feature_available": True,
                  "quiet_hours": [_QUIET], "request_id": "r1"}


@respx.mock
def test_my_notification_settings_belong_to_the_key_s_owner(client):
    """Per manager, not per community: this reads the settings of whoever owns
    the key, and another manager of the same community has their own."""
    respx.get(f"{PROD}/v1/community/my-notification-settings").mock(
        return_value=httpx.Response(200, json=_NOTIFICATIONS))

    settings = client.community.my_notification_settings()
    assert settings.enabled is True
    assert settings.feature_available is True
    assert len(settings.quiet_hours) == 1
    assert settings.quiet_hours[0].quiet_hours_id == 41
    assert settings.quiet_hours[0].days_of_the_week == "MTWHF"


@respx.mock
def test_feature_available_false_is_visible_before_a_write_403s(client):
    respx.get(f"{PROD}/v1/community/my-notification-settings").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "enabled": False, "feature_available": False,
            "quiet_hours": []}))

    settings = client.community.my_notification_settings()
    assert settings.feature_available is False
    assert settings.enabled is False


@respx.mock
def test_set_my_notifications_enabled_returns_the_whole_object(client):
    """All four of these return the full settings object, so nothing needs a
    follow-up GET."""
    route = respx.put(f"{PROD}/v1/community/my-notification-settings").mock(
        return_value=httpx.Response(200, json=_NOTIFICATIONS))

    settings = client.community.set_my_notifications_enabled(True)
    assert _body(route) == {"enabled": True}
    assert settings.enabled is True
    assert len(settings.quiet_hours) == 1


@respx.mock
def test_notification_writes_403_when_the_community_disallows_the_feature(
        client):
    respx.put(f"{PROD}/v1/community/my-notification-settings").mock(
        return_value=httpx.Response(403, json={"error": {
            "code": "open_notifications_disabled",
            "message": "Member-open notifications are disabled for this "
                       "community"}}))

    with pytest.raises(PermissionDeniedError) as e:
        client.community.set_my_notifications_enabled(True)
    assert e.value.code == "open_notifications_disabled"


@respx.mock
def test_quiet_hours_window_wraps_past_midnight_as_one_window(client):
    """THE trap of this wave: a key schedule and a recurring hold open must be
    split at midnight, and a quiet-hours window must NOT be. 22:00-06:00 is one
    window here; sending it as two would be wrong, not merely verbose."""
    route = respx.post(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours").mock(
        return_value=httpx.Response(200, json=_NOTIFICATIONS))

    settings = client.community.add_quiet_hours(
        "MTWHF", start_time="22:00", end_time="06:00")
    assert _body(route) == {"days_of_the_week": "MTWHF",
                            "start_time": "22:00", "end_time": "06:00"}
    window = settings.quiet_hours[0]
    assert window.wraps_midnight is True
    assert window.all_day is False


@respx.mock
def test_a_daytime_quiet_hours_window_does_not_read_as_wrapping(client):
    respx.post(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours").mock(
        return_value=httpx.Response(200, json={
            **_NOTIFICATIONS,
            "quiet_hours": [{**_QUIET, "start_time": "09:00",
                             "end_time": "17:00"}]}))

    window = client.community.add_quiet_hours(
        "MTWHF", start_time="09:00", end_time="17:00").quiet_hours[0]
    assert window.wraps_midnight is False


@respx.mock
def test_add_quiet_hours_omits_both_times_for_an_all_day_window(client):
    """All day on the named days is expressed by omission, not by sending
    nulls."""
    route = respx.post(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours").mock(
        return_value=httpx.Response(200, json={
            **_NOTIFICATIONS,
            "quiet_hours": [{"quiet_hours_id": 42, "days_of_the_week": "SU",
                             "start_time": None, "end_time": None}]}))

    settings = client.community.add_quiet_hours("SU")
    assert _body(route) == {"days_of_the_week": "SU"}
    window = settings.quiet_hours[0]
    assert window.all_day is True
    assert window.wraps_midnight is False


@respx.mock
def test_quiet_hours_does_not_accept_the_hold_open_24_00_idiom(client):
    """`"24:00"` is a key-schedule/hold-open sentinel, needed there only
    because those windows cannot wrap. Here it is refused — and a caller who
    carried it across gets an error rather than a window that never fires."""
    respx.post(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours").mock(
        return_value=httpx.Response(422, json={"error": {
            "code": "invalid_time",
            "message": "end_time must be HH:MM between 00:00 and 23:59"}}))

    with pytest.raises(APIError) as e:
        client.community.add_quiet_hours(
            "MTWHF", start_time="22:00", end_time="24:00")
    assert e.value.status_code == 422
    assert e.value.code == "invalid_time"


@respx.mock
def test_a_zero_length_quiet_hours_window_is_refused(client):
    """start == end would suppress nothing, so the server refuses it rather
    than saving a window that silently does nothing."""
    respx.post(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours").mock(
        return_value=httpx.Response(422, json={"error": {
            "code": "invalid_time",
            "message": "start_time and end_time must differ"}}))

    with pytest.raises(APIError) as e:
        client.community.add_quiet_hours(
            "MTWHF", start_time="22:00", end_time="22:00")
    assert e.value.code == "invalid_time"


@respx.mock
def test_bad_day_letters_are_refused(client):
    respx.post(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours").mock(
        return_value=httpx.Response(422, json={"error": {
            "code": "invalid_days",
            "message": "Invalid day 'X' in days_of_the_week"}}))

    with pytest.raises(APIError) as e:
        client.community.add_quiet_hours("MTWX")
    assert e.value.code == "invalid_days"


@respx.mock
def test_quiet_hours_are_additive_and_removed_one_at_a_time(client):
    """Adding appends; replacing a schedule means deleting what you no longer
    want. Both calls answer with the whole list, so the result is the new
    state."""
    respx.post(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours").mock(
        return_value=httpx.Response(200, json={
            **_NOTIFICATIONS,
            "quiet_hours": [_QUIET, {**_QUIET, "quiet_hours_id": 42,
                                     "days_of_the_week": "SU"}]}))
    respx.delete(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours/41").mock(
        return_value=httpx.Response(200, json={
            **_NOTIFICATIONS,
            "quiet_hours": [{**_QUIET, "quiet_hours_id": 42,
                             "days_of_the_week": "SU"}]}))

    added = client.community.add_quiet_hours("SU")
    assert [w.quiet_hours_id for w in added.quiet_hours] == [41, 42]

    remaining = client.community.remove_quiet_hours(41)
    assert [w.quiet_hours_id for w in remaining.quiet_hours] == [42]


@respx.mock
def test_removing_another_manager_s_window_is_a_404_that_deletes_nothing(
        client):
    """Including another manager of the same community — the API deliberately
    does not distinguish "not yours" from "does not exist"."""
    respx.delete(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours/99").mock(
        return_value=httpx.Response(404, json={"error": {
            "code": "quiet_hours_not_found",
            "message": "Quiet-hours window not found for this community "
                       "manager"}}))

    with pytest.raises(NotFoundError) as e:
        client.community.remove_quiet_hours(99)
    assert e.value.code == "quiet_hours_not_found"


@respx.mock
def test_notification_writes_simulate_on_a_test_key(client):
    """Test keys validate and scope-check every one of the three writes, and
    save nothing."""
    respx.put(f"{PROD}/v1/community/my-notification-settings").mock(
        return_value=httpx.Response(200, json={
            **_NOTIFICATIONS, "result": "simulated"}))
    respx.post(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours").mock(
        return_value=httpx.Response(200, json={
            **_NOTIFICATIONS, "result": "simulated"}))
    respx.delete(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours/41").mock(
        return_value=httpx.Response(200, json={
            **_NOTIFICATIONS, "result": "simulated"}))

    assert client.community.set_my_notifications_enabled(
        False).simulated is True
    assert client.community.add_quiet_hours("SU").simulated is True
    # Nothing was deleted, and the window is still in the list it returns.
    removed = client.community.remove_quiet_hours(41)
    assert removed.simulated is True
    assert [w.quiet_hours_id for w in removed.quiet_hours] == [41]


@respx.mock
def test_a_string_quiet_hours_id_is_url_encoded(client):
    """The server types the path parameter as a string; ids arrive as integers
    today, but either must address the same window."""
    route = respx.delete(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours/41").mock(
        return_value=httpx.Response(200, json=_NOTIFICATIONS))

    client.community.remove_quiet_hours("41")
    assert route.calls.last.request.url.path.endswith("/quiet-hours/41")


# -- both clients ------------------------------------------------------------- #

WAVE2_METHODS = (
    "settings",
    "update_settings",
    "homes",
    "add_home",
    "home",
    "update_home",
    "remove_home",
    "set_move_out_date",
    "my_notification_settings",
    "set_my_notifications_enabled",
    "add_quiet_hours",
    "remove_quiet_hours",
)


def test_both_clients_expose_every_wave2_method():
    """The two clients must not drift: a method that lands on only one of them
    is a silent gap for half the users."""
    sync_community = NimbioClient("nimbio_test_x").community
    async_community = AsyncNimbioClient("nimbio_test_x").community
    for name in WAVE2_METHODS:
        assert hasattr(sync_community, name), f"sync client missing {name}"
        assert hasattr(async_community, name), f"async client missing {name}"


@respx.mock
async def test_async_settings_read_and_patch(test_key):
    respx.get(f"{PROD}/v1/community/settings").mock(
        return_value=httpx.Response(200, json=_SETTINGS))
    route = respx.patch(f"{PROD}/v1/community/settings").mock(
        return_value=httpx.Response(200, json={
            **_SETTINGS, "changed": ["member_term_custom"]}))

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        s = await client.community.settings()
        assert s.feature("allow_hold_opens") is True
        assert s.feature("is_open_log_history_enabled") is False

        patched = await client.community.update_settings(
            {"member_term_custom": "Owner"})
        assert _body(route) == {"settings": {"member_term_custom": "Owner"}}
        assert patched.changed == ["member_term_custom"]


@respx.mock
async def test_async_homes_family(test_key):
    homes_route = respx.get(f"{PROD}/v1/community/homes").mock(
        return_value=httpx.Response(200, json={"result": "ok",
                                               "homes": [_HOME]}))
    respx.post(f"{PROD}/v1/community/homes").mock(
        return_value=httpx.Response(200, json={"result": "ok", "home": _HOME}))
    respx.get(f"{PROD}/v1/community/homes/h1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "home": {**_HOME, "members": [_RESIDENT]}}))
    patch_route = respx.patch(f"{PROD}/v1/community/homes/h1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "home": {**_HOME, "hidden": True}}))
    respx.delete(f"{PROD}/v1/community/homes/h1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "home_id": "h1", "deleted": True,
            "detached_member_count": 2}))

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        assert [h.home_id for h in
                await client.community.homes(include_hidden=False)] == ["h1"]
        assert _params(homes_route) == {"include_hidden": "false"}

        assert (await client.community.add_home("12 Elm St")).home_id == "h1"
        assert len((await client.community.home("h1")).members) == 1

        assert (await client.community.update_home(
            "h1", hidden=True)).hidden is True
        assert _body(patch_route) == {"hidden": True}

        removed = await client.community.remove_home("h1")
        assert removed.detached_member_count == 2


@respx.mock
async def test_async_move_out_date_and_notifications(test_key):
    move_out = respx.put(
        f"{PROD}/v1/community/members/4021/move-out-date").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "account_community_id": 4021,
            "move_out_date": None}))
    respx.get(f"{PROD}/v1/community/my-notification-settings").mock(
        return_value=httpx.Response(200, json=_NOTIFICATIONS))
    enabled_route = respx.put(
        f"{PROD}/v1/community/my-notification-settings").mock(
        return_value=httpx.Response(200, json={
            **_NOTIFICATIONS, "enabled": False}))
    quiet_route = respx.post(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours").mock(
        return_value=httpx.Response(200, json=_NOTIFICATIONS))
    respx.delete(
        f"{PROD}/v1/community/my-notification-settings/quiet-hours/41").mock(
        return_value=httpx.Response(200, json={
            **_NOTIFICATIONS, "quiet_hours": []}))

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        cleared = await client.community.set_move_out_date(4021, None)
        assert _body(move_out) == {"move_out_date": None}
        assert cleared.move_out_date is None

        assert (await
                client.community.my_notification_settings()).enabled is True

        off = await client.community.set_my_notifications_enabled(False)
        assert _body(enabled_route) == {"enabled": False}
        assert off.enabled is False

        added = await client.community.add_quiet_hours(
            "MTWHF", start_time="22:00", end_time="06:00")
        assert _body(quiet_route) == {"days_of_the_week": "MTWHF",
                                      "start_time": "22:00",
                                      "end_time": "06:00"}
        assert added.quiet_hours[0].wraps_midnight is True

        emptied = await client.community.remove_quiet_hours(41)
        assert emptied.quiet_hours == []
