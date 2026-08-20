"""Typed response models for the Nimbio community API.

Every model is a lightweight, tolerant dataclass: it pulls the documented
fields out of the JSON response for autocomplete and type-checking, while always
retaining the full decoded payload on ``.raw`` so nothing is ever lost. Unknown
or newly added server fields are preserved in ``.raw`` even if they have no typed
attribute yet, so the client keeps working across server updates.

These models are intentionally read-only value objects. You never construct them
yourself; the client builds them from API responses via ``from_dict``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _d(raw: Any) -> Dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


# --------------------------------------------------------------------------- #
# Account / auth
# --------------------------------------------------------------------------- #

@dataclass
class ApiKeyInfo:
    """Metadata and live usage counters for the authenticating API key."""

    api_key_id: Optional[str]
    prefix: Optional[str]
    name: Optional[str]
    mode: Optional[str]  # "test" | "live"
    type: Optional[str]  # "account" | "community"
    community_id: Optional[str]
    capabilities: List[str]
    last_used_datetime: Optional[str]
    minute_limit: Optional[int]
    minute_count: Optional[int]
    month_limit: Optional[int]
    month_count: Optional[int]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "ApiKeyInfo":
        d = _d(raw)
        return cls(
            api_key_id=d.get("api_key_id"),
            prefix=d.get("prefix"),
            name=d.get("name"),
            mode=d.get("mode"),
            type=d.get("type"),
            community_id=d.get("community_id"),
            capabilities=list(d.get("capabilities") or []),
            last_used_datetime=d.get("last_used_datetime"),
            # Servers before the 2026-07 fix emitted only the legacy names
            # (calls_this_minute, ...) — accept both.
            minute_limit=d.get("minute_limit", d.get("rate_limit_per_minute")),
            minute_count=d.get("minute_count", d.get("calls_this_minute")),
            month_limit=d.get("month_limit", d.get("quota_per_month")),
            month_count=d.get("month_count", d.get("calls_this_month")),
            raw=d,
        )


@dataclass
class Me:
    """Result of :meth:`me` — who the API key belongs to, plus usage."""

    account_id: Optional[str]
    key: ApiKeyInfo
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "Me":
        d = _d(raw)
        return cls(
            account_id=d.get("account_id"),
            key=ApiKeyInfo.from_dict(d.get("key")),
            raw=d,
        )


@dataclass
class Health:
    """Result of :meth:`health` — backend reachability."""

    ok: bool
    wamp: Optional[str]  # "connected" | "disconnected"
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "Health":
        d = _d(raw)
        return cls(ok=bool(d.get("ok")), wamp=d.get("wamp"), raw=d)


# --------------------------------------------------------------------------- #
# Gate status
# --------------------------------------------------------------------------- #

@dataclass
class PossibleStatus:
    """One entry of a latch's configured status vocabulary."""

    status: Optional[str]
    transient: bool
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "PossibleStatus":
        d = _d(raw)
        return cls(status=d.get("status"), transient=bool(d.get("transient")), raw=d)


@dataclass
class Latch:
    """One latch and its latest sensed physical state.

    ``possible_statuses`` is the latch's configured status vocabulary (empty
    when no sensing is configured) — use it to classify the latch (e.g. a
    Locked/Unlocked door vs an Open/Closed gate) instead of hardcoding labels.
    """

    latch_id: Optional[str]
    latch_name: Optional[str]
    status: Optional[str]
    offline: bool
    message: Optional[str]
    possible_statuses: List[PossibleStatus] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "Latch":
        d = _d(raw)
        return cls(
            latch_id=d.get("latch_id") or d.get("id"),
            latch_name=d.get("latch_name") or d.get("name"),
            status=d.get("status"),
            offline=bool(d.get("offline")),
            message=d.get("latch_status_current_message"),
            possible_statuses=[PossibleStatus.from_dict(x)
                               for x in (d.get("possible_statuses") or [])],
            raw=d,
        )


