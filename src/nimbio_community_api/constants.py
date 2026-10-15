"""The server's known vocabularies, shipped as constants.

``me().key.capabilities``, a stream/webhook event's ``type``, a guest link's
``state`` — all plain strings. Hand-typing one is a silent false negative —
``"hold_open"`` is not ``"hold_opens"``, and the check just returns False
forever — so the names live here instead, next to the client that compares
against them.

Two kinds live here, and they earn their place differently. A few are
*arguments* you send (:data:`GUEST_LINK_TYPES`, :data:`GEOFENCE_MODES`,
:data:`CHANGE_LOG_TYPES`): a typo there is **loud**, because the server answers
422 immediately, so those are for autocomplete. The rest are *response* values
you compare against (:data:`GUEST_LINK_STATES`,
:data:`KEY_USAGE_REPORT_TYPES`, :data:`CAPABILITIES`), where a typo is
**silent** — a False that never explains itself and leaves a dead link looking
live, or a household's opens looking like one person's.

Every list is *open*: the server may add to any of them at any time and an
older client must keep working. Nothing here rejects a value it does not
recognise, and nothing in this SDK filters a response against these tuples.
Treat them as the names you can reference, not as an exhaustive set to validate
against.
"""

from __future__ import annotations

from typing import Iterable, Tuple

__all__ = [
    "CAPABILITIES",
    "ACCOUNT_KEY_CAPABILITIES",
    "STREAM_EVENT_TYPES",
    "ACCOUNT_EVENT_TYPES",
    "DIRECTORY_CALL_OUTCOMES",
    "OPEN_HISTORY_TYPES",
    "OPEN_HISTORY_RESULTS",
    "GUEST_LINK_TYPES",
    "GUEST_LINK_STATES",
    "GEOFENCE_MODES",
    "CHANGE_LOG_TYPES",
    "KEY_USAGE_REPORT_TYPES",
    "has_capability",
]


def __dir__() -> list:
    """Keep ``dir(constants)`` to the public names.

    This module is something callers *browse* for a name to reference, so the
    typing imports it happens to need should not sit in the list alongside the
    vocabularies (PEP 562).
    """
    return list(__all__)

# --------------------------------------------------------------------------- #
# API key capabilities
# --------------------------------------------------------------------------- #
#
# The API declares these append-only and never renamed, so a name here is safe
# to hardcode. A community-scoped key carries all of them; an account-scoped
# key carries ACCOUNT_KEY_CAPABILITIES instead.

CAPABILITIES: Tuple[str, ...] = (
    "open",
    "gate_status",
    "key_statuses",
    "hold_opens",
    "webhooks",
    "members",
    "messages",
    "access_logs",
    "key_schedules",
    "key_usage",
    "change_logs",
    "homes",
    "short_codes",
    "guest_view_entry",
    "access_codes",
    "guest_links",
    "map",
    "open_notifications",
    "settings",
    "sense_lines",
    "nfc_tags",
    "access_code_mode",
)

#: The capabilities an account-scoped key can have. ``open`` and
#: ``open_history`` (``account.history()``) are always there;
#: ``directory_call_events`` appears only while directory call events
#: (``account.stream_events()`` / ``account.directory_calls()``) are released
#: for that account, so check for it rather than assuming. Community-scoped
#: keys get every entry in :data:`CAPABILITIES` and never the account-only ones.
ACCOUNT_KEY_CAPABILITIES: Tuple[str, ...] = ("open", "directory_call_events",
                                             "open_history")


# --------------------------------------------------------------------------- #
# Event types
# --------------------------------------------------------------------------- #
#
# One vocabulary, two delivery paths. There is deliberately no separate webhook
# constant: the catalog a webhook subscription accepts and the types
# `stream_events()` yields come from the same server-side source, and shipping
# two names for one list would invite callers to reason about which applies
# where. `community.webhook_event_types()` is the authoritative runtime source.

#: The event types Nimbio delivers, by webhook and over the SSE stream alike —
#: a webhook subscribes to names from this list, and ``stream_events()`` yields
#: them as ``.type``.
#:
#: This is a **convenience snapshot** for autocomplete and typo-avoidance, not
#: the source of truth: :meth:`community.webhook_event_types` asks the server
#: for the live catalog, which is what to read when you need today's truth
#: rather than a name to compare against. The server may add types at any time,
#: and nothing in this SDK rejects one it does not recognise.
STREAM_EVENT_TYPES: Tuple[str, ...] = (
    "sense_line.changed",
    "open.succeeded",
    "open.failed",
    "device.online",
    "device.offline",
    "hold_open.changed",
    "member.requested",
    "member.approved",
    "member.removed",
    "directory.call",
)

#: The event types ``account.stream_events()`` yields — events about *you*
#: rather than a community, delivered to account-scoped keys only. A separate
#: list because it is a separate stream with a separate filter: passing one of
#: these to the community stream's ``events=`` is a 400, and vice versa.
#:
#: ``directory_call.ringing`` fires when a GuestView visitor calls you (or a
#: home you belong to); ``directory_call.ended`` follows exactly once per call.
#: Append-only, like every list here.
ACCOUNT_EVENT_TYPES: Tuple[str, ...] = (
    "directory_call.ringing",
    "directory_call.ended",
)

