"""Coverage for the endpoints added in wave 1: community info, the paged and
single member reads, the message log, the key PATCH, member approval, the four
bulk member writes, the recurring/suspend hold-open family, and the webhook
delivery log + replays.

Wire contracts are asserted once against the sync client (both clients consume
the same endpoint registry); the async client is exercised for the shapes where
a wrapper could realistically drift, and every new method is asserted present
on both at the bottom.
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


# -- community info ----------------------------------------------------------- #

_INFO = {
    "community_id": 2585,
    "community_uuid": "6f1c2a80",
    "name": "Sunset Ridge",
    "active": True,
    "timezone": "America/Los_Angeles",
    "timezones": ["America/Los_Angeles"],
    "features": {"hold_opens": True, "access_log_history": True,
                 "directory_viewing": False},
    "latches": [{"latch_id": "l1", "latch_name": "Main Entrance",
                 "offline": False, "timezone": "America/Los_Angeles",
                 "box_id": "b1", "box_name": "Front Gate Box"}],
    "terminology": {"member": {"singular": "Tenant"}},
    "counts": {"latches": 2, "members_accepted": 87},
    "property_type": {"id": 2, "name": "Commercial"},
    "number_of_units": 120,
}


@respx.mock
def test_info_reads_the_bootstrap_fields(client):
    respx.get(f"{PROD}/v1/community").mock(
        return_value=httpx.Response(200, json=_INFO))

    info = client.community.info()
    assert info.community_id == 2585
    assert info.name == "Sunset Ridge"
    assert info.timezone == "America/Los_Angeles"
    assert info.latches[0].latch_id == "l1"
    assert info.latches[0].box_name == "Front Gate Box"
    assert info.counts["members_accepted"] == 87
    assert info.property_type["name"] == "Commercial"


@respx.mock
def test_info_feature_helper_is_the_alternative_to_probing_for_a_403(client):
    """`features` exists so an integration can branch before it calls. An
    unknown flag reads False rather than raising — a server that has never
    heard of a feature cannot have it switched on."""
    respx.get(f"{PROD}/v1/community").mock(
        return_value=httpx.Response(200, json=_INFO))

    info = client.community.info()
    assert info.feature("hold_opens") is True
    assert info.feature("directory_viewing") is False
    assert info.feature("a_flag_this_release_never_heard_of") is False


@respx.mock
def test_info_survives_a_multi_site_community_with_no_agreed_timezone(client):
    respx.get(f"{PROD}/v1/community").mock(return_value=httpx.Response(200, json={
        **_INFO, "timezone": None,
        "timezones": ["America/Los_Angeles", "America/Denver"]}))

    info = client.community.info()
    assert info.timezone is None
    assert len(info.timezones) == 2
    assert info.latches[0].timezone == "America/Los_Angeles"


# -- members: paged + single -------------------------------------------------- #

_MEMBER_ROW = {
    "id": "a1", "is_home": False, "account_community_id": 4021,
    "first_name": "Dana", "last_name": "Lee",
    "phone_numbers": ["+1 555-123-4567"],
    "keys": [{"key_name": "Front Gate Key", "key_id": "k1", "disabled": False}],
    "accepted": True, "subkey_count": 1, "created_datetime": "2026-01-14",
}


@respx.mock
def test_members_page_sends_every_query_param(client):
    route = respx.get(f"{PROD}/v1/community/members/page").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "bucket": "unaccepted", "page": 2, "size": 25,
            "total": 137, "has_more": True, "members": [_MEMBER_ROW]}))

    page = client.community.members_page(
        bucket="unaccepted", page=2, size=25, search="555-1234")
    assert _params(route) == {"bucket": "unaccepted", "page": "2",
                              "size": "25", "search": "555-1234"}
    assert page.bucket == "unaccepted"
    assert page.total == 137
    assert page.has_more is True
    assert len(page) == 1
    assert [m.first_name for m in page] == ["Dana"]


@respx.mock
def test_members_page_omits_an_unset_search(client):
    route = respx.get(f"{PROD}/v1/community/members/page").mock(
        return_value=httpx.Response(200, json={"result": "ok", "members": []}))

    client.community.members_page()
    assert _params(route) == {"bucket": "accepted", "page": "1", "size": "100"}


@respx.mock
def test_member_row_carries_the_roster_detail(client):
    respx.get(f"{PROD}/v1/community/members/page").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "members": [_MEMBER_ROW]}))

    row = client.community.members_page().members[0]
    assert row.full_name == "Dana Lee"
    assert row.phone_numbers == ["+1 555-123-4567"]
    # The list read sends `phone_numbers`; the singular attribute still answers.
    assert row.phone_number == "+1 555-123-4567"
    assert row.keys[0]["key_id"] == "k1"
    assert row.subkey_count == 1
    assert row.is_home is False


@respx.mock
def test_member_reads_one_member_with_its_bucket(client):
    respx.get(f"{PROD}/v1/community/members/4021").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "bucket": "accepted", "status": 1, **_MEMBER_ROW}))

    member = client.community.member(4021)
    assert member.account_community_id == 4021
    assert member.bucket == "accepted"
    assert member.status == 1


@respx.mock
def test_member_of_another_community_is_an_ordinary_404(client):
    """A foreign member and an unknown id are deliberately indistinguishable —
    a key can only ever read its own roster."""
    respx.get(f"{PROD}/v1/community/members/999").mock(
        return_value=httpx.Response(404, json={"error": {
            "code": "member_not_found", "message": "Member not found"}}))

    with pytest.raises(NotFoundError) as ei:
        client.community.member(999)
    assert ei.value.code == "member_not_found"


# -- message log -------------------------------------------------------------- #

@respx.mock
def test_messages_paginates_and_parses(client):
    route = respx.get(f"{PROD}/v1/community/messages").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "limit": 10, "offset": 20, "has_more": False,
            "messages": [{"message_id": 4821,
                          "message": "Gate service Thursday 9am-noon.",
                          "sender_name": "Dana Lee",
                          "sender_account_id": "3f9c",
                          "sent_at": "2026-06-09T18:02:00+00:00",
                          "community_uuid": "a1b2"}]}))

    page = client.community.messages(limit=10, offset=20)
    assert _params(route) == {"limit": "10", "offset": "20"}
    assert len(page) == 1
    assert page.messages[0].message_id == 4821
    assert page.messages[0].sender_name == "Dana Lee"
    assert page.has_more is False


# -- key rename / disable ----------------------------------------------------- #

@respx.mock
def test_update_key_sends_only_the_fields_given(client):
    """Each field is applied only when present, so a rename must not carry a
    `disabled: null` that would clobber the key's state."""
    route = respx.patch(f"{PROD}/v1/community/keys/k1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "r1", "descendant_key_count": 42,
            "key": {"id": "k1", "name": "Contractor Key", "disabled": False}}))

    result = client.community.update_key("k1", name="Contractor Key")
    assert _body(route) == {"name": "Contractor Key"}
    assert result.key is not None
    assert result.key.name == "Contractor Key"
    assert result.descendant_key_count == 42


