"""Coverage for the key access-schedule surface (sync client; the async client
shares the same endpoint registry, so the wire contract is asserted once here
and parity is asserted structurally at the bottom)."""

import json as _json

import httpx
import pytest
import respx

from nimbio_community_api import AsyncNimbioClient, NimbioClient, models

PROD = "https://api.nimbio.com"

_SCHEDULE = {
    "key_id": "k1",
    "key_name": "Main Gate Key",
    "is_temporal_enabled": True,
    "restricted": True,
    "permanently_blocked": False,
    "windows": [{"temporal_date_id": "t1", "days_of_the_week": "MTWHF",
                 "start_time": "06:00", "end_time": "18:00"}],
    "latch_count": 1,
    "latches": [{"latch_id": "l1", "name": "Main Gate"}],
    "is_community_key": True,
    "descendant_key_count": 42,
    "inactive_window_count": 0,
    "request_id": "r1",
}


@pytest.fixture
def client(test_key):
    c = NimbioClient(test_key, max_retries=0)
    yield c
    c.close()


def _body(route):
    return _json.loads(route.calls.last.request.content)


# -- reads -------------------------------------------------------------------- #

@respx.mock
def test_key_schedules_list(client):
    respx.get(f"{PROD}/v1/community/key-schedules").mock(
        return_value=httpx.Response(200, json={"keys": [_SCHEDULE], "request_id": "r1"}))

    result = client.community.key_schedules()
    assert len(result) == 1
    assert list(result)[0].key_id == "k1"
    assert result.keys[0].restricted is True
    assert result.keys[0].windows[0].days_of_the_week == "MTWHF"


@respx.mock
def test_blocked_helper_surfaces_the_broken_state(client):
    """A key with windows but the restriction switched off is denied at all
    times; .blocked is how a caller finds those without knowing the rule."""
    blocked = {**_SCHEDULE, "key_id": "k2", "restricted": False,
               "permanently_blocked": True, "is_temporal_enabled": False}
    respx.get(f"{PROD}/v1/community/key-schedules").mock(
        return_value=httpx.Response(200, json={"keys": [_SCHEDULE, blocked]}))

    result = client.community.key_schedules()
    assert [k.key_id for k in result.blocked] == ["k2"]


@respx.mock
def test_single_key_schedule(client):
    respx.get(f"{PROD}/v1/community/keys/k1/schedule").mock(
        return_value=httpx.Response(200, json=_SCHEDULE))

    schedule = client.community.key_schedule("k1")
    assert schedule.key_id == "k1"
    assert schedule.is_community_key is True
    # The blast radius must survive parsing — it is what a caller checks before
    # restricting a community key.
    assert schedule.descendant_key_count == 42
    assert schedule.latch_count == 1


@respx.mock
def test_key_id_is_url_encoded(client):
    route = respx.get(f"{PROD}/v1/community/keys/a%2Fb/schedule").mock(
        return_value=httpx.Response(200, json=_SCHEDULE))
    client.community.key_schedule("a/b")
    assert route.called


# -- writes ------------------------------------------------------------------- #

@respx.mock
def test_set_key_schedule_from_dicts(client):
    route = respx.put(f"{PROD}/v1/community/keys/k1/schedule").mock(
        return_value=httpx.Response(200, json=_SCHEDULE))

    client.community.set_key_schedule("k1", [
        {"days_of_the_week": "MTWHF", "start_time": "06:00", "end_time": "18:00"}])

    assert _body(route) == {"windows": [
        {"days_of_the_week": "MTWHF", "start_time": "06:00", "end_time": "18:00"}]}


@respx.mock
def test_set_key_schedule_from_model_objects(client):
    """A window read back from the API can be sent straight back without the
    caller unpacking it — and the server-assigned id is not echoed."""
    route = respx.put(f"{PROD}/v1/community/keys/k1/schedule").mock(
        return_value=httpx.Response(200, json=_SCHEDULE))

    window = models.ScheduleWindow(
        days_of_the_week="SU", start_time="09:00", end_time="17:00",
        temporal_date_id="t9")
    client.community.set_key_schedule("k1", [window])

    assert _body(route) == {"windows": [
        {"days_of_the_week": "SU", "start_time": "09:00", "end_time": "17:00"}]}


@respx.mock
def test_empty_windows_clears_the_restriction(client):
    route = respx.put(f"{PROD}/v1/community/keys/k1/schedule").mock(
        return_value=httpx.Response(200, json={
            **_SCHEDULE, "restricted": False, "windows": []}))

    result = client.community.set_key_schedule("k1", [])
    assert _body(route) == {"windows": []}
    assert result.restricted is False
    assert result.windows == []