@dataclass
class GateStatus:
    """Result of :meth:`community.gate_status` — per-latch sensed state."""

    latches: List[Latch]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "GateStatus":
        d = _d(raw)
        return cls(
            latches=[Latch.from_dict(x) for x in (d.get("latches") or [])],
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Members
# --------------------------------------------------------------------------- #

@dataclass
class Member:
    """A single community member."""

    account_community_id: Optional[int]
    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()

    @classmethod
    def from_dict(cls, raw: Any) -> "Member":
        d = _d(raw)
        return cls(
            account_community_id=d.get("account_community_id"),
            first_name=d.get("first_name"),
            last_name=d.get("last_name"),
            phone_number=d.get("phone_number"),
            raw=d,
        )


@dataclass
class Members:
    """Result of :meth:`community.members` — pending/accepted/removed lists."""

    accepted: List[Member]
    unaccepted: List[Member]
    removed: List[Member]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "Members":
        d = _d(raw)
        m = lambda k: [Member.from_dict(x) for x in (d.get(k) or [])]  # noqa: E731
        return cls(accepted=m("accepted"), unaccepted=m("unaccepted"),
                   removed=m("removed"), raw=d)


# --------------------------------------------------------------------------- #
# Keys
# --------------------------------------------------------------------------- #

@dataclass
class CommunityKey:
    """A community key with its access restrictions (from ``community.keys``).

    Nested ``sharing``, ``expiry``, ``temporal``, and ``latches`` structures are
    left as plain dicts/lists (available on this object and on ``.raw``) — they
    are configuration detail that callers usually index into directly.
    """

    id: Optional[str]
    name: Optional[str]
    disabled: bool
    hidden: bool
    pending: bool
    is_favorite: bool
    sharing: Dict[str, Any]
    expiry: Dict[str, Any]
    temporal: Dict[str, Any]
    latches: List[Dict[str, Any]]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "CommunityKey":
        d = _d(raw)
        return cls(
            id=d.get("id"),
            name=d.get("name"),
            disabled=bool(d.get("disabled")),
            hidden=bool(d.get("hidden")),
            pending=bool(d.get("pending")),
            is_favorite=bool(d.get("is_favorite")),
            sharing=_d(d.get("sharing")),
            expiry=_d(d.get("expiry")),
            temporal=_d(d.get("temporal")),
            latches=list(d.get("latches") or []),
            raw=d,
        )


@dataclass
class KeyStatuses:
    """Result of :meth:`community.key_statuses` — live key + latch state.

    The backend payload mixes configuration and transient status; it is exposed
    here as the ``keys`` list and ``hold_opens`` map with full fidelity on
    ``.raw``. Use :meth:`community.keys` for the restriction-focused view.
    """

    keys: List[Dict[str, Any]]
    hold_opens: Dict[str, Any]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "KeyStatuses":
        d = _d(raw)
        return cls(keys=list(d.get("keys") or []),
                   hold_opens=_d(d.get("hold_opens")), raw=d)


# --------------------------------------------------------------------------- #
# Writes (opens, messages, member management)
# --------------------------------------------------------------------------- #

@dataclass
class OpenResult:
    """Result of :meth:`community.open`.

    - Live key, success: ``result == "opened"``, ``key_log_id`` set.
    - Test key:          ``result == "simulated"``, ``simulated`` is ``True``.

    Denials (403) and gate-did-not-confirm (504) raise exceptions rather than
    returning here. ``request_id`` ties the call to the server-side audit log.
    """

    result: Optional[str]
    request_id: Optional[str]
    key_log_id: Optional[int]
    latch_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def opened(self) -> bool:
        """True when a live open was confirmed by the box."""
        return self.result == "opened"

    @property
    def simulated(self) -> bool:
        """True when this was a test-mode (no side effect) call."""
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "OpenResult":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            request_id=d.get("request_id"),
            key_log_id=d.get("key_log_id"),
            latch_id=d.get("latch_id"),
            raw=d,
        )


@dataclass
class WriteResult:
    """Generic result for community write endpoints (messages, member mgmt).

    ``result`` is the server's outcome string (e.g. ``"member_added"``,
    ``"keys_granted"``, ``"sent"``, or ``"simulated"`` for test-mode calls).
    Endpoint-specific extras (``account_community_id``, ``granted``, ``keys``,
    ``revoked_key_ids``, ...) are available via ``[...]``/``.get`` and ``.raw``.
    """

    result: Optional[str]
    request_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    @classmethod
    def from_dict(cls, raw: Any) -> "WriteResult":
        d = _d(raw)
        return cls(result=d.get("result"), request_id=d.get("request_id"), raw=d)


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #

@dataclass
class AccessLogEntry:
    """One row in an access log (a gate open)."""

    datetime: Optional[str]
    key_name: Optional[str]
    latch_name: Optional[str]
    user: Optional[str]
    phone: Optional[str]
    location: Optional[str]
    open_desc: Optional[str]
    open_result: Optional[str]
    reason_desc: Optional[str]
    source: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessLogEntry":
        d = _d(raw)
        return cls(
            datetime=d.get("datetime"),
            key_name=d.get("key_name"),
            latch_name=d.get("latch_name"),
            user=d.get("user"),
            phone=d.get("phone"),
            location=d.get("location"),
            open_desc=d.get("open_desc"),
            open_result=d.get("open_result"),
            reason_desc=d.get("reason_desc"),
            source=d.get("source"),
            raw=d,
        )


