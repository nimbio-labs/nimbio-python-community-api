"""Asynchronous client — for asyncio programs (FastAPI, aiohttp, bots, ...)."""

from __future__ import annotations

import asyncio
from typing import (
    Any,
    AsyncIterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Union,
)

import httpx

from . import _exceptions as exc
from . import _sse
from ._base import UNSET, BaseClient, endpoints
from ._cache import DEFAULT_CACHE_SIZE
from .models import (
    AccessCode,
    AccessCodeCreated,
    AccessCodeDeleted,
    AccessCodeEligibleLatches,
    AccessCodeLogPage,
    AccessCodeMode,
    AccessCodeModeChange,
    AccessCodeModeStatus,
    AccessCodes,
    AccessLogEntry,
    AccessLogPage,
    AccountKey,
    AccountOpen,
    BulkResult,
    ChangeLogPage,
    CommunityInfo,
    CommunityKey,
    CommunityMap,
    CommunitySettings,
    DeliveryReplay,
    DeliveryReplayBatch,
    DirectoryCall,
    DirectoryCallPage,
    GateStatus,
    GateStatusLogEntry,
    GateStatusLogPage,
    GuestLink,
    GuestLinkLatchExclusions,
    GuestLinkLogPage,
    GuestViewEntry,
    GuestViewEntryLogPage,
    Health,
    HoldOpenDisabledUntil,
    HoldOpenEventAdded,
    HoldOpenEventRemoved,
    HoldOpens,
    Home,
    HomeRemoved,
    KeySchedule,
    KeySchedules,
    KeyStatuses,
    KeyUpdateResult,
    KeyUsageReport,
    ManualHoldOpenResult,
    MapLatch,
    Me,
    Member,
    MemberAccessLogPage,
    Members,
    MembersPage,
    MessagesPage,
    MoveOutDate,
    NfcScanLogPage,
    NfcTag,
    NfcTagPage,
    NotificationSettings,
    OpenHistoryPage,
    OpenResult,
    RecurringHoldOpen,
    RecurringHoldOpenRemoved,
    SenseLine,
    SenseLineRecordPage,
    SenseLines,
    ShortCode,
    StreamEvent,
    StreamReset,
    Webhook,
    WebhookCreateResult,
    WebhookDelivery,
    WebhookSecret,
    WriteResult,
)


class AsyncNimbioClient(BaseClient):
    """Non-blocking client for the Nimbio community API.

    Example::

        import asyncio
        from nimbio_community_api import AsyncNimbioClient

        async def main():
            async with AsyncNimbioClient("nimbio_test_...") as client:
                me = await client.me()
                print(me.account_id)
                await client.community.open("latch-id-123")

        asyncio.run(main())

    The method surface is identical to :class:`NimbioClient`; every call is a
    coroutine, and the log iterators are async generators.

    **Conditional requests are on by default**, exactly as on the sync client:
    a ``304 Not Modified`` replays the body from a bounded per-client cache and
    refunds your monthly quota, transparently and without ever serving stale
    data. ``cache=False`` opts out, ``cache_size=...`` resizes, and
    :meth:`cache_stats` reports what actually happened. ``integration=...``
    identifies a product built on the SDK, as on the sync client.
    """

    def __init__(self, api_key: Optional[str] = None, *,
                 environment: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: Optional[float] = None,
                 max_retries: int = 2,
                 default_headers: Optional[dict] = None,
                 cache: bool = True,
                 cache_size: int = DEFAULT_CACHE_SIZE,
                 integration: Optional[str] = None,
                 http_client: Optional[httpx.AsyncClient] = None) -> None:
        super().__init__(
            api_key, environment=environment, base_url=base_url,
            timeout=30.0 if timeout is None else timeout,
            max_retries=max_retries, default_headers=default_headers,
            cache=cache, cache_size=cache_size, integration=integration,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=self.timeout)
        self.community = _AsyncCommunity(self)
        self.account = _AsyncAccount(self)

    # -- lifecycle ---------------------------------------------------------- #

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncNimbioClient":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()

    # -- core request loop -------------------------------------------------- #

    async def _request(self, spec, *, auth: bool = True) -> Any:
        method, path, params, json, parser = spec
        prepared = self._prepare(method, path, params=params, json=json, auth=auth)
        cache_key = self._cache_begin(prepared, path)
        attempt = 0
        while True:
            try:
                resp = await self._http.request(
                    prepared.method, prepared.url, headers=prepared.headers,
                    params=prepared.params, json=prepared.json,
                )
            except httpx.TimeoutException as e:
                raise exc.APITimeoutError(cause=e) from e
            except httpx.HTTPError as e:
                raise exc.APIConnectionError(str(e) or "Connection error",
                                             cause=e) from e

            if self._should_retry(resp.status_code, attempt):
                await asyncio.sleep(self._retry_delay(attempt, resp.headers))
                attempt += 1
                continue

            if cache_key is not None and resp.status_code == 304:
                cached = self._cache_hit(cache_key, resp.headers)
                if cached is None:
                    # Evicted between sending the conditional header and the
                    # 304 arriving. We have no body to return, so drop the
                    # header and ask again unconditionally.
                    prepared.headers.pop("If-None-Match", None)
                    cache_key = None
                    continue
                # Decode and parse from the stored bytes every time: a 304's
                # return value is a brand-new object graph, exactly like a
                # 200's, so a caller mutating one cannot affect the next read.
                payload = self._decode(200, cached, resp.headers)
                data = self._parse(200, payload, resp.headers)
                return parser(data) if parser else data

            if cache_key is not None:
                self._cache_miss(cache_key, resp.status_code, resp.headers,
                                 resp.content)
            payload = self._decode(resp.status_code, resp.content, resp.headers)
            data = self._parse(resp.status_code, payload, resp.headers)
            return parser(data) if parser else data

    # -- SSE consumer (shared by community and account streams) ------------ #

    async def _stream(self, path: str, events: Optional[Sequence[str]],
                      last_event_id: Optional[str], reconnect: bool,
                      ) -> AsyncIterator[Union[StreamEvent, StreamReset]]:
        cursor = last_event_id
        attempt = 0
        while True:
            prepared = self._prepare("GET", path,
                                     params=_sse.stream_params(events, cursor))
            timeout = httpx.Timeout(self.timeout or 30.0,
                                    read=_sse.STREAM_READ_TIMEOUT)
            try:
                async with self._http.stream(prepared.method, prepared.url,
                                             headers=prepared.headers,
                                             params=prepared.params,
                                             timeout=timeout) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        payload = self._decode(resp.status_code, resp.content,
                                               resp.headers)
                        self._parse(resp.status_code, payload, resp.headers)
                    parser = _sse.SSEParser()
                    async for line in resp.aiter_lines():
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
            if not reconnect:
                return
            await asyncio.sleep(_sse.backoff_delay(attempt))
            attempt += 1

    # -- top-level endpoints ------------------------------------------------ #

    async def health(self) -> Health:
        """Backend reachability (unauthenticated). Does not raise on 503."""
        method, path, params, json, parser = endpoints.health()
        prepared = self._prepare(method, path, params=params, json=json, auth=False)
        try:
            resp = await self._http.request(prepared.method, prepared.url,
                                            headers=prepared.headers)
        except httpx.TimeoutException as e:
            raise exc.APITimeoutError(cause=e) from e
        except httpx.HTTPError as e:
            raise exc.APIConnectionError(str(e) or "Connection error", cause=e) from e
        payload = self._decode(resp.status_code, resp.content, resp.headers)
        return Health.from_dict(payload if isinstance(payload, dict) else {})

    async def me(self) -> Me:
        """Metadata and live usage counters for the authenticating key."""
        return await self._request(endpoints.me())


class _AsyncAccount:
    """``client.account.*`` — account-scoped operations (async)."""

    def __init__(self, client: AsyncNimbioClient) -> None:
        self._c = client

    async def keys(self, *, include_hidden: bool = False) -> List[AccountKey]:
        return await self._c._request(endpoints.account_keys(include_hidden))

    async def open(self, key_id: str, latch_id: str, *,
                   note: Optional[str] = None,
                   idempotency_key: Optional[str] = None) -> OpenResult:
        return await self._c._request(
            endpoints.account_open(key_id, latch_id, note, idempotency_key))

    # -- directory calls ----------------------------------------------------- #

    async def directory_calls(self, *, limit: int = 20,
                              before: Optional[str] = None) -> DirectoryCallPage:
        """GuestView calls that rang you, newest first. Semantics match
        :meth:`NimbioClient.account.directory_calls`."""
        return await self._c._request(
            endpoints.account_directory_calls(limit, before))

    async def iter_directory_calls(self, *, limit: int = 20,
                                   before: Optional[str] = None,
                                   ) -> AsyncIterator[DirectoryCall]:
        """Yield every directory call, newest first, across all pages."""
        while True:
            page = await self.directory_calls(limit=limit, before=before)
            for call in page.calls:
                yield call
            # A cursor that does not advance would re-yield the same page forever.
            if (page.next_before is None or not page.calls
                    or page.next_before == before):
                return
            before = page.next_before

    # -- open history -------------------------------------------------------- #

    async def history(self, *, date_from: Optional[str] = None,
                      date_to: Optional[str] = None,
                      key_id: Optional[str] = None,
                      page: int = 0) -> OpenHistoryPage:
        """One page of opens on your keys, newest first. Semantics match
        :meth:`NimbioClient.account.history`."""
        return await self._c._request(
            endpoints.account_history(date_from, date_to, key_id, page))

    async def iter_history(self, *, date_from: Optional[str] = None,
                           date_to: Optional[str] = None,
                           key_id: Optional[str] = None,
                           start_page: int = 0) -> AsyncIterator[AccountOpen]:
        """Yield every open in the window, newest first, across all pages."""
        page = start_page
        while True:
            result = await self.history(date_from=date_from, date_to=date_to,
                                        key_id=key_id, page=page)
            for row in result.opens:
                yield row
            if not result.has_more or not result.opens:
                return
            # Pin the window the first page used; a defaulted "to" would slide.
            date_from = date_from or result.date_from
            date_to = date_to or result.date_to
            page += 1

    # -- live events --------------------------------------------------------- #

    def stream_events(self, *, events: Optional[Sequence[str]] = None,
                      last_event_id: Optional[str] = None,
                      reconnect: bool = True,
                      ) -> AsyncIterator[Union[StreamEvent, StreamReset]]:
        """Async-iterate your live account events (GuestView calls to you).
        Semantics match :meth:`NimbioClient.account.stream_events`."""
        return self._c._stream(_sse.ACCOUNT_STREAM_PATH, events, last_event_id,
                               reconnect)