@respx.mock
def test_none_is_treated_as_clearing(client):
    route = respx.put(f"{PROD}/v1/community/keys/k1/schedule").mock(
        return_value=httpx.Response(200, json={**_SCHEDULE, "windows": []}))
    client.community.set_key_schedule("k1", None)
    assert _body(route) == {"windows": []}


@respx.mock
def test_all_day_window_sends_null_times(client):
    route = respx.put(f"{PROD}/v1/community/keys/k1/schedule").mock(
        return_value=httpx.Response(200, json=_SCHEDULE))

    client.community.set_key_schedule("k1", [
        models.ScheduleWindow(days_of_the_week="SU")])

    assert _body(route) == {"windows": [
        {"days_of_the_week": "SU", "start_time": None, "end_time": None}]}


@respx.mock
def test_end_of_day_sentinel_passes_through(client):
    """'24:00' is the gapless way to end at midnight and must not be rewritten."""
    route = respx.put(f"{PROD}/v1/community/keys/k1/schedule").mock(
        return_value=httpx.Response(200, json=_SCHEDULE))

    client.community.set_key_schedule("k1", [
        models.ScheduleWindow("MTWHF", "22:00", "24:00")])

    assert _body(route) == {"windows": [
        {"days_of_the_week": "MTWHF", "start_time": "22:00", "end_time": "24:00"}]}


@respx.mock
def test_test_mode_write_is_flagged_simulated(client):
    respx.put(f"{PROD}/v1/community/keys/k1/schedule").mock(
        return_value=httpx.Response(200, json={
            "result": "simulated", "key_id": "k1",
            "would_set": "MTWHF 06:00-18:00", "request_id": "r1"}))

    result = client.community.set_key_schedule("k1", [
        {"days_of_the_week": "MTWHF", "start_time": "06:00", "end_time": "18:00"}])
    assert result.simulated is True


@respx.mock
def test_overnight_window_raises_bad_request(client):
    from nimbio_community_api import BadRequestError

    respx.put(f"{PROD}/v1/community/keys/k1/schedule").mock(
        return_value=httpx.Response(400, json={"error": {
            "code": "overnight_not_supported",
            "message": "Window 1 ends before it starts.",
            "request_id": "r1"}}))

    with pytest.raises(BadRequestError):
        client.community.set_key_schedule("k1", [
            {"days_of_the_week": "MTWHF", "start_time": "22:00", "end_time": "06:00"}])


# -- sync/async parity -------------------------------------------------------- #

@respx.mock
def test_inactive_windows_are_surfaced_not_silently_dropped(client):
    """The list returns only windows in force today. A caller that saw
    `windows: []` with no other signal would read an expired schedule as "no
    restriction", so the count has to come through."""
    expired = {**_SCHEDULE, "windows": [], "restricted": False,
               "inactive_window_count": 2}
    respx.get(f"{PROD}/v1/community/key-schedules").mock(
        return_value=httpx.Response(200, json={"keys": [expired], "request_id": "r1"}))

    row = client.community.key_schedules().keys[0]
    assert row.windows == []
    assert row.inactive_window_count == 2


@respx.mock
def test_member_key_is_refused_with_its_own_code(client):
    """Schedules are community-keys-only. A member's key must come back as
    not_a_community_key so the caller knows to schedule the community key
    instead of hunting for an access problem."""
    from nimbio_community_api import PermissionDeniedError

    respx.put(f"{PROD}/v1/community/keys/member1/schedule").mock(
        return_value=httpx.Response(403, json={"error": {
            "code": "not_a_community_key",
            "message": ("Access schedules are set on the community key, which "
                        "applies to every member beneath it."),
            "request_id": "r1"}}))

    with pytest.raises(PermissionDeniedError) as excinfo:
        client.community.set_key_schedule(
            "member1", [models.ScheduleWindow("MTWHF", "06:00", "18:00")])
    assert excinfo.value.code == "not_a_community_key"


def test_async_client_exposes_the_same_methods():
    """The two clients must not drift: every schedule method on the sync client
    exists on the async one too."""
    sync_community = NimbioClient("nimbio_test_x").community
    async_community = AsyncNimbioClient("nimbio_test_x").community
    for name in ("key_schedules", "key_schedule", "set_key_schedule"):
        assert hasattr(sync_community, name)
        assert hasattr(async_community, name)
