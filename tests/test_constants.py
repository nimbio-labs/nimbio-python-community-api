"""The shipped vocabularies and the capability helper.

These exist so callers stop hand-typing capability and event-type strings — a
typo there is a silent False, not an error — so what matters is that the names
are exactly the server's and that nothing here rejects a value it has not seen.
"""

import pytest

from nimbio_community_api import (
    CAPABILITIES,
    GUEST_LINK_STATES,
    GUEST_LINK_TYPES,
    STREAM_EVENT_TYPES,
    constants,
    has_capability,
    models,
)


def test_capabilities_are_the_api_declared_names():
    assert CAPABILITIES == (
        "open", "gate_status", "key_statuses", "hold_opens", "webhooks",
        "members", "messages", "access_logs", "key_schedules", "key_usage",
        "change_logs", "homes", "short_codes", "guest_view_entry",
        "access_codes", "guest_links", "map", "open_notifications",
        "settings", "sense_lines", "nfc_tags")
    assert len(CAPABILITIES) == 21
    assert len(set(CAPABILITIES)) == 21


def test_stream_event_types_are_the_servers_ten():
    assert STREAM_EVENT_TYPES == (
        "sense_line.changed", "open.succeeded", "open.failed", "device.online",
        "device.offline", "hold_open.changed", "member.requested",
        "member.approved", "member.removed", "directory.call")
    assert len(STREAM_EVENT_TYPES) == 10


def test_there_is_exactly_one_event_vocabulary():
    """Webhook subscriptions and the SSE stream take the same names from the
    same server-side source. A second constant would invite callers to believe
    they are different sets — and would duplicate a live endpoint
    (`webhook_event_types()`) that can never go stale."""
    assert not [n for n in dir(constants) if "WEBHOOK" in n]


def test_the_public_namespace_is_only_the_intended_names():
    """This module is browsed for a name to reference, so the typing imports it
    needs must not sit in the listing alongside the vocabularies."""
    expected = ["CAPABILITIES", "ACCOUNT_KEY_CAPABILITIES",
                "STREAM_EVENT_TYPES", "GUEST_LINK_TYPES", "GUEST_LINK_STATES",
                "GEOFENCE_MODES", "CHANGE_LOG_TYPES", "KEY_USAGE_REPORT_TYPES",
                "has_capability"]
    assert constants.__all__ == expected
    assert dir(constants) == sorted(expected)  # dir() sorts what __dir__ returns
    for name in expected:
        assert hasattr(constants, name)


def test_account_keys_only_ever_get_open():
    assert constants.ACCOUNT_KEY_CAPABILITIES == ("open",)
    assert set(constants.ACCOUNT_KEY_CAPABILITIES) <= set(CAPABILITIES)


@pytest.mark.parametrize("vocabulary", [CAPABILITIES, STREAM_EVENT_TYPES,
                                        GUEST_LINK_TYPES, GUEST_LINK_STATES,
                                        constants.GEOFENCE_MODES,
                                        constants.CHANGE_LOG_TYPES,
                                        constants.KEY_USAGE_REPORT_TYPES])
def test_the_vocabularies_are_immutable(vocabulary):
    """Callers reference these; a caller must not be able to edit them for
    everyone else in the process."""
    with pytest.raises((AttributeError, TypeError)):
        vocabulary.append("nope")  # type: ignore[attr-defined]


def test_has_capability_reads_a_key_capability_list():
    assert has_capability(["open", "hold_opens"], "hold_opens") is True
    assert has_capability(["open"], "hold_opens") is False


def test_has_capability_tolerates_nothing_to_check():
    assert has_capability([], "open") is False
    assert has_capability(None, "open") is False  # type: ignore[arg-type]


def test_an_unknown_capability_is_answered_not_rejected():
    """The server may add capabilities at any time; an older client must keep
    working rather than raising on a name it has never heard of."""
    assert has_capability(["a_capability_from_the_future"],
                          "a_capability_from_the_future") is True
    assert has_capability(["open"], "a_capability_from_the_future") is False


def test_api_key_info_answers_for_itself():
    key = models.ApiKeyInfo.from_dict(
        {"type": "community", "capabilities": ["open", "webhooks"]})
    assert key.has_capability("webhooks") is True
    assert key.has_capability("nfc_tags") is False


def test_a_key_that_reported_no_capabilities_has_none():
    assert models.ApiKeyInfo.from_dict({}).has_capability("open") is False