@dataclass
class AccessLogPage:
    """A page of community access-log rows (1000 per page)."""

    logs: List[AccessLogEntry]
    page: Optional[int]
    has_more: bool
    date_from: Optional[str]
    date_to: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessLogPage":
        d = _d(raw)
        return cls(
            logs=[AccessLogEntry.from_dict(x) for x in (d.get("logs") or [])],
            page=d.get("page"),
            has_more=bool(d.get("has_more")),
            date_from=d.get("from"),
            date_to=d.get("to"),
            raw=d,
        )


@dataclass
class MemberAccessLogPage:
    """A member's access-log rows for a 30-day window."""

    logs: List[AccessLogEntry]
    account_community_id: Optional[int]
    window: Optional[str]
    truncated: bool
    date_from: Optional[str]
    date_to: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "MemberAccessLogPage":
        d = _d(raw)
        return cls(
            logs=[AccessLogEntry.from_dict(x) for x in (d.get("logs") or [])],
            account_community_id=d.get("account_community_id"),
            window=d.get("window"),
            truncated=bool(d.get("truncated")),
            date_from=d.get("from"),
            date_to=d.get("to"),
            raw=d,
        )


@dataclass
class GateStatusLogEntry:
    """One physical open/closed transition."""

    datetime: Optional[str]
    latch_name: Optional[str]
    status_label: Optional[str]
    sense_line: Optional[int]
    state: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "GateStatusLogEntry":
        d = _d(raw)
        return cls(
            datetime=d.get("datetime"),
            latch_name=d.get("latch_name"),
            status_label=d.get("status_label"),
            sense_line=d.get("sense_line"),
            state=d.get("state"),
            raw=d,
        )


