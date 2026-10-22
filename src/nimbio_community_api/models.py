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
from typing import Any, Dict, List, Literal, Optional


def _d(raw: Any) -> Dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _int(value: Any) -> Optional[int]:
    """An integer count, or ``None`` when the server sent something that is
    not one — a malformed field must not take the whole response down."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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

    def has_capability(self, capability: str) -> bool:
        """True when this key carries ``capability``.

        Pass a name from :data:`nimbio_community_api.constants.CAPABILITIES`
        rather than a literal — a typo is a False that never explains itself.
        An account-scoped key has ``"open"``, plus ``"directory_call_events"``
        while that feature is released for its account; a community-scoped key
        has every capability in :data:`~nimbio_community_api.constants.CAPABILITIES`.
        """
        from .constants import has_capability as _has

        return _has(self.capabilities, capability)

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
# Community identity
# --------------------------------------------------------------------------- #

@dataclass
class CommunityLatch:
    """One latch as ``community.info()`` describes it — identity and wiring,
    not live state.

    ``latch_id`` is what :meth:`community.open` and every hold-open call take.
    ``timezone`` is the clock this latch's times are written in; it comes from
    the box the latch hangs off, which is why a multi-site community can have
    more than one.
    """

    latch_id: Optional[str]
    latch_name: Optional[str]
    offline: bool
    timezone: Optional[str]
    box_id: Optional[str]
    box_name: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "CommunityLatch":
        d = _d(raw)
        return cls(
            latch_id=d.get("latch_id") or d.get("id"),
            latch_name=d.get("latch_name") or d.get("name"),
            offline=bool(d.get("offline")),
            timezone=d.get("timezone"),
            box_id=d.get("box_id"),
            box_name=d.get("box_name"),
            raw=d,
        )


@dataclass
class CommunityInfo:
    """Result of :meth:`community.info` — the community this key is bound to.

    ``features`` is the resolved on/off state of everything the rest of the
    surface gates on: branch on it rather than calling an endpoint and reading
    a 403 (``features["hold_opens"]`` false means every hold-open call 403s).
    ``latches`` is where ``latch_id`` values come from. ``counts``,
    ``terminology`` and ``property_type`` stay plain dicts — they are display
    detail callers index into directly.

    ``timezone`` is the single zone every configured latch agrees on, or None
    when they disagree or none is set; ``timezones`` lists every distinct zone
    and each entry in ``latches`` carries its own, so a multi-site community
    reads the per-latch value.
    """

    community_id: Optional[int]
    community_uuid: Optional[str]
    name: Optional[str]
    active: bool
    timezone: Optional[str]
    timezones: List[str] = field(default_factory=list)
    features: Dict[str, Any] = field(default_factory=dict)
    latches: List[CommunityLatch] = field(default_factory=list)
    counts: Dict[str, Any] = field(default_factory=dict)
    terminology: Dict[str, Any] = field(default_factory=dict)
    property_type: Dict[str, Any] = field(default_factory=dict)
    number_of_units: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def feature(self, name: str) -> bool:
        """True when the named feature is switched on for this community.

        An unknown feature reads as False — a server that has not been taught
        the flag yet cannot have it enabled.
        """
        return bool(self.features.get(name))

    @classmethod
    def from_dict(cls, raw: Any) -> "CommunityInfo":
        d = _d(raw)
        return cls(
            community_id=d.get("community_id"),
            community_uuid=d.get("community_uuid"),
            name=d.get("name"),
            active=bool(d.get("active")),
            timezone=d.get("timezone"),
            timezones=list(d.get("timezones") or []),
            features=_d(d.get("features")),
            latches=[CommunityLatch.from_dict(x) for x in (d.get("latches") or [])],
            counts=_d(d.get("counts")),
            terminology=_d(d.get("terminology")),
            property_type=_d(d.get("property_type")),
            number_of_units=d.get("number_of_units"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Members
# --------------------------------------------------------------------------- #

@dataclass
class Member:
    """A single community member.

    One shape for all three member reads. :meth:`community.members` fills the
    name/phone fields; the paged read and :meth:`community.member` add the
    roster detail (``keys``, ``subkey_count``, ``is_home``, ``accepted``), and
    the single-member read alone sets ``bucket`` and ``status``.

    ``phone_numbers`` is the full list a member may have; ``phone_number`` is
    the first of them when the server sends a list instead of a single value.
    A row with ``is_home`` true is a *home*, not a person: ``keys`` there lists
    the home's members' ids.

    Each entry in ``keys`` is a plain dict carrying ``key_id``, ``key_name``,
    ``disabled``, ``latches``, ``parent_key_id``, and — for a key with an end
    date — ``expires_at`` (UTC ``"YYYY-MM-DD HH:MM:SS"``), ``expires_at_valid``
    and ``installer_grant``. ``disabled`` means REVOKED and does not include
    expiry, so a lapsed key still reports it falsy; read ``expires_at_valid``
    as well for "is this key currently in force?".

    ``installer_grant`` on the member itself means they are on the roster only
    because a Nimbio installer was granted a temporary 7-day key for the gate
    they installed. It is revocable like any other member key.
    """

    account_community_id: Optional[int]
    first_name: Optional[str]
    last_name: Optional[str]
    phone_number: Optional[str]
    id: Optional[str] = None
    phone_numbers: List[str] = field(default_factory=list)
    keys: List[Dict[str, Any]] = field(default_factory=list)
    is_home: bool = False
    accepted: Optional[bool] = None
    subkey_count: Optional[int] = None
    created_datetime: Optional[str] = None
    installer_grant: bool = False
    bucket: Optional[str] = None  # single-member read only
    status: Optional[int] = None  # single-member read only
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()

    @classmethod
    def from_dict(cls, raw: Any) -> "Member":
        d = _d(raw)
        phone_numbers = [p for p in (d.get("phone_numbers") or []) if p]
        return cls(
            account_community_id=d.get("account_community_id"),
            first_name=d.get("first_name"),
            last_name=d.get("last_name"),
            phone_number=d.get("phone_number") or (
                phone_numbers[0] if phone_numbers else None),
            id=d.get("id"),
            phone_numbers=phone_numbers,
            keys=list(d.get("keys") or []),
            is_home=bool(d.get("is_home")),
            accepted=d.get("accepted"),
            subkey_count=d.get("subkey_count"),
            created_datetime=d.get("created_datetime"),
            installer_grant=bool(d.get("installer_grant")),
            bucket=d.get("bucket"),
            status=d.get("status"),
            raw=d,
        )


@dataclass
class MembersPage:
    """Result of :meth:`community.members_page` — one page of one bucket.

    ``total`` is the size of the **filtered** set, not of the whole bucket:
    with a ``search`` it counts the matches, so paging through a search never
    skips anyone. ``page`` is 1-indexed.
    """

    members: List[Member]
    bucket: Optional[str]
    page: Optional[int]
    size: Optional[int]
    total: Optional[int]
    has_more: bool
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.members)

    def __len__(self) -> int:
        return len(self.members)

    @classmethod
    def from_dict(cls, raw: Any) -> "MembersPage":
        d = _d(raw)
        return cls(
            members=[Member.from_dict(x) for x in (d.get("members") or [])],
            bucket=d.get("bucket"),
            page=d.get("page"),
            size=d.get("size"),
            total=d.get("total"),
            has_more=bool(d.get("has_more")),
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
class KeyUpdateResult:
    """Result of :meth:`community.update_key`.

    ``key`` is the updated key in the same shape :meth:`community.keys`
    returns, and ``descendant_key_count`` is the blast radius: how many member
    keys descend from it and therefore inherit a ``disabled`` change. Both are
    None on a test-mode call, which reports ``result == "simulated"`` and the
    fields it *would* have written under ``raw["would_set"]``.
    """

    result: Optional[str]
    key: Optional[CommunityKey]
    descendant_key_count: Optional[int]
    request_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "KeyUpdateResult":
        d = _d(raw)
        key = d.get("key")
        return cls(
            result=d.get("result"),
            key=CommunityKey.from_dict(key) if isinstance(key, dict) else None,
            descendant_key_count=d.get("descendant_key_count"),
            request_id=d.get("request_id"),
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


@dataclass
class BulkSummary:
    """How a bulk batch went, in three numbers. ``failed`` is per-item failure,
    not a rejected batch — a rejected batch raises instead."""

    total: int = 0
    succeeded: int = 0
    failed: int = 0
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "BulkSummary":
        d = _d(raw)
        return cls(
            total=int(d.get("total") or 0),
            succeeded=int(d.get("succeeded") or 0),
            failed=int(d.get("failed") or 0),
            raw=d,
        )


@dataclass
class BulkItemResult:
    """One item's outcome inside a bulk response.

    ``index`` is the item's position in the request, and each row echoes the
    identifier it was addressed by (``account_community_id``, or
    ``phone_number`` for a bulk add) — so results can be zipped back against
    the input and only the failures re-submitted.

    ``ok`` is the item's verdict. On a failure, ``code`` and ``message`` say
    why (``already_member``, ``member_not_accepted``, ``key_not_held``, ...).
    Endpoint-specific detail (``granted``, ``revoked_key_ids``,
    ``already_revoked_community_key_ids``, ``key_ids``, ``account_id``) is on
    ``raw``.
    """

    index: Optional[int]
    ok: bool
    account_community_id: Optional[int] = None
    phone_number: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    @classmethod
    def from_dict(cls, raw: Any) -> "BulkItemResult":
        d = _d(raw)
        return cls(
            index=d.get("index"),
            ok=bool(d.get("ok")),
            account_community_id=d.get("account_community_id"),
            phone_number=d.get("phone_number"),
            code=d.get("code"),
            message=d.get("message"),
            raw=d,
        )


@dataclass
class BulkResult:
    """Result of the four bulk member writes — an HTTP **207**, one entry per
    input item, in request order.

    A 207 does **not** mean every item succeeded. The batch was processed;
    each item carries its own verdict, because the side effects an item fires
    (a push, a webhook delivery) cannot be rolled back once sent. Check
    ``.summary.failed`` or iterate ``.failures`` — never just the status code.

    A whole-batch rejection is different: a foreign member or key, an over-size
    batch or a repeated id rejects everything with nothing applied, and that
    arrives as a raised :class:`BadRequestError` / 422, not as this object.

    ``simulated`` is an explicit flag here, not an outcome string: ``result``
    stays ``"batch_processed"`` for test and live keys alike.
    """

    result: Optional[str]
    simulated: bool
    summary: BulkSummary
    results: List[BulkItemResult] = field(default_factory=list)
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    @property
    def failures(self) -> List[BulkItemResult]:
        """The items that did not succeed — what to fix and re-submit."""
        return [r for r in self.results if not r.ok]

    @property
    def successes(self) -> List[BulkItemResult]:
        return [r for r in self.results if r.ok]

    @classmethod
    def from_dict(cls, raw: Any) -> "BulkResult":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            simulated=bool(d.get("simulated")),
            summary=BulkSummary.from_dict(d.get("summary")),
            results=[BulkItemResult.from_dict(x) for x in (d.get("results") or [])],
            request_id=d.get("request_id"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #

@dataclass
class Message:
    """One message already sent to the community.

    ``sent_at`` is ISO-8601 in **UTC**. ``sender_name`` /
    ``sender_account_id`` identify the community manager it was sent as: an API
    key acts as its owning manager, so a message sent through this API is not
    distinguishable from one that person sent from the portal.
    """

    message_id: Optional[int]
    message: Optional[str]
    sender_name: Optional[str]
    sender_account_id: Optional[str]
    sent_at: Optional[str]
    community_uuid: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "Message":
        d = _d(raw)
        return cls(
            message_id=d.get("message_id"),
            message=d.get("message"),
            sender_name=d.get("sender_name"),
            sender_account_id=d.get("sender_account_id"),
            sent_at=d.get("sent_at"),
            community_uuid=d.get("community_uuid"),
            raw=d,
        )


@dataclass
class MessagesPage:
    """Result of :meth:`community.messages` — sent messages, newest first.

    Only real sends are recorded. A test-mode key's send is validated and
    discarded, so nothing simulated ever appears here and there is no
    simulated/real flag to check: a test key reads the live history but can
    never add to it.
    """

    messages: List[Message]
    limit: Optional[int]
    offset: Optional[int]
    has_more: bool
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.messages)

    def __len__(self) -> int:
        return len(self.messages)

    @classmethod
    def from_dict(cls, raw: Any) -> "MessagesPage":
        d = _d(raw)
        return cls(
            messages=[Message.from_dict(x) for x in (d.get("messages") or [])],
            limit=d.get("limit"),
            offset=d.get("offset"),
            has_more=bool(d.get("has_more")),
            raw=d,
        )

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


@dataclass
class HoldOpenDisabledUntil:
    """Result of :meth:`community.set_hold_open_disabled_until`.

    ``disabled_until`` is the moment the suspension lifts, in the **latch's
    local time** — None once hold opens are running again. ``held_open``
    reports the latch's state after the call: setting a suspension releases a
    hold that was already active.
    """

    result: Optional[str]
    latch_id: Optional[str]
    disabled_until: Optional[str]
    held_open: Optional[bool]
    request_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "HoldOpenDisabledUntil":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            latch_id=d.get("latch_id"),
            disabled_until=d.get("disabled_until"),
            held_open=d.get("held_open"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class RecurringHoldOpen:
    """Result of :meth:`community.add_hold_open_recurring` and
    :meth:`community.update_hold_open_recurring`.

    Keep ``temporal_date_id`` — it addresses the schedule for later changes and
    is the same id that appears under ``recurring[]`` in
    :meth:`community.hold_opens`.

    ``schedule`` is the saved schedule as the server stores it:
    ``days_of_the_week``, ``recurring_week``, ``active``, and
    ``temporal_times`` (each with ``start``/``end`` as ``HH:MM:SS`` in the
    latch's local time — an empty list means all-day). It is left as a plain
    dict, and is absent on a test-mode call, which reports
    ``result == "simulated"`` and echoes the request under ``raw["would_add"]``.
    """

    result: Optional[str]
    latch_id: Optional[str]
    temporal_date_id: Optional[str]
    schedule: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "RecurringHoldOpen":
        d = _d(raw)
        schedule = _d(d.get("schedule"))
        return cls(
            result=d.get("result"),
            latch_id=d.get("latch_id"),
            temporal_date_id=d.get("temporal_date_id")
            or schedule.get("temporal_date_id"),
            schedule=schedule,
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class RecurringHoldOpenRemoved:
    """Result of :meth:`community.remove_hold_open_recurring`.

    ``removed`` is True when the schedule was deleted. This call is
    deliberately **not** idempotent — an id that is not on this latch raises
    :class:`NotFoundError` rather than reporting a cheerful False, because a
    silent success would let a caller believe it had cancelled a schedule that
    is still holding a gate open.
    """

    result: Optional[str]
    removed: bool
    latch_id: Optional[str]
    temporal_date_id: Optional[str]
    request_id: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "RecurringHoldOpenRemoved":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            removed=bool(d.get("removed")),
            latch_id=d.get("latch_id"),
            temporal_date_id=d.get("temporal_date_id"),
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


@dataclass
class WebhookDelivery:
    """One delivery attempt of one event to one webhook.

    ``status`` is ``pending``, ``delivered``, or ``failed``; ``attempts``
    counts tries so far and ``last_status_code`` / ``last_error`` describe the
    most recent one. ``next_attempt_datetime`` is set while Nimbio is still
    retrying.

    The event body Nimbio sent is not echoed back. ``last_error`` does carry
    the first part of *your own* endpoint's response on a non-2xx reply — which
    is what makes a broken receiver diagnosable, and worth knowing about if
    your error pages carry anything sensitive.
    """

    delivery_id: Optional[str]
    event_id: Optional[str]
    event_type: Optional[str]
    status: Optional[str]
    attempts: Optional[int]
    last_status_code: Optional[int]
    last_error: Optional[str]
    next_attempt_datetime: Optional[str]
    created_datetime: Optional[str]
    delivered_datetime: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def failed(self) -> bool:
        """True for a delivery in the terminal ``failed`` state — the ones
        :meth:`community.retry_failed_deliveries` re-sends."""
        return self.status == "failed"

    @classmethod
    def from_dict(cls, raw: Any) -> "WebhookDelivery":
        d = _d(raw)
        return cls(
            delivery_id=d.get("delivery_id"),
            event_id=d.get("event_id"),
            event_type=d.get("event_type"),
            status=d.get("status"),
            attempts=d.get("attempts"),
            last_status_code=d.get("last_status_code"),
            last_error=d.get("last_error"),
            next_attempt_datetime=d.get("next_attempt_datetime"),
            created_datetime=d.get("created_datetime"),
            delivered_datetime=d.get("delivered_datetime"),
            raw=d,
        )


@dataclass
class DeliveryReplay:
    """A newly enqueued replay of a past delivery.

    ``delivery_id`` is new — a replay is a new delivery row — while
    ``event_id`` is the **original** event's, because the replay re-sends the
    original payload byte for byte. ``replayed_from_delivery_id`` points back
    at the attempt it re-sends.
    """

    result: Optional[str]
    delivery_id: Optional[str]
    replayed_from_delivery_id: Optional[str]
    event_id: Optional[str]
    event_type: Optional[str]
    status: Optional[str]
    created_datetime: Optional[str]
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        """True on a test-mode key: nothing was enqueued."""
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "DeliveryReplay":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            delivery_id=d.get("delivery_id"),
            replayed_from_delivery_id=d.get("replayed_from_delivery_id"),
            event_id=d.get("event_id"),
            event_type=d.get("event_type"),
            status=d.get("status"),
            created_datetime=d.get("created_datetime"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class DeliveryReplayBatch:
    """Result of :meth:`community.retry_failed_deliveries` — what was actually
    re-enqueued, which is not the same as what was asked for.

    ``replayed`` holds the new deliveries, ``replayed_count`` their number.
    ``skipped_in_flight`` counts deliveries Nimbio is still retrying itself
    (replaying those would double-fire), and ``skipped_duplicate_event`` counts
    candidates dropped because another replay in the same batch already covers
    that event id. Both skips are normal: calling this twice in a row re-sends
    nothing the second time.
    """

    result: Optional[str]
    webhook_id: Optional[str]
    replayed: List[DeliveryReplay] = field(default_factory=list)
    replayed_count: int = 0
    skipped_in_flight: int = 0
    skipped_duplicate_event: int = 0
    limit: Optional[int] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.replayed)

    def __len__(self) -> int:
        return len(self.replayed)

    @property
    def simulated(self) -> bool:
        """True on a test-mode key: nothing was enqueued."""
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "DeliveryReplayBatch":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            webhook_id=d.get("webhook_id"),
            replayed=[DeliveryReplay.from_dict(x) for x in (d.get("replayed") or [])],
            replayed_count=int(d.get("replayed_count") or 0),
            skipped_in_flight=int(d.get("skipped_in_flight") or 0),
            skipped_duplicate_event=int(d.get("skipped_duplicate_event") or 0),
            limit=d.get("limit"),
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
    — the event-specific fields live under ``data["data"]``. Events from
    ``account.stream_events()`` carry ``account_id`` in place of
    ``community_id``; parse those with :meth:`DirectoryCallRinging.from_event`
    / :meth:`DirectoryCallEnded.from_event`.
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
    reads (``gate_status()`` / ``hold_opens()``, or
    ``account.directory_calls()`` on the account stream), then keep iterating.
    """

    reason: Optional[str] = None


# --------------------------------------------------------------------------- #
# Directory calls (account events)
# --------------------------------------------------------------------------- #
#
# A GuestView visitor calling *you*. Delivered live on the account stream
# (``account.stream_events()``) as ``directory_call.ringing`` and
# ``directory_call.ended``, and kept as history behind
# ``account.directory_calls()``. Every string vocabulary here is open: an
# unrecognised ``outcome`` or ``ended_by`` is carried through as-is, never
# rejected — compare against :data:`constants.DIRECTORY_CALL_OUTCOMES`.

@dataclass
class DirectoryCallCommunity:
    """The community the call was placed at."""

    id: Optional[int]
    name: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "DirectoryCallCommunity":
        d = _d(raw)
        return cls(id=_int(d.get("id")), name=d.get("name"), raw=d)


@dataclass
class DirectoryCallLatch:
    """The gate the visitor is standing at."""

    id: Optional[str]
    name: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "DirectoryCallLatch":
        d = _d(raw)
        return cls(id=d.get("id"), name=d.get("name"), raw=d)


@dataclass
class DirectoryCallCalled:
    """Who the visitor called: you directly (``type == "member"``) or a home
    you belong to (``type == "home"``, with ``home_id``/``home_name`` set) —
    a home call rings every member of that home."""

    type: Optional[str]  # "member" | "home"
    home_id: Optional[str]
    home_name: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "DirectoryCallCalled":
        d = _d(raw)
        return cls(type=d.get("type"), home_id=d.get("home_id"),
                   home_name=d.get("home_name"), raw=d)


@dataclass
class DirectoryCallCaller:
    """A caller who was signed in to Nimbio when they called.

    Anonymous guests have no caller object at all (the parent's ``caller`` is
    None). Either name may still be None for a signed-in caller who never set
    one. The caller's account id is never disclosed.
    """

    signed_in: bool
    first_name: Optional[str]
    last_name: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def display_name(self) -> Optional[str]:
        """``"First Last"`` from whichever parts are present, else None."""
        name = " ".join(p for p in (self.first_name, self.last_name) if p)
        return name or None

    @classmethod
    def from_dict(cls, raw: Any) -> "DirectoryCallCaller":
        d = _d(raw)
        return cls(signed_in=bool(d.get("signed_in")),
                   first_name=d.get("first_name"),
                   last_name=d.get("last_name"), raw=d)


def _caller(value: Any) -> Optional[DirectoryCallCaller]:
    return DirectoryCallCaller.from_dict(value) if isinstance(value, dict) else None


def _event_payload(event: Any) -> Dict[str, Any]:
    """The per-event fields of a :class:`StreamEvent`, or a dict as given."""
    if isinstance(event, StreamEvent):
        return event.payload
    return _d(event)


@dataclass
class DirectoryCallRinging:
    """``directory_call.ringing`` — a visitor is calling you right now.

    Build one from a stream event with :meth:`from_event`. You have until
    ``answer_window_ends_at`` (nine minutes after ``placed_at``) to answer in
    the Nimbio app; exactly one ``directory_call.ended`` follows for the same
    ``directory_call_id``.
    """

    directory_call_id: Optional[str]
    placed_at: Optional[str]
    answer_window_ends_at: Optional[str]
    community: DirectoryCallCommunity
    latch: Optional[DirectoryCallLatch]  # None when the call has no gate
    called: DirectoryCallCalled
    arrived_via: Optional[str]  # "nfc" | "link"
    caller: Optional[DirectoryCallCaller]  # None for an anonymous guest
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_event(cls, event: Any) -> "DirectoryCallRinging":
        """Parse a ``directory_call.ringing`` :class:`StreamEvent` (or its
        ``payload`` dict)."""
        return cls.from_dict(_event_payload(event))

    @classmethod
    def from_dict(cls, raw: Any) -> "DirectoryCallRinging":
        d = _d(raw)
        latch = d.get("latch")
        return cls(
            directory_call_id=d.get("directory_call_id"),
            placed_at=d.get("placed_at"),
            answer_window_ends_at=d.get("answer_window_ends_at"),
            community=DirectoryCallCommunity.from_dict(d.get("community")),
            latch=(DirectoryCallLatch.from_dict(latch)
                   if isinstance(latch, dict) else None),
            called=DirectoryCallCalled.from_dict(d.get("called")),
            arrived_via=d.get("arrived_via"),
            caller=_caller(d.get("caller")),
            raw=d,
        )


@dataclass
class DirectoryCallEnded:
    """``directory_call.ended`` — sent exactly once per call when it ends.

    ``outcome`` is the **call's** outcome, the same for everyone it rang
    (``opened``, ``answered`` or ``missed``) and an open vocabulary: a newer
    server may send a value this release does not know, which is passed
    through unchanged. Your own part is in the ``*_by_you`` flags — declining
    does not end the call for anyone else, so ``declined_by_you`` can be True
    while ``outcome`` is ``opened``.
    """

    directory_call_id: Optional[str]
    outcome: Optional[str]  # open set: "opened" | "answered" | "missed" | ...
    ended_at: Optional[str]
    ended_by: Optional[str]  # open set: "caller" | "callee" | "timeout" | ...
    answered_at: Optional[str]
    answered_by_you: bool
    answered_by_first_name: Optional[str]
    declined_by_you: bool
    opened_by_you: bool
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_event(cls, event: Any) -> "DirectoryCallEnded":
        """Parse a ``directory_call.ended`` :class:`StreamEvent` (or its
        ``payload`` dict)."""
        return cls.from_dict(_event_payload(event))

    @classmethod
    def from_dict(cls, raw: Any) -> "DirectoryCallEnded":
        d = _d(raw)
        return cls(
            directory_call_id=d.get("directory_call_id"),
            outcome=d.get("outcome"),
            ended_at=d.get("ended_at"),
            ended_by=d.get("ended_by"),
            answered_at=d.get("answered_at"),
            answered_by_you=bool(d.get("answered_by_you")),
            answered_by_first_name=d.get("answered_by_first_name"),
            declined_by_you=bool(d.get("declined_by_you")),
            opened_by_you=bool(d.get("opened_by_you")),
            raw=d,
        )


@dataclass
class DirectoryCall:
    """One row of :meth:`account.directory_calls` — a call that rang you.

    Carries every ``directory_call.ringing`` field plus where the call got
    to. ``state`` is ``ringing``, ``answered`` or ``ended``; ``outcome`` and
    the ``ended_*`` fields are None while the call is still live. Both
    ``state`` and ``outcome`` are open vocabularies.
    """

    directory_call_id: Optional[str]
    placed_at: Optional[str]
    answer_window_ends_at: Optional[str]
    community: DirectoryCallCommunity
    latch: Optional[DirectoryCallLatch]
    called: DirectoryCallCalled
    arrived_via: Optional[str]
    caller: Optional[DirectoryCallCaller]
    state: Optional[str]  # open set: "ringing" | "answered" | "ended" | ...
    outcome: Optional[str]  # open set; None while live
    ended_at: Optional[str]
    ended_by: Optional[str]
    answered_at: Optional[str]
    answered_by_you: bool
    answered_by_first_name: Optional[str]
    declined_by_you: bool
    opened_by_you: bool
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "DirectoryCall":
        d = _d(raw)
        ringing = DirectoryCallRinging.from_dict(d)
        ended = DirectoryCallEnded.from_dict(d)
        return cls(
            directory_call_id=ringing.directory_call_id,
            placed_at=ringing.placed_at,
            answer_window_ends_at=ringing.answer_window_ends_at,
            community=ringing.community,
            latch=ringing.latch,
            called=ringing.called,
            arrived_via=ringing.arrived_via,
            caller=ringing.caller,
            state=d.get("state"),
            outcome=ended.outcome,
            ended_at=ended.ended_at,
            ended_by=ended.ended_by,
            answered_at=ended.answered_at,
            answered_by_you=ended.answered_by_you,
            answered_by_first_name=ended.answered_by_first_name,
            declined_by_you=ended.declined_by_you,
            opened_by_you=ended.opened_by_you,
            raw=d,
        )


@dataclass
class DirectoryCallPage:
    """Result of :meth:`account.directory_calls` — newest first.

    Pass ``next_before`` back as ``before=`` for the next (older) page; it is
    None on the last page. Or let :meth:`account.iter_directory_calls` walk
    the pages for you.
    """

    calls: List[DirectoryCall]
    next_before: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def has_more(self) -> bool:
        return self.next_before is not None

    def __iter__(self):
        return iter(self.calls)

    def __len__(self) -> int:
        return len(self.calls)

    @classmethod
    def from_dict(cls, raw: Any) -> "DirectoryCallPage":
        d = _d(raw)
        return cls(
            calls=[DirectoryCall.from_dict(x) for x in (d.get("calls") or [])],
            next_before=d.get("next_before") or None,
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Account open history
# --------------------------------------------------------------------------- #

@dataclass
class AccountOpenKey:
    """The key on *your* account an open is filed under — for an open on a key
    you shared, your key, not the shared copy that physically opened."""

    id: Optional[str]
    name: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccountOpenKey":
        d = _d(raw)
        return cls(id=d.get("id"), name=d.get("name"), raw=d)


@dataclass
class AccountOpenLatch:
    """The gate that was opened."""

    id: Optional[str]
    name: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccountOpenLatch":
        d = _d(raw)
        return cls(id=d.get("id"), name=d.get("name"), raw=d)


@dataclass
class AccountOpenedBy:
    """Who opened: ``is_you`` when your own key did; otherwise ``name`` is the
    opener as the app shows it, or the guest link's label for a guest-link
    open. No contact details are ever included."""

    is_you: bool
    name: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccountOpenedBy":
        d = _d(raw)
        return cls(is_you=bool(d.get("is_you")), name=d.get("name"), raw=d)


@dataclass
class AccountOpenGuestLink:
    """The guest link an open was made through."""

    id: Optional[int]
    label: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccountOpenGuestLink":
        d = _d(raw)
        return cls(id=_int(d.get("id")), label=d.get("label"), raw=d)


@dataclass
class AccountOpen:
    """One row of :meth:`account.history` — an open on one of your keys,
    including opens on keys you shared with someone else.

    ``opened_at`` is in the latch's local offset, as the app shows it.
    ``open_type`` (e.g. ``"open"``; ``"unknown"`` for an unnamed id) and
    ``result`` (e.g. ``"opened"``) are
    stable lowercase names but an **open** vocabulary: a newer server may send
    a value this release does not know, which is passed through unchanged.
    The raw ``open_type_id`` / ``result_id`` ride along; the known names are
    :data:`constants.OPEN_HISTORY_TYPES` / :data:`constants.OPEN_HISTORY_RESULTS`.

    ``id`` is the open's stable log id, unique across your history. A fresh
    open is logged before the gate answers and its ``result`` is filled in up
    to ~18s later, so to poll, re-read a trailing minute and upsert by ``id``
    rather than moving ``date_from`` past rows you have already seen.
    """

    id: Optional[int]
    opened_at: Optional[str]
    key: AccountOpenKey
    latch: AccountOpenLatch
    opened_by: AccountOpenedBy
    guest_link: Optional[AccountOpenGuestLink]  # None unless via a guest link
    open_type: Optional[str]  # open set
    result: Optional[str]  # open set
    open_type_id: Optional[int]
    result_id: Optional[int]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccountOpen":
        d = _d(raw)
        guest_link = d.get("guest_link")
        return cls(
            id=_int(d.get("id")),
            opened_at=d.get("opened_at"),
            key=AccountOpenKey.from_dict(d.get("key")),
            latch=AccountOpenLatch.from_dict(d.get("latch")),
            opened_by=AccountOpenedBy.from_dict(d.get("opened_by")),
            guest_link=(AccountOpenGuestLink.from_dict(guest_link)
                        if isinstance(guest_link, dict) else None),
            open_type=d.get("open_type"),
            result=d.get("result"),
            open_type_id=_int(d.get("open_type_id")),
            result_id=_int(d.get("result_id")),
            raw=d,
        )


@dataclass
class OpenHistoryPage:
    """Result of :meth:`account.history` — one page (up to 1000 rows) of
    opens, newest first across all your keys.

    ``date_from``/``date_to`` echo the effective window (the server clamps
    ``from`` to the 90-day retention floor). Ask for ``page + 1`` while
    ``has_more`` is true, or let :meth:`account.iter_history` do it.
    """

    opens: List[AccountOpen]
    page: Optional[int]
    has_more: bool
    date_from: Optional[str]
    date_to: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.opens)

    def __len__(self) -> int:
        return len(self.opens)

    @classmethod
    def from_dict(cls, raw: Any) -> "OpenHistoryPage":
        d = _d(raw)
        return cls(
            opens=[AccountOpen.from_dict(x) for x in (d.get("opens") or [])],
            page=_int(d.get("page")),
            has_more=bool(d.get("has_more")),
            date_from=d.get("from"),
            date_to=d.get("to"),
            raw=d,
        )


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


# --------------------------------------------------------------------------- #
# Community settings
# --------------------------------------------------------------------------- #

@dataclass
class CommunitySettings:
    """Result of :meth:`community.settings` and
    :meth:`community.update_settings` — the community's configuration.

    ``settings`` is everything :meth:`community.update_settings` may change.
    ``read_only`` is what Nimbio provisions for you and an API key cannot
    touch; it is here for **feature discovery**, which is the point of the read:
    several endpoint families are gated on these flags, and without them the
    only way to learn a feature is off is to call it and read a 403. Use
    :meth:`feature` rather than indexing.

    ``read_only.event_keys_enabled`` is the *resolved* answer for event links —
    the settable ``settings["event_keys_override"]``
    (``inherit``/``allow``/``deny``) combined with the property type's default.

    ``read_only.access_code_mode`` (``per_member`` / ``single_entry``) is the
    one read-only value an API key *can* change — but only through
    :meth:`community.set_access_code_mode`, because switching it deletes every
    access code in the community and needs an explicit confirm. Sending it to
    :meth:`community.update_settings` is a 422.

    ``terminology`` is the resolved member/home wording actually shown to
    members; ``terminology_options`` is the property type's picker list, which
    is where a ``*_terminology_option_id`` comes from. Both stay plain dicts —
    they are display detail a caller indexes into directly.

    ``changed`` names the keys a patch actually applied, and is empty on a
    read. A test-mode patch reports ``result == "simulated"`` with the
    community's **unchanged** settings.
    """

    community_id: Optional[int]
    settings: Dict[str, Any] = field(default_factory=dict)
    read_only: Dict[str, Any] = field(default_factory=dict)
    terminology: Dict[str, Any] = field(default_factory=dict)
    terminology_options: Dict[str, Any] = field(default_factory=dict)
    changed: List[str] = field(default_factory=list)
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    def feature(self, name: str) -> bool:
        """True when the named ``read_only`` flag is switched on.

        This is the pre-flight check that replaces calling an endpoint to see
        whether it 403s: ``feature("allow_hold_opens")`` false means every
        hold-open call is refused, and ``feature("is_open_log_history_enabled")``
        false means the two log reads are. An unknown flag reads False — a
        server that has never heard of it cannot have it switched on.
        """
        return bool(self.read_only.get(name))

    def setting(self, name: str, default: Any = None) -> Any:
        """One settable value, or ``default`` when this server did not send it."""
        return self.settings.get(name, default)

    @classmethod
    def from_dict(cls, raw: Any) -> "CommunitySettings":
        d = _d(raw)
        return cls(
            community_id=d.get("community_id"),
            settings=_d(d.get("settings")),
            read_only=_d(d.get("read_only")),
            terminology=_d(d.get("terminology")),
            terminology_options=_d(d.get("terminology_options")),
            changed=list(d.get("changed") or []),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Homes / units roster
# --------------------------------------------------------------------------- #

@dataclass
class HomeResident:
    """One member attached to a home, as :meth:`community.home` returns them.

    ``account_community_id`` is the id every other member endpoint takes —
    including :meth:`community.set_move_out_date`. ``accepted`` false is a
    pending request, not a resident yet.
    """

    account_community_id: Optional[int]
    account_id: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    phone_numbers: List[str] = field(default_factory=list)
    accepted: bool = False
    move_out_date: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "HomeResident":
        d = _d(raw)
        return cls(
            account_community_id=d.get("account_community_id"),
            account_id=d.get("account_id"),
            first_name=d.get("first_name"),
            last_name=d.get("last_name"),
            phone_numbers=list(d.get("phone_numbers") or []),
            accepted=bool(d.get("accepted")),
            move_out_date=d.get("move_out_date"),
            raw=d,
        )


@dataclass
class Home:
    """One home (unit) — a row of :meth:`community.homes`, or the full resource
    :meth:`community.home`, :meth:`community.add_home` and
    :meth:`community.update_home` return.

    ``members`` is populated only by :meth:`community.home`; the list read and
    the writes report ``member_count`` alone. Read it before
    :meth:`community.remove_home`, which detaches every one of them.

    A test-mode write reports ``result == "simulated"`` and creates or changes
    nothing, so the identifying fields are None — what *would* have been
    written is echoed on ``.raw`` (``would_create`` / ``would_set``).
    """

    home_id: Optional[str]
    address: Optional[str]
    name: Optional[str] = None
    owner_occupied: bool = False
    hidden: bool = False
    home_phone: Optional[str] = None
    home_email: Optional[str] = None
    owner_name: Optional[str] = None
    created_datetime: Optional[str] = None
    member_count: int = 0
    members: List[HomeResident] = field(default_factory=list)
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "Home":
        # Accepts either a bare home row (the list read) or the ``{"result":
        # ..., "home": {...}}`` envelope the single read and the writes return.
        d = _d(raw)
        home = _d(d.get("home")) if "home" in d else d
        return cls(
            home_id=home.get("home_id", d.get("home_id")),
            address=home.get("address"),
            name=home.get("name"),
            owner_occupied=bool(home.get("owner_occupied")),
            hidden=bool(home.get("hidden")),
            home_phone=home.get("home_phone"),
            home_email=home.get("home_email"),
            owner_name=home.get("owner_name"),
            created_datetime=home.get("created_datetime"),
            member_count=int(home.get("member_count") or 0),
            members=[HomeResident.from_dict(m) for m in (home.get("members") or [])],
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class HomeRemoved:
    """Result of :meth:`community.remove_home`.

    ``detached_member_count`` is the blast radius the call actually had: every
    resident attached to the home was detached from it. They remain members and
    keep their keys, but they are no longer associated with any unit and
    **nothing restores the association automatically**.

    On a test-mode call ``deleted`` is False, ``result`` is ``"simulated"`` and
    ``detached_member_count`` is what the call *would* have detached (the
    server sends it as ``would_detach_member_count``).
    """

    result: Optional[str]
    home_id: Optional[str]
    deleted: bool = False
    detached_member_count: int = 0
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "HomeRemoved":
        d = _d(raw)
        count = d.get("detached_member_count")
        if count is None:
            count = d.get("would_detach_member_count")
        return cls(
            result=d.get("result"),
            home_id=d.get("home_id"),
            deleted=bool(d.get("deleted")),
            detached_member_count=int(count or 0),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class MoveOutDate:
    """Result of :meth:`community.set_move_out_date`.

    ``move_out_date`` is the stored value, ``None`` once cleared. A test-mode
    call reports ``result == "simulated"``, stores nothing, and echoes the
    value it would have set (the server sends it as ``would_set``).
    """

    result: Optional[str]
    account_community_id: Optional[int]
    move_out_date: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "MoveOutDate":
        d = _d(raw)
        date = d.get("move_out_date", d.get("would_set"))
        return cls(
            result=d.get("result"),
            account_community_id=d.get("account_community_id"),
            move_out_date=date,
            request_id=d.get("request_id"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# My member-open notification settings
# --------------------------------------------------------------------------- #

@dataclass
class QuietHours:
    """One window during which this manager's member-open alerts are suppressed.

    ``days_of_the_week`` is a letter string from ``MTWHFSU`` where **H is
    Thursday**, ``S`` is Saturday and ``U`` is Sunday, naming the day the
    window *starts* on. ``start_time`` and ``end_time`` are ``'HH:MM'``,
    24-hour, **evaluated in the local timezone of the gate that was opened** —
    not the manager's, and not UTC.

    Unlike a key access schedule, a quiet-hours window MAY wrap past midnight:
    ``22:00``-``06:00`` is one window, not two. See :attr:`wraps_midnight`.
    """

    quiet_hours_id: Optional[Any]
    days_of_the_week: str = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def all_day(self) -> bool:
        """True when the window covers its whole day(s) — both times unset."""
        return self.start_time is None and self.end_time is None

    @property
    def wraps_midnight(self) -> bool:
        """True when this window runs past midnight into the next morning.

        Legal here and nowhere else on this API: key schedules and recurring
        hold opens both refuse a reversed window and must be split in two.
        """
        if not self.start_time or not self.end_time:
            return False
        return self.start_time > self.end_time

    @classmethod
    def from_dict(cls, raw: Any) -> "QuietHours":
        d = _d(raw)
        return cls(
            quiet_hours_id=d.get("quiet_hours_id"),
            days_of_the_week=d.get("days_of_the_week") or "",
            start_time=d.get("start_time"),
            end_time=d.get("end_time"),
            raw=d,
        )


@dataclass
class NotificationSettings:
    """Member-open notification settings for **the community manager who owns
    the API key** — returned by all four of
    :meth:`community.my_notification_settings`,
    :meth:`community.set_my_notifications_enabled`,
    :meth:`community.add_quiet_hours` and :meth:`community.remove_quiet_hours`.

    These are **per manager, not per community**. A community with several
    managers has several independent settings objects, and turning ``enabled``
    off through one key does not stop another manager's alerts.

    ``enabled`` is whether this manager is pushed to when a member opens a
    gate. ``feature_available`` is whether the community permits the feature at
    all — false makes all three writes 403 ``open_notifications_disabled`` and
    leaves ``enabled`` with no effect.

    Every one of the four calls returns the complete object, quiet hours
    included, so nothing here needs a follow-up read.
    """

    result: Optional[str]
    enabled: bool = False
    feature_available: bool = False
    quiet_hours: List[QuietHours] = field(default_factory=list)
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "NotificationSettings":
        d = _d(raw)
        return cls(
            result=d.get("result"),
            enabled=bool(d.get("enabled")),
            feature_available=bool(d.get("feature_available")),
            quiet_hours=[QuietHours.from_dict(q)
                         for q in (d.get("quiet_hours") or [])],
            request_id=d.get("request_id"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Guest access — shared pieces
# --------------------------------------------------------------------------- #

@dataclass
class NamedLatch:
    """A gate referred to by id and name, nothing more.

    The guest-access surface names gates in three places — the latches behind a
    guest link, the gates GuestView Entry covers, and the gates access codes are
    allowed to open — and the server spells the pair two ways
    (``latch_id``/``latch_name`` and ``id``/``name``). Both are accepted here so
    the attribute names never depend on which endpoint the row came from.
    """

    latch_id: Optional[str]
    latch_name: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "NamedLatch":
        d = _d(raw)
        return cls(
            latch_id=d.get("latch_id", d.get("id")),
            latch_name=d.get("latch_name", d.get("name")),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Guest links
# --------------------------------------------------------------------------- #

@dataclass
class GuestLink:
    """One guest link — returned by :meth:`community.guest_links`,
    :meth:`community.create_guest_link` and :meth:`community.revoke_guest_link`.

    **This object is secret material.** ``token`` and ``url`` are a working
    gate: anyone holding the URL can open the latches in ``latches`` with no
    account, no key and no login. The list read returns them just as the create
    call does, so a recovered link is exactly as usable as a fresh one.

    For that reason ``token``, ``url`` and ``raw`` are **left out of this
    object's** ``repr``: printing a link at a prompt, or interpolating one into
    a log line, should not put a working gate in your scrollback. Read the
    attributes by name when you actually need to send the link, and treat what
    you get the way you would treat a password.

    ``state`` is computed by the server at read time and is one of ``active``,
    ``upcoming`` (an event link whose window has not opened), ``expired``,
    ``spent`` (a limited-use link out of opens), ``revoked``, or
    ``feature_disabled`` (the community switched the feature off underneath it).
    Branch on it rather than re-deriving it from the timestamps — a link can be
    dead for reasons no timestamp shows.

    ``max_uses`` / ``uses_consumed`` are meaningful for ``limited_use`` links;
    an ``event`` link has unlimited opens inside ``window_start``/``window_end``
    and reports its usage through ``total_opens`` alone.
    """

    guest_link_id: Optional[Any]
    link_type: Optional[str] = None
    state: Optional[str] = None
    token: Optional[str] = field(default=None, repr=False)
    url: Optional[str] = field(default=None, repr=False)
    title: Optional[str] = None
    subtitle: Optional[str] = None
    extra_info: Optional[str] = None
    community_id: Optional[Any] = None
    key_id: Optional[str] = None
    key_name: Optional[str] = None
    latches: List[NamedLatch] = field(default_factory=list)
    max_uses: Optional[int] = None
    uses_consumed: int = 0
    total_opens: int = 0
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    notify_on_use: bool = False
    revoked: bool = False
    revoked_datetime: Optional[str] = None
    created_at: Optional[str] = None
    created_by_account_id: Optional[str] = None
    created_by_cm: bool = False
    created_by_name: Optional[str] = None
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @property
    def active(self) -> bool:
        """True only for ``state == "active"``.

        Deliberately not "not revoked": a spent, expired, not-yet-open or
        feature-disabled link is equally unusable, and only ``state`` knows.
        """
        return self.state == "active"

    @property
    def uses_remaining(self) -> Optional[int]:
        """Opens left on a ``limited_use`` link, or None when unlimited.

        None for an ``event`` link (unlimited inside its window) and for any
        link the server did not give a ``max_uses``.
        """
        if self.max_uses is None:
            return None
        return max(0, int(self.max_uses) - int(self.uses_consumed or 0))

    @property
    def latch_ids(self) -> List[str]:
        """Just the ids of the gates this link opens."""
        return [x.latch_id for x in self.latches if x.latch_id is not None]

    @classmethod
    def from_dict(cls, raw: Any) -> "GuestLink":
        # Accepts a bare row (the list read) or the ``{"result": ...,
        # "guest_link": {...}}`` envelope the create and revoke calls return.
        d = _d(raw)
        link = _d(d.get("guest_link")) if isinstance(d.get("guest_link"), dict) else d
        return cls(
            guest_link_id=link.get("guest_link_id"),
            link_type=link.get("link_type"),
            state=link.get("state"),
            token=link.get("token"),
            url=link.get("url"),
            title=link.get("title"),
            subtitle=link.get("subtitle"),
            extra_info=link.get("extra_info"),
            community_id=link.get("community_id"),
            key_id=link.get("key_id"),
            key_name=link.get("key_name"),
            latches=[NamedLatch.from_dict(x) for x in (link.get("latches") or [])],
            max_uses=link.get("max_uses"),
            uses_consumed=int(link.get("uses_consumed") or 0),
            total_opens=int(link.get("total_opens") or 0),
            window_start=link.get("window_start"),
            window_end=link.get("window_end"),
            expires_at=link.get("expires_at"),
            last_used_at=link.get("last_used_at"),
            notify_on_use=bool(link.get("notify_on_use")),
            revoked=bool(link.get("revoked")),
            revoked_datetime=link.get("revoked_datetime"),
            created_at=link.get("created_at"),
            created_by_account_id=link.get("created_by_account_id"),
            created_by_cm=bool(link.get("created_by_cm")),
            created_by_name=link.get("created_by_name"),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class GuestLinkLogEntry:
    """One attempt against a guest link — an open, a refusal, or a throttle.

    **Guest PII.** ``client_ip`` and ``user_agent`` belong to whoever followed
    the link, and a signed-in redeemer's display name rides along on ``.raw``
    when the community requires an account. Retain accordingly.
    """

    guest_link_log_id: Optional[Any]
    guest_link_id: Optional[Any] = None
    link_title: Optional[str] = None
    link_type: Optional[str] = None
    latch_id: Optional[str] = None
    latch_name: Optional[str] = None
    log_datetime: Optional[str] = None
    result: Optional[str] = None
    use_number: Optional[int] = None
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def opened(self) -> bool:
        return self.result == "opened"

    @classmethod
    def from_dict(cls, raw: Any) -> "GuestLinkLogEntry":
        d = _d(raw)
        return cls(
            guest_link_log_id=d.get("guest_link_log_id"),
            guest_link_id=d.get("guest_link_id"),
            link_title=d.get("link_title"),
            link_type=d.get("link_type"),
            latch_id=d.get("latch_id"),
            latch_name=d.get("latch_name"),
            log_datetime=d.get("log_datetime"),
            result=d.get("result"),
            use_number=d.get("use_number"),
            client_ip=d.get("client_ip"),
            user_agent=d.get("user_agent"),
            raw=d,
        )


@dataclass
class GuestLinkLogPage:
    """A page of guest-link attempts, newest first.

    Offset-paged: ask for the next page with ``offset + limit``. The server
    does not report a total, so a page shorter than ``limit`` is the end.
    """

    logs: List[GuestLinkLogEntry] = field(default_factory=list)
    limit: Optional[int] = None
    offset: Optional[int] = None
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.logs)

    def __len__(self) -> int:
        return len(self.logs)

    @classmethod
    def from_dict(cls, raw: Any) -> "GuestLinkLogPage":
        d = _d(raw)
        return cls(
            logs=[GuestLinkLogEntry.from_dict(x) for x in (d.get("logs") or [])],
            limit=d.get("limit"),
            offset=d.get("offset"),
            result=d.get("result"),
            raw=d,
        )


@dataclass
class GuestLinkLatchExclusions:
    """Gates the community has barred from each guest-link type.

    **Absence is permission.** A gate that is not listed for a link type may
    back a link of that type, so an empty answer means every gate the backing
    key opens is offerable. The list is **per link type**: a gate barred from
    ``event`` links may still be fine for ``limited_use`` ones.

    ``by_type`` is the raw mapping (``{"event": [...], "limited_use": [...]}``);
    :meth:`excluded_for` and :meth:`is_excluded` are the safe way to read it,
    because a link type the server has never mentioned means "nothing excluded",
    not KeyError.
    """

    by_type: Dict[str, List[str]] = field(default_factory=dict)
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def excluded_for(self, link_type: str) -> List[str]:
        """Latch ids barred from ``link_type`` — empty when none are."""
        return list(self.by_type.get(link_type) or [])

    def is_excluded(self, link_type: str, latch_id: str) -> bool:
        """True when naming ``latch_id`` on a ``link_type`` link would be a 422."""
        return latch_id in self.excluded_for(link_type)

    @classmethod
    def from_dict(cls, raw: Any) -> "GuestLinkLatchExclusions":
        d = _d(raw)
        excluded = d.get("excluded_latch_ids")
        by_type: Dict[str, List[str]] = {}
        if isinstance(excluded, dict):
            for link_type, ids in excluded.items():
                by_type[str(link_type)] = list(ids or [])
        return cls(by_type=by_type, result=d.get("result"), raw=d)


# --------------------------------------------------------------------------- #
# Directory access codes
# --------------------------------------------------------------------------- #

@dataclass
class AccessCode:
    """One access code as the community sees it — **never its PIN**.

    ``code_masked`` is a run of asterisks and ``code_length`` its length; the
    cleartext is returned exactly once, by :meth:`community.create_access_code`,
    and nothing reads it back. A lost PIN is replaced, not recovered.

    ``api_managed`` is True for the codes this API key created, and those are
    the only ones :meth:`community.update_access_code` and
    :meth:`community.delete_access_code` will touch — a resident's own code
    answers 404 to both.

    ``has_schedule`` says a recurring weekly window is attached; that window is
    evaluated in **the gate's own local timezone**, while ``expires_at`` is an
    absolute UTC cutoff. A code carrying both must satisfy both.

    In ``single_entry`` mode (see :meth:`community.access_code_mode`) a row
    also carries the owner's 3-letter ``preamble`` and ``entry_code_masked``
    — preamble in clear, PIN masked (``"ESM******"``) — which is the shape of
    what the visitor types. In ``per_member`` mode both are ``None``.
    """

    directory_access_code_id: Optional[Any]
    account_id: Optional[str] = None
    owner_name: Optional[str] = None
    api_managed: bool = False
    code_masked: Optional[str] = None
    code_length: Optional[int] = None
    preamble: Optional[str] = None
    entry_code_masked: Optional[str] = None
    disabled: bool = False
    expires_at: Optional[str] = None
    has_schedule: bool = False
    latch_ids: List[str] = field(default_factory=list)
    latches: List[NamedLatch] = field(default_factory=list)
    created_at: Optional[str] = None
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCode":
        # Accepts a bare row (the list read) or the ``{"result": ...,
        # "access_code": {...}}`` envelope the update returns — that one echoes
        # only the fields it changed, so everything here is optional.
        d = _d(raw)
        code = _d(d.get("access_code")) if isinstance(d.get("access_code"), dict) else d
        return cls(
            directory_access_code_id=code.get("directory_access_code_id"),
            account_id=code.get("account_id"),
            owner_name=code.get("owner_name"),
            api_managed=bool(code.get("api_managed")),
            code_masked=code.get("code_masked"),
            code_length=code.get("code_length"),
            preamble=code.get("preamble"),
            entry_code_masked=code.get("entry_code_masked"),
            disabled=bool(code.get("disabled")),
            expires_at=code.get("expires_at"),
            has_schedule=bool(code.get("has_schedule")),
            latch_ids=list(code.get("latch_ids") or []),
            latches=[NamedLatch.from_dict(x) for x in (code.get("latches") or [])],
            created_at=code.get("created_at"),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class AccessCodes:
    """Every access code in the community, residents' own codes included.

    ``feature_enabled`` mirrors the community's Directory Access Codes setting.
    When it is False the list still reads, but every write answers 403
    ``access_codes_disabled`` — branch on it rather than on an exception.

    ``access_code_mode`` is the mode the rows were read under — ``per_member``
    or ``single_entry`` (see :class:`AccessCodeModeStatus`) — so one call says
    whether to show each row's ``entry_code_masked`` or its ``code_masked``.
    """

    access_codes: List[AccessCode] = field(default_factory=list)
    feature_enabled: bool = False
    access_code_mode: Optional[str] = None
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.access_codes)

    def __len__(self) -> int:
        return len(self.access_codes)

    @property
    def api_managed(self) -> List[AccessCode]:
        """Only the codes this API key created — the ones it may edit or delete."""
        return [c for c in self.access_codes if c.api_managed]

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCodes":
        d = _d(raw)
        return cls(
            access_codes=[AccessCode.from_dict(x)
                          for x in (d.get("access_codes") or [])],
            feature_enabled=bool(d.get("feature_enabled")),
            access_code_mode=d.get("access_code_mode"),
            result=d.get("result"),
            raw=d,
        )


@dataclass
class AccessCodeCreated:
    """Result of :meth:`community.create_access_code` — **carries the PIN**.

    ``code`` is the cleartext the visitor will type, and this response is the
    **only** place it ever appears: the list read masks it and no other call
    reveals it. Deliver it now; if you lose it, delete the code and mint a new
    one.

    In ``single_entry`` mode (see :meth:`community.access_code_mode`) the
    visitor types the key owner's 3-letter ``preamble`` followed by the PIN,
    and ``entry_code`` is that full string (``"ESM481502"``) — returned once,
    like ``code``. In ``per_member`` mode both are ``None`` and the visitor
    types ``code`` alone.

    Because of that, ``code``, ``code_normalized``, ``entry_code`` and ``raw``
    are kept out of this object's ``repr`` — a create call logged at debug
    level should not write a working PIN to disk.

    A test-mode key validates and stores nothing: ``result`` is ``"simulated"``
    and the identifiers are absent.
    """

    directory_access_code_id: Optional[Any]
    code: Optional[str] = field(default=None, repr=False)
    code_normalized: Optional[str] = field(default=None, repr=False)
    preamble: Optional[str] = None
    entry_code: Optional[str] = field(default=None, repr=False)
    account_id: Optional[str] = None
    key_id: Optional[str] = None
    latch_ids: List[str] = field(default_factory=list)
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCodeCreated":
        d = _d(raw)
        code = _d(d.get("access_code")) if isinstance(d.get("access_code"), dict) else d
        return cls(
            directory_access_code_id=code.get("directory_access_code_id"),
            code=code.get("code"),
            code_normalized=code.get("code_normalized"),
            preamble=code.get("preamble"),
            entry_code=code.get("entry_code"),
            account_id=code.get("account_id"),
            key_id=code.get("key_id"),
            latch_ids=list(code.get("latch_ids") or []),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class AccessCodeDeleted:
    """Result of :meth:`community.delete_access_code`.

    The PIN stops working immediately and its gate assignments go with it. The
    redemption log rows survive, so the history of who came through the gate is
    not lost with the code. A test-mode key reports ``result == "simulated"``
    and deletes nothing.
    """

    directory_access_code_id: Optional[Any]
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCodeDeleted":
        d = _d(raw)
        return cls(
            directory_access_code_id=d.get("directory_access_code_id"),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class AccessCodeEligibleLatches:
    """The gates a community manager has allowed access codes to open.

    Every id passed to :meth:`community.create_access_code` or
    :meth:`community.update_access_code` must appear here or the call is
    rejected with ``invalid_latch``. The allowlist is set in the CM portal only
    — this API can read it and never change it.
    """

    latches: List[NamedLatch] = field(default_factory=list)
    feature_enabled: bool = False
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.latches)

    def __len__(self) -> int:
        return len(self.latches)

    @property
    def latch_ids(self) -> List[str]:
        """Just the ids — what a create or update call takes."""
        return [x.latch_id for x in self.latches if x.latch_id is not None]

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCodeEligibleLatches":
        d = _d(raw)
        return cls(
            latches=[NamedLatch.from_dict(x) for x in (d.get("latches") or [])],
            feature_enabled=bool(d.get("feature_enabled")),
            result=d.get("result"),
            raw=d,
        )


@dataclass
class AccessCodeLogEntry:
    """One access-code entry attempt at a keypad or in GuestView.

    ``code_entered_masked`` is asterisks and never the typed digits — on a
    successful attempt the entered code *is* a working PIN, so the server never
    sends it. Correlate a row back to a code you minted through
    ``directory_access_code_id``, which is set whenever the entry matched an
    existing code.

    ``result`` names the outcome: ``opened``, ``code_not_found``,
    ``code_disabled``, ``code_expired``, ``temporal_blocked``,
    ``latch_not_assigned``, ``open_failed``, and others the server may add.
    Rows carry the visitor's ``client_ip`` and the code owner's name.
    """

    directory_access_code_log_id: Optional[Any]
    directory_access_code_id: Optional[Any] = None
    account_id: Optional[str] = None
    owner_name: Optional[str] = None
    latch_id: Optional[str] = None
    log_datetime: Optional[str] = None
    result: Optional[str] = None
    code_entered_masked: Optional[str] = None
    client_ip: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def opened(self) -> bool:
        return self.result == "opened"

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCodeLogEntry":
        d = _d(raw)
        return cls(
            directory_access_code_log_id=d.get("directory_access_code_log_id"),
            directory_access_code_id=d.get("directory_access_code_id"),
            account_id=d.get("account_id"),
            owner_name=d.get("owner_name"),
            latch_id=d.get("latch_id"),
            log_datetime=d.get("log_datetime"),
            result=d.get("result"),
            code_entered_masked=d.get("code_entered_masked"),
            client_ip=d.get("client_ip"),
            raw=d,
        )


@dataclass
class AccessCodeLogPage:
    """A page of access-code entry attempts, newest first.

    Offset-paged; ``limit`` is clamped server-side to 1-200 and ``offset``
    floored at 0, so the ``limit`` and ``offset`` echoed here are what the
    server actually applied, not what you asked for.
    """

    logs: List[AccessCodeLogEntry] = field(default_factory=list)
    limit: Optional[int] = None
    offset: Optional[int] = None
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.logs)

    def __len__(self) -> int:
        return len(self.logs)

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCodeLogPage":
        d = _d(raw)
        return cls(
            logs=[AccessCodeLogEntry.from_dict(x) for x in (d.get("logs") or [])],
            limit=d.get("limit"),
            offset=d.get("offset"),
            result=d.get("result"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Access-code mode (per-member vs single-entry)
# --------------------------------------------------------------------------- #

AccessCodeMode = Literal["per_member", "single_entry"]
"""The two access-code systems a community can run.

``per_member`` — the default: a GuestView visitor picks the member they are
visiting and types that member's PIN. ``single_entry`` — one "Enter access
code" field for the whole community; every member carries a 3-letter
**preamble** and the visitor types preamble + PIN (``ESM481502``).
"""


@dataclass
class AccessCodeModePreview:
    """What switching the access-code mode would do — a read-only dry run.

    The same counts appear in three places: ``flip_preview`` on
    :class:`AccessCodeModeStatus`, ``error.preview`` on the 409
    ``requires_confirmation`` that :meth:`community.set_access_code_mode`
    raises without ``confirm=True`` (reach it as ``ConflictError.preview``),
    and ``would_change`` on a test key's simulated flip.

    ``codes_to_delete`` is **every** code in the community — residents' own
    included, not just this key's — because the strings change meaning with
    the mode. ``members_affected`` is how many members lose at least one code
    and will be notified. ``members_to_assign_preamble`` is how many would be
    given a preamble (zero when switching back to ``per_member``).

    ``mode`` is the community's *current* mode where the server includes it
    (the 409 preview and ``would_change``); it is ``None`` on ``flip_preview``,
    whose parent carries the current mode. A count the server omitted or sent
    malformed reads ``None`` rather than raising.
    """

    new_mode: Optional[str] = None
    codes_to_delete: Optional[int] = None
    members_affected: Optional[int] = None
    members_to_assign_preamble: Optional[int] = None
    mode: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def destructive(self) -> bool:
        """True when confirming would delete at least one code."""
        return (self.codes_to_delete or 0) > 0

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCodeModePreview":
        d = _d(raw)
        return cls(
            new_mode=d.get("new_mode"),
            codes_to_delete=_int(d.get("codes_to_delete")),
            members_affected=_int(d.get("members_affected")),
            members_to_assign_preamble=_int(
                d.get("members_to_assign_preamble")),
            mode=d.get("mode"),
            raw=d,
        )


@dataclass
class AccessCodeModeStatus:
    """Result of :meth:`community.access_code_mode` — the mode in force and
    what switching to the other one would cost.

    ``mode`` is ``per_member`` or ``single_entry`` (see :data:`AccessCodeMode`).
    ``flip_preview`` is a dry run of :meth:`community.set_access_code_mode` to
    the *other* mode; read it before flipping so a human sees the cost first.
    """

    mode: Optional[str]
    flip_preview: AccessCodeModePreview = field(
        default_factory=AccessCodeModePreview)
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def single_entry(self) -> bool:
        return self.mode == "single_entry"

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCodeModeStatus":
        d = _d(raw)
        return cls(
            mode=d.get("mode"),
            flip_preview=AccessCodeModePreview.from_dict(d.get("flip_preview")),
            result=d.get("result"),
            raw=d,
        )


@dataclass
class AccessCodeModeChange:
    """Result of :meth:`community.set_access_code_mode`, after the server
    accepted the request.

    Three outcomes land here (the fourth — the 409 asking for confirmation —
    is raised as :class:`ConflictError`):

    - **Unchanged**: the community was already in that mode. ``changed`` is
      False and nothing happened.
    - **Live flip**: ``changed`` is True; ``deleted_codes`` says how many codes
      went and ``notified_members`` how many members were told.
    - **Simulated** (test key with ``confirm=True``): ``simulated`` is True,
      ``changed`` is False, and ``would_change`` carries the preview of what a
      live key would have done. ``mode`` is ``None`` because nothing moved.
    """

    mode: Optional[str]
    changed: bool = False
    deleted_codes: Optional[int] = None
    notified_members: Optional[int] = None
    would_change: Optional[AccessCodeModePreview] = None
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "AccessCodeModeChange":
        d = _d(raw)
        would = d.get("would_change")
        return cls(
            mode=d.get("mode"),
            changed=bool(d.get("changed")),
            deleted_codes=_int(d.get("deleted_codes")),
            notified_members=_int(d.get("notified_members")),
            would_change=(AccessCodeModePreview.from_dict(would)
                          if isinstance(would, dict) else None),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# GuestView Entry
# --------------------------------------------------------------------------- #

@dataclass
class GuestViewEntrySchedule:
    """One window during which GuestView Entry is permitted at one gate.

    **Evaluated in the latch's own local timezone** at the moment a visitor taps
    open — never UTC, never yours, never the community's. ``09:00``-``17:00`` on
    a Los Angeles gate is 9-to-5 Pacific; the same window on a New York gate is
    9-to-5 Eastern.

    ``days_of_the_week`` is a letter string from ``MTWHFSU`` where **H is
    Thursday** and **U is Sunday**, naming the day the window *starts* on.
    ``start_time`` and ``end_time`` are ``'HH:MM'``, 24-hour, or None for an
    unbounded end. An ``end_time`` earlier than ``start_time`` wraps past
    midnight as **one** window — see :attr:`wraps_midnight`.

    The schedule is a whitelist of permitted times: a latch with **no** windows
    is available to guests at any hour, and the first window you add is what
    starts restricting it.
    """

    schedule_id: Optional[Any]
    latch_id: Optional[str] = None
    latch_name: Optional[str] = None
    days_of_the_week: str = ""
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def all_day(self) -> bool:
        """True when the window covers its whole day(s) — both times unset."""
        return self.start_time is None and self.end_time is None

    @property
    def wraps_midnight(self) -> bool:
        """True when this window runs past midnight into the next morning.

        Legal here, as it is for quiet hours — and unlike key schedules and
        recurring hold opens, which refuse a reversed window and must be split
        in two. ``"24:00"`` is not accepted here; the range is ``00:00`` to
        ``23:59``.
        """
        if not self.start_time or not self.end_time:
            return False
        return self.start_time > self.end_time

    @classmethod
    def from_dict(cls, raw: Any) -> "GuestViewEntrySchedule":
        d = _d(raw)
        return cls(
            schedule_id=d.get("schedule_id"),
            latch_id=d.get("latch_id"),
            latch_name=d.get("latch_name"),
            days_of_the_week=d.get("days_of_the_week") or "",
            start_time=d.get("start_time"),
            end_time=d.get("end_time"),
            raw=d,
        )


@dataclass
class GuestViewEntry:
    """The complete GuestView Entry configuration — returned by the read *and*
    by every one of its writes, so nothing here needs a follow-up GET.

    - ``allowed`` — the community master switch.
    - ``eligible_latches`` — the gates a visitor may open. Nothing outside this
      set is reachable, whatever the schedule says.
    - ``schedule`` — the recurring windows, each evaluated in **its latch's own
      local timezone**. A latch with no windows is available at any hour.
    - ``directory_viewing_enabled`` — read-only context: whether the GuestView
      *directory listing* is on. A separate feature; guest entry does not need
      it.

    ``latch_ids`` is the read half of the read-modify-write that
    :meth:`community.set_guest_view_entry_latches` requires — that call replaces
    the whole set, so build the list you send from this, never from memory.

    ``created_schedule_ids`` is populated by
    :meth:`community.add_guest_view_entry_schedule` (one id per latch the window
    was applied to) and ``removed_schedule_id`` by
    :meth:`community.remove_guest_view_entry_schedule`; both are empty on a
    plain read.
    """

    allowed: bool = False
    directory_viewing_enabled: bool = False
    eligible_latches: List[NamedLatch] = field(default_factory=list)
    schedule: List[GuestViewEntrySchedule] = field(default_factory=list)
    schedule_timezone: Optional[str] = None
    created_schedule_ids: List[Any] = field(default_factory=list)
    removed_schedule_id: Optional[Any] = None
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @property
    def latch_ids(self) -> List[str]:
        """The currently-eligible gate ids — the input to a read-modify-write.

        ``set_guest_view_entry_latches(entry.latch_ids + [new_id])`` adds a gate
        without destroying the others' schedules; composing that list any other
        way is how a caller silently deletes them.
        """
        return [x.latch_id for x in self.eligible_latches if x.latch_id is not None]

    def schedule_for(self, latch_id: str) -> List[GuestViewEntrySchedule]:
        """Every window attached to one gate.

        An empty list means that gate is guest-accessible at **any** hour, not
        that it is closed — the schedule is a whitelist of permitted times.
        """
        return [w for w in self.schedule if w.latch_id == latch_id]

    @classmethod
    def from_dict(cls, raw: Any) -> "GuestViewEntry":
        d = _d(raw)
        e = _d(d.get("guest_view_entry")) if "guest_view_entry" in d else d
        return cls(
            allowed=bool(e.get("allowed")),
            directory_viewing_enabled=bool(e.get("directory_viewing_enabled")),
            eligible_latches=[NamedLatch.from_dict(x)
                              for x in (e.get("eligible_latches") or [])],
            schedule=[GuestViewEntrySchedule.from_dict(x)
                      for x in (e.get("schedule") or [])],
            schedule_timezone=e.get("schedule_timezone"),
            created_schedule_ids=list(d.get("created_schedule_ids") or []),
            removed_schedule_id=d.get("removed_schedule_id"),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class GuestViewEntryLogEntry:
    """One GuestView Entry attempt.

    **This row identifies a visitor**: ``first_name``, ``last_name``, ``phone``
    and ``client_ip`` belong to the person who stood at the gate. Handle and
    retain accordingly.

    ``result`` is ``opened`` or a failure reason such as ``outside_schedule``,
    ``latch_not_eligible``, ``rate_limited`` or ``scan_required``.
    """

    guest_view_entry_log_id: Optional[Any]
    account_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    client_ip: Optional[str] = None
    latch_id: Optional[str] = None
    latch_name: Optional[str] = None
    log_datetime: Optional[str] = None
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def opened(self) -> bool:
        return self.result == "opened"

    @classmethod
    def from_dict(cls, raw: Any) -> "GuestViewEntryLogEntry":
        d = _d(raw)
        return cls(
            guest_view_entry_log_id=d.get("guest_view_entry_log_id"),
            account_id=d.get("account_id"),
            first_name=d.get("first_name"),
            last_name=d.get("last_name"),
            phone=d.get("phone"),
            client_ip=d.get("client_ip"),
            latch_id=d.get("latch_id"),
            latch_name=d.get("latch_name"),
            log_datetime=d.get("log_datetime"),
            result=d.get("result"),
            raw=d,
        )


@dataclass
class GuestViewEntryLogPage:
    """A page of GuestView Entry attempts, newest first.

    ``has_more`` is true when the page came back full. ``limit`` is clamped
    server-side to 1-200 and ``offset`` floored at 0, so the values echoed here
    are what the server applied.
    """

    logs: List[GuestViewEntryLogEntry] = field(default_factory=list)
    limit: Optional[int] = None
    offset: Optional[int] = None
    has_more: bool = False
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.logs)

    def __len__(self) -> int:
        return len(self.logs)

    @classmethod
    def from_dict(cls, raw: Any) -> "GuestViewEntryLogPage":
        d = _d(raw)
        return cls(
            logs=[GuestViewEntryLogEntry.from_dict(x) for x in (d.get("logs") or [])],
            limit=d.get("limit"),
            offset=d.get("offset"),
            has_more=bool(d.get("has_more")),
            result=d.get("result"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# GuestView short codes
# --------------------------------------------------------------------------- #

@dataclass
class ShortCode:
    """One GuestView short code — what a visitor types, or the QR on a placard.

    ``latch_id`` is the gate the code preselects, or None for a code that opens
    the directory without one. ``latch_name`` comes along so signage can be
    rendered or checked without a second lookup.

    Short codes are unique across **all of Nimbio**, not just your community,
    and **there is no way to delete one** — not through this API and not through
    the portal. A code you mint is permanent.
    """

    short_code: Optional[str]
    community_id: Optional[Any] = None
    latch_id: Optional[str] = None
    latch_name: Optional[str] = None
    disabled: bool = False
    require_security_code: bool = False
    created_at: Optional[str] = None
    last_updated_datetime: Optional[str] = None
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "ShortCode":
        # Accepts a bare row (the list read) or the ``{"result": ...,
        # "short_code": {...}}`` envelope the writes return — note the envelope
        # key and the scalar field share a name, so the shape decides.
        d = _d(raw)
        sc = _d(d.get("short_code")) if isinstance(d.get("short_code"), dict) else d
        return cls(
            short_code=sc.get("short_code"),
            community_id=sc.get("community_id"),
            latch_id=sc.get("latch_id"),
            latch_name=sc.get("latch_name"),
            disabled=bool(sc.get("disabled")),
            require_security_code=bool(sc.get("require_security_code")),
            created_at=sc.get("created_at"),
            last_updated_datetime=sc.get("last_updated_datetime"),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# NFC tags
# --------------------------------------------------------------------------- #

@dataclass
class NfcTag:
    """One NFC fob or card issued to the community.

    ``tag_uid_hex`` is the tag's **physical UID — publicly readable, not a
    secret**: anything with an NFC radio can read it off the fob. It is the
    join key between a tag and its rows in :meth:`community.nfc_scan_log`. No
    cryptographic tag material is ever returned by this API, and programming a
    blank fob is a separate operator-side job with a card reader.

    ``latch_id`` is the gate the tag opens, or None when it is unassigned — a
    tag opens the gate it is bound to, not a member's key. ``disabled`` is the
    kill switch, and it takes effect for **physical gate taps**: a disabled
    tag's next tap on any gate is refused.

    ``notes`` is reported but **cannot be set over this API**.
    """

    tag_id: Optional[Any]
    tag_serial: Optional[str] = None
    tag_uid_hex: Optional[str] = None
    latch_id: Optional[str] = None
    disabled: bool = False
    notes: Optional[str] = None
    created_at: Optional[str] = None
    last_scan_at: Optional[str] = None
    last_updated_datetime: Optional[str] = None
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def assigned(self) -> bool:
        """True when the tag is bound to a gate.

        An unassigned tag is still yours — it stays in the community and can be
        re-assigned later.
        """
        return self.latch_id is not None

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @classmethod
    def from_dict(cls, raw: Any) -> "NfcTag":
        # Accepts a bare row (the list read) or the ``{"result": ..., "tag":
        # {...}}`` envelope the single read and the PATCH return.
        d = _d(raw)
        t = _d(d.get("tag")) if isinstance(d.get("tag"), dict) else d
        return cls(
            tag_id=t.get("tag_id"),
            tag_serial=t.get("tag_serial"),
            tag_uid_hex=t.get("tag_uid_hex"),
            latch_id=t.get("latch_id"),
            disabled=bool(t.get("disabled")),
            notes=t.get("notes"),
            created_at=t.get("created_at"),
            last_scan_at=t.get("last_scan_at"),
            last_updated_datetime=t.get("last_updated_datetime"),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class NfcTagPage:
    """A page of NFC tags, newest first.

    Page-numbered rather than offset-paged: ``page`` is 1-based and floored at
    1, ``results_per_page`` is clamped to 1-200, and both echo what the server
    actually applied. ``total`` counts the whole match, so
    ``total > page * results_per_page`` means there is another page.
    """

    items: List[NfcTag] = field(default_factory=list)
    page: Optional[int] = None
    results_per_page: Optional[int] = None
    total: Optional[int] = None
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @classmethod
    def from_dict(cls, raw: Any) -> "NfcTagPage":
        d = _d(raw)
        return cls(
            items=[NfcTag.from_dict(x) for x in (d.get("items") or [])],
            page=d.get("page"),
            results_per_page=d.get("results_per_page"),
            total=d.get("total"),
            result=d.get("result"),
            raw=d,
        )


@dataclass
class NfcScanLogEntry:
    """One recorded NFC tap.

    Joins to a tag by ``tag_uid_hex`` (or ``tag_id``) and to a gate by
    ``latch_id``. ``result`` is the scan verdict and ``open_outcome`` what the
    gate then did, so a tap that was accepted but did not open is visible as
    the two disagreeing.

    **This row can name a person**: ``first_name``/``last_name`` are filled in
    where the tap resolved to a member, which is what lets a security review
    attribute a tap. The device's IP address and Nimbio-internal record ids are
    not exposed.
    """

    scan_log_id: Optional[Any]
    scanned_at: Optional[str] = None
    tag_id: Optional[Any] = None
    tag_serial: Optional[str] = None
    tag_uid_hex: Optional[str] = None
    latch_id: Optional[str] = None
    latch_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    result: Optional[str] = None
    open_outcome: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def opened(self) -> bool:
        return self.open_outcome == "opened"

    @property
    def member_name(self) -> Optional[str]:
        """The tapping member's name, or None when the tap resolved to nobody."""
        name = " ".join(x for x in (self.first_name, self.last_name) if x)
        return name or None

    @classmethod
    def from_dict(cls, raw: Any) -> "NfcScanLogEntry":
        d = _d(raw)
        return cls(
            scan_log_id=d.get("scan_log_id"),
            scanned_at=d.get("scanned_at"),
            tag_id=d.get("tag_id"),
            tag_serial=d.get("tag_serial"),
            tag_uid_hex=d.get("tag_uid_hex"),
            latch_id=d.get("latch_id"),
            latch_name=d.get("latch_name"),
            first_name=d.get("first_name"),
            last_name=d.get("last_name"),
            result=d.get("result"),
            open_outcome=d.get("open_outcome"),
            raw=d,
        )


@dataclass
class NfcScanLogPage:
    """A page of NFC taps, newest first.

    Offset-paged; ``limit`` is clamped server-side to 1-200 and ``offset``
    floored at 0, so the values echoed here are what the server applied.
    """

    items: List[NfcScanLogEntry] = field(default_factory=list)
    limit: Optional[int] = None
    offset: Optional[int] = None
    total: Optional[int] = None
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    @classmethod
    def from_dict(cls, raw: Any) -> "NfcScanLogPage":
        d = _d(raw)
        return cls(
            items=[NfcScanLogEntry.from_dict(x) for x in (d.get("items") or [])],
            limit=d.get("limit"),
            offset=d.get("offset"),
            total=d.get("total"),
            result=d.get("result"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Sense lines
# --------------------------------------------------------------------------- #

@dataclass
class SenseLineRecord:
    """One raw transition a box reported on one of its inputs.

    ``state`` is the number the hardware reported; ``status`` is the label that
    state is configured to mean, or **None when the state has no configured
    meaning**. An unmapped state is itself a finding, which is why these rows
    are returned rather than dropped.

    ``box_id``/``box_name`` are absent on the ``last_record`` embedded in a
    single sense line (the box is the one you asked about) and present on rows
    from :meth:`community.sense_line_records`.
    """

    logged_at: Optional[str]
    state: Optional[Any] = None
    status: Optional[str] = None
    sense_line_id: Optional[int] = None
    box_id: Optional[str] = None
    box_name: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "SenseLineRecord":
        d = _d(raw)
        return cls(
            logged_at=d.get("logged_at"),
            state=d.get("state"),
            status=d.get("status"),
            sense_line_id=d.get("sense_line_id"),
            box_id=d.get("box_id"),
            box_name=d.get("box_name"),
            raw=d,
        )


@dataclass
class SenseLineStatusMapping:
    """What one raw state on one input is configured to mean.

    ``sense_line_state`` is the number off the wire, ``status`` the label the
    apps show for it (``"Open"``, ``"Closed"``, ``"Locked"`` ...), and
    ``transient_ms`` is non-zero when the label is shown briefly and then
    reverts.

    This mapping is set when the hardware is installed and is **read-only**
    here — an unmapped state cannot be given a meaning through this API.
    """

    sense_line_state: Optional[Any]
    status: Optional[str] = None
    latch_id: Optional[str] = None
    latch_name: Optional[str] = None
    transient_ms: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def transient(self) -> bool:
        """True when the label is shown briefly and then reverts."""
        return bool(self.transient_ms)

    @classmethod
    def from_dict(cls, raw: Any) -> "SenseLineStatusMapping":
        d = _d(raw)
        return cls(
            sense_line_state=d.get("sense_line_state"),
            status=d.get("status"),
            latch_id=d.get("latch_id"),
            latch_name=d.get("latch_name"),
            transient_ms=d.get("transient_ms"),
            raw=d,
        )


@dataclass
class SenseLine:
    """One physical input on a Nimbio box — the feedback loop behind gate status.

    A sense line is what reports whether a gate actually moved. It feeds
    :meth:`community.gate_status`, the gate-status-change log, and the
    ``sense_line.changed`` event.

    Two configuration flags, and one derived answer:

    - ``sense_line_online`` — whether the input is switched on at all. Off
      means the box's raw transitions are **still recorded** (see
      :meth:`community.sense_line_records`) but the server acts on none of them.
    - ``latch_data_online`` — whether its readings may drive the gate status
      reported to the apps and to this API.
    - ``reporting`` — true only when both are on, which is exactly the
      condition for a transition to update gate status or fire
      ``sense_line.changed``. **A gate stuck on one status with
      ``reporting`` false is a configuration problem, not a stuck gate.**

    ``sense_line_id`` is an **input number on a board, unique only within its
    box** — two boxes in one community both have a "sense line 1", which is why
    ``box_id`` is required to address one.

    ``status_map`` and ``last_record`` come back on the single read and the
    PATCH, not on the list. A ``last_record`` weeks old on a gate that moves
    daily points at the wiring or the box, not at the configuration.
    """

    sense_line_id: Optional[int]
    box_id: Optional[str] = None
    box_name: Optional[str] = None
    sense_line_online: bool = False
    latch_data_online: bool = False
    reporting: bool = False
    latches: List[NamedLatch] = field(default_factory=list)
    status_map: List[SenseLineStatusMapping] = field(default_factory=list)
    last_record: Optional[SenseLineRecord] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    def status_for(self, state: Any) -> Optional[str]:
        """The configured label for one raw ``state``, or None if unmapped.

        None means the state has no configured meaning on this input — a
        finding worth reporting, not a lookup failure.
        """
        for m in self.status_map:
            if m.sense_line_state == state:
                return m.status
        return None

    @classmethod
    def from_dict(cls, raw: Any) -> "SenseLine":
        d = _d(raw)
        online = bool(d.get("sense_line_online"))
        data_online = bool(d.get("latch_data_online"))
        last = d.get("last_record")
        return cls(
            sense_line_id=d.get("sense_line_id"),
            box_id=d.get("box_id"),
            box_name=d.get("box_name"),
            sense_line_online=online,
            latch_data_online=data_online,
            # Server-derived, but computed here too so an older server that
            # omits it still answers the question the field exists to answer.
            reporting=bool(d.get("reporting", online and data_online)),
            latches=[NamedLatch.from_dict(x) for x in (d.get("latches") or [])],
            status_map=[SenseLineStatusMapping.from_dict(x)
                        for x in (d.get("status_map") or [])],
            last_record=(SenseLineRecord.from_dict(last)
                         if isinstance(last, dict) else None),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class SenseLineBox:
    """One box in the sense-line listing, with the gates wired to it."""

    box_id: Optional[str]
    box_name: Optional[str] = None
    latches: List[NamedLatch] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "SenseLineBox":
        d = _d(raw)
        return cls(
            box_id=d.get("box_id"),
            box_name=d.get("box_name"),
            latches=[NamedLatch.from_dict(x) for x in (d.get("latches") or [])],
            raw=d,
        )


@dataclass
class SenseLines:
    """Every sense line on the community's boxes, plus the boxes themselves.

    Iterating this yields the sense lines. :attr:`not_reporting` is the
    diagnostic shortcut: those are the inputs whose transitions change nothing,
    so a gate that never updates its status is explained by appearing there.
    """

    sense_lines: List[SenseLine] = field(default_factory=list)
    boxes: List[SenseLineBox] = field(default_factory=list)
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.sense_lines)

    def __len__(self) -> int:
        return len(self.sense_lines)

    @property
    def not_reporting(self) -> List[SenseLine]:
        """The inputs whose readings the server acts on for nothing.

        Either flag being off puts a line here. A gate frozen on one status
        with its input in this list is a configuration problem, not a stuck
        gate.
        """
        return [x for x in self.sense_lines if not x.reporting]

    def for_box(self, box_id: str) -> List[SenseLine]:
        """Only the inputs on one box."""
        return [x for x in self.sense_lines if x.box_id == box_id]

    @classmethod
    def from_dict(cls, raw: Any) -> "SenseLines":
        d = _d(raw)
        return cls(
            sense_lines=[SenseLine.from_dict(x)
                         for x in (d.get("sense_lines") or [])],
            boxes=[SenseLineBox.from_dict(x) for x in (d.get("boxes") or [])],
            result=d.get("result"),
            raw=d,
        )


@dataclass
class SenseLineRecordPage:
    """A page of raw sense-line transitions, newest first.

    **Rows are written even when a sense line is switched off**, which is what
    makes this the endpoint to reach for when a gate misreports: a healthy
    stream here alongside a stale :meth:`community.gate_status` proves the
    wiring is fine and the configuration is not.

    ``limit`` is clamped server-side to 1-200 and ``offset`` floored at 0.
    """

    records: List[SenseLineRecord] = field(default_factory=list)
    limit: Optional[int] = None
    offset: Optional[int] = None
    has_more: bool = False
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    @property
    def unmapped(self) -> List[SenseLineRecord]:
        """Rows whose raw state has no configured meaning (``status`` is None)."""
        return [x for x in self.records if x.status is None]

    @classmethod
    def from_dict(cls, raw: Any) -> "SenseLineRecordPage":
        d = _d(raw)
        return cls(
            records=[SenseLineRecord.from_dict(x)
                     for x in (d.get("records") or [])],
            limit=d.get("limit"),
            offset=d.get("offset"),
            has_more=bool(d.get("has_more")),
            result=d.get("result"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Map and geofences
# --------------------------------------------------------------------------- #

@dataclass
class GeoPoint:
    """A WGS84 decimal-degree coordinate pair."""

    latitude: Optional[float]
    longitude: Optional[float]
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "GeoPoint":
        d = _d(raw)
        return cls(latitude=d.get("latitude"), longitude=d.get("longitude"),
                   raw=d)


def _point(raw: Any) -> Optional[GeoPoint]:
    """A :class:`GeoPoint`, or None for the nulls the map surface uses."""
    return GeoPoint.from_dict(raw) if isinstance(raw, dict) else None


@dataclass
class Geofence:
    """One gate's proximity geofence.

    ``center`` is WGS84 decimal degrees and ``radius_meters`` is **metres**.
    A ``center`` of None means no fence has ever been configured for this gate
    — use the latch's :attr:`MapLatch.box_location` as the suggested centre.

    ``min_radius_meters`` (100) is the smallest radius the mobile apps can
    honour: Android's Geofence API and iOS region monitoring both degrade below
    roughly that, so a smaller fence would read as configured and never fire.
    A write below it is **rejected with 422 ``radius_below_minimum``, not
    silently raised**.

    ``mode`` is ``prompt`` (notify on arrival, the member taps to open) or
    ``auto_open`` — see
    :data:`nimbio_community_api.constants.GEOFENCE_MODES`.
    """

    enabled: bool = False
    mode: Optional[str] = None
    radius_meters: Optional[int] = None
    min_radius_meters: Optional[int] = None
    center: Optional[GeoPoint] = None
    updated_by_account_id: Optional[str] = None
    updated_datetime: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def configured(self) -> bool:
        """True when this gate has a centre — the prerequisite for enabling it."""
        return self.center is not None

    @classmethod
    def from_dict(cls, raw: Any) -> "Geofence":
        d = _d(raw)
        return cls(
            enabled=bool(d.get("enabled")),
            mode=d.get("mode"),
            radius_meters=d.get("radius_meters"),
            min_radius_meters=d.get("min_radius_meters"),
            center=_point(d.get("center")),
            updated_by_account_id=d.get("updated_by_account_id"),
            updated_datetime=d.get("updated_datetime"),
            raw=d,
        )


@dataclass
class MapLatch:
    """One gate on the map: where it is, and the fence it advertises.

    ``box_location`` is the location of the Nimbio device the gate is wired to
    — the fallback centre for a gate that has never had one configured.
    :attr:`suggested_center` picks the right one for you.

    **These coordinates are physical-security information**: they say exactly
    where a property's entrances are. Handle them accordingly.
    """

    latch_id: Optional[str]
    latch_name: Optional[str] = None
    box_id: Optional[str] = None
    box_location: Optional[GeoPoint] = None
    geofence: Optional[Geofence] = None
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def simulated(self) -> bool:
        return self.result == "simulated"

    @property
    def suggested_center(self) -> Optional[GeoPoint]:
        """The gate's own centre, or its device's location as the fallback.

        Enabling a fence requires a centre. A gate whose ``geofence.center`` is
        None has never had one configured, and its device's location is the
        sensible starting point.
        """
        if self.geofence is not None and self.geofence.center is not None:
            return self.geofence.center
        return self.box_location

    @classmethod
    def from_dict(cls, raw: Any) -> "MapLatch":
        # Accepts a bare row (from the map read) or the ``{"result": ...,
        # "latch": {...}}`` envelope the geofence PATCH returns.
        d = _d(raw)
        latch = _d(d.get("latch")) if isinstance(d.get("latch"), dict) else d
        fence = latch.get("geofence")
        return cls(
            latch_id=latch.get("latch_id"),
            latch_name=latch.get("latch_name"),
            box_id=latch.get("box_id"),
            box_location=_point(latch.get("box_location")),
            geofence=(Geofence.from_dict(fence)
                      if isinstance(fence, dict) else None),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


@dataclass
class MapBox:
    """One Nimbio device on the map, with its own location and its gates."""

    box_id: Optional[str]
    box_name: Optional[str] = None
    location: Optional[GeoPoint] = None
    latches: List[MapLatch] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "MapBox":
        d = _d(raw)
        return cls(
            box_id=d.get("box_id"),
            box_name=d.get("box_name"),
            location=_point(d.get("location")),
            latches=[MapLatch.from_dict(x) for x in (d.get("latches") or [])],
            raw=d,
        )


@dataclass
class CommunityMap:
    """Where the community's gates are, and the geofence each one advertises.

    Coordinates are WGS84 decimal degrees; radii are metres.
    ``min_radius_meters`` is the floor a write must respect and
    ``geofence_modes`` the legal set for ``mode`` — read them from here rather
    than hardcoding, since they are what the server will enforce.

    **This response is physical-security information**: it says exactly where a
    property's entrances are. It is scoped to your community key; treating it
    as sensitive downstream is on you.
    """

    boxes: List[MapBox] = field(default_factory=list)
    community_location: Optional[GeoPoint] = None
    geofence_modes: List[str] = field(default_factory=list)
    min_radius_meters: Optional[int] = None
    result: Optional[str] = None
    request_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def latches(self) -> List[MapLatch]:
        """Every gate across every box, flattened."""
        return [latch for box in self.boxes for latch in box.latches]

    def latch(self, latch_id: str) -> Optional[MapLatch]:
        """One gate by id, or None when this community has no such gate."""
        for x in self.latches:
            if x.latch_id == latch_id:
                return x
        return None

    @property
    def unconfigured(self) -> List[MapLatch]:
        """Gates that have never had a fence centre configured.

        Each one's :attr:`MapLatch.suggested_center` is the device location to
        start from.
        """
        return [x for x in self.latches
                if x.geofence is None or x.geofence.center is None]

    @classmethod
    def from_dict(cls, raw: Any) -> "CommunityMap":
        d = _d(raw)
        return cls(
            boxes=[MapBox.from_dict(x) for x in (d.get("boxes") or [])],
            community_location=_point(d.get("community_location")),
            geofence_modes=list(d.get("geofence_modes") or []),
            min_radius_meters=d.get("min_radius_meters"),
            result=d.get("result"),
            request_id=d.get("request_id"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Configuration change log
# --------------------------------------------------------------------------- #

@dataclass
class ChangeLogEntry:
    """One configuration change — who changed what, when.

    ``summary`` is a rendered human-readable sentence; ``details`` is the
    per-``action_type`` payload behind it, whose keys vary by trail and by
    action, so read it defensively. ``log_id`` is unique within its
    ``log_type``, not across all four.
    """

    log_id: Optional[Any]
    log_type: Optional[str] = None
    action_type: Optional[str] = None
    datetime: Optional[str] = None
    account_id: Optional[str] = None
    account_display_name: Optional[str] = None
    summary: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, raw: Any) -> "ChangeLogEntry":
        d = _d(raw)
        return cls(
            log_id=d.get("log_id"),
            log_type=d.get("log_type"),
            action_type=d.get("action_type"),
            datetime=d.get("datetime"),
            account_id=d.get("account_id"),
            account_display_name=d.get("account_display_name"),
            summary=d.get("summary"),
            details=_d(d.get("details")),
            raw=d,
        )


@dataclass
class ChangeLogPage:
    """A page of one configuration trail, newest first.

    ``log_type`` echoes which of the four trails this is. ``days``,
    ``date_from`` and ``date_to`` report the window the server **actually
    used**: a look-back above the 30-day retention cap is clamped rather than
    rejected, so read these rather than assuming you got what you asked for.
    """

    logs: List[ChangeLogEntry] = field(default_factory=list)
    log_type: Optional[str] = None
    days: Optional[int] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    limit: Optional[int] = None
    offset: Optional[int] = None
    total: Optional[int] = None
    has_more: bool = False
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.logs)

    def __len__(self) -> int:
        return len(self.logs)

    @classmethod
    def from_dict(cls, raw: Any) -> "ChangeLogPage":
        d = _d(raw)
        return cls(
            logs=[ChangeLogEntry.from_dict(x) for x in (d.get("logs") or [])],
            log_type=d.get("log_type"),
            days=d.get("days"),
            date_from=d.get("from"),
            date_to=d.get("to"),
            limit=d.get("limit"),
            offset=d.get("offset"),
            total=d.get("total"),
            has_more=bool(d.get("has_more")),
            result=d.get("result"),
            raw=d,
        )


# --------------------------------------------------------------------------- #
# Key usage report
# --------------------------------------------------------------------------- #

@dataclass
class KeyUsageReport:
    """Per-key usage history for a date window — the portal's Access Logs report.

    **Read ``report_type`` before reading any row's ``user``.** Nimbio
    attributes an open differently by property type and *the server decides
    which rule applies*; there is no parameter for it, because getting it wrong
    would misreport who opened a gate.

    - ``"commercial"`` — ``user`` is the **actual opener's** name.
    - ``"residential"`` — ``user`` is ``"<master key owner> Keychain"``. Every
      open on a household's keys is attributed to the account holder, so you
      cannot tell which member of the household opened the gate. This groups;
      it does **not** anonymize — the account holder is named.

    ``date_from``/``date_to`` are the window actually used and
    ``requested_from``/``requested_to`` what you asked for; ``clamped`` is true
    when they differ because the range exceeded ``max_range_days``. Dates are
    ``'YYYY-MM-DD'`` in the community's own ``timezone``, not yours.

    Rows carry personal data beyond ``user`` — ``phone`` and ``location``.
    """

    logs: List[AccessLogEntry] = field(default_factory=list)
    report_type: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    requested_from: Optional[str] = None
    requested_to: Optional[str] = None
    timezone: Optional[str] = None
    page: Optional[int] = None
    has_more: bool = False
    clamped: bool = False
    max_range_days: Optional[int] = None
    result: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def __iter__(self):
        return iter(self.logs)

    def __len__(self) -> int:
        return len(self.logs)

    @property
    def residential(self) -> bool:
        """True when every row's ``user`` is a household, not an individual.

        **One-sided on purpose.** False means "not the household rule" — it
        does *not* mean ``"commercial"``. An attribution rule this release
        predates reads False here too, so code that must tell commercial from
        something new has to read :attr:`report_type` itself rather than
        treating this as a two-way switch.
        """
        return self.report_type == "residential"

    @classmethod
    def from_dict(cls, raw: Any) -> "KeyUsageReport":
        d = _d(raw)
        return cls(
            logs=[AccessLogEntry.from_dict(x) for x in (d.get("logs") or [])],
            report_type=d.get("report_type"),
            date_from=d.get("from"),
            date_to=d.get("to"),
            requested_from=d.get("requested_from"),
            requested_to=d.get("requested_to"),
            timezone=d.get("timezone"),
            page=d.get("page"),
            has_more=bool(d.get("has_more")),
            clamped=bool(d.get("clamped")),
            max_range_days=d.get("max_range_days"),
            result=d.get("result"),
            raw=d,
        )
