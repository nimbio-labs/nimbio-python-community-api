"""Coverage for the endpoints added in wave 4 — the last of them: NFC tags and
their scan log, sense lines (the hardware diagnostics behind gate status), the
community map with its geofence write, and the two audit reads.

Wire contracts are asserted once against the sync client (both clients consume
the same endpoint registry); the async client is exercised for the shapes where
a wrapper could realistically drift, and every new method is asserted present on
both at the bottom.

Three tests exist to keep a *contract* honest rather than to check a wrapper:

* `test_disabling_a_last_tag_is_a_warning_not_a_veto` pins the 409
  `requires_confirmation` -> retry-with-confirm flow, which is the reason
  revoking a stolen fob stays possible.
* `test_sense_line_requires_a_box_id` pins `box_id` as required on the two
  single-sense-line calls — the OpenAPI schema says otherwise, and getting it
  wrong turns a type error into a runtime 422.
* `test_a_radius_below_the_minimum_is_rejected_not_clamped` pins that the SDK
  forwards a too-small radius untouched, so nobody "fixes" the 422 by clamping
  client-side and shipping a fence that never fires.
"""

import json as _json

import httpx
import pytest
import respx

from nimbio_community_api import (
    CHANGE_LOG_TYPES,
    GEOFENCE_MODES,
    KEY_USAGE_REPORT_TYPES,
    APIError,
    AsyncNimbioClient,
    BadRequestError,
    ConflictError,
    NimbioClient,
    NotFoundError,
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

_TAG = {
    "created_at": "2026-05-02T09:15:00+00:00",
    "disabled": False,
    "last_scan_at": "2026-08-17T18:42:11+00:00",
    "last_updated_datetime": "2026-08-17T18:42:11+00:00",
    "latch_id": "3f1c",
    "notes": "Unit 214 — resident fob",
    "tag_id": 4182,
    "tag_serial": "NFC-7K2MQ9XA",
    "tag_uid_hex": "04a1b2c3d4e580",
}

_SCAN = {
    "first_name": "Dana",
    "last_name": "Lee",
    "latch_id": "3f1c",
    "latch_name": "Pedestrian Gate",
    "open_outcome": "opened",
    "result": "ok",
    "scan_log_id": 90211,
    "scanned_at": "2026-08-17T18:42:11+00:00",
    "tag_id": 4182,
    "tag_serial": "NFC-7K2MQ9XA",
    "tag_uid_hex": "04a1b2c3d4e580",
}

_SENSE_LINE = {
    "box_id": "b1c2",
    "box_name": "Front Entrance Box",
    "created_at": "2026-01-04T18:02:11+00:00",
    "latch_data_online": True,
    "latches": [{"latch_id": "l1", "latch_name": "Main Gate"}],
    "reporting": True,
    "sense_line_id": 1,
    "sense_line_online": True,
    "updated_at": "2026-06-30T09:14:52+00:00",
}

_SENSE_LINE_DETAIL = {
    **_SENSE_LINE,
    "last_record": {"logged_at": "2026-08-17T22:41:07+00:00", "state": 0},
    "result": "ok",
    "status_map": [
        {"latch_id": "l1", "latch_name": "Main Gate", "sense_line_state": 0,
         "status": "Closed", "transient_ms": 0},
        {"latch_id": "l1", "latch_name": "Main Gate", "sense_line_state": 1,
         "status": "Open", "transient_ms": 1500},
    ],
}

_MAP = {
    "boxes": [
        {
            "box_id": "b1",
            "box_name": "Front Entry",
            "latches": [
                {
                    "box_id": "b1",
                    "box_location": {"latitude": 36.1699, "longitude": -115.1398},
                    "geofence": {
                        "center": {"latitude": 36.1699, "longitude": -115.1398},
                        "enabled": True,
                        "min_radius_meters": 100,
                        "mode": "prompt",
                        "radius_meters": 150,
                        "updated_by_account_id": "a1b2",
                        "updated_datetime": "2026-08-18T17:04:11+00:00",
                    },
                    "latch_id": "l1",
                    "latch_name": "Main Gate",
                },
                {
                    "box_id": "b1",
                    "box_location": {"latitude": 36.17, "longitude": -115.14},
                    "geofence": {"center": None, "enabled": False,
                                 "min_radius_meters": 100, "mode": "prompt",
                                 "radius_meters": 100},
                    "latch_id": "l2",
                    "latch_name": "Pool Gate",
                },
            ],
            "location": {"latitude": 36.1699, "longitude": -115.1398},
        }
    ],
    "community_location": {"latitude": 36.1699, "longitude": -115.1398},
    "geofence_modes": ["prompt", "auto_open"],
    "min_radius_meters": 100,
    "request_id": "b1c2",
    "result": "ok",
}


# -- NFC tags ----------------------------------------------------------------- #

@respx.mock
def test_nfc_tags_pages_and_reports_the_public_uid(client):
    route = respx.get(f"{PROD}/v1/community/nfc-tags").mock(
        return_value=httpx.Response(200, json={
            "items": [_TAG], "page": 2, "result": "ok",
            "results_per_page": 25, "total": 31}))

    page = client.community.nfc_tags(search="NFC-7K2", page=2,
                                     results_per_page=25)
    assert _params(route) == {"search": "NFC-7K2", "page": "2",
                              "results_per_page": "25"}
    assert page.total == 31
    assert page.page == 2
    assert len(page) == 1
    # The physical UID is the join key to the scan log, and is not a secret.
    assert [t.tag_uid_hex for t in page] == ["04a1b2c3d4e580"]
    assert page.items[0].assigned is True


@respx.mock
def test_nfc_tags_defaults_are_sent_explicitly(client):
    route = respx.get(f"{PROD}/v1/community/nfc-tags").mock(
        return_value=httpx.Response(200, json={"items": [], "result": "ok"}))

    assert len(client.community.nfc_tags()) == 0
    assert _params(route) == {"page": "1", "results_per_page": "50"}


@respx.mock
def test_nfc_tag_unwraps_the_envelope(client):
    respx.get(f"{PROD}/v1/community/nfc-tags/4182").mock(
        return_value=httpx.Response(200, json={"result": "ok", "tag": _TAG}))

    tag = client.community.nfc_tag(4182)
    assert tag.tag_id == 4182
    assert tag.tag_serial == "NFC-7K2MQ9XA"
    assert tag.notes == "Unit 214 — resident fob"


@respx.mock
def test_another_communitys_tag_is_indistinguishable_from_an_unknown_one(client):
    respx.get(f"{PROD}/v1/community/nfc-tags/999").mock(
        return_value=httpx.Response(404, json={
            "error": {"code": "tag_not_found", "message": "Tag not found"}}))

    with pytest.raises(NotFoundError) as e:
        client.community.nfc_tag(999)
    assert e.value.code == "tag_not_found"


@respx.mock
def test_update_nfc_tag_sends_only_what_you_asked_for(client):
    route = respx.patch(f"{PROD}/v1/community/nfc-tags/4182").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "tag": {**_TAG, "disabled": True}}))

    # Kill a lost fob without touching its gate binding.
    tag = client.community.update_nfc_tag(4182, disabled=True)
    assert _body(route) == {"disabled": True}
    assert tag.disabled is True


