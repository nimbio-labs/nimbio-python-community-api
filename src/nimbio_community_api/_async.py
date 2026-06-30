"""Asynchronous client — for asyncio programs (FastAPI, aiohttp, bots, ...)."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List, Optional, Sequence

import httpx

from . import _exceptions as exc
from ._base import BaseClient, endpoints
from .models import (
    AccessLogEntry,
    AccessLogPage,
    CommunityKey,
    GateStatus,
    GateStatusLogEntry,
    GateStatusLogPage,
    Health,
    KeyStatuses,
    Me,
    MemberAccessLogPage,
    Members,
    OpenResult,
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