@respx.mock
def test_update_key_disable_reports_the_blast_radius(client):
    """Disabling a community key denies every member key descended from it, so
    descendant_key_count is the number that matters on this call."""
    route = respx.patch(f"{PROD}/v1/community/keys/k1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "request_id": "r1", "descendant_key_count": 87,
            "key": {"id": "k1", "name": "Main Gate", "disabled": True}}))

    result = client.community.update_key("k1", disabled=True)
    assert _body(route) == {"disabled": True}
    assert result.key is not None
    assert result.key.disabled is True
    assert result.descendant_key_count == 87


@respx.mock
def test_update_key_simulated_has_no_key(client):
    respx.patch(f"{PROD}/v1/community/keys/k1").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "key_id": "k1", "request_id": "r1",
            "would_set": {"disabled": True}}))

    result = client.community.update_key("k1", disabled=True)
    assert result.simulated is True
    assert result.key is None
    assert result.raw["would_set"] == {"disabled": True}


# -- member approval ---------------------------------------------------------- #

@respx.mock
def test_approve_member_sends_keys_and_optional_fields(client):
    route = respx.post(f"{PROD}/v1/community/members/4021/approve").mock(
        return_value=httpx.Response(200, json={
            "result": "member_approved", "request_id": "r1",
            "account_community_id": 4021, "account_id": "a1",
            "keys": [{"key_id": "k1"}]}))

    result = client.community.approve_member(
        4021, ["k1"], move_out_date="2027-01-31")
    assert _body(route) == {"key_ids": ["k1"], "move_out_date": "2027-01-31"}
    assert result.result == "member_approved"
    assert result.get("account_id") == "a1"


@respx.mock
def test_approve_member_omits_unset_optionals(client):
    route = respx.post(f"{PROD}/v1/community/members/4021/approve").mock(
        return_value=httpx.Response(200, json={"result": "member_approved"}))

    client.community.approve_member(4021, ["k1"])
    assert _body(route) == {"key_ids": ["k1"]}


@respx.mock
def test_approving_an_already_approved_member_raises_conflict(client):
    """409 is the one the caller acts on: there is nothing left to approve, and
    it must not be confused with a failure worth retrying."""
    respx.post(f"{PROD}/v1/community/members/4021/approve").mock(
        return_value=httpx.Response(409, json={"error": {
            "code": "already_accepted",
            "message": "Member is already an accepted member of this community",
            "request_id": "r1"}}))

    with pytest.raises(ConflictError) as ei:
        client.community.approve_member(4021, ["k1"])
    assert ei.value.status_code == 409
    assert ei.value.code == "already_accepted"