@respx.mock
def test_detaching_a_tag_is_not_the_same_as_leaving_it_alone(client):
    """`latch_id=None` detaches; omitting it must not send the field at all."""
    route = respx.patch(f"{PROD}/v1/community/nfc-tags/4182").mock(
        return_value=httpx.Response(200, json={
            "result": "ok", "tag": {**_TAG, "latch_id": None}}))

    detached = client.community.update_nfc_tag(4182, latch_id=None)
    assert _body(route) == {"latch_id": None}
    assert detached.assigned is False

    client.community.update_nfc_tag(4182, disabled=False)
    assert _body(route) == {"disabled": False}, "omitted latch_id leaked"


@respx.mock
def test_reviving_and_binding_in_one_call(client):
    """`disabled` is applied first, so False + a latch revives then binds."""
    route = respx.patch(f"{PROD}/v1/community/nfc-tags/4182").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "tag": {**_TAG, "disabled": False, "latch_id": "9b7c"}}))

    tag = client.community.update_nfc_tag(4182, disabled=False,
                                          latch_id="9b7c")
    assert _body(route) == {"disabled": False, "latch_id": "9b7c"}
    assert tag.latch_id == "9b7c"


@respx.mock
def test_a_dead_fob_cannot_be_routed_to_a_gate(client):
    respx.patch(f"{PROD}/v1/community/nfc-tags/4182").mock(
        return_value=httpx.Response(422, json={
            "error": {"code": "conflicting_fields",
                      "message": "A disabled tag cannot be assigned"}}))

    # 422 has no dedicated subclass; the code is what identifies it.
    with pytest.raises(APIError) as e:
        client.community.update_nfc_tag(4182, disabled=True, latch_id="9b7c")
    assert e.value.code == "conflicting_fields"


