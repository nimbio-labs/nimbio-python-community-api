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
            last_used_datetime=d.get("last_used_datetime"),
            minute_limit=d.get("minute_limit"),
            minute_count=d.get("minute_count"),
            month_limit=d.get("month_limit"),
            month_count=d.get("month_count"),
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
class Latch:
    """One latch and its latest sensed physical state."""

    latch_id: Optional[str]
    latch_name: Optional[str]
    status: Optional[str]
    offline: bool
    message: Optional[str]
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
