"""Synchronous client — works in any plain (non-async) Python program."""

from __future__ import annotations

import time
from typing import Any, Iterator, List, Optional, Sequence, Union

import httpx

from . import _exceptions as exc
from . import _sse
from ._base import BaseClient, endpoints
from .models import (
    AccessLogEntry,
    AccessLogPage,
    AccountKey,
    CommunityKey,
    GateStatus,
    GateStatusLogEntry,
    GateStatusLogPage,
    Health,
    HoldOpenEventAdded,
    HoldOpenEventRemoved,
    HoldOpens,
    KeySchedule,
    KeySchedules,
    KeyStatuses,
    ManualHoldOpenResult,
    Me,
    MemberAccessLogPage,
    Members,
    OpenResult,
    StreamEvent,
    StreamReset,
    Webhook,
    WebhookCreateResult,
    WebhookSecret,
    WriteResult,
)


class NimbioClient(BaseClient):
    """Blocking client for the Nimbio community API.

    Example::

        from nimbio_community_api import NimbioClient

        with NimbioClient("nimbio_test_...") as client:
            print(client.me().account_id)
            client.community.open("latch-id-123", note="front gate")

    Configuration precedence: explicit arguments > environment variables
    (``NIMBIO_API_KEY``, ``NIMBIO_ENV``, ``NIMBIO_BASE_URL``) > defaults
    (``environment="prod"``).
    """

    def __init__(self, api_key: Optional[str] = None, *,
                 environment: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: Optional[float] = None,
                 max_retries: int = 2,
                 default_headers: Optional[dict] = None,
                 http_client: Optional[httpx.Client] = None) -> None:
        super().__init__(
            api_key, environment=environment, base_url=base_url,
            timeout=30.0 if timeout is None else timeout,
            max_retries=max_retries, default_headers=default_headers,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=self.timeout)
        self.community = _SyncCommunity(self)
        self.account = _SyncAccount(self)

    # -- lifecycle ---------------------------------------------------------- #

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "NimbioClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- core request loop -------------------------------------------------- #

    def _request(self, spec, *, auth: bool = True) -> Any:
        method, path, params, json, parser = spec
        prepared = self._prepare(method, path, params=params, json=json, auth=auth)
        attempt = 0
        while True:
            try:
                resp = self._http.request(
                    prepared.method, prepared.url, headers=prepared.headers,
                    params=prepared.params, json=prepared.json,
                )
            except httpx.TimeoutException as e:
                raise exc.APITimeoutError(cause=e) from e
            except httpx.HTTPError as e:
                raise exc.APIConnectionError(str(e) or "Connection error",
                                             cause=e) from e

            if self._should_retry(resp.status_code, attempt):
                time.sleep(self._retry_delay(attempt, resp.headers))
                attempt += 1
                continue

            payload = self._decode(resp.status_code, resp.content, resp.headers)
            data = self._parse(resp.status_code, payload, resp.headers)
            return parser(data) if parser else data

    # -- top-level endpoints ------------------------------------------------ #

    def health(self) -> Health:
        """Backend reachability (unauthenticated). Does not raise on 503."""
        method, path, params, json, parser = endpoints.health()
        prepared = self._prepare(method, path, params=params, json=json, auth=False)
        try:
            resp = self._http.request(prepared.method, prepared.url,
                                      headers=prepared.headers)
        except httpx.TimeoutException as e:
            raise exc.APITimeoutError(cause=e) from e
        except httpx.HTTPError as e:
            raise exc.APIConnectionError(str(e) or "Connection error", cause=e) from e
        payload = self._decode(resp.status_code, resp.content, resp.headers)
        return Health.from_dict(payload if isinstance(payload, dict) else {})

    def me(self) -> Me:
        """Metadata and live usage counters for the authenticating key."""
        return self._request(endpoints.me())