@respx.mock
def test_disabling_a_last_tag_is_a_warning_not_a_veto(client):
    """The 409 -> retry-with-confirm flow the docstring documents.

    A write that would leave a Scan Only gate with no working tag answers 409
    `requires_confirmation`. It is deliberately not a hard refusal — revoking a
    stolen fob has to stay possible — so ConflictError must be recoverable by
    repeating the call with confirm=True.
    """
    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        body = _json.loads(request.content)
        if not body.get("confirm"):
            return httpx.Response(409, json={"error": {
                "code": "requires_confirmation",
                "message": "Pedestrian Gate would be left with no working tag"}})
        return httpx.Response(200, json={
            "result": "ok", "tag": {**_TAG, "disabled": True}})

    respx.patch(f"{PROD}/v1/community/nfc-tags/4182").mock(side_effect=responder)

    with pytest.raises(ConflictError) as e:
        client.community.update_nfc_tag(4182, disabled=True)
    assert e.value.code == "requires_confirmation"
    assert e.value.status_code == 409

    tag = client.community.update_nfc_tag(4182, disabled=True, confirm=True)
    assert tag.disabled is True
    assert calls["n"] == 2


@respx.mock
def test_nfc_scan_log_filters_and_attributes_a_tap(client):
    route = respx.get(f"{PROD}/v1/community/nfc-tags/scan-log").mock(
        return_value=httpx.Response(200, json={
            "items": [_SCAN, {**_SCAN, "scan_log_id": 90210,
                              "first_name": None, "last_name": None,
                              "open_outcome": "did_not_open"}],
            "limit": 50, "offset": 0, "result": "ok", "total": 2}))

    page = client.community.nfc_scan_log(tag_uid_hex="04a1b2c3d4e580",
                                         result="ok", limit=10, offset=5)
    assert _params(route) == {"limit": "10", "offset": "5", "result": "ok",
                              "tag_uid_hex": "04a1b2c3d4e580"}
    assert len(page) == 2
    assert page.items[0].member_name == "Dana Lee"
    assert page.items[0].opened is True
    # A tap that resolved to nobody names nobody.
    assert page.items[1].member_name is None
    assert page.items[1].opened is False


# -- sense lines --------------------------------------------------------------- #

@respx.mock
def test_sense_lines_derives_the_answer_you_usually_want(client):
    route = respx.get(f"{PROD}/v1/community/sense-lines").mock(
        return_value=httpx.Response(200, json={
            "boxes": [{"box_id": "b1c2", "box_name": "Front Entrance Box",
                       "latches": [{"latch_id": "l1",
                                    "latch_name": "Main Gate"}]}],
            "result": "ok",
            "sense_lines": [
                _SENSE_LINE,
                # Wired and switched on, but barred from driving gate status:
                # this is the "gate stuck on one status" configuration.
                {**_SENSE_LINE, "sense_line_id": 2, "latch_data_online": False,
                 "reporting": False},
            ]}))

    lines = client.community.sense_lines(box_id="b1c2")
    assert _params(route) == {"box_id": "b1c2"}
    assert len(lines) == 2
    assert [x.sense_line_id for x in lines.not_reporting] == [2]
    assert lines.for_box("b1c2") == list(lines)
    assert lines.boxes[0].latches[0].latch_name == "Main Gate"