# -- bulk member writes ------------------------------------------------------- #

_BULK_GRANT = {
    "result": "batch_processed", "request_id": "r1", "simulated": False,
    "summary": {"total": 3, "succeeded": 2, "failed": 1},
    "results": [
        {"index": 0, "account_community_id": 4021, "ok": True,
         "granted": {"created": ["k1"], "enabled": [], "exists": []}},
        {"index": 1, "account_community_id": 4022, "ok": True,
         "granted": {"created": [], "enabled": [], "exists": ["k2"]}},
        {"index": 2, "account_community_id": 4023, "ok": False,
         "code": "member_not_accepted",
         "message": "Member is not an accepted member of this community"},
    ],
}


@respx.mock
def test_bulk_grant_keys_sends_items_verbatim(client):
    route = respx.post(f"{PROD}/v1/community/members/keys/bulk-grant").mock(
        return_value=httpx.Response(207, json=_BULK_GRANT))

    result = client.community.bulk_grant_keys([
        {"account_community_id": 4021, "key_ids": ["k1"]},
        {"account_community_id": 4022, "key_ids": ["k2"]},
    ])
    assert _body(route) == {"items": [
        {"account_community_id": 4021, "key_ids": ["k1"]},
        {"account_community_id": 4022, "key_ids": ["k2"]}]}
    assert result.summary.total == 3
    assert len(result) == 3


@respx.mock
def test_a_207_is_not_success_and_the_failures_are_reachable(client):
    """The whole point of the 207: the batch was processed, individual items
    still failed. A caller reading only the status code would ship a silent
    partial roster import."""
    respx.post(f"{PROD}/v1/community/members/keys/bulk-grant").mock(
        return_value=httpx.Response(207, json=_BULK_GRANT))

    result = client.community.bulk_grant_keys(
        [{"account_community_id": 4021, "key_ids": ["k1"]}])
    assert result.summary.failed == 1
    assert len(result.failures) == 1
    assert result.failures[0].account_community_id == 4023
    assert result.failures[0].code == "member_not_accepted"
    assert len(result.successes) == 2
    # Per-item detail is not flattened away.
    assert result.successes[1]["granted"]["exists"] == ["k2"]
    assert result.successes[0].get("granted")["created"] == ["k1"]


@respx.mock
def test_bulk_add_members_reports_per_item_phone_numbers(client):
    route = respx.post(f"{PROD}/v1/community/members/bulk-add").mock(
        return_value=httpx.Response(207, json={
            "result": "batch_processed", "request_id": "r1", "simulated": False,
            "summary": {"total": 2, "succeeded": 1, "failed": 1},
            "results": [
                {"index": 0, "phone_number": "+15551234567", "ok": True,
                 "account_community_id": 4021, "account_id": "a1"},
                {"index": 1, "phone_number": "+15557654321", "ok": False,
                 "code": "already_member",
                 "message": "Account already a member of community"}]}))

    result = client.community.bulk_add_members([
        {"phone_number": "+15551234567", "key_ids": ["k1"]},
        {"phone_number": "+15557654321", "key_ids": ["k1"]},
    ])
    assert len(_body(route)["items"]) == 2
    assert result.failures[0].phone_number == "+15557654321"
    assert result.failures[0].code == "already_member"


@respx.mock
def test_bulk_revoke_keys_posts_to_its_own_path(client):
    route = respx.post(f"{PROD}/v1/community/members/keys/bulk-revoke").mock(
        return_value=httpx.Response(207, json={
            "result": "batch_processed", "simulated": False,
            "summary": {"total": 1, "succeeded": 1, "failed": 0},
            "results": [{"index": 0, "account_community_id": 4021, "ok": True,
                         "revoked_key_ids": [],
                         "already_revoked_community_key_ids": ["k1"]}]}))

    result = client.community.bulk_revoke_keys(
        [{"account_community_id": 4021, "key_ids": ["k1"]}])
    assert _body(route) == {"items": [
        {"account_community_id": 4021, "key_ids": ["k1"]}]}
    # Re-submitting is safe: an already-revoked key still succeeds.
    assert result.failures == []
    assert result.results[0]["already_revoked_community_key_ids"] == ["k1"]


@respx.mock
def test_bulk_set_keys_disabled_sends_the_batch_wide_flag(client):
    route = respx.post(f"{PROD}/v1/community/members/keys/bulk-disabled").mock(
        return_value=httpx.Response(207, json={
            "result": "batch_processed", "simulated": False,
            "summary": {"total": 1, "succeeded": 0, "failed": 1},
            "results": [{"index": 0, "account_community_id": 4022, "ok": False,
                         "disabled": True, "code": "key_not_held",
                         "message": "Member does not hold a key"}]}))

    result = client.community.bulk_set_keys_disabled(
        [{"account_community_id": 4022, "key_ids": ["k1"]}], True)
    assert _body(route) == {
        "items": [{"account_community_id": 4022, "key_ids": ["k1"]}],
        "disabled": True}
    assert result.failures[0].code == "key_not_held"