class _SyncAccount:
    """``client.account.*`` — account-scoped operations (your own keys).

    Requires an account-scoped API key; community-scoped keys raise
    :class:`PermissionDeniedError` (``not_account_key``).
    """

    def __init__(self, client: NimbioClient) -> None:
        self._c = client

    def keys(self, *, include_hidden: bool = False) -> List[AccountKey]:
        """Every Nimbio key on your account, with its latches nested."""
        return self._c._request(endpoints.account_keys(include_hidden))

    def open(self, key_id: str, latch_id: str, *, note: Optional[str] = None,
             idempotency_key: Optional[str] = None) -> OpenResult:
        """Open one of your latches through one of your keys. Live keys fire
        the gate (synchronous, blocks until the box confirms); test keys
        simulate. Denials raise :class:`PermissionDeniedError`; a
        non-confirming gate raises :class:`GateNotOpenedError`."""
        return self._c._request(
            endpoints.account_open(key_id, latch_id, note, idempotency_key))


class _SyncCommunity:
    """``client.community.*`` — community-scoped operations.

    Requires a community-scoped API key; account-scoped keys raise
    :class:`PermissionDeniedError` (``not_community_key``).
    """

    def __init__(self, client: NimbioClient) -> None:
        self._c = client

    # -- reads -------------------------------------------------------------- #

    def gate_status(self) -> GateStatus:
        """Latest sensed open/closed state for every latch in the community."""
        return self._c._request(endpoints.gate_status())

    def members(self) -> Members:
        """Pending / accepted / removed members."""
        return self._c._request(endpoints.members())

    def key_statuses(self) -> KeyStatuses:
        """All keys and latches with live disabled/offline/held-open state."""
        return self._c._request(endpoints.key_statuses())

    def keys(self) -> List[CommunityKey]:
        """Every community key with its access restrictions."""
        return self._c._request(endpoints.keys())

    # -- writes ------------------------------------------------------------- #

    def open(self, latch_id: str, *, note: Optional[str] = None,
             idempotency_key: Optional[str] = None) -> OpenResult:
        """Open a latch. Live keys fire the gate (synchronous, blocks until the
        box confirms); test keys simulate. Denials raise
        :class:`PermissionDeniedError`; a non-confirming gate raises
        :class:`GateNotOpenedError`."""
        return self._c._request(endpoints.open(latch_id, note, idempotency_key))

    def message(self, message: str) -> WriteResult:
        """Send a message to every community member (test keys validate only)."""
        return self._c._request(endpoints.message(message))

    def add_member(self, phone_number: str,
                   key_ids: Sequence[str]) -> WriteResult:
        """Add a member by phone number and grant them the given community keys."""
        return self._c._request(endpoints.add_member(phone_number, key_ids))

    def grant_keys(self, account_community_id: int,
                   key_ids: Sequence[str]) -> WriteResult:
        """Grant additional community keys to an existing member."""
        return self._c._request(endpoints.grant_keys(account_community_id, key_ids))

    def revoke_keys(self, account_community_id: int, key_ids: Sequence[str], *,
                    remove_member: bool = False) -> WriteResult:
        """Revoke community keys from a member (optionally remove them entirely)."""
        return self._c._request(
            endpoints.revoke_keys(account_community_id, key_ids, remove_member))

    def set_keys_disabled(self, account_community_id: int,
                          key_ids: Sequence[str], disabled: bool) -> WriteResult:
        """Disable or re-enable a member's keys (reversible — keys not removed)."""
        return self._c._request(
            endpoints.set_keys_disabled(account_community_id, key_ids, disabled))

    # -- hold opens ---------------------------------------------------------- #

    def hold_opens(self) -> HoldOpens:
        """Hold-open state per latch: the combined ``held_open`` truth, the
        ``manual`` toggle, one-time ``events``, and ``recurring`` schedules.
        Requires the community's Hold Opens feature to be enabled."""
        return self._c._request(endpoints.hold_opens())

    def set_hold_open(self, latch_id: str, state: bool) -> ManualHoldOpenResult:
        """Turn the manual hold open on/off for a latch. ``manual`` reflects
        only this toggle; turning it off does not cancel an active scheduled
        window. Test keys simulate."""
        return self._c._request(endpoints.set_hold_open(latch_id, state))

    def add_hold_open_event(self, latch_id: str, *, start: str,
                            end: str) -> HoldOpenEventAdded:
        """Add a one-time hold-open window ('YYYY-MM-DD HH:MM', latch-local
        time). Keep the returned ``event_id`` to end the window early."""
        return self._c._request(
            endpoints.add_hold_open_event(latch_id, start, end))

    def remove_hold_open_event(self, latch_id: str,
                               event_id: str) -> HoldOpenEventRemoved:
        """Remove a one-time hold-open window early. Idempotent."""
        return self._c._request(
            endpoints.remove_hold_open_event(latch_id, event_id))

    # -- key access schedules ------------------------------------------------ #

    def key_schedules(self) -> KeySchedules:
        """Access schedules for the community's own keys.

        Community keys only. A schedule on a community key *is* the
        community-wide rule -- it applies to every member key beneath it -- so
        member keys are neither listed here nor schedulable: :meth:`key_schedule`
        and :meth:`set_key_schedule` refuse one with ``not_a_community_key``
        (403).

        ``windows`` holds only what is in force today; anything whose date range
        has passed is counted in ``inactive_window_count`` instead.

        ``.blocked`` lists keys denied at all times because a saved schedule is
        switched off. Does not consume the monthly quota."""
        return self._c._request(endpoints.key_schedules())

    def key_schedule(self, key_id: str) -> KeySchedule:
        """One community key's access schedule.

        ``key_id`` must be one of the community's own keys; a member's key is
        refused with ``not_a_community_key`` (403). Returns **every** window,
        expired ones included, because :meth:`set_key_schedule` replaces the
        whole schedule. Does not consume the monthly quota."""
        return self._c._request(endpoints.key_schedule(key_id))

    def set_key_schedule(self, key_id: str, windows) -> KeySchedule:
        """Replace a community key's access schedule.

        ``windows`` is the COMPLETE schedule -- pass ``[]`` to remove every
        restriction. Accepts :class:`ScheduleWindow` objects or plain dicts of
        ``{days_of_the_week, start_time, end_time}``.

        Days are letters from ``MTWHFSU`` (**H is Thursday**, U is Sunday).
        Times are ``'HH:MM'`` in each gate's local time and cannot run past
        midnight -- send two windows for overnight access.

        Community keys only: a member's own key cannot be scheduled and is
        refused with ``not_a_community_key`` (403). The schedule applies to every
        member key beneath the community key, so check ``descendant_key_count``
        (live members only) first. Test keys simulate."""
        return self._c._request(endpoints.set_key_schedule(key_id, windows))

    # -- webhooks ------------------------------------------------------------ #

    def webhook_event_types(self) -> List[str]:
        """The catalog of event types a webhook can subscribe to."""
        return self._c._request(endpoints.webhook_event_types())

    def webhooks(self) -> List[Webhook]:
        """All webhooks registered on the community (secrets never listed)."""
        return self._c._request(endpoints.webhooks())

    def create_webhook(self, url: str, events: Sequence[str], *,
                       description: Optional[str] = None) -> WebhookCreateResult:
        """Register a webhook (public https only). The HMAC signing secret is
        on ``.webhook.secret`` of the result — returned ONCE, store it. Verify
        deliveries with :mod:`nimbio_community_api.webhooks`."""
        return self._c._request(
            endpoints.create_webhook(url, events, description))

    def update_webhook(self, webhook_id: str, *, url: Optional[str] = None,
                       events: Optional[Sequence[str]] = None,
                       active: Optional[bool] = None,
                       description: Optional[str] = None) -> WebhookCreateResult:
        """Edit a webhook; ``active=True`` revives an auto-disabled one."""
        return self._c._request(endpoints.update_webhook(
            webhook_id, url=url, events=events, active=active,
            description=description))

    def delete_webhook(self, webhook_id: str) -> WriteResult:
        """Delete a webhook and its subscriptions."""
        return self._c._request(endpoints.delete_webhook(webhook_id))

    def rotate_webhook_secret(self, webhook_id: str) -> WebhookSecret:
        """Mint a new signing secret (returned once); the old one stops working."""
        return self._c._request(endpoints.rotate_webhook_secret(webhook_id))

    def test_webhook(self, webhook_id: str) -> WriteResult:
        """Queue a synthetic ``ping`` delivery to verify connectivity."""
        return self._c._request(endpoints.test_webhook(webhook_id))

    # -- live events --------------------------------------------------------- #

    def stream_events(self, *, events: Optional[Sequence[str]] = None,
                      last_event_id: Optional[str] = None,
                      reconnect: bool = True,
                      ) -> Iterator[Union[StreamEvent, StreamReset]]:
        """Iterate the community's live events over SSE — the same payloads
        webhooks deliver, pushed over an outbound connection (works behind
        NAT, no public endpoint needed).

        Yields a :class:`~nimbio_community_api.models.StreamEvent` per event,
        and a :class:`~nimbio_community_api.models.StreamReset` when the
        server cannot replay a reconnect gap — re-seed via the status reads
        (``gate_status()`` / ``hold_opens()``), then keep iterating.

        With ``reconnect=True`` (default) dropped connections re-open with
        exponential backoff, resuming from the last seen event id. HTTP errors
        (401, 403, 429 ``stream_limit``, ...) always raise. Connecting charges
        one per-minute request and is monthly-quota-exempt; delivered events
        are free.
        """
        c = self._c
        cursor = last_event_id
        attempt = 0
        while True:
            prepared = c._prepare("GET", _sse.STREAM_PATH,
                                  params=_sse.stream_params(events, cursor))
            timeout = httpx.Timeout(c.timeout or 30.0,
                                    read=_sse.STREAM_READ_TIMEOUT)
            try:
                with c._http.stream(prepared.method, prepared.url,
                                    headers=prepared.headers,
                                    params=prepared.params,
                                    timeout=timeout) as resp:
                    if resp.status_code != 200:
                        resp.read()
                        payload = c._decode(resp.status_code, resp.content,
                                            resp.headers)
                        c._parse(resp.status_code, payload, resp.headers)
                    parser = _sse.SSEParser()
                    for line in resp.iter_lines():
                        frame = parser.feed(line)
                        if frame is None:
                            continue
                        model = _sse.frame_to_model(frame)
                        if model is None:
                            continue
                        attempt = 0
                        cursor = None if isinstance(model, StreamReset) else model.id
                        yield model
            except httpx.TimeoutException as e:
                if not reconnect:
                    raise exc.APITimeoutError(cause=e) from e
            except httpx.HTTPError as e:
                if not reconnect:
                    raise exc.APIConnectionError(str(e) or "Connection error",
                                                 cause=e) from e
            # Stream ended (server close / deploy / slow-client drop) or a
            # transport error with reconnect enabled: back off and resume.
            if not reconnect:
                return
            time.sleep(_sse.backoff_delay(attempt))
            attempt += 1

    # -- logs --------------------------------------------------------------- #

    def member_access_logs(self, account_community_id: int, *,
                           window: str = "last_30") -> MemberAccessLogPage:
        """A member's opens for a 30-day window (``last_30``/``30_60``/``60_90``)."""
        return self._c._request(
            endpoints.member_access_logs(account_community_id, window))

    def access_log(self, *, page: int = 0) -> AccessLogPage:
        """One page (1000 rows) of the community access log (last 90 days)."""
        return self._c._request(endpoints.access_log(page))

    def gate_status_log(self, *, page: int = 0) -> GateStatusLogPage:
        """One page (1000 rows) of physical gate open/closed transitions."""
        return self._c._request(endpoints.gate_status_log(page))

    # -- pagination helpers ------------------------------------------------- #

    def iter_access_log(self, *, start_page: int = 0) -> Iterator[AccessLogEntry]:
        """Yield every access-log row, walking pages until ``has_more`` is false."""
        page = start_page
        while True:
            result = self.access_log(page=page)
            yield from result.logs
            if not result.has_more:
                return
            page += 1

    def iter_gate_status_log(self, *,
                             start_page: int = 0) -> Iterator[GateStatusLogEntry]:
        """Yield every gate status-change row across all pages."""
        page = start_page
        while True:
            result = self.gate_status_log(page=page)
            yield from result.logs
            if not result.has_more:
                return
            page += 1