@respx.mock
def test_sense_lines_box_id_is_a_filter_and_may_be_omitted(client):
    route = respx.get(f"{PROD}/v1/community/sense-lines").mock(
        return_value=httpx.Response(200, json={"result": "ok",
                                               "sense_lines": []}))

    assert len(client.community.sense_lines()) == 0
    assert _params(route) == {}


def test_reporting_is_computed_when_an_older_server_omits_it():
    """`reporting` is derived, so the model can answer even without the field."""
    both_on = models.SenseLine.from_dict(
        {"sense_line_id": 1, "sense_line_online": True,
         "latch_data_online": True})
    one_off = models.SenseLine.from_dict(
        {"sense_line_id": 1, "sense_line_online": True,
         "latch_data_online": False})
    assert both_on.reporting is True
    assert one_off.reporting is False


def test_sense_line_requires_a_box_id():
    """A sense line id is an input number unique only within its box.

    The OpenAPI schema marks `box_id` optional (the handler validates it), but
    omitting it is a 422 `box_id_required`, so both single-sense-line calls
    take it as a required positional argument — a TypeError here rather than a
    round trip that was never going to work.
    """
    c = NimbioClient("nimbio_test_x", max_retries=0)
    with pytest.raises(TypeError):
        c.community.sense_line(1)
    with pytest.raises(TypeError):
        c.community.update_sense_line(1, sense_line_online=False)
    ac = AsyncNimbioClient("nimbio_test_x", max_retries=0)
    with pytest.raises(TypeError):
        ac.community.sense_line(1)
    c.close()


@respx.mock
def test_sense_line_detail_explains_a_gates_status(client):
    route = respx.get(f"{PROD}/v1/community/sense-lines/1").mock(
        return_value=httpx.Response(200, json=_SENSE_LINE_DETAIL))

    line = client.community.sense_line(1, "b1c2")
    assert _params(route) == {"box_id": "b1c2"}
    assert line.reporting is True
    assert line.status_for(0) == "Closed"
    assert line.status_for(1) == "Open"
    # An unmapped state has no configured meaning — a finding, not an error.
    assert line.status_for(7) is None
    assert line.status_map[1].transient is True
    assert line.status_map[0].transient is False
    assert line.last_record.logged_at == "2026-08-17T22:41:07+00:00"


@respx.mock
def test_update_sense_line_writes_configuration_only(client):
    route = respx.patch(f"{PROD}/v1/community/sense-lines/1").mock(
        return_value=httpx.Response(200, json={
            **_SENSE_LINE_DETAIL, "reporting": False,
            "sense_line_online": False}))

    line = client.community.update_sense_line(1, "b1c2",
                                              sense_line_online=False)
    assert _params(route) == {"box_id": "b1c2"}
    # Only the flag asked for — an omitted flag is left exactly as it was.
    assert _body(route) == {"sense_line_online": False}
    assert line.reporting is False

    client.community.update_sense_line(1, "b1c2", sense_line_online=True,
                                       latch_data_online=True)
    assert _body(route) == {"sense_line_online": True,
                            "latch_data_online": True}