@respx.mock
def test_bulk_simulated_is_a_flag_not_an_outcome_string(client):
    """`result` stays "batch_processed" for a test key, so a caller checking
    result == "simulated" would read a dry run as a real import."""
    respx.post(f"{PROD}/v1/community/members/keys/bulk-grant").mock(
        return_value=httpx.Response(207, json={
            "result": "batch_processed", "simulated": True,
            "summary": {"total": 1, "succeeded": 1, "failed": 0},
            "results": [{"index": 0, "account_community_id": 4021, "ok": True}]}))

    result = client.community.bulk_grant_keys(
        [{"account_community_id": 4021, "key_ids": ["k1"]}])
    assert result.result == "batch_processed"
    assert result.simulated is True


@respx.mock
def test_a_rejected_batch_raises_instead_of_returning_items(client):
    """Validate-all-then-apply: a foreign member rejects the whole batch with
    nothing applied, and that is an error, not a 207 full of failures."""
    from nimbio_community_api import APIError

    respx.post(f"{PROD}/v1/community/members/keys/bulk-grant").mock(
        return_value=httpx.Response(422, json={"error": {
            "code": "scope_denied",
            "message": "item 12: member 91234 is not in this community",
            "request_id": "r1"}}))

    with pytest.raises(APIError) as ei:
        client.community.bulk_grant_keys(
            [{"account_community_id": 91234, "key_ids": ["k1"]}])
    assert ei.value.code == "scope_denied"


# -- hold opens: suspend / resume --------------------------------------------- #

@respx.mock
def test_set_hold_open_disabled_until_sends_latch_local_time(client):
    route = respx.put(
        f"{PROD}/v1/community/latches/l1/hold-open/disabled-until").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "latch_id": "l1",
            "disabled_until": "2026-12-25 23:59:00", "held_open": False,
            "request_id": "r1"}))

    result = client.community.set_hold_open_disabled_until(
        "l1", "2026-12-25 23:59")
    assert _body(route) == {"until": "2026-12-25 23:59"}
    assert result.disabled_until == "2026-12-25 23:59:00"
    assert result.held_open is False


@respx.mock
def test_resuming_sends_an_explicit_null_rather_than_an_empty_body(client):
    """`until` is required precisely so an empty body can never resume by
    accident; None has to travel as JSON null."""
    route = respx.put(
        f"{PROD}/v1/community/latches/l1/hold-open/disabled-until").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "latch_id": "l1", "disabled_until": None,
            "held_open": False, "request_id": "r1"}))

    result = client.community.set_hold_open_disabled_until("l1", None)
    assert _body(route) == {"until": None}
    assert result.disabled_until is None


@respx.mock
def test_hold_open_writes_need_the_feature_enabled(client):
    respx.put(f"{PROD}/v1/community/latches/l1/hold-open/disabled-until").mock(
        return_value=httpx.Response(403, json={"error": {
            "code": "hold_opens_disabled",
            "message": "Hold opens are not enabled for this community"}}))

    with pytest.raises(PermissionDeniedError) as ei:
        client.community.set_hold_open_disabled_until("l1", None)
    assert ei.value.code == "hold_opens_disabled"


# -- hold opens: recurring schedules ------------------------------------------ #

_SCHEDULE_RESPONSE = {
    "result": "ok", "latch_id": "l1", "temporal_date_id": "t1",
    "request_id": "r1",
    "schedule": {"temporal_date_id": "t1", "days_of_the_week": "MTWHF",
                 "recurring_week": 1, "active": False,
                 "temporal_times": [{"temporal_time_id": "tt1",
                                     "start": "08:00:00", "end": "09:00:00"}]},
}


@respx.mock
def test_add_hold_open_recurring_sends_days_and_times(client):
    route = respx.post(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring").mock(
        return_value=httpx.Response(200, json=_SCHEDULE_RESPONSE))

    result = client.community.add_hold_open_recurring(
        "l1", days_of_the_week="MTWHF", start_time="08:00", end_time="09:00",
        recurring_week=1)
    assert _body(route) == {"days_of_the_week": "MTWHF", "start_time": "08:00",
                            "end_time": "09:00", "recurring_week": 1}
    assert result.temporal_date_id == "t1"
    assert result.schedule["temporal_times"][0]["start"] == "08:00:00"


