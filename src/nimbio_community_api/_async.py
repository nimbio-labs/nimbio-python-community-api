"""Asynchronous client — for asyncio programs (FastAPI, aiohttp, bots, ...)."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List, Optional, Sequence, Union

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
    """

    def __init__(self, api_key: Optional[str] = None, *,
                 environment: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: Optional[float] = None,
                 max_retries: int = 2,
                 default_headers: Optional[dict] = None,
                 http_client: Optional[httpx.AsyncClient] = None) -> None:
        super().__init__(
            api_key, environment=environment, base_url=base_url,
            timeout=30.0 if timeout is None else timeout,
            max_retries=max_retries, default_headers=default_headers,
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

            payload = self._decode(resp.status_code, resp.content, resp.headers)
            data = self._parse(resp.status_code, payload, resp.headers)
            return parser(data) if parser else data

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


class _AsyncCommunity:
    """``client.community.*`` — community-scoped operations (async)."""

    def __init__(self, client: AsyncNimbioClient) -> None:
        self._c = client

    # -- reads -------------------------------------------------------------- #

    async def gate_status(self) -> GateStatus:
        return await self._c._request(endpoints.gate_status())

    async def members(self) -> Members:
        return await self._c._request(endpoints.members())

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

    # -- key access schedules ------------------------------------------------ #

    async def key_schedules(self) -> KeySchedules:
        """Access schedules for the community's keys.

        Returns the community's own key(s) plus every member key that currently
        **has** a schedule. Unrestricted member keys are omitted — a community
        can hold tens of thousands of them — so use :meth:`key_schedule` to read
        one by id.

        ``.blocked`` lists keys denied at all times because a saved schedule is
        switched off. Does not consume the monthly quota."""
        return await self._c._request(endpoints.key_schedules())

    async def key_schedule(self, key_id: str) -> KeySchedule:
        """One key's access schedule. Does not consume the monthly quota."""
        return await self._c._request(endpoints.key_schedule(key_id))

    async def set_key_schedule(self, key_id: str, windows) -> KeySchedule:
        """Replace a key's access schedule.

        ``windows`` is the COMPLETE schedule -- pass ``[]`` to remove every
        restriction. Accepts :class:`ScheduleWindow` objects or plain dicts of
        ``{days_of_the_week, start_time, end_time}``.

        Days are letters from ``MTWHFSU`` (**H is Thursday**, U is Sunday).
        Times are ``'HH:MM'`` in each gate's local time and cannot run past
        midnight -- send two windows for overnight access.

        A schedule on the community key applies to every member key beneath it;
        check ``descendant_key_count`` first. Test keys simulate."""
        return await self._c._request(endpoints.set_key_schedule(key_id, windows))

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

    # -- live events --------------------------------------------------------- #

    async def stream_events(self, *, events: Optional[Sequence[str]] = None,
                            last_event_id: Optional[str] = None,
                            reconnect: bool = True,
                            ) -> AsyncIterator[Union[StreamEvent, StreamReset]]:
        """Async-iterate the community's live events over SSE. Semantics match
        :meth:`NimbioClient.community.stream_events` — StreamEvent per event,
        StreamReset when a reconnect gap can't be replayed (re-seed via the
        status reads), automatic reconnect with backoff, HTTP errors raise."""
        c = self._c
        cursor = last_event_id
        attempt = 0
        while True:
            prepared = c._prepare("GET", _sse.STREAM_PATH,
                                  params=_sse.stream_params(events, cursor))
            timeout = httpx.Timeout(c.timeout or 30.0,
                                    read=_sse.STREAM_READ_TIMEOUT)
            try:
                async with c._http.stream(prepared.method, prepared.url,
                                          headers=prepared.headers,
                                          params=prepared.params,
                                          timeout=timeout) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        payload = c._decode(resp.status_code, resp.content,
                                            resp.headers)
                        c._parse(resp.status_code, payload, resp.headers)
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