@respx.mock
def test_records_are_written_even_when_a_line_is_switched_off(client):
    """The property that makes this the endpoint to reach for.

    A healthy record stream alongside a stale gate status is proof the wiring
    is fine and the configuration is not — so the SDK must surface these rows
    including the ones whose state has no configured label.
    """
    route = respx.get(f"{PROD}/v1/community/sense-lines/records").mock(
        return_value=httpx.Response(200, json={
            "has_more": True, "limit": 50, "offset": 0, "result": "ok",
            "records": [
                {"box_id": "b1c2", "box_name": "Front Entrance Box",
                 "logged_at": "2026-08-17T22:41:07+00:00", "sense_line_id": 1,
                 "state": 1, "status": "Open"},
                {"box_id": "b1c2", "box_name": "Front Entrance Box",
                 "logged_at": "2026-08-17T22:40:12+00:00", "sense_line_id": 1,
                 "state": 3, "status": None},
            ]}))

    page = client.community.sense_line_records(box_id="b1c2", sense_line_id=1,
                                               limit=25, offset=50)
    assert _params(route) == {"box_id": "b1c2", "sense_line_id": "1",
                              "limit": "25", "offset": "50"}
    assert page.has_more is True
    assert len(page) == 2
    assert [r.state for r in page.unmapped] == [3]


# -- map and geofences --------------------------------------------------------- #

@respx.mock
def test_map_reports_the_limits_the_server_will_enforce(client):
    respx.get(f"{PROD}/v1/community/map").mock(
        return_value=httpx.Response(200, json=_MAP))

    m = client.community.map()
    assert m.min_radius_meters == 100
    assert list(m.geofence_modes) == list(GEOFENCE_MODES)
    assert m.community_location.latitude == 36.1699
    assert [x.latch_id for x in m.latches] == ["l1", "l2"]
    assert m.latch("l1").geofence.radius_meters == 150
    assert m.latch("nope") is None
    # A gate with no centre has never had one configured — its device's
    # location is the suggested starting point.
    assert [x.latch_id for x in m.unconfigured] == ["l2"]
    assert m.latch("l2").geofence.configured is False
    assert m.latch("l2").suggested_center.latitude == 36.17
    assert m.latch("l1").suggested_center.latitude == 36.1699


@respx.mock
def test_update_geofence_is_a_partial_update(client):
    route = respx.patch(f"{PROD}/v1/community/latches/l1/geofence").mock(
        return_value=httpx.Response(200, json={
            "latch": _MAP["boxes"][0]["latches"][0], "request_id": "b1c2",
            "result": "ok"}))

    latch = client.community.update_geofence("l1", enabled=True, mode="prompt")
    assert _body(route) == {"enabled": True, "mode": "prompt"}
    assert latch.latch_id == "l1"
    assert latch.geofence.enabled is True

    # Centre and radius move together with nothing else disturbed.
    client.community.update_geofence("l1", latitude=36.1699,
                                     longitude=-115.1398, radius_meters=250)
    assert _body(route) == {"latitude": 36.1699, "longitude": -115.1398,
                            "radius_meters": 250}


@respx.mock
def test_a_radius_below_the_minimum_is_rejected_not_clamped(client):
    """The SDK must forward a too-small radius untouched.

    Clamping client-side would produce a fence that reads as configured and
    never fires, because Android/iOS region monitoring degrades below ~100 m.
    The 422 is the point.
    """
    route = respx.patch(f"{PROD}/v1/community/latches/l1/geofence").mock(
        return_value=httpx.Response(422, json={
            "error": {"code": "radius_below_minimum",
                      "message": "radius_meters must be at least 100"}}))

    with pytest.raises(APIError) as e:
        client.community.update_geofence("l1", radius_meters=40)
    assert e.value.code == "radius_below_minimum"
    assert _body(route) == {"radius_meters": 40}, "the SDK clamped the radius"


@respx.mock
def test_a_geofence_patch_with_nothing_to_change_is_a_400(client):
    respx.patch(f"{PROD}/v1/community/latches/l1/geofence").mock(
        return_value=httpx.Response(400, json={
            "error": {"code": "nothing_to_update", "message": "No fields"}}))

    with pytest.raises(BadRequestError) as e:
        client.community.update_geofence("l1")
    assert e.value.code == "nothing_to_update"