@respx.mock
def test_an_all_day_schedule_omits_the_times(client):
    """Omitting both times is how all-day is expressed — sending nulls would be
    a different request."""
    route = respx.post(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring").mock(
        return_value=httpx.Response(200, json=_SCHEDULE_RESPONSE))

    client.community.add_hold_open_recurring("l1", days_of_the_week="SU")
    assert _body(route) == {"days_of_the_week": "SU"}


@respx.mock
def test_an_overnight_window_is_refused_by_the_server(client):
    """A window may not wrap past midnight; the caller splits it into
    22:00-24:00 and 00:00-06:00 instead."""
    from nimbio_community_api import APIError

    respx.post(f"{PROD}/v1/community/latches/l1/hold-open/recurring").mock(
        return_value=httpx.Response(422, json={"error": {
            "code": "invalid_time",
            "message": "end_time must be after start_time",
            "request_id": "r1"}}))

    with pytest.raises(APIError) as ei:
        client.community.add_hold_open_recurring(
            "l1", days_of_the_week="MTWHF", start_time="22:00",
            end_time="06:00")
    assert ei.value.code == "invalid_time"


@respx.mock
def test_update_hold_open_recurring_is_a_partial_update(client):
    route = respx.patch(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring/t1").mock(
        return_value=httpx.Response(200, json=_SCHEDULE_RESPONSE))

    client.community.update_hold_open_recurring(
        "l1", "t1", days_of_the_week="MTWHFS")
    # Only what was passed: an omitted time must keep its current value, not be
    # cleared.
    assert _body(route) == {"days_of_the_week": "MTWHFS"}


@respx.mock
def test_clear_times_is_explicit_not_inferred_from_missing_times(client):
    route = respx.patch(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring/t1").mock(
        return_value=httpx.Response(200, json=_SCHEDULE_RESPONSE))

    client.community.update_hold_open_recurring("l1", "t1", clear_times=True)
    assert _body(route) == {"clear_times": True}


@respx.mock
def test_remove_hold_open_recurring_returns_the_removed_schedule(client):
    respx.delete(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring/t1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "removed": True, "latch_id": "l1",
            "temporal_date_id": "t1", "request_id": "r1"}))

    result = client.community.remove_hold_open_recurring("l1", "t1")
    assert result.removed is True
    assert result.temporal_date_id == "t1"


@respx.mock
def test_removing_an_unknown_schedule_404s_rather_than_succeeding(client):
    """Deliberately NOT idempotent: a cheerful success would let a caller
    believe it had cancelled a schedule that is still holding a gate open."""
    respx.delete(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring/nope").mock(
        return_value=httpx.Response(404, json={"error": {
            "code": "schedule_not_found",
            "message": "Recurring schedule not found on this latch"}}))

    with pytest.raises(NotFoundError) as ei:
        client.community.remove_hold_open_recurring("l1", "nope")
    assert ei.value.code == "schedule_not_found"


# -- webhook deliveries ------------------------------------------------------- #

_DELIVERIES = {
    "result": "ok",
    "deliveries": [
        {"delivery_id": "d1", "event_type": "sense_line.changed",
         "event_id": "e1", "status": "delivered", "attempts": 1,
         "last_status_code": 200, "last_error": None,
         "next_attempt_datetime": None,
         "created_datetime": "2026-08-18T14:03:11+00:00",
         "delivered_datetime": "2026-08-18T14:03:12+00:00"},
        {"delivery_id": "d2", "event_type": "open.succeeded", "event_id": "e2",
         "status": "failed", "attempts": 5, "last_status_code": 502,
         "last_error": "502 Bad Gateway", "next_attempt_datetime": None,
         "created_datetime": "2026-08-18T13:59:02+00:00",
         "delivered_datetime": None},
    ],
}


@respx.mock
def test_webhook_deliveries_parses_both_outcomes(client):
    route = respx.get(f"{PROD}/v1/community/webhooks/w1/deliveries").mock(
        return_value=httpx.Response(200, json=_DELIVERIES))

    deliveries = client.community.webhook_deliveries("w1", limit=10)
    assert _params(route) == {"limit": "10"}
    assert [d.delivery_id for d in deliveries] == ["d1", "d2"]
    assert deliveries[0].failed is False
    assert deliveries[1].failed is True
    assert deliveries[1].last_status_code == 502
    assert deliveries[1].last_error == "502 Bad Gateway"


@respx.mock
def test_webhook_deliveries_of_an_unknown_webhook_404s(client):
    respx.get(f"{PROD}/v1/community/webhooks/nope/deliveries").mock(
        return_value=httpx.Response(404, json={"error": {
            "code": "webhook_not_found",
            "message": "Webhook not found for this community"}}))

    with pytest.raises(NotFoundError):
        client.community.webhook_deliveries("nope")


