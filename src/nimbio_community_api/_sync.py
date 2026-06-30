"""Synchronous client — works in any plain (non-async) Python program."""

from __future__ import annotations

import time
from typing import Any, Iterator, List, Optional, Sequence

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