# -- audit trails --------------------------------------------------------------- #

@respx.mock
def test_change_logs_reports_the_window_it_actually_used(client):
    route = respx.get(f"{PROD}/v1/community/change-logs").mock(
        return_value=httpx.Response(200, json={
            "days": 30, "from": "2026-05-11T17:04:03+00:00", "has_more": False,
            "limit": 500, "log_type": "guest_link", "offset": 0,
            "result": "ok", "to": "2026-06-10T17:04:03+00:00", "total": 1,
            "logs": [{
                "account_display_name": "Dana Lee", "account_id": "a1b2",
                "action_type": "link_created",
                "datetime": "2026-06-06T11:05:55+00:00",
                "details": {"guest_link_id": 733}, "log_id": 733,
                "log_type": "guest_link",
                "summary": "Created event link #733"}]}))

    # A look-back above the retention cap is clamped, not rejected.
    page = client.community.change_logs("guest_link", days=365)
    assert _params(route) == {"type": "guest_link", "days": "365",
                              "limit": "500", "offset": "0"}
    assert page.days == 30
    assert page.log_type == "guest_link"
    assert page.date_from == "2026-05-11T17:04:03+00:00"
    assert page.date_to == "2026-06-10T17:04:03+00:00"
    assert len(page) == 1
    assert [x.summary for x in page] == ["Created event link #733"]
    assert page.logs[0].details == {"guest_link_id": 733}


@respx.mock
def test_key_usage_says_how_it_attributed_each_row(client):
    """`report_type` decides what `user` means, and the server chooses it."""
    route = respx.get(f"{PROD}/v1/community/key-usage").mock(
        return_value=httpx.Response(200, json={
            "clamped": True, "from": "2026-05-28", "has_more": False,
            "max_range_days": 14, "page": 0, "report_type": "residential",
            "requested_from": "2026-01-01", "requested_to": "2026-06-10",
            "result": "ok", "timezone": "America/Los_Angeles", "to": "2026-06-10",
            "logs": [{"datetime": "2026-06-09T11:02:00",
                      "key_name": "Front Gate", "latch_name": "Front Gate",
                      "open_desc": "Open", "open_result": "Opened",
                      "phone": "+15551234567", "location": "Mobile",
                      "reason_desc": "Master", "source": "Mobile",
                      "user": "Dana Lee Keychain"}]}))

    report = client.community.key_usage("2026-01-01", "2026-06-10", page=0)
    assert _params(route) == {"from": "2026-01-01", "to": "2026-06-10",
                              "page": "0"}
    assert report.residential is True
    assert report.report_type in KEY_USAGE_REPORT_TYPES
    # The window was clamped: read what was used, not what you asked for.
    assert report.clamped is True
    assert (report.date_from, report.date_to) == ("2026-05-28", "2026-06-10")
    assert (report.requested_from, report.requested_to) == ("2026-01-01",
                                                            "2026-06-10")
    assert report.timezone == "America/Los_Angeles"
    assert len(report) == 1
    assert [row.user for row in report] == ["Dana Lee Keychain"]
    assert report.logs[0].phone == "+15551234567"


def test_commercial_and_residential_reports_differ_in_what_user_means():
    commercial = models.KeyUsageReport.from_dict(
        {"report_type": "commercial", "logs": [{"user": "Dana Lee"}]})
    assert commercial.residential is False
    assert commercial.logs[0].user == "Dana Lee"


def test_residential_is_one_sided():
    """`residential is False` means "not the household rule", NOT "commercial".

    An attribution rule this release predates reads False here too, so nothing
    may treat the accessor as a two-way switch — read `report_type` itself to
    tell commercial from something new.
    """
    future = models.KeyUsageReport.from_dict(
        {"report_type": "future_rule", "logs": [{"user": "Dana Lee"}]})
    assert future.residential is False
    assert future.report_type not in KEY_USAGE_REPORT_TYPES
    # An absent report_type reads False as well, and says just as little.
    assert models.KeyUsageReport.from_dict({}).residential is False