@respx.mock
def test_retry_failed_deliveries_reports_what_was_actually_enqueued(client):
    """replayed_count is not the number asked for: in-flight deliveries and
    duplicate events are skipped so a retry can never double-fire."""
    route = respx.post(
        f"{PROD}/v1/community/webhooks/w1/deliveries/retry-failed").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "webhook_id": "w1", "replayed_count": 1,
            "replayed": [{"delivery_id": "d9",
                          "replayed_from_delivery_id": "d2",
                          "event_id": "e2", "event_type": "member.approved",
                          "status": "pending",
                          "created_datetime": "2026-08-18T15:10:00+00:00"}],
            "skipped_in_flight": 1, "skipped_duplicate_event": 2,
            "limit": 25, "request_id": "r1"}))

    batch = client.community.retry_failed_deliveries(
        "w1", since="2026-08-18T13:00:00+00:00", limit=25)
    assert _params(route) == {"since": "2026-08-18T13:00:00+00:00",
                              "limit": "25"}
    assert batch.replayed_count == 1
    assert batch.skipped_in_flight == 1
    assert batch.skipped_duplicate_event == 2
    assert len(batch) == 1
    assert batch.replayed[0].replayed_from_delivery_id == "d2"


@respx.mock
def test_retry_failed_omits_an_unset_since(client):
    route = respx.post(
        f"{PROD}/v1/community/webhooks/w1/deliveries/retry-failed").mock(
        return_value=httpx.Response(200, json={"result": "ok"}))

    client.community.retry_failed_deliveries("w1")
    assert _params(route) == {"limit": "50"}


@respx.mock
def test_replay_delivery_keeps_the_original_event_id(client):
    """The replay carries the original event_id (and so the original
    X-Nimbio-Delivery header); only the delivery_id is new."""
    respx.post(
        f"{PROD}/v1/community/webhooks/w1/deliveries/d2/replay").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "delivery_id": "d9",
            "replayed_from_delivery_id": "d2", "event_id": "e2",
            "event_type": "member.approved", "status": "pending",
            "created_datetime": "2026-08-18T15:10:00+00:00",
            "request_id": "r1"}))

    replay = client.community.replay_delivery("w1", "d2")
    assert replay.delivery_id == "d9"
    assert replay.replayed_from_delivery_id == "d2"
    assert replay.event_id == "e2"
    assert replay.status == "pending"
    assert replay.simulated is False


@respx.mock
def test_replay_of_an_in_flight_delivery_raises_conflict(client):
    """409 delivery_in_flight is recoverable and actionable: Nimbio is still
    retrying that event itself, so the caller waits rather than double-firing."""
    respx.post(
        f"{PROD}/v1/community/webhooks/w1/deliveries/d2/replay").mock(
        return_value=httpx.Response(409, json={"error": {
            "code": "delivery_in_flight",
            "message": "A delivery of that event is still pending",
            "request_id": "r1"}}))

    with pytest.raises(ConflictError) as ei:
        client.community.replay_delivery("w1", "d2")
    assert ei.value.status_code == 409
    assert ei.value.code == "delivery_in_flight"
    assert ei.value.request_id == "r1"


@respx.mock
def test_replay_against_a_disabled_webhook_raises_conflict(client):
    """The other actionable 409: the caller fixes it themselves with
    update_webhook(active=True)."""
    respx.post(
        f"{PROD}/v1/community/webhooks/w1/deliveries/d2/replay").mock(
        return_value=httpx.Response(409, json={"error": {
            "code": "webhook_disabled",
            "message": "Webhook is disabled or inactive"}}))

    with pytest.raises(ConflictError) as ei:
        client.community.replay_delivery("w1", "d2")
    assert ei.value.code == "webhook_disabled"


@respx.mock
def test_test_mode_keys_enqueue_nothing(client):
    respx.post(
        f"{PROD}/v1/community/webhooks/w1/deliveries/d2/replay").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "webhook_id": "w1", "delivery_id": "d2",
            "request_id": "r1"}))

    assert client.community.replay_delivery("w1", "d2").simulated is True


@respx.mock
def test_test_mode_keys_enqueue_no_batch_either(client):
    respx.post(
        f"{PROD}/v1/community/webhooks/w1/deliveries/retry-failed").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "webhook_id": "w1", "request_id": "r1"}))

    batch = client.community.retry_failed_deliveries("w1")
    assert batch.simulated is True
    assert batch.replayed_count == 0


# -- sync / async parity ------------------------------------------------------ #

WAVE1_METHODS = (
    "info",
    "members_page",
    "member",
    "messages",
    "update_key",
    "approve_member",
    "bulk_add_members",
    "bulk_grant_keys",
    "bulk_revoke_keys",
    "bulk_set_keys_disabled",
    "set_hold_open_disabled_until",
    "add_hold_open_recurring",
    "update_hold_open_recurring",
    "remove_hold_open_recurring",
    "webhook_deliveries",
    "retry_failed_deliveries",
    "replay_delivery",
)


