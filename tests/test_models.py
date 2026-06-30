"""Unit tests for the response models: tolerant parsing, properties, .raw."""

from nimbio_community_api import models as m


def test_me_full_and_empty():
    me = m.Me.from_dict({"account_id": "a1", "key": {
        "api_key_id": "k1", "prefix": "nimbio_test_x", "name": "N", "mode": "test",
        "last_used_datetime": "2026-06-10T12:00:00+00:00",
        "minute_limit": 60, "minute_count": 1, "month_limit": 100, "month_count": 5}})
    assert me.account_id == "a1"
    assert me.key.mode == "test"
    assert me.key.month_count == 5
    assert me.raw["account_id"] == "a1"

    empty = m.Me.from_dict({})
    assert empty.account_id is None
    assert empty.key.api_key_id is None
    assert empty.key.raw == {}


def test_me_handles_non_dict():
    me = m.Me.from_dict(None)
    assert me.account_id is None
    assert me.key.mode is None


def test_health():
    h = m.Health.from_dict({"ok": True, "wamp": "connected"})
    assert h.ok is True and h.wamp == "connected"
    assert m.Health.from_dict({}).ok is False


def test_latch_aliases_id_and_name():
    # Falls back from latch_id/latch_name to id/name.
    latch = m.Latch.from_dict({"id": "l1", "name": "Gate", "status": "open",
                               "offline": 1})
    assert latch.latch_id == "l1"
    assert latch.latch_name == "Gate"
    assert latch.offline is True


def test_gate_status_list():
    gs = m.GateStatus.from_dict({"latches": [
        {"latch_id": "l1", "latch_name": "A"},
        {"latch_id": "l2", "latch_name": "B", "offline": True}]})
    assert [x.latch_id for x in gs.latches] == ["l1", "l2"]
    assert gs.latches[1].offline is True
    assert m.GateStatus.from_dict({}).latches == []


def test_member_full_name():
    member = m.Member.from_dict({"account_community_id": 1, "first_name": "Dana",
                                 "last_name": "Lee", "phone_number": "+1555"})
    assert member.full_name == "Dana Lee"
    assert m.Member.from_dict({"first_name": "Solo"}).full_name == "Solo"
    assert m.Member.from_dict({}).full_name == ""


def test_members_buckets():
    members = m.Members.from_dict({
        "accepted": [{"account_community_id": 1}],
        "unaccepted": [{"account_community_id": 2}],
        "removed": [],
    })
    assert members.accepted[0].account_community_id == 1
    assert members.unaccepted[0].account_community_id == 2
    assert members.removed == []
    empty = m.Members.from_dict({})
    assert empty.accepted == [] and empty.unaccepted == [] and empty.removed == []


def test_community_key_nested_kept_as_dicts():
    key = m.CommunityKey.from_dict({
        "id": "k1", "name": "Front", "disabled": True, "hidden": False,
        "pending": False, "is_favorite": True,
        "sharing": {"allow_subkeys": True, "max_share_depth": 2},
        "expiry": {"expires_at": "2026", "active": True},
        "temporal": {"enabled": True, "windows": [{"days": "Mon"}]},
        "latches": [{"latch_id": "l1", "name": "Front Gate"}]})
    assert key.id == "k1"
    assert key.disabled is True and key.is_favorite is True
    assert key.sharing["max_share_depth"] == 2
    assert key.expiry["active"] is True
    assert key.temporal["windows"][0]["days"] == "Mon"
    assert key.latches[0]["latch_id"] == "l1"

    bare = m.CommunityKey.from_dict({"id": "k2"})
    assert bare.sharing == {} and bare.latches == []


def test_key_statuses():
    ks = m.KeyStatuses.from_dict({"keys": [{"id": "k1"}], "hold_opens": {"a": 1}})
    assert ks.keys[0]["id"] == "k1"
    assert ks.hold_opens == {"a": 1}
    assert m.KeyStatuses.from_dict({}).keys == []


def test_open_result_properties():
    opened = m.OpenResult.from_dict({"result": "opened", "request_id": "r1",
                                     "key_log_id": 9001})
    assert opened.opened is True and opened.simulated is False
    assert opened.key_log_id == 9001

    sim = m.OpenResult.from_dict({"result": "simulated", "request_id": "r2",
                                  "latch_id": "l1"})
    assert sim.simulated is True and sim.opened is False
    assert sim.latch_id == "l1"


def test_write_result_access_helpers():
    wr = m.WriteResult.from_dict({"result": "keys_granted", "request_id": "r1",
                                  "account_community_id": 4021,
                                  "granted": {"created": ["k1"]}})
    assert wr.result == "keys_granted"
    assert wr.simulated is False
    assert wr["account_community_id"] == 4021
    assert wr.get("granted")["created"] == ["k1"]
    assert wr.get("missing", "default") == "default"

    sim = m.WriteResult.from_dict({"result": "simulated", "request_id": "r2"})
    assert sim.simulated is True


def test_write_result_getitem_raises_keyerror():
    wr = m.WriteResult.from_dict({"result": "sent"})
    import pytest
    with pytest.raises(KeyError):
        _ = wr["does_not_exist"]


def test_access_log_page():
    page = m.AccessLogPage.from_dict({
        "page": 0, "has_more": True, "from": "2026-03-12", "to": "2026-06-10",
        "logs": [{"key_name": "Front", "latch_name": "Gate", "user": "Dana",
                  "phone": "+1555", "location": "Front", "open_desc": "Opened",
                  "open_result": "success", "reason_desc": "", "source": "app",
                  "datetime": "2026-06-09T18:02:00+00:00"}]})
    assert page.has_more is True
    assert page.date_from == "2026-03-12" and page.date_to == "2026-06-10"
    row = page.logs[0]
    assert row.key_name == "Front" and row.user == "Dana" and row.source == "app"
    assert m.AccessLogPage.from_dict({}).logs == []


def test_member_access_log_page():
    page = m.MemberAccessLogPage.from_dict({
        "account_community_id": 4021, "window": "last_30", "truncated": True,
        "from": "2026-05-11", "to": "2026-06-10", "logs": [{"key_name": "A"}]})
    assert page.account_community_id == 4021
    assert page.window == "last_30" and page.truncated is True
    assert page.logs[0].key_name == "A"


def test_gate_status_log_page():
    page = m.GateStatusLogPage.from_dict({
        "page": 1, "has_more": False, "logs": [
            {"datetime": "t", "latch_name": "Gate", "status_label": "Opened",
             "sense_line": 1, "state": "open"}]})
    assert page.page == 1 and page.has_more is False
    entry = page.logs[0]
    assert entry.status_label == "Opened" and entry.sense_line == 1
    assert entry.state == "open"
    assert m.GateStatusLogPage.from_dict({}).logs == []


def test_unknown_fields_preserved_on_raw():
    # Forward-compat: server adds a field the model doesn't surface yet.
    me = m.Me.from_dict({"account_id": "a1", "key": {}, "new_server_field": 42})
    assert me.raw["new_server_field"] == 42