# -- constants ------------------------------------------------------------------ #

def test_wave4_vocabularies():
    assert GEOFENCE_MODES == ("prompt", "auto_open")
    assert CHANGE_LOG_TYPES == ("hold_open", "key_schedule", "guest_view",
                                "guest_link")
    assert KEY_USAGE_REPORT_TYPES == ("commercial", "residential")


def test_test_mode_writes_report_themselves_as_simulated():
    """Every wave-4 write echoes `result`, so a test key is visible as one."""
    assert models.NfcTag.from_dict(
        {"result": "simulated", "tag": _TAG}).simulated is True
    assert models.SenseLine.from_dict(
        {**_SENSE_LINE_DETAIL, "result": "simulated"}).simulated is True
    assert models.MapLatch.from_dict(
        {"result": "simulated",
         "latch": _MAP["boxes"][0]["latches"][0]}).simulated is True
    assert models.NfcTag.from_dict({"tag": _TAG}).simulated is False


def test_the_paged_reads_iterate_their_rows():
    scans = models.NfcScanLogPage.from_dict({"items": [_SCAN]})
    records = models.SenseLineRecordPage.from_dict(
        {"records": [{"logged_at": "2026-08-17T22:41:07+00:00", "state": 1}]})
    assert [x.scan_log_id for x in scans] == [90211]
    assert [x.state for x in records] == [1]


def test_the_unset_sentinel_reprs_readably():
    """It shows up as a signature default, so it must not print as an address."""
    from nimbio_community_api._base import UNSET

    assert repr(UNSET) == "UNSET"


# -- both clients --------------------------------------------------------------- #

WAVE4_METHODS = (
    "nfc_tags",
    "nfc_tag",
    "update_nfc_tag",
    "nfc_scan_log",
    "sense_lines",
    "sense_line",
    "update_sense_line",
    "sense_line_records",
    "map",
    "update_geofence",
    "change_logs",
    "key_usage",
)


def test_both_clients_expose_every_wave4_method():
    """The two clients must not drift: a method that lands on only one of them
    is a silent gap for half the users."""
    sync_community = NimbioClient("nimbio_test_x").community
    async_community = AsyncNimbioClient("nimbio_test_x").community
    for name in WAVE4_METHODS:
        assert hasattr(sync_community, name), f"sync client missing {name}"
        assert hasattr(async_community, name), f"async client missing {name}"


@respx.mock
async def test_async_nfc_family(test_key):
    respx.get(f"{PROD}/v1/community/nfc-tags").mock(
        return_value=httpx.Response(200, json={
            "items": [_TAG], "page": 1, "result": "ok",
            "results_per_page": 50, "total": 1}))
    respx.get(f"{PROD}/v1/community/nfc-tags/scan-log").mock(
        return_value=httpx.Response(200, json={
            "items": [_SCAN], "limit": 50, "offset": 0, "result": "ok",
            "total": 1}))
    respx.get(f"{PROD}/v1/community/nfc-tags/4182").mock(
        return_value=httpx.Response(200, json={"result": "ok", "tag": _TAG}))

    calls = {"n": 0}

    def responder(request):
        calls["n"] += 1
        if not _json.loads(request.content).get("confirm"):
            return httpx.Response(409, json={"error": {
                "code": "requires_confirmation", "message": "last tag"}})
        return httpx.Response(200, json={"result": "ok",
                                         "tag": {**_TAG, "disabled": True}})

    patch_route = respx.patch(
        f"{PROD}/v1/community/nfc-tags/4182").mock(side_effect=responder)

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        assert [t.tag_id for t in await client.community.nfc_tags()] == [4182]
        assert (await client.community.nfc_tag(4182)).assigned is True

        scans = await client.community.nfc_scan_log(result="ok")
        assert scans.items[0].member_name == "Dana Lee"

        # The 409 is recoverable on the async client too.
        with pytest.raises(ConflictError) as e:
            await client.community.update_nfc_tag(4182, disabled=True)
        assert e.value.code == "requires_confirmation"

        tag = await client.community.update_nfc_tag(4182, disabled=True,
                                                    confirm=True)
        assert tag.disabled is True
        assert _body(patch_route) == {"disabled": True, "confirm": True}
        assert calls["n"] == 2

        # Omitted latch_id must not leak on the async wrapper either.
        await client.community.update_nfc_tag(4182, latch_id=None,
                                              confirm=True)
        assert _body(patch_route) == {"latch_id": None, "confirm": True}