def test_both_clients_expose_every_wave1_method():
    """The two clients must not drift: a method that lands on only one of them
    is a silent gap for half the users."""
    sync_community = NimbioClient("nimbio_test_x").community
    async_community = AsyncNimbioClient("nimbio_test_x").community
    for name in WAVE1_METHODS:
        assert hasattr(sync_community, name), f"sync client missing {name}"
        assert hasattr(async_community, name), f"async client missing {name}"


@respx.mock
async def test_async_info(test_key):
    respx.get(f"{PROD}/v1/community").mock(
        return_value=httpx.Response(200, json=_INFO))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        info = await client.community.info()
        assert info.name == "Sunset Ridge"
        assert info.feature("hold_opens") is True


@respx.mock
async def test_async_members_page_and_member(test_key):
    respx.get(f"{PROD}/v1/community/members/page").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "bucket": "accepted", "total": 1,
            "members": [_MEMBER_ROW]}))
    respx.get(f"{PROD}/v1/community/members/4021").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "bucket": "accepted", **_MEMBER_ROW}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        page = await client.community.members_page(search="Dana")
        assert page.total == 1
        member = await client.community.member(4021)
        assert member.bucket == "accepted"


@respx.mock
async def test_async_messages_and_update_key(test_key):
    respx.get(f"{PROD}/v1/community/messages").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "has_more": False,
            "messages": [{"message_id": 1, "message": "hi"}]}))
    respx.patch(f"{PROD}/v1/community/keys/k1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "descendant_key_count": 3,
            "key": {"id": "k1", "disabled": True}}))
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        assert len(await client.community.messages()) == 1
        result = await client.community.update_key("k1", disabled=True)
        assert result.descendant_key_count == 3


@respx.mock
async def test_async_approve_and_bulk_writes(test_key):
    respx.post(f"{PROD}/v1/community/members/4021/approve").mock(
        return_value=httpx.Response(200, json={"result": "member_approved"}))
    for path in ("bulk-add",):
        respx.post(f"{PROD}/v1/community/members/{path}").mock(
            return_value=httpx.Response(207, json=_BULK_GRANT))
    for path in ("bulk-grant", "bulk-revoke", "bulk-disabled"):
        respx.post(f"{PROD}/v1/community/members/keys/{path}").mock(
            return_value=httpx.Response(207, json=_BULK_GRANT))

    items = [{"account_community_id": 4021, "key_ids": ["k1"]}]
    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        approved = await client.community.approve_member(4021, ["k1"])
        assert approved.result == "member_approved"
        assert (await client.community.bulk_add_members(
            [{"phone_number": "+15551234567", "key_ids": ["k1"]}])).summary.total == 3
        assert len(await client.community.bulk_grant_keys(items)) == 3
        assert len(await client.community.bulk_revoke_keys(items)) == 3
        assert (await client.community.bulk_set_keys_disabled(
            items, True)).summary.failed == 1


@respx.mock
async def test_async_hold_open_family(test_key):
    respx.put(f"{PROD}/v1/community/latches/l1/hold-open/disabled-until").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "latch_id": "l1", "disabled_until": None}))
    respx.post(f"{PROD}/v1/community/latches/l1/hold-open/recurring").mock(
        return_value=httpx.Response(200, json=_SCHEDULE_RESPONSE))
    respx.patch(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring/t1").mock(
        return_value=httpx.Response(200, json=_SCHEDULE_RESPONSE))
    respx.delete(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring/t1").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "removed": True, "temporal_date_id": "t1"}))

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        resumed = await client.community.set_hold_open_disabled_until("l1", None)
        assert resumed.disabled_until is None
        added = await client.community.add_hold_open_recurring(
            "l1", days_of_the_week="MTWHF", start_time="08:00",
            end_time="09:00")
        assert added.temporal_date_id == "t1"
        changed = await client.community.update_hold_open_recurring(
            "l1", "t1", clear_times=True)
        assert changed.temporal_date_id == "t1"
        removed = await client.community.remove_hold_open_recurring("l1", "t1")
        assert removed.removed is True


@respx.mock
async def test_async_delivery_reads_and_replays(test_key):
    respx.get(f"{PROD}/v1/community/webhooks/w1/deliveries").mock(
        return_value=httpx.Response(200, json=_DELIVERIES))
    respx.post(
        f"{PROD}/v1/community/webhooks/w1/deliveries/retry-failed").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "replayed_count": 0, "replayed": []}))
    respx.post(f"{PROD}/v1/community/webhooks/w1/deliveries/d2/replay").mock(
        return_value=httpx.Response(409, json={"error": {
            "code": "webhook_disabled", "message": "Webhook is disabled"}}))

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        assert len(await client.community.webhook_deliveries("w1")) == 2
        assert (await client.community.retry_failed_deliveries(
            "w1")).replayed_count == 0
        with pytest.raises(ConflictError):
            await client.community.replay_delivery("w1", "d2")


