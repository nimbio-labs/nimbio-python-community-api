"""The shipped vocabularies and the capability helper.

These exist so callers stop hand-typing capability and event-type strings — a
typo there is a silent False, not an error — so what matters is that the names
are exactly the server's and that nothing here rejects a value it has not seen.
"""

import re
from pathlib import Path

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
        "settings", "sense_lines", "nfc_tags", "access_code_mode")
    assert len(CAPABILITIES) == 22
    assert len(set(CAPABILITIES)) == 22


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
                "STREAM_EVENT_TYPES", "ACCOUNT_EVENT_TYPES",
                "DIRECTORY_CALL_OUTCOMES", "OPEN_HISTORY_TYPES",
                "OPEN_HISTORY_RESULTS", "GUEST_LINK_TYPES", "GUEST_LINK_STATES",
                "GEOFENCE_MODES", "CHANGE_LOG_TYPES", "KEY_USAGE_REPORT_TYPES",
                "has_capability"]
    assert constants.__all__ == expected
    assert dir(constants) == sorted(expected)  # dir() sorts what __dir__ returns
    for name in expected:
        assert hasattr(constants, name)


def test_account_keys_get_open_directory_call_events_and_open_history():
    assert constants.ACCOUNT_KEY_CAPABILITIES == (
        "open", "directory_call_events", "open_history")
    # "open" is shared; the other two are account-only.
    assert set(constants.ACCOUNT_KEY_CAPABILITIES) & set(CAPABILITIES) == {"open"}


def test_account_stream_vocabularies():
    assert constants.ACCOUNT_EVENT_TYPES == (
        "directory_call.ringing", "directory_call.ended")
    # Separate streams, separate filters: no name belongs to both.
    assert not set(constants.ACCOUNT_EVENT_TYPES) & set(STREAM_EVENT_TYPES)
    assert constants.DIRECTORY_CALL_OUTCOMES == ("opened", "answered", "missed")


@pytest.mark.parametrize("vocabulary", [CAPABILITIES, STREAM_EVENT_TYPES,
                                        GUEST_LINK_TYPES, GUEST_LINK_STATES,
                                        constants.GEOFENCE_MODES,
                                        constants.CHANGE_LOG_TYPES,
                                        constants.KEY_USAGE_REPORT_TYPES,
                                        constants.ACCOUNT_EVENT_TYPES,
                                        constants.DIRECTORY_CALL_OUTCOMES,
                                        constants.OPEN_HISTORY_TYPES,
                                        constants.OPEN_HISTORY_RESULTS])
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


def test_open_history_vocabularies():
    """The contract's id -> name maps, in id order, plus ``unknown``."""
    assert constants.OPEN_HISTORY_TYPES == (
        "open", "do_not_open", "emergency_open", "emergency_fail",
        "doorbell_or_emergency_prompt", "bluetooth_unlock", "bluetooth_lock",
        "unlock", "do_not_unlock", "lock", "do_not_lock", "unknown")
    assert constants.OPEN_HISTORY_RESULTS == (
        "opened", "did_not_open", "locked", "did_not_lock",
        "fail_open_trying_bluetooth", "fail_lock_trying_bluetooth",
        "unlock_bluetooth", "lock_bluetooth", "fail_lock_bluetooth",
        "fail_unlock_bluetooth", "unused_bluetooth", "lock_already_unlocked",
        "lock_already_locked", "unlocked", "did_not_unlock", "unknown")
    for vocab in (constants.OPEN_HISTORY_TYPES, constants.OPEN_HISTORY_RESULTS):
        assert len(set(vocab)) == len(vocab)


_NPM_CONSTANTS = (Path(__file__).resolve().parents[2]
                  / "nimbio-npm-community-api" / "src" / "constants.ts")


@pytest.mark.parametrize("name", ["OPEN_HISTORY_TYPES", "OPEN_HISTORY_RESULTS"])
def test_open_history_vocabularies_match_the_npm_sdk(name):
    """The two SDKs are peers; a vocabulary must not drift between them. Runs
    only where the npm SDK is checked out alongside this repo."""
    if not _NPM_CONSTANTS.is_file():
        pytest.skip("nimbio-npm-community-api is not checked out alongside")
    m = re.search(rf"export const {name} = Object\.freeze\(\[(.*?)\]",
                  _NPM_CONSTANTS.read_text(encoding="utf-8"), re.S)
    assert m, f"{name} not found in the npm SDK"
    assert tuple(re.findall(r'"([^"]+)"', m.group(1))) == getattr(constants, name)