@respx.mock
async def test_async_sense_lines_map_and_audit(test_key):
    respx.get(f"{PROD}/v1/community/sense-lines").mock(
        return_value=httpx.Response(200, json={
            "result": "ok",
            "sense_lines": [{**_SENSE_LINE, "latch_data_online": False,
                             "reporting": False}]}))
    detail_route = respx.get(f"{PROD}/v1/community/sense-lines/1").mock(
        return_value=httpx.Response(200, json=_SENSE_LINE_DETAIL))
    patch_route = respx.patch(f"{PROD}/v1/community/sense-lines/1").mock(
        return_value=httpx.Response(200, json=_SENSE_LINE_DETAIL))
    records_route = respx.get(f"{PROD}/v1/community/sense-lines/records").mock(
        return_value=httpx.Response(200, json={
            "has_more": False, "limit": 50, "offset": 0, "result": "ok",
            "records": [{"logged_at": "2026-08-17T22:41:07+00:00",
                         "sense_line_id": 1, "state": 1, "status": "Open"}]}))
    respx.get(f"{PROD}/v1/community/map").mock(
        return_value=httpx.Response(200, json=_MAP))
    geofence_route = respx.patch(
        f"{PROD}/v1/community/latches/l1/geofence").mock(
        return_value=httpx.Response(200, json={
            "latch": _MAP["boxes"][0]["latches"][0], "result": "ok"}))
    change_route = respx.get(f"{PROD}/v1/community/change-logs").mock(
        return_value=httpx.Response(200, json={
            "days": 7, "has_more": False, "limit": 500, "log_type": "hold_open",
            "logs": [], "offset": 0, "result": "ok", "total": 0}))
    usage_route = respx.get(f"{PROD}/v1/community/key-usage").mock(
        return_value=httpx.Response(200, json={
            "clamped": False, "from": "2026-06-01", "has_more": False,
            "logs": [], "page": 1, "report_type": "commercial",
            "result": "ok", "to": "2026-06-10"}))

    async with AsyncNimbioClient(test_key, max_retries=0) as client:
        lines = await client.community.sense_lines()
        assert len(lines.not_reporting) == 1

        line = await client.community.sense_line(1, "b1c2")
        assert _params(detail_route) == {"box_id": "b1c2"}
        assert line.status_for(1) == "Open"

        await client.community.update_sense_line(1, "b1c2",
                                                 latch_data_online=True)
        assert _params(patch_route) == {"box_id": "b1c2"}
        assert _body(patch_route) == {"latch_data_online": True}

        page = await client.community.sense_line_records(limit=10)
        assert _params(records_route) == {"limit": "10", "offset": "0"}
        assert len(page) == 1

        m = await client.community.map()
        assert m.min_radius_meters == 100

        latch = await client.community.update_geofence("l1", enabled=False)
        assert _body(geofence_route) == {"enabled": False}
        assert latch.latch_id == "l1"

        logs = await client.community.change_logs("hold_open", days=7,
                                                  limit=100, offset=10)
        assert _params(change_route) == {"type": "hold_open", "days": "7",
                                         "limit": "100", "offset": "10"}
        assert logs.log_type == "hold_open"

        report = await client.community.key_usage("2026-06-01", "2026-06-10",
                                                  page=1)
        assert _params(usage_route) == {"from": "2026-06-01", "to": "2026-06-10",
                                        "page": "1"}
        assert report.residential is False