# -- tolerant parsing --------------------------------------------------------- #

@pytest.mark.parametrize("model", [
    models.CommunityInfo, models.MembersPage, models.MessagesPage,
    models.KeyUpdateResult, models.BulkResult, models.HoldOpenDisabledUntil,
    models.RecurringHoldOpen, models.RecurringHoldOpenRemoved,
    models.WebhookDelivery, models.DeliveryReplay, models.DeliveryReplayBatch,
    models.Member, models.Message, models.BulkItemResult, models.BulkSummary,
    models.CommunityLatch,
])
def test_every_new_model_survives_an_empty_or_absent_payload(model):
    """House rule: a model never raises on a payload it did not expect."""
    assert model.from_dict({}).raw == {}
    assert model.from_dict(None).raw == {}


def test_recurring_schedule_id_falls_back_to_the_nested_schedule():
    """The id is what addresses the schedule later; take it from wherever the
    server put it rather than handing back None."""
    result = models.RecurringHoldOpen.from_dict(
        {"result": "ok", "schedule": {"temporal_date_id": "t7"}})
    assert result.temporal_date_id == "t7"


# -- simulated writes and the remaining option branches ----------------------- #

@respx.mock
def test_approve_member_can_ask_for_a_dry_run_on_a_live_key(client):
    """dry_run validates the member, keys and date without approving anyone —
    the rehearsal a live key would otherwise have no way to do."""
    route = respx.post(f"{PROD}/v1/community/members/4021/approve").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "request_id": "r1"}))

    result = client.community.approve_member(4021, ["k1"], dry_run=True)
    assert _body(route) == {"key_ids": ["k1"], "dry_run": True}
    assert result.simulated is True


@respx.mock
def test_update_hold_open_recurring_replaces_the_window(client):
    route = respx.patch(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring/t1").mock(
        return_value=httpx.Response(200, json=_SCHEDULE_RESPONSE))

    client.community.update_hold_open_recurring(
        "l1", "t1", start_time="07:30", end_time="09:30", recurring_week=2)
    assert _body(route) == {"start_time": "07:30", "end_time": "09:30",
                            "recurring_week": 2}


@respx.mock
def test_hold_open_recurring_writes_simulate_on_a_test_key(client):
    """A test key echoes the request under would_add and schedules nothing, so
    `.schedule` is empty rather than a schedule that does not exist."""
    respx.post(f"{PROD}/v1/community/latches/l1/hold-open/recurring").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "latch_id": "l1", "request_id": "r1",
            "would_add": {"days_of_the_week": "MTWHF", "start_time": "08:00"}}))
    respx.put(f"{PROD}/v1/community/latches/l1/hold-open/disabled-until").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "would_set": None, "latch_id": "l1"}))
    respx.delete(
        f"{PROD}/v1/community/latches/l1/hold-open/recurring/t1").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "latch_id": "l1", "temporal_date_id": "t1"}))

    added = client.community.add_hold_open_recurring(
        "l1", days_of_the_week="MTWHF", start_time="08:00")
    assert added.simulated is True
    assert added.schedule == {}
    assert added.raw["would_add"]["days_of_the_week"] == "MTWHF"

    assert client.community.set_hold_open_disabled_until(
        "l1", None).simulated is True

    removed = client.community.remove_hold_open_recurring("l1", "t1")
    assert removed.simulated is True
    # Nothing was deleted, and the model does not pretend otherwise.
    assert removed.removed is False


@respx.mock
def test_the_page_and_batch_models_iterate(client):
    """`for x in result` is how these read at a call site, so the containers
    iterate their rows rather than needing `.messages` / `.replayed`."""
    respx.get(f"{PROD}/v1/community/messages").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "messages": [{"message_id": 1, "message": "hi"}]}))
    respx.post(f"{PROD}/v1/community/members/keys/bulk-grant").mock(
        return_value=httpx.Response(207, json=_BULK_GRANT))
    respx.post(
        f"{PROD}/v1/community/webhooks/w1/deliveries/retry-failed").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "replayed_count": 1,
            "replayed": [{"delivery_id": "d9", "event_id": "e2"}]}))

    assert [m.message for m in client.community.messages()] == ["hi"]
    assert [r.index for r in client.community.bulk_grant_keys(
        [{"account_community_id": 4021, "key_ids": ["k1"]}])] == [0, 1, 2]
    assert [d.delivery_id for d in
            client.community.retry_failed_deliveries("w1")] == ["d9"]