class _AsyncCommunity:
    """``client.community.*`` — community-scoped operations (async)."""

    def __init__(self, client: AsyncNimbioClient) -> None:
        self._c = client

    # -- reads -------------------------------------------------------------- #

    async def info(self) -> CommunityInfo:
        """**Call this first.** The community this key is bound to.

        The bootstrap read for any integration, and the source of the three
        things the rest of this surface assumes you already know:

        - **Latch ids.** ``.latches[i].latch_id`` is what :meth:`open` and every
          hold-open call take — read them here rather than scraping a
          gate-status payload. Live sensed state is not duplicated here; call
          :meth:`gate_status` for that.
        - **Feature flags.** ``.features`` (or ``.feature("hold_opens")``) is
          what this community has switched on. Branch on it instead of calling
          an endpoint and interpreting a 403.
        - **Timezone.** Every time you read or write on this API is in the
          community's local clock, and that clock lives on its hardware:
          ``.timezone`` is the one zone every latch agrees on, or None when
          they differ — then use each latch's own.

        Contains no personal data, and is quota-exempt: safe to call on startup
        and on every config refresh."""
        return await self._c._request(endpoints.info())

    async def gate_status(self) -> GateStatus:
        return await self._c._request(endpoints.gate_status())

    async def members(self) -> Members:
        return await self._c._request(endpoints.members())

    async def members_page(self, *, bucket: str = "accepted", page: int = 1,
                           size: int = 100,
                           search: Optional[str] = None) -> MembersPage:
        """One bucket of the roster, paged and optionally searched.

        ``bucket`` is ``"accepted"`` (default), ``"unaccepted"`` (pending join
        requests) or ``"removed"``. ``page`` is **1-indexed**; ``size`` is
        1-500. ``search`` is a case-insensitive substring match over first
        name, last name and phone number — punctuation is ignored, so
        ``"555-1234"`` matches ``"+1 555-123-4567"``.

        Filtering happens before paging, so ``.total`` counts the matches and
        paging through a search never skips anyone. Prefer this over
        :meth:`members` when polling a large community or when you only need
        one bucket: it ships far less data (and far fewer phone numbers)."""
        return await self._c._request(
            endpoints.members_page(bucket, page, size, search))

    async def member(self, account_community_id: int) -> Member:
        """One member, by ``account_community_id``.

        The id comes from :meth:`members` / :meth:`members_page` or off a
        ``member.requested`` webhook. ``.bucket`` says which list they are in.

        A member of any other community raises :class:`NotFoundError`, exactly
        as an unknown id does — a key can only ever read its own roster."""
        return await self._c._request(endpoints.member(account_community_id))

    async def messages(self, *, limit: int = 50,
                       offset: int = 0) -> MessagesPage:
        """Messages already sent to this community, newest first.

        The read half of :meth:`message`: confirm a broadcast landed, render a
        history, or check before re-sending after an ambiguous failure.
        ``limit`` is 1-200; ``sent_at`` is ISO-8601 in **UTC**.

        Only real sends are recorded — a test-mode key's send is validated and
        discarded, so nothing simulated ever appears here. A test key reads the
        live history but can never add to it."""
        return await self._c._request(endpoints.messages(limit, offset))

    async def key_statuses(self) -> KeyStatuses:
        return await self._c._request(endpoints.key_statuses())

    async def keys(self) -> List[CommunityKey]:
        return await self._c._request(endpoints.keys())

    # -- writes ------------------------------------------------------------- #

    async def open(self, latch_id: str, *, note: Optional[str] = None,
                   idempotency_key: Optional[str] = None) -> OpenResult:
        return await self._c._request(
            endpoints.open(latch_id, note, idempotency_key))

    async def message(self, message: str) -> WriteResult:
        return await self._c._request(endpoints.message(message))

    async def add_member(self, phone_number: str,
                         key_ids: Sequence[str]) -> WriteResult:
        return await self._c._request(endpoints.add_member(phone_number, key_ids))

    async def grant_keys(self, account_community_id: int,
                         key_ids: Sequence[str]) -> WriteResult:
        return await self._c._request(
            endpoints.grant_keys(account_community_id, key_ids))

    async def revoke_keys(self, account_community_id: int,
                          key_ids: Sequence[str], *,
                          remove_member: bool = False) -> WriteResult:
        return await self._c._request(
            endpoints.revoke_keys(account_community_id, key_ids, remove_member))

    async def set_keys_disabled(self, account_community_id: int,
                                key_ids: Sequence[str],
                                disabled: bool) -> WriteResult:
        return await self._c._request(
            endpoints.set_keys_disabled(account_community_id, key_ids, disabled))

    async def update_key(self, key_id: str, *, name: Optional[str] = None,
                         disabled: Optional[bool] = None) -> KeyUpdateResult:
        """Rename one of the community's own keys, or disable it
        community-wide.

        Send ``name``, ``disabled``, or both; each is applied only when given,
        so this never clobbers the field you did not send. Sending neither is
        refused (422) rather than treated as a no-op.

        **Disabling a community key affects every member holding a child of
        it.** Sharing a key mints a *child* key on the recipient's account, and
        disabled state is inherited down that chain — so disabling the
        community's key instantly denies every member key descended from it,
        potentially the entire community. ``.descendant_key_count`` on the
        result is that blast radius; read it before disabling.

        Test keys simulate: ``.result`` is ``"simulated"``, ``.key`` is None."""
        return await self._c._request(endpoints.update_key(key_id, name, disabled))

    async def approve_member(self, account_community_id: int,
                             key_ids: Sequence[str], *,
                             move_out_date: Optional[str] = None,
                             dry_run: Optional[bool] = None) -> WriteResult:
        """Approve a pending join request and grant the member their keys.

        Closes the loop opened by the ``member.requested`` webhook: the person
        in the ``unaccepted`` bucket becomes an accepted member, gets a key on
        their account for each id in ``key_ids`` (community key ids, from
        :meth:`key_statuses`), receives the approval push, and the community's
        ``member.approved`` webhook fires — exactly as if a community manager
        had approved them in the portal.

        ``move_out_date`` is an optional ``'YYYY-MM-DD'`` stamped on the
        membership. ``dry_run=True`` validates without approving.

        Approving an already-approved member raises :class:`ConflictError`
        (409, ``already_accepted``). Test keys simulate."""
        return await self._c._request(endpoints.approve_member(
            account_community_id, key_ids, move_out_date, dry_run))

    # -- bulk member writes -------------------------------------------------- #

    async def bulk_add_members(self,
                               items: Sequence[Mapping[str, Any]]) -> BulkResult:
        """Add many members by phone number in one call — the roster import.

        ``items`` is a sequence of ``{"phone_number": ..., "key_ids": [...]}``
        mappings, at most 100. Key scope, phone shape and in-batch duplicate
        phone numbers are all checked before anything is created; any of them
        rejects the **whole** batch (422) with nothing applied.

        This is the highest-side-effect call on the API: each successful item
        may create an account, mints keys, pushes a notification to that member
        and fires a ``member.approved`` webhook — none of it undoable. An
        already-accepted member fails with ``already_member`` while the rest of
        the batch still runs, so re-submitting after a partial failure does not
        double-add anyone.

        Returns 207 with one entry per item, in request order — a 207 does NOT
        mean every item succeeded, so read ``.failures``. Quota: one unit per
        item. Test keys validate everything and change nothing."""
        return await self._c._request(endpoints.bulk_add_members(items))

    async def bulk_grant_keys(self,
                              items: Sequence[Mapping[str, Any]]) -> BulkResult:
        """Grant community keys to many members in one call.

        ``items`` is a sequence of ``{"account_community_id": ...,
        "key_ids": [...]}`` mappings, at most 100. Every item is checked
        against your community *before* anything is applied — one member or key
        belonging elsewhere rejects the whole batch (422) with nothing changed.

        Grants are idempotent: a key the member already holds is reported under
        the item's ``granted["exists"]`` and changes nothing, so re-submitting a
        batch (or only its failures) is safe.

        Returns 207 with one entry per item; read ``.failures`` rather than the
        status code. Quota: one unit per item. Test keys simulate."""
        return await self._c._request(endpoints.bulk_grant_keys(items))

    async def bulk_revoke_keys(self,
                               items: Sequence[Mapping[str, Any]]) -> BulkResult:
        """Revoke community keys from many members in one call.

        ``items`` is a sequence of ``{"account_community_id": ...,
        "key_ids": [...]}`` mappings, at most 100, validated in full before
        anything is applied.

        **Keys only** — members stay members. Removing a member entirely is
        deliberately not batched: use :meth:`revoke_keys` with
        ``remove_member=True`` per member, so a mass removal is always an
        explicit, per-member act.

        Re-submitting is safe: a key the member no longer holds comes back
        under the item's ``already_revoked_community_key_ids`` and the item
        still succeeds. Quota: one unit per item. Test keys simulate."""
        return await self._c._request(endpoints.bulk_revoke_keys(items))

    async def bulk_set_keys_disabled(self, items: Sequence[Mapping[str, Any]],
                                     disabled: bool) -> BulkResult:
        """Disable or enable many members' keys in one call (reversible — no
        key is removed).

        ``items`` is a sequence of ``{"account_community_id": ...,
        "key_ids": [...]}`` mappings, at most 100, validated in full before
        anything is applied. ``disabled`` applies to the whole batch: True
        disables, False re-enables.

        Setting a key to the state it is already in is a no-op, so
        re-submitting is safe. A key the member does not hold is a per-item
        ``key_not_held`` failure — unlike revoke there is no "already in the
        desired state" reading, and enabling a key someone does not have needs
        a grant, not a toggle.

        Quota: one unit per item. Test keys simulate."""
        return await self._c._request(
            endpoints.bulk_set_keys_disabled(items, disabled))

    # -- hold opens ---------------------------------------------------------- #

    async def hold_opens(self) -> HoldOpens:
        return await self._c._request(endpoints.hold_opens())

    async def set_hold_open(self, latch_id: str,
                            state: bool) -> ManualHoldOpenResult:
        return await self._c._request(endpoints.set_hold_open(latch_id, state))

    async def add_hold_open_event(self, latch_id: str, *, start: str,
                                  end: str) -> HoldOpenEventAdded:
        return await self._c._request(
            endpoints.add_hold_open_event(latch_id, start, end))

    async def remove_hold_open_event(self, latch_id: str,
                                     event_id: str) -> HoldOpenEventRemoved:
        return await self._c._request(
            endpoints.remove_hold_open_event(latch_id, event_id))

    async def set_hold_open_disabled_until(
        self, latch_id: str, until: Optional[str],
    ) -> HoldOpenDisabledUntil:
        """Suspend **every** scheduled hold open on a latch, or resume them —
        the holiday / special-event override.

        While the suspension is in force the scheduler skips all recurring and
        one-time windows on this latch and releases any hold already active. It
        clears itself once the moment passes.

        ``until`` is ``'YYYY-MM-DD HH:MM'`` in the **latch's own local time**
        (the ``timezone`` :meth:`hold_opens` reports for it), never UTC. It is
        **required**: pass ``None`` to resume now. That is deliberate — an
        empty body can then never resume by accident.

        Per latch, not per community: suspending one gate's schedules leaves
        the others running. Requires the community's Hold Opens feature (403
        ``hold_opens_disabled``). Test keys simulate."""
        return await self._c._request(
            endpoints.set_hold_open_disabled_until(latch_id, until))

    async def add_hold_open_recurring(self, latch_id: str, *,
                                      days_of_the_week: str,
                                      start_time: Optional[str] = None,
                                      end_time: Optional[str] = None,
                                      recurring_week: Optional[int] = None,
                                      ) -> RecurringHoldOpen:
        """Hold a gate open on a repeating weekly schedule — business hours,
        trash day, a standing delivery window.

        **Days:** letters from ``MTWHFSU``, where **H is Thursday, S is
        Saturday and U is Sunday** — the same string the read emits. A 1-127
        bitmask is also accepted.

        **Times:** ``'HH:MM'`` in the **latch's own local time** (the
        ``timezone`` :meth:`hold_opens` reports for it), never UTC and no
        offset accepted: ``"08:00"`` means 08:00 at the gate. Omit both for an
        **all-day** schedule.

        A window **may not wrap past midnight**: ``22:00``-``06:00`` is
        refused. Split it into ``22:00``-``24:00`` plus ``00:00``-``06:00`` the
        next day, and use ``"24:00"`` rather than ``"23:59"`` so the two halves
        leave no gap.

        Keep the returned ``.temporal_date_id`` — it addresses the schedule for
        :meth:`update_hold_open_recurring` and
        :meth:`remove_hold_open_recurring`. Requires the community's Hold Opens
        feature (403 ``hold_opens_disabled``). Test keys simulate."""
        return await self._c._request(endpoints.add_hold_open_recurring(
            latch_id, days_of_the_week, start_time, end_time, recurring_week))

    async def update_hold_open_recurring(
        self, latch_id: str, temporal_date_id: str, *,
        days_of_the_week: Optional[str] = None,
        start_time: Optional[str] = None, end_time: Optional[str] = None,
        recurring_week: Optional[int] = None,
        clear_times: Optional[bool] = None,
    ) -> RecurringHoldOpen:
        """Change an existing recurring schedule. Partial update: anything left
        out keeps its current value.

        Time handling is explicit rather than inferred:

        - ``start_time`` + ``end_time`` **replace** the schedule's window,
        - ``clear_times=True`` removes the window, making the schedule all-day,
        - sending neither leaves the times alone.

        Days are ``MTWHFSU`` letters (**H is Thursday**, S Saturday, U Sunday);
        times are ``'HH:MM'`` in the **latch's local time**, never UTC, and
        still may not wrap past midnight. A ``temporal_date_id`` that is not on
        this latch raises :class:`NotFoundError`. Requires the community's Hold
        Opens feature (403 ``hold_opens_disabled``). Test keys simulate."""
        return await self._c._request(endpoints.update_hold_open_recurring(
            latch_id, temporal_date_id, days_of_the_week, start_time, end_time,
            recurring_week, clear_times))

    async def remove_hold_open_recurring(self, latch_id: str,
                                         temporal_date_id: str,
                                         ) -> RecurringHoldOpenRemoved:
        """Delete a recurring hold-open schedule.

        Deliberately **not idempotent**: a ``temporal_date_id`` that is not on
        this latch raises :class:`NotFoundError` rather than reporting a
        cheerful success, because succeeding silently would let a caller
        believe it had cancelled a schedule that is still holding a gate open.

        Requires the community's Hold Opens feature (403
        ``hold_opens_disabled``). Test keys simulate."""
        return await self._c._request(
            endpoints.remove_hold_open_recurring(latch_id, temporal_date_id))

    # -- key access schedules ------------------------------------------------ #

    async def key_schedules(self) -> KeySchedules:
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
        return await self._c._request(endpoints.key_schedules())

    async def key_schedule(self, key_id: str) -> KeySchedule:
        """One community key's access schedule.

        ``key_id`` must be one of the community's own keys; a member's key is
        refused with ``not_a_community_key`` (403). Returns **every** window,
        expired ones included, because :meth:`set_key_schedule` replaces the
        whole schedule. Does not consume the monthly quota."""
        return await self._c._request(endpoints.key_schedule(key_id))

    async def set_key_schedule(self, key_id: str, windows) -> KeySchedule:
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
        return await self._c._request(endpoints.set_key_schedule(key_id, windows))

    # -- community settings -------------------------------------------------- #

    async def settings(self) -> CommunitySettings:
        """The community's configuration — the settable half and the
        provisioned half.

        ``.settings`` is everything :meth:`update_settings` may change.
        ``.read_only`` is what Nimbio provisions for you, and reading it is the
        reason this endpoint is worth calling: several endpoint families are
        gated on those flags, and **without this call the only way to learn a
        feature is off is to call it and get a 403**. Use ``.feature(name)``::

            s = client.community.settings()
            if s.feature("allow_hold_opens"):
                client.community.hold_opens()

        ``allow_hold_opens`` false 403s the whole hold-open family;
        ``is_open_log_history_enabled`` false 403s :meth:`access_log` and
        :meth:`gate_status_log`; ``allow_guest_view_entry`` gates GuestView
        Entry. ``event_keys_enabled`` is the *resolved* answer for event keys,
        combining the settable ``event_keys_override``
        (``inherit``/``allow``/``deny``) with the property type's default.
        ``access_code_mode`` (``per_member`` / ``single_entry``) is the one
        read-only value an API key *can* change — but only through
        :meth:`set_access_code_mode`, because switching it deletes every
        access code in the community and needs an explicit confirm.

        Those flags and the two per-community caps
        (``event_key_max_window_hours``, ``limited_use_link_max_uses``) are
        Nimbio-side provisioning decisions, not a gap in the API — nobody
        changes them from the CM portal either, and sending one to
        :meth:`update_settings` is a 422. Contact Nimbio to change one.

        Unlike :meth:`info`, this read **does** consume the monthly quota: it
        is setup-time configuration, not something to poll."""
        return await self._c._request(endpoints.settings())

    async def update_settings(self, settings: Mapping[str, Any]) -> CommunitySettings:
        """Change the community's configuration — a partial update.

        Pass only the keys you want to change; everything else is left alone.
        The whole patch is validated **before anything is written**, so a batch
        containing one bad value applies **nothing** — you never have to reason
        about a half-applied profile. ``.changed`` names the keys actually
        applied.

        An unknown key is **rejected, never ignored**: 422 ``invalid_setting``
        naming it. So is a read-only one (``allow_hold_opens``,
        ``is_open_log_history_enabled``, ``allow_guest_view_entry``,
        ``event_key_max_window_hours``, ``limited_use_link_max_uses``) — those
        are provisioned by Nimbio; the message says which and to contact
        support. So is ``access_code_mode``, but for a different reason: the
        flip deletes every access code, so it lives behind its own confirm
        handshake in :meth:`set_access_code_mode` and the 422 points there.

        Fifteen fields are settable: ``allow_directory_viewing``,
        ``allow_directory_access_codes``,
        ``is_new_member_request_home_enabled``,
        ``limited_use_links_members_only``,
        ``limited_use_links_require_account``, ``event_keys_require_account``,
        ``event_keys_override``, and the terminology pair
        ``{member,home}_terminology_option_id`` /
        ``{member,home}_term_custom`` / ``{member,home}_term_custom_plural`` /
        ``{member,home}_icon``.

        Within a terminology side a **custom label and a picker option are
        mutually exclusive** — setting one clears the other. Labels cap at 255
        characters, icons at 64, control characters are refused, and an empty
        string or ``None`` clears a custom label back to the default.

        **These settings change what the rest of the API does.** Turning
        ``allow_directory_viewing`` off makes the directory disappear for
        members and guests; ``event_keys_override="deny"`` stops event keys
        working community-wide whatever the property type allows.

        Test keys validate the whole patch and return ``.simulated`` with the
        community's *unchanged* settings."""
        return await self._c._request(endpoints.update_settings(settings))

    # -- homes / units roster ------------------------------------------------ #

    async def homes(self, *, include_hidden: bool = True) -> List[Home]:
        """Every home (unit) in the community, with its resident count, sorted
        by address.

        ``include_hidden`` defaults to **True** — a roster sync wants the whole
        set. Pass False to match what the CM portal lists.

        Rows carry counts, not people: read one home with :meth:`home` to see
        who is attached to it."""
        return await self._c._request(endpoints.homes(include_hidden))

    async def add_home(self, home_address: str) -> Home:
        """Add a home (unit) to the community.

        Returns the created home as a full resource — id, address, flags and
        resident count — so a roster sync can record it without a second call.

        Test keys validate the address and create nothing: ``.simulated`` is
        True, ``.home_id`` is None, and the address that would have been used
        is echoed on ``.raw["would_create"]``."""
        return await self._c._request(endpoints.add_home(home_address))

    async def home(self, home_id: str) -> Home:
        """One home, plus its residents and their move-out dates.

        ``.members`` is populated only here — the list read reports
        ``member_count`` alone. **Call this before :meth:`remove_home`** if you
        want to know the blast radius before committing to it.

        A home belonging to another community reads as 404, the same as one
        that does not exist."""
        return await self._c._request(endpoints.home(home_id))

    async def update_home(self, home_id: str, *, home_address: Optional[str] = None,
                    owner_occupied: Optional[bool] = None,
                    hidden: Optional[bool] = None) -> Home:
        """Edit a home: any of ``home_address``, ``owner_occupied``,
        ``hidden``. A field you omit is left alone, so you can change one
        without reading the rest; sending none at all is 400 ``no_fields``.

        ``hidden`` is a **setter, not a toggle** — ``hidden=True`` sent twice
        leaves the home hidden, so a retry is safe. Hiding a home that still
        has residents attached is refused with 409 ``home_occupied``; move them
        out first.

        Test keys validate and change nothing (``.simulated``, with the
        would-be values on ``.raw["would_set"]``)."""
        return await self._c._request(endpoints.update_home(
            home_id, home_address=home_address, owner_occupied=owner_occupied,
            hidden=hidden))

    async def remove_home(self, home_id: str) -> HomeRemoved:
        """Remove a home from the community — **and detach every resident
        attached to it.**

        This is the most destructive call on this surface. The detached
        residents remain members and keep their keys, but they are no longer
        associated with any unit, and **nothing restores the association
        automatically**: you would have to re-add the home and re-attach each
        resident by hand.

        ``.detached_member_count`` reports how many were affected. Call
        :meth:`home` first if you want that number *before* you commit::

            if len(client.community.home(home_id).members) == 0:
                client.community.remove_home(home_id)

        Test keys report the count they *would* detach on
        ``.detached_member_count``, leave ``.deleted`` False, and change
        nothing."""
        return await self._c._request(endpoints.remove_home(home_id))

    async def set_move_out_date(self, account_community_id: int,
                          move_out_date: Optional[str]) -> MoveOutDate:
        """Record (or clear) a member's move-out date, so their access lapses
        without anyone remembering to revoke it.

        ``move_out_date`` is ``'YYYY-MM-DD'``; pass ``None`` to clear a date
        already set. The value is always sent, null included — an absent field
        would be a 422 rather than a silent no-op.

        ``account_community_id`` is the member id the rest of the member
        surface uses, and it must belong to this key's community: another
        community's member is 404 ``member_not_found``. Test keys validate and
        store nothing."""
        return await self._c._request(
            endpoints.set_move_out_date(account_community_id, move_out_date))

    # -- my member-open notification settings -------------------------------- #

    async def my_notification_settings(self) -> NotificationSettings:
        """Member-open notification settings for **the community manager who
        owns this API key** — not a community-wide setting.

        An API key acts as its owning manager, so this always reads *that
        person's* settings. A community with several managers has several
        independent objects: two keys owned by two managers of the same
        community return two different ones here, and neither can see or change
        the other's.

        ``.enabled`` is whether that manager is pushed to when one of the
        community's members opens a gate. ``.feature_available`` is whether the
        community permits the feature at all — false makes all three writes 403
        ``open_notifications_disabled`` and leaves ``.enabled`` with no effect.

        ``.quiet_hours`` are the windows suppressing that manager's alerts,
        each **evaluated in the local timezone of the gate that was opened**.
        Does not consume the monthly quota."""
        return await self._c._request(endpoints.my_notification_settings())

    async def set_my_notifications_enabled(self,
                                     enabled: bool) -> NotificationSettings:
        """Turn member-open alerts on or off for **the community manager who
        owns this API key** — not for the community, and not for its other
        managers. Turning it off here does not stop anyone else's alerts.

        Returns the **full** updated settings object, quiet hours included, so
        no follow-up read is needed.

        Requires the community's member-open notifications feature
        (``feature_available``); otherwise 403 ``open_notifications_disabled``,
        and a non-boolean is 422 ``invalid_enabled``. Test keys validate and
        scope-check but never save (``.simulated``)."""
        return await self._c._request(
            endpoints.set_my_notifications_enabled(enabled))

    async def add_quiet_hours(self, days_of_the_week: str,
                        start_time: Optional[str] = None,
                        end_time: Optional[str] = None) -> NotificationSettings:
        """Add one quiet-hours window to **this API key's own manager's**
        settings — it suppresses that manager's alerts only.

        **The midnight rule here is the opposite of the one you just used.**
        This API spells ``'HH:MM'`` three ways and only this one wraps:

        =========================  ==================  ================
        surface                    wraps past midnight ``"24:00"``
        =========================  ==================  ================
        key schedules              no — send two       n/a
        recurring hold opens       no — send two       accepted
        **quiet hours (here)**     **yes — one**       **rejected**
        =========================  ==================  ================

        So ``22:00``-``06:00`` is **one** window, not two, and ``"24:00"`` is
        refused. Carrying the hold-open idiom across fails silently: you get a
        window that never suppresses anything. A ``start_time`` equal to its
        ``end_time`` is refused too (422 ``invalid_time``) — a zero-length
        window suppresses nothing. Omit both times for an all-day window.

        **Timezone:** a window is evaluated in the local timezone of the gate
        that was opened — each device carries its own — not the manager's and
        not UTC. A community with gates in two timezones suppresses each gate's
        alerts on that gate's own clock. Getting this backwards is the other
        way a window silently fails to suppress real alerts, so it is worth
        stating in your own UI.

        ``days_of_the_week`` is letters from ``MTWHFSU`` (**H is Thursday**, S
        Saturday, U Sunday) naming the day the window *starts* on; at least one
        is required, and a bad letter is 422 ``invalid_days``.

        This call is **additive** — each one appends a window. To replace a
        schedule, :meth:`remove_quiet_hours` the ones you no longer want.
        Returns the full updated settings object. Requires
        ``feature_available``; otherwise 403. Test keys validate but never
        save."""
        return await self._c._request(
            endpoints.add_quiet_hours(days_of_the_week, start_time, end_time))

    async def remove_quiet_hours(self,
                           quiet_hours_id: Union[int, str],
                           ) -> NotificationSettings:
        """Delete one quiet-hours window from **this API key's own manager's**
        settings.

        The counterpart to :meth:`add_quiet_hours`: one call removes one
        window, which is how a schedule is replaced — delete the windows you no
        longer want, then add the ones you do.

        The window must belong to that manager. An id belonging to a different
        manager — **including another manager of the same community** — is 404
        ``quiet_hours_not_found`` and deletes nothing; the API deliberately
        does not distinguish "not yours" from "does not exist".

        Returns the full updated settings object. Test keys validate ownership
        but never delete."""
        return await self._c._request(endpoints.remove_quiet_hours(quiet_hours_id))

    # -- guest links --------------------------------------------------------- #

    async def guest_links(self, *, include_inactive: bool = True) -> List[GuestLink]:
        """Every guest link on the community, newest first.

        **A leaked listing is a leaked set of working gate links.** ``token``
        and the ready-to-send ``url`` are returned here, not only at creation —
        a link recovered from this list is exactly as usable as the one the
        create call returned. Anyone holding the URL can open the gate: no
        account, no key, no login. Treat this response the way you would treat
        a password, and **do not log it**. Logging responses at debug level is
        an ordinary thing to do and it would write working gate links to disk;
        :class:`~nimbio_community_api.models.GuestLink` keeps ``token`` and
        ``url`` out of its ``repr`` for that reason, but ``.raw`` and any
        ``json.dumps`` of it still carry them.

        That the list returns them is deliberate — it is what makes a lost URL
        recoverable instead of unrecoverable — and it is exactly why the read
        deserves the same care as the write.

        ``include_inactive=False`` narrows to ``active`` and ``upcoming`` links.
        Each row's ``.state`` is computed live: ``active``, ``upcoming``,
        ``expired``, ``spent``, ``revoked``, or ``feature_disabled``. Branch on
        it rather than re-deriving it from the timestamps."""
        return await self._c._request(endpoints.guest_links(include_inactive))

    async def create_guest_link(self, link_type: str, latch_ids: Sequence[str], *,
                          key_id: Optional[str] = None,
                          title: Optional[str] = None,
                          subtitle: Optional[str] = None,
                          extra_info: Optional[str] = None,
                          max_uses: Optional[int] = None,
                          expires_at: Optional[str] = None,
                          window_start: Optional[str] = None,
                          window_end: Optional[str] = None,
                          notify_on_use: Optional[bool] = None) -> GuestLink:
        """Mint a guest link and get back its ready-to-send URL — the booking
        integration's whole point: issue a gate link when a reservation is
        confirmed, :meth:`revoke_guest_link` it at checkout.

        **The result is secret material.** ``.url`` opens the gate for anyone
        who has it, with no account and no login. Hand it to the guest and do
        not log it — see :meth:`guest_links`, which returns it too.

        ``link_type`` is ``"event"`` or ``"limited_use"``, and the two take
        different limits:

        - **event** — requires ``title``, ``window_start`` and ``window_end``.
          Unlimited opens between those two instants. The window may not exceed
          the community's cap (**8 hours** unless the community raised it) and
          may not have already ended.
        - **limited_use** — requires ``max_uses``, 1 to the community's cap
          (**20** by default). ``expires_at`` is an optional wall-clock
          backstop; it defaults to, and may not exceed, **30 days** from now.

        **Datetimes** are ISO-8601. An offset (including ``Z``) is honoured and
        a **naive string is read as UTC** — communities carry no timezone of
        their own — and everything returned is UTC. A datetime that does not
        parse is rejected outright rather than quietly treated as absent.

        ``key_id`` names the community key behind the link and may be omitted
        only when the community has exactly one. That choice decides which
        gates the link could ever reach: every id in ``latch_ids`` must be
        openable by that key, and none may be excluded for this link type —
        check :meth:`guest_link_latch_exclusions` first, because naming an
        excluded gate is a 422.

        **An API key can mint an ``event`` link even when the community has
        event keys switched off.** That switch aims at *members* — it stops
        members minting event links — and has never applied to a manager acting
        on the management surface, so a settings flip cannot break links a
        manager handed out for tonight; an API key inherits the carve-out. This
        is a real widening: if your integration should honour the community
        setting, read ``features.event_keys`` from :meth:`info` and branch on it
        yourself, because the API will not do it for you.

        Raises :class:`ConflictError` (409) when a limit or the community's
        configuration refuses the link. Test keys validate and mint nothing."""
        return await self._c._request(endpoints.create_guest_link(
            link_type, latch_ids, key_id=key_id, title=title,
            subtitle=subtitle, extra_info=extra_info, max_uses=max_uses,
            expires_at=expires_at, window_start=window_start,
            window_end=window_end, notify_on_use=notify_on_use))

    async def revoke_guest_link(self,
                          guest_link_id: Union[int, str]) -> GuestLink:
        """Kill a guest link — the checkout half of :meth:`create_guest_link`.

        **Terminal: there is no un-revoke.** A revoked link stays dead; to
        restore access, mint a new one. Revoking an already-revoked link is a
        no-op success, so a retry after an ambiguous failure is safe.

        The id must belong to this key's community. One that does not is a 404,
        identical to the answer an unknown id gets — an API key cannot probe
        another community's ids.

        Test mode reports what it *would* have revoked and leaves the link
        live, so a test-key run never actually closes a guest out."""
        return await self._c._request(endpoints.revoke_guest_link(guest_link_id))

    async def guest_link_logs(self, *, guest_link_id: Optional[Union[int, str]] = None,
                        limit: int = 50, offset: int = 0) -> GuestLinkLogPage:
        """Every attempt against the community's guest links, newest first —
        successes, refusals and rate-limited hits alike.

        **This is guest PII.** Rows carry the redeemer's IP address and user
        agent, and the display name of a signed-in account when the community
        requires one. Handle and retain accordingly.

        ``guest_link_id`` narrows to one link; a link belonging to another
        community is a 404, the same answer an unknown id gets. The server does
        not report a total, so a page shorter than ``limit`` is the end."""
        return await self._c._request(
            endpoints.guest_link_logs(guest_link_id, limit, offset))

    async def guest_link_latch_exclusions(self) -> GuestLinkLatchExclusions:
        """Gates the community has taken out of each guest-link type.

        **Absence is permission.** A gate that is not listed may back a link of
        that type, so an empty answer means every gate the backing key opens is
        offerable. The list is **per link type**: a gate barred from ``event``
        links may still be fine for ``limited_use`` ones. Read it before
        :meth:`create_guest_link` — naming an excluded gate is a 422.

        **Read-only on purpose.** The setter behind this list narrows what a
        link type may ever cover, which makes it a safety control rather than a
        configuration knob, so exposing it to API callers was deliberately
        deferred — not forgotten, and not a gap to file."""
        return await self._c._request(endpoints.guest_link_latch_exclusions())

    # -- directory access codes ---------------------------------------------- #

    async def access_codes(self) -> AccessCodes:
        """Every access code in the community — residents' own codes included,
        matching what the CM portal shows.

        **The PIN is never returned here.** ``.code_masked`` is a run of
        asterisks and ``.code_length`` its length; the cleartext is returned
        exactly once, by :meth:`create_access_code`. If you lose a PIN, delete
        the code and create a new one — there is no way to read it back.

        ``.api_managed`` is True for the codes this API key created, and those
        are the only ones :meth:`update_access_code` and
        :meth:`delete_access_code` will touch; anything else answers 404.
        ``.feature_enabled`` mirrors the community's Directory Access Codes
        setting — branch on it rather than on a 403.

        In ``single_entry`` mode (:meth:`access_code_mode`) each row also
        carries the owner's 3-letter ``.preamble`` and ``.entry_code_masked``
        — the preamble in clear, the PIN masked — which is the shape of what
        the visitor types. In ``per_member`` mode both are None.
        ``.access_code_mode`` names the mode the list was read under, so one
        call tells you how to present the rows."""
        return await self._c._request(endpoints.access_codes())

    async def create_access_code(self, code: str, latch_ids: Sequence[str], *,
                           expires_in_hours: Optional[int] = None,
                           expires_in_days: Optional[int] = None,
                           temporal: Optional[Mapping[str, Any]] = None,
                           ) -> AccessCodeCreated:
        """Mint a keypad / GuestView PIN on this key's community.

        **The PIN comes back exactly once — in this response.** Deliver it to
        the visitor now; no later call will reveal it, and
        :meth:`access_codes` masks it forever after.

        In ``single_entry`` mode (:meth:`access_code_mode`) the visitor types
        the key owner's 3-letter preamble followed by the PIN, and
        ``.entry_code`` is that full string (``"ESM481502"``) — also returned
        once. Hand the visitor ``.entry_code`` when it is set and ``.code``
        otherwise.

        Three independent limits, which do different things:

        - ``expires_in_hours`` / ``expires_in_days`` are **mutually exclusive**
          (passing both is a 422). Either sets one absolute cutoff, computed
          **in UTC from the moment of this call**. After it passes the code is
          dead.
        - ``temporal`` is a **recurring weekly window** (e.g. weekdays
          09:00-17:00), evaluated in the **gate's own local timezone** at
          redemption — not UTC and not the caller's zone. It never expires on
          its own. Its keys are ``days_of_the_week``, ``start``, ``end`` and
          ``recurring_week`` — note **``start``/``end``, not
          ``start_time``/``end_time``** as the hold-open and GuestView Entry
          schedules spell them.

        A code may carry both, and then must satisfy both: inside the weekly
        window *and* before the cutoff. Omitting both makes a code that works
        until it is disabled or deleted.

        Every id in ``latch_ids`` must be on the community's access-code
        allowlist — read :meth:`access_code_eligible_latches` — or the call is
        rejected with ``invalid_latch``. Raises :class:`ConflictError` (409) on
        a duplicate code, and 403 ``access_codes_disabled`` when the community
        has the feature off. Test keys validate and store nothing."""
        return await self._c._request(endpoints.create_access_code(
            code, latch_ids, expires_in_hours=expires_in_hours,
            expires_in_days=expires_in_days, temporal=temporal))

    async def update_access_code(self, directory_access_code_id: Union[int, str], *,
                           disabled: Optional[bool] = None,
                           latch_ids: Optional[Sequence[str]] = None,
                           expires_in_hours: Optional[int] = None,
                           expires_in_days: Optional[int] = None,
                           temporal: Optional[Mapping[str, Any]] = None,
                           ) -> AccessCode:
        """Change a code **this key created**: switch it off after the visit
        (``disabled=True``), re-point it at different gates, push out its
        cutoff, or replace its weekly window.

        A code a resident created in the app, or one belonging to another
        community, answers 404 — this endpoint reaches neither. Use the CM
        portal for a resident's own PIN.

        **The PIN itself cannot be changed**; delete the code and create a new
        one. Omitted fields are left as they are, and there is **no way to
        clear** an existing cutoff or weekly window — to stop a code working,
        disable or delete it. Sending an empty body is a 400, so pass at least
        one field.

        Expiry and ``temporal`` mean exactly what they mean on
        :meth:`create_access_code`: a UTC cutoff recomputed from *now* (so
        re-sending ``expires_in_days=1`` extends the code by a day rather than
        confirming the old cutoff), and a recurring window evaluated in the
        gate's local timezone. Test mode validates and changes nothing."""
        return await self._c._request(endpoints.update_access_code(
            directory_access_code_id, disabled=disabled, latch_ids=latch_ids,
            expires_in_hours=expires_in_hours,
            expires_in_days=expires_in_days, temporal=temporal))

    async def delete_access_code(self, directory_access_code_id: Union[int, str],
                           ) -> AccessCodeDeleted:
        """Delete a code **this key created**. The PIN stops working
        immediately and its gate assignments go with it.

        The redemption log rows stay, so the history of who came through the
        gate is preserved — :meth:`access_code_logs` still shows them.

        A resident's own code, or a code in another community, answers 404.
        Test mode validates and deletes nothing."""
        return await self._c._request(
            endpoints.delete_access_code(directory_access_code_id))

    async def access_code_eligible_latches(self) -> AccessCodeEligibleLatches:
        """The gates a community manager has allowed access codes to open.

        Every ``latch_ids`` entry passed to :meth:`create_access_code` or
        :meth:`update_access_code` must appear here, or the call is rejected
        with ``invalid_latch``. **This allowlist is set in the CM portal only**
        — the API can read it, never change it.

        ``.feature_enabled`` mirrors the community's Directory Access Codes
        setting; when it is False, writes return 403
        ``access_codes_disabled``."""
        return await self._c._request(endpoints.access_code_eligible_latches())

    async def access_code_logs(self, *, limit: int = 50,
                         offset: int = 0) -> AccessCodeLogPage:
        """Every access-code entry attempt in the community, newest first.

        ``limit`` is clamped server-side to 1-200 (default 50) and ``offset``
        floored at 0. ``.result`` names the outcome — ``opened``,
        ``code_not_found``, ``code_disabled``, ``code_expired``,
        ``temporal_blocked``, ``latch_not_assigned``, ``open_failed``, and
        others the server may add.

        ``.code_entered_masked`` is asterisks, never the typed digits: a
        successful attempt's entered code *is* a working PIN. Correlate a row
        to a code you minted through ``.directory_access_code_id``, which is
        set whenever the entry matched an existing code. Rows carry the
        visitor's ``.client_ip`` and the code owner's name — this is the
        community's own log, the same one the CM portal shows."""
        return await self._c._request(endpoints.access_code_logs(limit, offset))

    async def access_code_mode(self) -> AccessCodeModeStatus:
        """Which of the two access-code systems the community runs, and what a
        switch would cost.

        - ``per_member`` — the default. A GuestView visitor finds the member
          they are visiting, taps the lock on that row and types **that
          member's** PIN. Codes are unique per member, so two members may hold
          the same digits.
        - ``single_entry`` — one "Enter access code" field for the whole
          community, no member picking. Every member carries a 3-letter
          **preamble** (A-Z, derived from their name, unique in the community)
          and the visitor types preamble + PIN, e.g. ``ESM481502``. Codes this
          key mints carry the key owner's preamble: :meth:`access_codes` rows
          report ``preamble`` / ``entry_code_masked`` and
          :meth:`create_access_code` returns the full ``entry_code`` once.

        ``.flip_preview`` is a read-only dry run of :meth:`set_access_code_mode`
        to the *other* mode: ``codes_to_delete`` (**every** code in the
        community, residents' own included), ``members_affected`` (how many
        lose a code and get notified) and ``members_to_assign_preamble``. Read
        it before you flip, so a human sees the cost first. The same value is
        reported read-only as ``read_only["access_code_mode"]`` by
        :meth:`settings`."""
        return await self._c._request(endpoints.access_code_mode())

    async def set_access_code_mode(self, mode: AccessCodeMode, *,
                             confirm: bool = False) -> AccessCodeModeChange:
        """Switch the community between ``per_member`` and ``single_entry``
        access codes.

        **This is destructive.** Switching in either direction deletes
        **every** access code in the community — the ones this key minted, the
        ones other integrations minted, and the ones residents made for
        themselves in the app — because a code's meaning changes with the mode
        (``481502`` versus ``ESM481502``). Every member who lost a code is
        notified by push and a community-wide message explains the new system.
        Switching to ``single_entry`` also assigns a preamble to every member
        who lacks one. Redemption log rows are kept.

        So it is the same two-step handshake as :meth:`update_nfc_tag`:

        1. Call with ``confirm=False`` (the default). If the community is
           already in that mode you get ``.changed == False`` and nothing
           happens. Otherwise :class:`ConflictError` **(409
           ``requires_confirmation``)** is raised — a warning, not a veto —
           with the flip preview on ``e.preview``, and again nothing happens.
        2. Show the preview to a human, then repeat with ``confirm=True``. The
           live result reports ``.deleted_codes`` and ``.notified_members``::

            try:
                await client.community.set_access_code_mode("single_entry")
            except ConflictError as e:
                if e.code != "requires_confirmation":
                    raise
                preview = models.AccessCodeModePreview.from_dict(e.preview)
                print(f"deletes {preview.codes_to_delete} codes")
                await client.community.set_access_code_mode("single_entry",
                                                      confirm=True)

        Passing ``confirm=True`` unconditionally opts out of the safety net —
        do that only behind your own confirmation step.

        This is deliberately **not** a key of :meth:`update_settings`: a
        generic settings write must never wipe every code by accident, so
        sending ``access_code_mode`` there is a 422 pointing here. An unknown
        ``mode`` is 422 ``invalid_mode``. Neither mode call is gated on the
        Directory Access Codes setting — the mode can be read and switched
        while the feature is off.

        **Test keys** run the 409 handshake exactly as above, and
        ``confirm=True`` then answers ``.simulated`` with ``.would_change`` —
        the same preview — deleting and notifying nothing."""
        return await self._c._request(
            endpoints.set_access_code_mode(mode, confirm=confirm))

    # -- GuestView Entry ------------------------------------------------------ #

    async def guest_view_entry(self) -> GuestViewEntry:
        """The complete GuestView Entry configuration in one read — and the
        **first half of every write** on this family, all four of which replace
        or extend what this returns.

        - ``.allowed`` — the community master switch.
        - ``.eligible_latches`` — the gates a visitor may open. Nothing outside
          this set is reachable via GuestView Entry, whatever the schedule
          says; ``.latch_ids`` is the list
          :meth:`set_guest_view_entry_latches` expects you to modify and send
          back.
        - ``.schedule`` — the recurring windows. **Each window is evaluated in
          its latch's own local timezone**, not UTC and not yours. A latch with
          **no** windows is available to guests at any hour; the first window
          you add is what starts restricting it.
        - ``.directory_viewing_enabled`` — read-only context: whether the
          GuestView *directory listing* is on. That is a separate feature;
          guest entry does not require it.

        Quota-exempt, so a config refresh costs nothing monthly (the per-minute
        limit still applies)."""
        return await self._c._request(endpoints.guest_view_entry())

    async def set_guest_view_entry_enabled(self, allowed: bool) -> GuestViewEntry:
        """Permit or forbid GuestView Entry for the community.

        An explicit setter, deliberately **not a toggle**: this endpoint is
        retryable, and a retried toggle would flip a gate's guest access back
        open. Sending the value it already has is a successful no-op.

        Turning it off leaves the eligible-latch set and the schedule intact,
        so turning it back on restores the same configuration — it is the safe
        way to suspend guest access without losing the setup. Returns the full
        updated settings, so no follow-up read is needed. Test-mode keys
        validate and report but change nothing."""
        return await self._c._request(
            endpoints.set_guest_view_entry_enabled(allowed))

    async def set_guest_view_entry_latches(self, latch_ids: Sequence[str],
                                     ) -> GuestViewEntry:
        """Set which gates a GuestView visitor may open.

        **This REPLACES the whole set** — that is why the API makes it a PUT.
        Send the complete list every time: any currently-eligible latch you
        leave out loses guest eligibility, **and its schedule windows are
        deleted along with it** (an ineligible latch never opens, so its
        windows would be dead rows). Sending ``[]`` removes GuestView Entry
        from every gate.

        **Read-modify-write, always.** Call :meth:`guest_view_entry` first and
        send back a modified copy of its ``.latch_ids`` rather than composing a
        list from memory::

            entry = client.community.guest_view_entry()
            client.community.set_guest_view_entry_latches(
                entry.latch_ids + [new_latch_id])

        A caller who adds one gate by sending a one-element list silently
        destroys every other gate's schedule, and nothing in the response says
        so beyond the shorter set it returns.

        Every id must belong to this key's community; a foreign latch is a 404
        and **nothing is written**. Requires GuestView Entry to be switched on
        (403 ``guest_view_entry_disabled`` otherwise). Returns the full updated
        settings. Test-mode keys validate and report but change nothing."""
        return await self._c._request(
            endpoints.set_guest_view_entry_latches(latch_ids))

    async def guest_view_entry_logs(self, *, limit: int = 50, offset: int = 0,
                              success: Optional[bool] = None,
                              ) -> GuestViewEntryLogPage:
        """Every GuestView Entry attempt on this community, newest first.

        **These rows identify visitors**: name, phone number and client IP of
        the person who stood at the gate, alongside the result (``opened``, or
        a failure reason such as ``outside_schedule``, ``latch_not_eligible``,
        ``rate_limited``, ``scan_required``). Handle and retain accordingly.

        ``success=True`` narrows to opens, ``False`` to failed attempts, and
        omitting it returns everything. ``limit`` is clamped server-side to
        1-200 (default 50) and ``offset`` floors at 0; ``.has_more`` is true
        when the page came back full.

        Readable whether or not GuestView Entry is currently switched on, so
        history survives the feature being turned off. Quota-exempt (the
        per-minute limit still applies)."""
        return await self._c._request(
            endpoints.guest_view_entry_logs(limit, offset, success))

    async def add_guest_view_entry_schedule(self, latch_ids: Sequence[str],
                                      days_of_the_week: str, *,
                                      start_time: Optional[str] = None,
                                      end_time: Optional[str] = None,
                                      ) -> GuestViewEntry:
        """Add one recurring window during which GuestView Entry is permitted,
        applied to each latch in ``latch_ids``.

        **Timezone: the window is evaluated in each LATCH's own local
        timezone**, at the moment a visitor taps open — never UTC, never the
        caller's, never the community's. ``09:00``-``17:00`` on a latch in Los
        Angeles means 9-to-5 Pacific, and the same window applied to a latch in
        New York means 9-to-5 Eastern. This is the rule hold-open windows and
        quiet hours follow too. A latch whose timezone cannot be resolved skips
        the window check and stays available around the clock.

        **The midnight rule here matches quiet hours, not key schedules.** This
        API spells ``'HH:MM'`` three ways and only two of them wrap:

        ==========================  ==================  ================
        surface                     wraps past midnight ``"24:00"``
        ==========================  ==================  ================
        key schedules               no — send two       n/a
        recurring hold opens        no — send two       accepted
        quiet hours                 yes — one           rejected
        **GuestView Entry (here)**  **yes — one**       **rejected**
        ==========================  ==================  ================

        So an ``end_time`` earlier than ``start_time`` wraps as **one** window
        — ``22:00``-``06:00`` is a single overnight window, not two — and the
        days name the day the window **starts** on. Times are ``'HH:MM'``
        24-hour strings between ``00:00`` and ``23:59``; ``"24:00"`` is
        refused, and ``end_time=None`` leaves the window unbounded at the end.

        ``days_of_the_week`` is a string of ``MTWHFSU`` letters — **H is
        tHursday and U is sUnday** — with no repeats and at least one day.

        **Adding the first window to a latch restricts it.** A latch with no
        windows is guest-accessible at any hour; the schedule is a whitelist of
        permitted times, so the first window you add is what starts closing the
        gate outside it. Additive: each call appends, so replace a schedule by
        removing the windows you no longer want.

        A latch outside this community is a 404 and nothing is written.
        ``.created_schedule_ids`` on the result holds one id per latch. Returns
        the full updated settings. Test-mode keys validate and report but
        change nothing."""
        return await self._c._request(endpoints.add_guest_view_entry_schedule(
            latch_ids, days_of_the_week, start_time=start_time,
            end_time=end_time))

    async def remove_guest_view_entry_schedule(self, schedule_id: Union[int, str],
                                         ) -> GuestViewEntry:
        """Delete one GuestView Entry window, by the ``schedule_id`` from
        :meth:`guest_view_entry`.

        **Removing a window widens access**, and removing a latch's *last*
        window makes that gate available to guests **at any hour** — the
        schedule is a whitelist of permitted times, not a blacklist. Treat this
        like any other permission-widening write.

        **Timezone reminder:** the windows you are choosing between are
        evaluated in each latch's own local timezone, so read the settings
        first and delete by id rather than reasoning about times in your own
        zone.

        An id belonging to another community is a 404 and nothing is deleted.
        Returns the full updated settings, with the id echoed on
        ``.removed_schedule_id``. Test-mode keys validate and report but change
        nothing."""
        return await self._c._request(
            endpoints.remove_guest_view_entry_schedule(schedule_id))

    # -- GuestView short codes ------------------------------------------------ #

    async def short_codes(self) -> List[ShortCode]:
        """Every GuestView short code assigned to this community.

        A short code is what a visitor types (or reaches via the QR on the
        placard) to open the community's guest directory and call a resident.
        Each entry carries the ``.latch_id`` it routes to plus the gate's
        ``.latch_name``, so signage can be rendered or verified without a
        second lookup. ``.latch_id`` is None for a code that routes to the
        directory without preselecting a gate.

        Codes belonging to other communities are never listed here."""
        return await self._c._request(endpoints.short_codes())

    async def create_short_code(self, *, code: Optional[str] = None,
                          latch_id: Optional[str] = None) -> ShortCode:
        """Mint a GuestView short code — the code a gate placard or sign will
        display.

        Omit ``code`` and the server generates one (7 letters and digits), the
        same way the portal does. Supply ``code`` to claim a specific one: it
        must be 6-10 letters and digits, and **short codes are unique across
        all of Nimbio, not just your community** — a code already in use
        anywhere raises :class:`ConflictError` (409 ``short_code_taken``),
        including a code that differs only in letter case, since a placard is
        read by a person. Generation retries on collision, so the
        server-generated path effectively never 409s.

        ``latch_id`` is optional and must be a gate in this community; without
        it the code routes to the directory without preselecting a gate.

        **There is no way to delete a short code** — not through this API, and
        not through the portal. A code you mint is permanent, so treat a
        generated code as something you will live with. Test keys validate and
        mint nothing."""
        return await self._c._request(endpoints.create_short_code(code, latch_id))

    async def assign_short_code(self, code: str, latch_id: str) -> ShortCode:
        """Repoint an existing short code at a different gate — move a printed
        placard's code from one latch to another without reprinting the sign.

        **Assignment is exclusive, so this silently detaches the gate the code
        pointed at before.** A short code routes to exactly one gate; nothing
        warns you that the old gate just lost its code, and the change takes
        effect for the next visitor who types it. Read :meth:`short_codes`
        first if you need to know what you are about to detach.

        The code must already belong to this community. An unknown code and a
        code owned by a different community both answer 404
        ``short_code_not_found`` — the namespace is global, so the API
        deliberately gives no way to tell those two apart, let alone to seize
        someone else's code. Claiming an unassigned code minted by a Nimbio
        admin (a pre-printed placard from a batch) is likewise not available
        here; that stays a portal operation.

        Test mode validates against this community and changes nothing."""
        return await self._c._request(endpoints.assign_short_code(code, latch_id))

    # -- NFC tags ------------------------------------------------------------ #

    async def nfc_tags(self, *, search: Optional[str] = None, page: int = 1,
                 results_per_page: int = 50) -> NfcTagPage:
        """Every NFC tag issued to this community, newest first.

        ``search`` matches a tag's serial, its physical UID, or its notes.
        ``page`` is 1-based (floored at 1) and ``results_per_page`` is clamped
        to 1-200; both are echoed back alongside ``.total`` so you can page
        without guessing.

        ``.tag_uid_hex`` is the fob's **physical, publicly readable UID — not a
        secret**, and the join key to :meth:`nfc_scan_log`. No cryptographic
        tag material is ever returned by this API; programming a blank fob is a
        separate operator-side job with a card reader."""
        return await self._c._request(
            endpoints.nfc_tags(search, page, results_per_page))

    async def nfc_tag(self, tag_id: Union[int, str]) -> NfcTag:
        """One tag of this community.

        A tag belonging to another community answers 404 ``tag_not_found``,
        exactly as an unknown id does — the API never confirms that someone
        else's tag exists."""
        return await self._c._request(endpoints.nfc_tag(tag_id))

    async def update_nfc_tag(self, tag_id: Union[int, str], *,
                       disabled: Optional[bool] = None,
                       latch_id: Any = UNSET,
                       confirm: Optional[bool] = None) -> NfcTag:
        """Assign, unassign, or disable one NFC tag — the one write this
        surface has. Send ``disabled``, ``latch_id``, or both; neither is 422
        ``empty_patch``.

        - ``disabled=True`` kills a lost fob, and **it takes effect for
          physical gate taps**: the next tap on any gate is refused.
          ``disabled=False`` revives it. This is an **explicit setter, never a
          toggle**, so revoking a stolen fob never depends on state you read a
          moment ago — and re-sending it is a no-op.
        - ``latch_id="<gate id>"`` binds the tag to one of your gates (a tag
          opens the gate it is bound to, not a member's key).
          ``latch_id=None`` detaches it; the tag stays in the community and can
          be re-assigned later. **Omitting the argument leaves the binding
          alone** — that is the difference the ``UNSET`` default carries.
        - **Order matters when both are sent:** ``disabled`` is applied first,
          so ``disabled=False, latch_id=...`` revives and then binds in one
          call, while ``disabled=True, latch_id=...`` is refused 422
          ``conflicting_fields`` — a dead fob cannot be routed to a gate.

        **A write that would leave a Scan Only gate with no working tag raises**
        :class:`ConflictError` **(409 ``requires_confirmation``) — a warning,
        not a veto.** Catch it and repeat the call with ``confirm=True``; that
        is the intended flow, and it is deliberately not a hard refusal because
        revoking a stolen fob has to stay possible::

            try:
                await client.community.update_nfc_tag(tag_id, disabled=True)
            except ConflictError as e:
                if e.code != "requires_confirmation":
                    raise
                # e.message says which gate is about to be left tagless.
                await client.community.update_nfc_tag(tag_id, disabled=True,
                                                      confirm=True)

        ``notes`` is reported by the reads but cannot be set here. Unknown tags
        and other communities' tags are both 404 ``tag_not_found``."""
        return await self._c._request(
            endpoints.update_nfc_tag(tag_id, disabled, latch_id, confirm))

    async def nfc_scan_log(self, *, limit: int = 50, offset: int = 0,
                     result: Optional[str] = None,
                     tag_uid_hex: Optional[str] = None) -> NfcScanLogPage:
        """Every NFC tap recorded for this community, newest first.

        Filter to one physical tag with ``tag_uid_hex`` (the UID from
        :meth:`nfc_tags`) or to one verdict with ``result``. ``limit`` is
        clamped to 1-200 and ``offset`` floored at 0.

        **Rows can name a person**: the tapping member's first and last name
        are present where the tap resolved to one, which is what lets a
        security review attribute a tap. The device's IP address and
        Nimbio-internal record ids are not exposed."""
        return await self._c._request(
            endpoints.nfc_scan_log(limit, offset, result, tag_uid_hex))

    # -- sense lines --------------------------------------------------------- #

    async def sense_lines(self, *, box_id: Optional[str] = None) -> SenseLines:
        """Every sense line on this community's boxes — the endpoint that
        answers "why does this gate always report closed?".

        A sense line is a physical input on a Nimbio box reporting whether a
        gate actually moved: the feedback loop behind :meth:`gate_status`, the
        gate-status-change log, and the ``sense_line.changed`` event. Each one
        carries two flags and a derived answer:

        - ``sense_line_online`` — whether the input is switched on at all. Off
          means raw transitions are **still recorded** (see
          :meth:`sense_line_records`) but the server acts on none of them.
        - ``latch_data_online`` — whether its readings may drive the gate
          status reported to the apps and to this API.
        - ``reporting`` — true only when both are on, which is exactly the
          condition for a transition to update gate status or fire
          ``sense_line.changed``. **A gate stuck on one status whose input has
          ``reporting`` false is a configuration problem, not a stuck gate** —
          ``.not_reporting`` lists those inputs directly.

        ``box_id`` is an optional filter here; omit it for every box in the
        community. Does not consume the monthly quota."""
        return await self._c._request(endpoints.sense_lines(box_id))

    async def sense_line(self, sense_line_id: int, box_id: str) -> SenseLine:
        """One sense line, with everything needed to explain a gate's status.

        **``box_id`` is required**, and positional for that reason: a sense
        line id is an *input number on a board*, unique only within its box, so
        two boxes in one community both have a "sense line 1". Omitting it is a
        422 ``box_id_required`` rather than a guess at which box you meant.

        Beyond the two flags (see :meth:`sense_lines`) this returns:

        - ``.status_map`` — the configured meaning of each raw state on this
          input: which latch it describes, the label the apps show, and
          ``transient_ms`` (non-zero = the label shows briefly then reverts).
          Set when the hardware is installed and **read-only** here.
        - ``.last_record`` — the most recent transition the box actually
          reported. **Weeks old on a gate that moves daily points at the wiring
          or the box, not at the configuration.**

        Does not consume the monthly quota."""
        return await self._c._request(endpoints.sense_line(sense_line_id, box_id))

    async def update_sense_line(self, sense_line_id: int, box_id: str, *,
                          sense_line_online: Optional[bool] = None,
                          latch_data_online: Optional[bool] = None) -> SenseLine:
        """Switch a sense line's two configuration flags on or off.

        **``box_id`` is required** for the same reason as on
        :meth:`sense_line`: the id alone does not identify an input.

        Send only the flags you want to change — an omitted flag is left
        exactly as it was, and each value is an **explicit set, never a
        toggle**, so re-sending the same call is a no-op. Omitting both is 422
        ``no_fields``.

        **This changes what a real gate reports.** Turning either flag off
        freezes that gate's status at its last known value for every app, for
        :meth:`gate_status`, and for the ``sense_line.changed`` event, and it
        affects hold-open logic that reads gate state. Turning a miswired input
        off is a legitimate repair; doing it by accident is not.

        This writes **configuration only**. The state-to-label wiring
        (``status_map``), the creation of sense lines, and the observed gate
        state itself are not writable here — observed state is what the
        hardware reports, and deliberately not something an API key can
        fabricate. Returns the sense line as it now stands; test-mode keys
        validate and change nothing."""
        return await self._c._request(
            endpoints.update_sense_line(sense_line_id, box_id,
                                        sense_line_online, latch_data_online))

    async def sense_line_records(self, *, box_id: Optional[str] = None,
                           sense_line_id: Optional[int] = None,
                           limit: int = 50,
                           offset: int = 0) -> SenseLineRecordPage:
        """What the boxes actually reported, newest first — the **raw**
        transitions read off the physical inputs, not the derived gate status.

        Two properties make this the endpoint to reach for when a gate
        misreports:

        - **Rows are written even when a sense line is switched off**, so a
          healthy stream here alongside a stale :meth:`gate_status` proves the
          wiring is fine and the configuration is not.
        - ``status`` is the configured label for that ``(sense_line_id,
          state)`` pair, or **None when the state has no configured meaning** —
          an unmapped state is itself a finding, so these rows are returned
          rather than dropped (``.unmapped`` collects them).

        ``box_id`` and ``sense_line_id`` are optional filters here — unlike on
        :meth:`sense_line`, nothing is being addressed, so a bare
        ``sense_line_id`` spans every box that has that input number. ``limit``
        is clamped to 1-200 and ``offset`` floored at 0.

        For the human-readable, latch-oriented version of the same history, see
        :meth:`gate_status_log`. Does not consume the monthly quota."""
        return await self._c._request(
            endpoints.sense_line_records(box_id, sense_line_id, limit, offset))

    # -- map and geofences --------------------------------------------------- #

    async def map(self) -> CommunityMap:
        """Where this community's gates are, and the geofence each advertises.

        Returns the community centre, one entry per Nimbio device with its own
        location, and every gate on that device with its geofence config.
        Coordinates are **WGS84 decimal degrees**; ``radius_meters`` is
        **metres**. ``.min_radius_meters`` is the floor a write must respect
        and ``.geofence_modes`` the legal set for ``mode`` — read them from here
        rather than hardcoding.

        A gate whose ``geofence.center`` is None has never had a fence
        configured; use its ``.box_location`` as the suggested centre
        (``.suggested_center`` does this for you, and ``.unconfigured`` lists
        those gates).

        **Gate coordinates are physical-security information: this response
        says exactly where a property's entrances are.** It is scoped to your
        community key; treating it as sensitive downstream is on you.

        **This read consumes monthly quota**, unlike :meth:`gate_status` — a
        map is setup-time configuration that changes when a human moves a pin,
        not a poll substitute."""
        return await self._c._request(endpoints.map())

    async def update_geofence(self, latch_id: str, *, enabled: Optional[bool] = None,
                        latitude: Optional[float] = None,
                        longitude: Optional[float] = None,
                        radius_meters: Optional[int] = None,
                        mode: Optional[str] = None) -> MapLatch:
        """Change one gate's proximity geofence.

        **Partial update** — only the fields you send change, which is why it
        is a PATCH. ``latitude`` and ``longitude`` move together: send both or
        neither. They are WGS84 decimal degrees, and out-of-range values are
        rejected rather than stored. There is deliberately **no way to clear a
        configured centre** through this surface: a silent clear would disable
        proximity behaviour on a real gate with nothing to show for it.

        **``radius_meters`` below ``min_radius_meters`` (100) is rejected with
        422 ``radius_below_minimum`` — NOT silently raised.** Android's Geofence
        API and iOS region monitoring both degrade below roughly 100 m, so a
        smaller fence would read as configured and never fire. Do not "fix"
        this by clamping client-side; the response always echoes the effective
        ``radius_meters`` so you can confirm what is in force.

        Enabling a fence requires a centre — the gate's own, or its device's
        location as a fallback (:attr:`~models.MapLatch.suggested_center`).
        ``mode`` is ``prompt`` (notify on arrival, the member taps to open) or
        ``auto_open``; see
        :data:`~nimbio_community_api.constants.GEOFENCE_MODES`.

        A body with nothing to change is 400 ``nothing_to_update``. Test-mode
        keys validate and write nothing."""
        return await self._c._request(
            endpoints.update_geofence(latch_id, enabled, latitude, longitude,
                                      radius_meters, mode))

    # -- audit trails -------------------------------------------------------- #

    async def change_logs(self, log_type: str, *, days: int = 30, limit: int = 500,
                    offset: int = 0) -> ChangeLogPage:
        """The community's **configuration** audit trail — who changed what,
        when.

        This is the *change* log. For the *access* trail (who opened which
        gate) use :meth:`access_log`; for physical open/closed transitions use
        :meth:`gate_status_log`. The two are easy to confuse: an access log
        tells you a gate opened, this tells you someone rewrote the schedule
        that let it open.

        ``log_type`` is required and selects exactly one of four trails — see
        :data:`~nimbio_community_api.constants.CHANGE_LOG_TYPES`:
        ``hold_open`` (manual on/off, one-time events, recurring schedules,
        disable-until dates), ``key_schedule``, ``guest_view`` (GuestView and
        Directory settings, short codes, directory access codes, GuestView
        Entry windows) or ``guest_link``.

        ``days`` is a look-back window; **values above the 30-day retention cap
        are clamped, not rejected**, so read ``.days``/``.date_from``/
        ``.date_to`` for the window actually used. Every row carries the same
        envelope — ``.log_type``, ``.log_id``, ``.action_type``, ``.datetime``,
        who did it, a rendered ``.summary`` and a per-action ``.details``."""
        return await self._c._request(
            endpoints.change_logs(log_type, days, limit, offset))

    async def key_usage(self, date_from: str, date_to: str, *,
                  page: int = 0) -> KeyUsageReport:
        """Per-key usage history over a date window — the same report a
        Community Manager sees on the portal's Access Logs page.

        ``date_from`` and ``date_to`` are inclusive ``'YYYY-MM-DD'`` dates **in
        the community's local timezone**, not yours; the timezone used comes
        back on ``.timezone``. A window longer than ``.max_range_days`` is
        clamped rather than rejected — ``.clamped`` says so, and
        ``.date_from``/``.date_to`` report what was actually read against
        ``.requested_from``/``.requested_to``.

        **Read ``.report_type`` before reading any row's ``user``.** Nimbio
        attributes an open differently by property type and *the server decides
        which rule applies* — there is no parameter for it, because getting it
        wrong would misreport who opened a gate:

        - ``"commercial"`` — ``user`` is the **actual opener's** name.
        - ``"residential"`` — ``user`` is ``"<master key owner> Keychain"``.
          Every open on a household's keys is attributed to the account holder,
          so you cannot tell which member of the household opened the gate.
          This groups; it does **not** anonymize — the account holder is named.

        Rows carry personal data beyond ``user``: ``phone`` and ``location``."""
        return await self._c._request(endpoints.key_usage(date_from, date_to, page))

    # -- webhooks ------------------------------------------------------------ #

    async def webhook_event_types(self) -> List[str]:
        return await self._c._request(endpoints.webhook_event_types())

    async def webhooks(self) -> List[Webhook]:
        return await self._c._request(endpoints.webhooks())

    async def create_webhook(self, url: str, events: Sequence[str], *,
                             description: Optional[str] = None
                             ) -> WebhookCreateResult:
        return await self._c._request(
            endpoints.create_webhook(url, events, description))

    async def update_webhook(self, webhook_id: str, *,
                             url: Optional[str] = None,
                             events: Optional[Sequence[str]] = None,
                             active: Optional[bool] = None,
                             description: Optional[str] = None
                             ) -> WebhookCreateResult:
        return await self._c._request(endpoints.update_webhook(
            webhook_id, url=url, events=events, active=active,
            description=description))

    async def delete_webhook(self, webhook_id: str) -> WriteResult:
        return await self._c._request(endpoints.delete_webhook(webhook_id))

    async def rotate_webhook_secret(self, webhook_id: str) -> WebhookSecret:
        return await self._c._request(
            endpoints.rotate_webhook_secret(webhook_id))

    async def test_webhook(self, webhook_id: str) -> WriteResult:
        return await self._c._request(endpoints.test_webhook(webhook_id))

    async def webhook_deliveries(self, webhook_id: str, *,
                                 limit: int = 50) -> List[WebhookDelivery]:
        """Delivery attempts for one webhook, newest first — what your receiver
        returned and when.

        This is how you tell a silently-broken endpoint from one Nimbio never
        fired at. ``.status`` is ``pending``, ``delivered`` or ``failed``;
        ``.attempts`` counts tries so far and ``.last_status_code`` /
        ``.last_error`` describe the most recent one. ``limit`` is 1-200.

        The event body Nimbio sent is not echoed back. ``last_error`` does
        carry the first part of *your own* endpoint's response on a non-2xx
        reply — which is what makes a broken receiver diagnosable, and worth
        knowing about if your error pages carry anything sensitive. Reads work
        for test and live keys alike."""
        return await self._c._request(
            endpoints.webhook_deliveries(webhook_id, limit))

    async def retry_failed_deliveries(self, webhook_id: str, *,
                                      since: Optional[str] = None,
                                      limit: int = 50) -> DeliveryReplayBatch:
        """Re-send every delivery for this webhook currently in the terminal
        ``failed`` state, oldest first — the "my receiver was down for an hour,
        send me what I missed" path.

        ``limit`` is 1-100 (default 50); ``since`` is an ISO-8601 instant that
        limits candidates to deliveries created at or after it.

        **The original event id and payload are preserved**, exactly as in
        :meth:`replay_delivery` — read that method's warning about handlers
        that do not de-duplicate on ``X-Nimbio-Delivery``.

        Deliveries still ``pending`` are skipped (``.skipped_in_flight``) so a
        retry can never race Nimbio's own backoff and double-fire, and
        candidates are de-duplicated by event id
        (``.skipped_duplicate_event``) — so calling this twice in a row
        re-sends nothing the second time. Read ``.replayed_count`` for what was
        actually enqueued, which is not what you asked for.

        Raises :class:`ConflictError` (409 ``webhook_disabled``) if the webhook
        is inactive or auto-disabled: re-enable it with
        ``update_webhook(webhook_id, active=True)`` first, or the re-sends
        would be discarded unsent. **Test-mode keys enqueue nothing** and
        return ``result: "simulated"``."""
        return await self._c._request(
            endpoints.retry_failed_deliveries(webhook_id, since, limit))

    async def replay_delivery(self, webhook_id: str,
                              delivery_id: str) -> DeliveryReplay:
        """Re-send one past delivery — the event you can see failed in
        :meth:`webhook_deliveries`, once your receiver is fixed. Works for a
        ``failed`` delivery and for a ``delivered`` one you no longer have.

        **The original event id and payload are re-sent byte for byte.** Nimbio
        stores the exact envelope it POSTed, and the ``X-Nimbio-Delivery``
        header carries the **event** id, not the delivery id. A consumer that
        de-duplicates on that header handles a replay correctly; **one that
        ignores it applies the event twice** — a second charge, a second gate
        open. The new ``.delivery_id`` is the only thing that differs, so the
        replay shows up in the delivery list beside the original, which keeps
        its failure record.

        The replay is signed with the webhook's **current** secret and a fresh
        ``X-Nimbio-Timestamp``, so a delivery replayed after a secret rotation
        fails a receiver still validating against the old secret.

        Raises :class:`ConflictError` (409) as ``delivery_in_flight`` when
        Nimbio is still retrying that event itself — replaying would
        double-fire — or ``webhook_disabled`` when the webhook is inactive;
        re-enable it with ``update_webhook(webhook_id, active=True)``. Unknown
        ids and ids belonging to another community are indistinguishable 404s.
        **Test-mode keys enqueue nothing** and return ``result:
        "simulated"``."""
        return await self._c._request(
            endpoints.replay_delivery(webhook_id, delivery_id))

    # -- live events --------------------------------------------------------- #

    def stream_events(self, *, events: Optional[Sequence[str]] = None,
                      last_event_id: Optional[str] = None,
                      reconnect: bool = True,
                      ) -> AsyncIterator[Union[StreamEvent, StreamReset]]:
        """Async-iterate the community's live events over SSE. Semantics match
        :meth:`NimbioClient.community.stream_events` — StreamEvent per event,
        StreamReset when a reconnect gap can't be replayed (re-seed via the
        status reads), automatic reconnect with backoff, HTTP errors raise."""
        return self._c._stream(_sse.STREAM_PATH, events, last_event_id,
                               reconnect)

    # -- logs --------------------------------------------------------------- #

    async def member_access_logs(self, account_community_id: int, *,
                                 window: str = "last_30") -> MemberAccessLogPage:
        return await self._c._request(
            endpoints.member_access_logs(account_community_id, window))

    async def access_log(self, *, page: int = 0) -> AccessLogPage:
        return await self._c._request(endpoints.access_log(page))

    async def gate_status_log(self, *, page: int = 0) -> GateStatusLogPage:
        return await self._c._request(endpoints.gate_status_log(page))

    # -- pagination helpers ------------------------------------------------- #

    async def iter_access_log(self, *,
                              start_page: int = 0) -> AsyncIterator[AccessLogEntry]:
        page = start_page
        while True:
            result = await self.access_log(page=page)
            for row in result.logs:
                yield row
            if not result.has_more:
                return
            page += 1

    async def iter_gate_status_log(
        self, *, start_page: int = 0
    ) -> AsyncIterator[GateStatusLogEntry]:
        page = start_page
        while True:
            result = await self.gate_status_log(page=page)
            for row in result.logs:
                yield row
            if not result.has_more:
                return
            page += 1