#: A directory call's ``outcome`` (``directory_call.ended`` and
#: ``account.directory_calls()`` rows): ``opened`` — someone opened the gate
#: for the caller; ``answered`` — someone picked up but did not open;
#: ``missed`` — nobody picked up. It is the call's outcome, the same for every
#: recipient. **Open:** a newer server may add a value, and it is passed
#: through unchanged, so keep a fallback branch.
DIRECTORY_CALL_OUTCOMES: Tuple[str, ...] = (
    "opened",
    "answered",
    "missed",
)

#: An ``account.history()`` row's ``open_type``: the kind of action, not where
#: the open came from. ``unknown`` stands in for an id the server has no name
#: for. **Open:** a newer server may add a value, passed through unchanged.
OPEN_HISTORY_TYPES: Tuple[str, ...] = (
    "open",
    "do_not_open",
    "emergency_open",
    "emergency_fail",
    "doorbell_or_emergency_prompt",
    "bluetooth_unlock",
    "bluetooth_lock",
    "unlock",
    "do_not_unlock",
    "lock",
    "do_not_lock",
    "unknown",
)

#: An ``account.history()`` row's ``result``. ``unknown`` means no result was
#: recorded (yet — a fresh open's result lands up to ~18s later). **Open**,
#: like :data:`OPEN_HISTORY_TYPES`.
OPEN_HISTORY_RESULTS: Tuple[str, ...] = (
    "opened",
    "did_not_open",
    "locked",
    "did_not_lock",
    "fail_open_trying_bluetooth",
    "fail_lock_trying_bluetooth",
    "unlock_bluetooth",
    "lock_bluetooth",
    "fail_lock_bluetooth",
    "fail_unlock_bluetooth",
    "unused_bluetooth",
    "lock_already_unlocked",
    "lock_already_locked",
    "unlocked",
    "did_not_unlock",
    "unknown",
)


# --------------------------------------------------------------------------- #
# Guest links
# --------------------------------------------------------------------------- #

#: The two kinds of guest link, which take different limits: an ``event`` link
#: requires a title and a ``window_start``/``window_end`` pair and allows
#: unlimited opens between them; a ``limited_use`` link requires ``max_uses``
#: and takes an optional ``expires_at`` backstop.
#:
#: A typo here is loud — the API answers 422 — so this is for autocomplete
#: rather than for safety.
GUEST_LINK_TYPES: Tuple[str, ...] = (
    "event",
    "limited_use",
)

#: The states a guest link can be in. The server computes ``state`` live at
#: read time, so it is the only field that knows whether a link works.
#:
#: A typo here is **silent**: comparing against ``"actve"`` is a False that
#: never explains itself and leaves a dead link looking live. Reference a name
#: from this tuple, or use ``GuestLink.active`` for the common case.
#:
#: ``upcoming`` is an event link whose window has not opened yet; ``spent`` is
#: a limited-use link that ran out of opens; ``feature_disabled`` is a link the
#: community switched off underneath — dead for a reason no timestamp shows.
GUEST_LINK_STATES: Tuple[str, ...] = (
    "active",
    "upcoming",
    "expired",
    "spent",
    "revoked",
    "feature_disabled",
)


# --------------------------------------------------------------------------- #
# Geofences
# --------------------------------------------------------------------------- #

#: The two behaviours a gate's geofence can have when a member arrives:
#: ``prompt`` notifies them and they tap to open; ``auto_open`` opens the gate
#: on arrival.
#:
#: The live set comes back on :meth:`community.map` as ``geofence_modes`` —
#: read that when you need today's truth. A typo here is loud (422), so this is
#: for autocomplete rather than for safety.
GEOFENCE_MODES: Tuple[str, ...] = (
    "prompt",
    "auto_open",
)


# --------------------------------------------------------------------------- #
# Configuration change log
# --------------------------------------------------------------------------- #

#: The four configuration audit trails :meth:`community.change_logs` can read.
#: The ``type`` argument is required and selects exactly one of them:
#:
#: - ``hold_open`` — manual on/off, one-time events, recurring schedules,
#:   disable-until dates
#: - ``key_schedule`` — key access schedules
#: - ``guest_view`` — GuestView/Directory settings, short codes, directory
#:   access codes, GuestView Entry windows
#: - ``guest_link`` — guest link creation, revocation, and link settings
CHANGE_LOG_TYPES: Tuple[str, ...] = (
    "hold_open",
    "key_schedule",
    "guest_view",
    "guest_link",
)


# --------------------------------------------------------------------------- #
# Key usage report
# --------------------------------------------------------------------------- #

#: How :meth:`community.key_usage` attributed each row's ``user``. **The server
#: chooses this from the community's property type — there is no parameter for
#: it** — and it changes what ``user`` means, so read
#: :attr:`models.KeyUsageReport.report_type` before reading a row:
#:
#: - ``commercial`` — ``user`` is the actual opener's name.
#: - ``residential`` — ``user`` is ``"<master key owner> Keychain"``: every
#:   open on a household's keys is attributed to the account holder.
KEY_USAGE_REPORT_TYPES: Tuple[str, ...] = (
    "commercial",
    "residential",
)


def has_capability(capabilities: Iterable[str], capability: str) -> bool:
    """True when ``capability`` is in ``capabilities``.

    ``capabilities`` is whatever the key reported (``me().key.capabilities``).
    Pass a name from :data:`CAPABILITIES` rather than a string literal — the
    check is a plain membership test, so a typo is a False that never explains
    itself. An unrecognised name is not an error: a newer server may know
    capabilities this release does not.
    """
    return capability in set(capabilities or ())