@dataclass
class GateStatusLogPage:
    """A page of gate status-change rows (1000 per page)."""

    logs: List[GateStatusLogEntry]
    page: Optional[int]
    has_more: bool
    date_from: Optional[str]
    date_to: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "GateStatusLogPage":
        d = _d(raw)
        return cls(
            logs=[GateStatusLogEntry.from_dict(x) for x in (d.get("logs") or [])],
            page=d.get("page"),
            has_more=bool(d.get("has_more")),
            date_from=d.get("from"),
            date_to=d.get("to"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Hold opens
# --------------------------------------------------------------------------- #

@dataclass
class HoldOpenLatch:
    """Hold-open state for one latch.

    ``held_open`` is the combined truth (manual OR an active one-time /
    recurring window); ``manual`` reflects only the manual toggle. ``events``
    and ``recurring`` are the raw window dicts as returned by the server.
    """

    latch_id: Optional[str]
    latch_name: Optional[str]
    held_open: bool
    manual: bool
    disabled_until: Optional[str]
    timezone: Optional[str]
    events: List[Dict[str, Any]] = field(default_factory=list)
    recurring: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "HoldOpenLatch":
        d = _d(raw)
        return cls(
            latch_id=d.get("latch_id"),
            latch_name=d.get("latch_name"),
            held_open=bool(d.get("held_open")),
            manual=bool(d.get("manual")),
            disabled_until=d.get("disabled_until"),
            timezone=d.get("timezone"),
            events=list(d.get("events") or []),
            recurring=list(d.get("recurring") or []),
            raw=d,
        )


@dataclass
class HoldOpens:
    """Result of :meth:`community.hold_opens` — hold-open state per latch."""

    latches: Dict[str, HoldOpenLatch]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "HoldOpens":
        d = _d(raw)
        entries = d.get("hold_opens") or {}
        return cls(
            latches={k: HoldOpenLatch.from_dict(v) for k, v in entries.items()
                     if isinstance(v, dict)},
            raw=d,
        )


@dataclass
class ManualHoldOpenResult:
    """Result of :meth:`community.set_hold_open`."""

    result: Optional[str]
    latch_id: Optional[str]
    manual: Optional[bool]
    held_open: Optional[bool]
    request_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "ManualHoldOpenResult":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            latch_id=d.get("latch_id"),
            manual=d.get("manual"),
            held_open=d.get("held_open"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class HoldOpenEventAdded:
    """Result of :meth:`community.add_hold_open_event` — keep ``event_id`` to
    end the window early via :meth:`community.remove_hold_open_event`."""

    result: Optional[str]
    event_id: Optional[str]
    latch_id: Optional[str]
    request_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "HoldOpenEventAdded":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            event_id=d.get("event_id"),
            latch_id=d.get("latch_id"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class HoldOpenEventRemoved:
    """Result of :meth:`community.remove_hold_open_event`. ``removed`` is
    False on an idempotent re-remove (the window was already gone)."""

    result: Optional[str]
    removed: bool
    request_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "HoldOpenEventRemoved":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            removed=bool(d.get("removed")),
            request_id=d.get("request_id"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Webhooks
# --------------------------------------------------------------------------- #

@dataclass
class Webhook:
    """One outbound webhook registration.

    ``secret`` is populated ONLY on the create / rotate-secret responses —
    store it then; it is never returned again.
    """

    webhook_id: Optional[str]
    url: Optional[str]
    events: List[str]
    description: Optional[str]
    active: Optional[bool]
    disabled: Optional[bool]
    secret: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "Webhook":
        d = _d(raw)
        return cls(
            webhook_id=d.get("webhook_id"),
            url=d.get("url"),
            events=list(d.get("events") or []),
            description=d.get("description"),
            active=d.get("active"),
            disabled=d.get("disabled"),
            secret=d.get("secret"),
            raw=d,
        )


@dataclass
class WebhookCreateResult:
    """Result of :meth:`community.create_webhook`."""

    result: Optional[str]
    webhook: Optional[Webhook]
    request_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @property
    def secret(self) -> Optional[str]:
        return self.webhook.secret if self.webhook else None

    @classmethod
    def from_dict(cls, raw: Any) -> "WebhookCreateResult":
        d = _d(raw)
        wh = d.get("webhook")
        return cls(
            result=d.get("result"),
            webhook=Webhook.from_dict(wh) if isinstance(wh, dict) else None,
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class WebhookSecret:
    """Result of :meth:`community.rotate_webhook_secret` — the new secret,
    returned once."""

    result: Optional[str]
    webhook_id: Optional[str]
    secret: Optional[str]
    request_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "WebhookSecret":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            webhook_id=d.get("webhook_id"),
            secret=d.get("secret"),
            request_id=d.get("request_id"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Account surface (account-scoped keys)
# --------------------------------------------------------------------------- #

@dataclass
class AccountLatch:
    """One latch reachable through one of your account's keys."""

    id: Optional[str]
    name: Optional[str]
    offline: bool
    location: Optional[str]
    held_open: bool
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccountLatch":
        d = _d(raw)
        return cls(
            id=d.get("id"),
            name=d.get("name"),
            offline=bool(d.get("offline")),
            location=d.get("location"),
            held_open=bool(d.get("held_open")),
            raw=d,
        )


@dataclass
class AccountKey:
    """One of your account's Nimbio keys, with its latches nested."""

    id: Optional[str]
    name: Optional[str]
    home: Optional[str]
    disabled: bool
    hidden: bool
    pending: bool
    parent_name: Optional[str]
    latches: List[AccountLatch] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccountKey":
        d = _d(raw)
        return cls(
            id=d.get("id"),
            name=d.get("name"),
            home=d.get("home"),
            disabled=bool(d.get("disabled")),
            hidden=bool(d.get("hidden")),
            pending=bool(d.get("pending")),
            parent_name=d.get("parent_name"),
            latches=[AccountLatch.from_dict(x) for x in (d.get("latches") or [])],
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Live event stream (SSE)
# --------------------------------------------------------------------------- #

@dataclass
class StreamEvent:
    """One live event from ``stream_events()``.

    ``data`` is the exact JSON body a webhook receiver gets for the same
    event: ``{"event", "id", "community_id", "occurred_at", "data": {...}}``
    — the event-specific fields live under ``data["data"]``.
    """

    id: str
    type: str  # e.g. "sense_line.changed", "hold_open.changed"
    data: Dict[str, Any] = field(default_factory=dict)

    @property
    def payload(self) -> Dict[str, Any]:
        """The event-specific fields (``data["data"]``)."""
        inner = self.data.get("data")
        return inner if isinstance(inner, dict) else {}


@dataclass
class StreamReset:
    """Marker yielded when the server cannot replay the requested cursor.

    The client's local picture may be stale: re-seed state via the status
    reads (``gate_status()`` / ``hold_opens()``), then keep iterating.
    """

    reason: Optional[str] = None


# --------------------------------------------------------------------------- #
# Key access schedules
# --------------------------------------------------------------------------- #

@dataclass
class ScheduleWindow:
    """One recurring window during which a key may open its gates.

    ``days_of_the_week`` is a letter string from ``MTWHFSU`` where **H is
    Thursday**, ``S`` is Saturday and ``U`` is Sunday. ``start_time`` and
    ``end_time`` are ``'HH:MM'`` in each gate's own local time; both are None
    for an all-day window.

    A window cannot run past midnight — the server rejects a reversed window
    with ``overnight_not_supported``. Express overnight access as two windows,
    the first ending ``"24:00"`` (the end-of-day sentinel, valid as an end only)
    and the second starting ``"00:00"`` the next day. Use ``"24:00"`` rather
    than ``"23:59"``: the comparison is ``now < end``, so ``"23:59"`` would
    leave a one-minute gap every night exactly where the two halves meet.
    """

    days_of_the_week: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    temporal_date_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "ScheduleWindow":
        d = _d(raw)
        return cls(
            days_of_the_week=d.get("days_of_the_week") or "",
            start_time=d.get("start_time"),
            end_time=d.get("end_time"),
            temporal_date_id=d.get("temporal_date_id"),
            raw=d,
        )

    def to_payload(self) -> Dict[str, Any]:
        """The wire form the API accepts (identifiers are server-assigned and
        deliberately omitted)."""
        return {
            "days_of_the_week": self.days_of_the_week,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


@dataclass
class KeySchedule:
    """A community key's access schedule.

    Schedules are set on the community's own keys only. That schedule *is* the
    community-wide rule: it applies to every member key beneath it. An
    individual member's key cannot be scheduled through this API and is refused
    with ``not_a_community_key`` (403).

    ``restricted`` means the key is genuinely time-limited.
    ``permanently_blocked`` means it has windows saved but the restriction is
    switched off, which denies **every** open at every hour — a fault to
    repair, not a working schedule. Saving a schedule through this SDK clears
    that state.

    ``descendant_key_count`` is the blast radius: how many **live** member keys
    inherit this restriction. Revoked and hidden keys are not counted, since
    they are refused at the gate whatever the schedule says. Check it before
    restricting a key.

    ``inactive_window_count`` is how many windows the list endpoint filtered out
    because their date range no longer covers today; ``windows`` then holds only
    what is in force. It is 0 on a single-key read, which returns every window
    — including expired ones — because a write replaces the whole schedule.
    """

    key_id: Optional[str]
    key_name: Optional[str]
    restricted: bool
    permanently_blocked: bool
    is_temporal_enabled: bool
    windows: List[ScheduleWindow] = field(default_factory=list)
    latch_count: int = 0
    latches: List[Dict[str, Any]] = field(default_factory=list)
    is_community_key: bool = False
    descendant_key_count: int = 0
    inactive_window_count: int = 0
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "KeySchedule":
        d = _d(raw)
        return cls(
            key_id=d.get("key_id"),
            key_name=d.get("key_name"),
            restricted=bool(d.get("restricted")),
            permanently_blocked=bool(d.get("permanently_blocked")),
            is_temporal_enabled=bool(d.get("is_temporal_enabled")),
            windows=[ScheduleWindow.from_dict(w) for w in (d.get("windows") or [])],
            latch_count=int(d.get("latch_count") or 0),
            latches=list(d.get("latches") or []),
            is_community_key=bool(d.get("is_community_key")),
            descendant_key_count=int(d.get("descendant_key_count") or 0),
            inactive_window_count=int(d.get("inactive_window_count") or 0),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class KeySchedules:
    """The community's own keys and their access schedules.

    Community keys only — member keys are not listed, and cannot be scheduled.
    A restriction on a community key cascades to every member beneath it, which
    is how a community-wide rule is expressed.
    """

    keys: List[KeySchedule] = field(default_factory=list)
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.keys)

    def __len__(self) -> int:
        return len(self.keys)

    @property
    def blocked(self) -> List[KeySchedule]:
        """Community keys denied at all times because a saved schedule is
        switched off. Re-saving the schedule repairs one."""
        return [k for k in self.keys if k.permanently_blocked]

    @classmethod
    def from_dict(cls, raw: Any) -> "KeySchedules":
        d = _d(raw)
        return cls(
            keys=[KeySchedule.from_dict(k) for k in (d.get("keys") or [])],
            request_id=d.get("request_id"),
            raw=d,
        )
