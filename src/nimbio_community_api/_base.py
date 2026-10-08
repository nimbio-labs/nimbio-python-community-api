"""Shared, transport-agnostic core for the sync and async clients.

This module owns everything that does *not* depend on whether I/O is blocking or
not: configuration resolution, header construction, URL building, response
decoding, error mapping, and the retry policy. The sync and async clients each
implement only the small send-loop that actually performs the HTTP round trip.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from . import _exceptions as exc
from ._cache import DEFAULT_CACHE_SIZE, CacheStats, ETagCache, cache_key
from ._environments import resolve_base_url
from ._version import __version__

# A modest default so a hung backend doesn't hang the caller forever. The
# community open is synchronous on the server and can legitimately take ~15-18s,
# so the default read timeout is comfortably above that.
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE = 0.5  # seconds; doubles each retry

ENV_API_KEY = "NIMBIO_API_KEY"
ENV_ENVIRONMENT = "NIMBIO_ENV"
ENV_BASE_URL = "NIMBIO_BASE_URL"

USER_AGENT = f"nimbio-community-api-python/{__version__}"
INTEGRATION_HEADER = "X-Nimbio-Integration"
# "<slug>/<version>", e.g. "home_assistant/0.4.1". The slug is the open-surface
# format from nimbioCore/shared-contracts/open-surfaces.md; the version is one
# User-Agent product-version token, so the value can be appended to the UA.
_INTEGRATION_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}/[A-Za-z0-9._+-]+$")
_INTEGRATION_MAX_LEN = 80


def _validate_integration(integration: Optional[str]) -> Optional[str]:
    """Return ``integration`` unchanged, or raise ``ValueError`` if malformed.

    A malformed value is a developer error, so it fails at construction rather
    than being sent and silently ignored by the server.
    """
    if integration is None:
        return None
    if (not isinstance(integration, str)
            or len(integration) > _INTEGRATION_MAX_LEN
            or not _INTEGRATION_RE.fullmatch(integration)):
        raise ValueError(
            f"integration must look like '<slug>/<version>' (slug "
            f"[a-z][a-z0-9_]{{1,31}}, at most {_INTEGRATION_MAX_LEN} "
            f"characters), e.g. 'home_assistant/0.4.1'; got {integration!r}"
        )
    return integration


class _Unset:
    """Sentinel for a PATCH field whose ``None`` is itself a meaningful value.

    ``update_nfc_tag(latch_id=None)`` detaches a tag from its gate, so "leave
    it alone" cannot also be spelled ``None``. Callers never pass this — it is
    only the default that means *omit the field*.
    """

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


@dataclass
class PreparedRequest:
    method: str
    url: str
    headers: dict
    params: Optional[dict]
    json: Optional[dict]


class BaseClient:
    """Configuration + request/response plumbing shared by both clients."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        environment: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Optional[Mapping[str, str]] = None,
        cache: bool = True,
        cache_size: int = DEFAULT_CACHE_SIZE,
        integration: Optional[str] = None,
    ) -> None:
        self._integration = _validate_integration(integration)
        api_key = api_key or os.environ.get(ENV_API_KEY)
        if not api_key:
            raise exc.NimbioConfigError(
                "No API key provided. Pass api_key=... or set the "
                f"{ENV_API_KEY} environment variable. Keys look like "
                "'nimbio_test_...' or 'nimbio_live_...'."
            )
        self._api_key = api_key

        environment = environment or os.environ.get(ENV_ENVIRONMENT)
        base_url = base_url or os.environ.get(ENV_BASE_URL)
        try:
            self.base_url = resolve_base_url(environment, base_url)
        except ValueError as e:
            raise exc.NimbioConfigError(str(e)) from None

        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self._default_headers = dict(default_headers or {})

        # One cache per client, and a client holds exactly one API key for its
        # whole life — which is how the API's `Vary: Authorization` is honoured
        # here: there is no path by which one key's stored body is reachable
        # under another key.
        self._cache: Optional[ETagCache] = (
            ETagCache(cache_size) if cache else None
        )

    # -- public, read-only introspection ------------------------------------ #

    @property
    def mode(self) -> Optional[str]:
        """``"test"``, ``"live"``, or ``None`` if the key prefix is unrecognized.

        Derived purely from the key string — no network call. Lets you guard
        destructive calls, e.g. ``assert client.mode == "test"`` in a script.
        """
        if self._api_key.startswith("nimbio_test_"):
            return "test"
        if self._api_key.startswith("nimbio_live_"):
            return "live"
        return None

    def cache_stats(self) -> CacheStats:
        """Hits, misses and stored entries for this client's ETag cache.

        A *hit* is a read the server answered ``304 Not Modified`` — the body
        came from the cache and the monthly quota was refunded. This is the
        only way to confirm the saving is actually happening; a client polling
        an unchanging gate should show hits climbing and misses flat.

        Reports zeroes throughout when the client was built with
        ``cache=False``. The counters are cumulative for the client's life.
        """
        if self._cache is None:
            return CacheStats(hits=0, misses=0, entries=0)
        return self._cache.stats()

    def __repr__(self) -> str:
        # Deliberately never includes the API key, so it is safe to log.
        return (f"{type(self).__name__}(base_url={self.base_url!r}, "
                f"mode={self.mode!r})")

    # -- request preparation ------------------------------------------------ #

    def _identity_headers(self) -> dict:
        """User-Agent, plus the integration header when one is configured.

        Unset, this is exactly the pre-``integration`` User-Agent and nothing
        else, so older callers send byte-for-byte the same requests.
        """
        if self._integration is None:
            return {"User-Agent": USER_AGENT}
        return {
            "User-Agent": f"{USER_AGENT} {self._integration}",
            INTEGRATION_HEADER: self._integration,
        }

    def _headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            **self._identity_headers(),
        }
        headers.update(self._default_headers)
        return headers

    def _prepare(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
        auth: bool = True,
    ) -> PreparedRequest:
        headers = self._headers() if auth else {
            "Accept": "application/json",
            **self._identity_headers(),
        }
        if json is not None:
            headers["Content-Type"] = "application/json"
        # Drop params whose value is None so callers can pass them unconditionally.
        clean_params = (
            {k: v for k, v in params.items() if v is not None} if params else None
        )
        return PreparedRequest(
            method=method,
            url=f"{self.base_url}{path}",
            headers=headers,
            params=clean_params or None,
            json=json,
        )

    # -- conditional requests ----------------------------------------------- #
    #
    # Three small hooks the sync and async send-loops both call, so the caching
    # policy lives in one place and only the await differs between them.

    def _cache_begin(self, prepared: PreparedRequest,
                     path: str) -> Optional[str]:
        """Attach ``If-None-Match`` if we hold an ETag; return the cache key.

        ``None`` means this request is not cacheable (caching off, not a GET,
        or an excluded path) and the send-loop should ignore the cache
        entirely.
        """
        if self._cache is None:
            return None
        key = cache_key(prepared.method, path, prepared.params)
        if key is None:
            return None
        etag = self._cache.etag_for(key)
        if etag is not None:
            prepared.headers["If-None-Match"] = etag
        return key

    def _cache_hit(self, key: str,
                   headers: Mapping[str, str]) -> Optional[bytes]:
        """Record a 304 and return the stored body to re-decode, if any."""
        if self._cache is None:  # pragma: no cover - key implies a cache
            return None
        return self._cache.hit(key, headers.get("etag"))

    def _cache_miss(self, key: str, status_code: int,
                    headers: Mapping[str, str], body: bytes) -> None:
        """Record a non-304 response and store it if it carries an ETag."""
        if self._cache is None:  # pragma: no cover - key implies a cache
            return
        self._cache.record_miss()
        etag = headers.get("etag") if 200 <= status_code < 300 else None
        if etag and body:
            self._cache.store(key, etag, body)
        else:
            # Either the route stopped offering an ETag or this read failed.
            # Drop whatever we were holding rather than leave an entry that
            # will keep asking a question the server no longer answers.
            self._cache.discard(key)

    # -- response handling -------------------------------------------------- #

    @staticmethod
    def _decode(status_code: int, body_bytes: bytes,
                headers: Mapping[str, str]) -> Any:
        if not body_bytes:
            return None
        import json as _json
        try:
            return _json.loads(body_bytes)
        except ValueError:
            # Non-JSON body (e.g. an upstream proxy error page). Preserve text.
            return {"_raw_text": body_bytes.decode("utf-8", "replace")}

    def _parse(self, status_code: int, payload: Any,
               headers: Mapping[str, str]) -> Any:
        """Return the decoded JSON for 2xx, or raise the mapped APIError."""
        if 200 <= status_code < 300:
            return payload if payload is not None else {}

        code = None
        message = None
        request_id = None
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                code = err.get("code")
                message = err.get("message")
                request_id = err.get("request_id")
            else:
                message = payload.get("_raw_text") or payload.get("message")
        message = message or f"HTTP {status_code}"

        klass = exc.exception_for(status_code, code)
        kwargs: dict = dict(
            status_code=status_code, code=code,
            request_id=request_id, response=payload, headers=headers,
        )
        if klass is exc.RateLimitError:
            kwargs["retry_after"] = _parse_retry_after(headers.get("retry-after"))
        raise klass(message, **kwargs)

    # -- retry policy ------------------------------------------------------- #

    def _should_retry(self, status_code: int, attempt: int) -> bool:
        if attempt >= self.max_retries:
            return False
        return status_code == 429 or status_code in (500, 502, 503, 504)

    def _retry_delay(self, attempt: int,
                     headers: Optional[Mapping[str, str]]) -> float:
        if headers is not None:
            ra = _parse_retry_after(headers.get("retry-after"))
            if ra is not None:
                return ra
        return DEFAULT_BACKOFF_BASE * (2 ** attempt)


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Endpoint registry — single source of truth for the HTTP surface.
#
# Each builder returns (method, path, params, json, parser). Both the sync and
# async clients consume these so the wire contract lives in exactly one place;
# only the await differs between the two client implementations.
# --------------------------------------------------------------------------- #

from . import models as _m  # noqa: E402


def _enc(latch_or_member: Any) -> str:
    from urllib.parse import quote
    return quote(str(latch_or_member), safe="")


class endpoints:
    """Namespace of endpoint specs: (method, path, params, json, parser)."""

    @staticmethod
    def health() -> Tuple[str, str, Optional[dict], Optional[dict], Any]:
        return "GET", "/healthz", None, None, _m.Health.from_dict

    @staticmethod
    def me():
        return "GET", "/v1/me", None, None, _m.Me.from_dict

    @staticmethod
    def account_keys(include_hidden: bool = False):
        return ("GET", "/v1/account/keys",
                {"include_hidden": "true"} if include_hidden else None, None,
                lambda d: [_m.AccountKey.from_dict(k)
                           for k in ((d or {}).get("keys") or [])])

    @staticmethod
    def account_open(key_id: str, latch_id: str, note: Optional[str] = None,
                     idempotency_key: Optional[str] = None):
        body: dict = {}
        if note is not None:
            body["note"] = note
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        return ("POST",
                f"/v1/account/keys/{_enc(key_id)}/latches/{_enc(latch_id)}/open",
                None, body, _m.OpenResult.from_dict)

    @staticmethod
    def info():
        return "GET", "/v1/community", None, None, _m.CommunityInfo.from_dict

    @staticmethod
    def gate_status():
        return ("GET", "/v1/community/gate-status", None, None,
                _m.GateStatus.from_dict)

    @staticmethod
    def members():
        return "GET", "/v1/community/members", None, None, _m.Members.from_dict

    @staticmethod
    def members_page(bucket: str = "accepted", page: int = 1, size: int = 100,
                     search: Optional[str] = None):
        return ("GET", "/v1/community/members/page",
                {"bucket": bucket, "page": page, "size": size, "search": search},
                None, _m.MembersPage.from_dict)

    @staticmethod
    def member(account_community_id: int):
        return ("GET",
                f"/v1/community/members/{_enc(account_community_id)}",
                None, None, _m.Member.from_dict)

    @staticmethod
    def messages(limit: int = 50, offset: int = 0):
        return ("GET", "/v1/community/messages",
                {"limit": limit, "offset": offset}, None,
                _m.MessagesPage.from_dict)

    @staticmethod
    def update_key(key_id: str, name: Optional[str] = None,
                   disabled: Optional[bool] = None):
        body: dict = {}
        if name is not None:
            body["name"] = name
        if disabled is not None:
            body["disabled"] = disabled
        return ("PATCH", f"/v1/community/keys/{_enc(key_id)}", None, body,
                _m.KeyUpdateResult.from_dict)

    @staticmethod
    def key_statuses():
        return ("GET", "/v1/community/key-statuses", None, None,
                _m.KeyStatuses.from_dict)

    @staticmethod
    def keys():
        return ("GET", "/v1/community/keys", None, None,
                lambda d: [_m.CommunityKey.from_dict(k)
                           for k in (d.get("keys") or [])])

    @staticmethod
    def open(latch_id: str, note: Optional[str] = None,
             idempotency_key: Optional[str] = None):
        body: dict = {}
        if note is not None:
            body["note"] = note
        if idempotency_key is not None:
            body["idempotency_key"] = idempotency_key
        return ("POST", f"/v1/community/latches/{_enc(latch_id)}/open",
                None, body, _m.OpenResult.from_dict)

    @staticmethod
    def message(message: str):
        return ("POST", "/v1/community/messages", None, {"message": message},
                _m.WriteResult.from_dict)

    @staticmethod
    def add_member(phone_number: str, key_ids: Any):
        return ("POST", "/v1/community/members", None,
                {"phone_number": phone_number, "key_ids": list(key_ids)},
                _m.WriteResult.from_dict)

    @staticmethod
    def grant_keys(account_community_id: int, key_ids: Any):
        return ("POST",
                f"/v1/community/members/{_enc(account_community_id)}/grant-keys",
                None, {"key_ids": list(key_ids)}, _m.WriteResult.from_dict)

    @staticmethod
    def revoke_keys(account_community_id: int, key_ids: Any,
                    remove_member: bool = False):
        return ("POST",
                f"/v1/community/members/{_enc(account_community_id)}/revoke-keys",
                None, {"key_ids": list(key_ids), "remove_member": remove_member},
                _m.WriteResult.from_dict)

    @staticmethod
    def set_keys_disabled(account_community_id: int, key_ids: Any,
                          disabled: bool):
        return ("POST",
                f"/v1/community/members/{_enc(account_community_id)}/keys-disabled",
                None, {"key_ids": list(key_ids), "disabled": disabled},
                _m.WriteResult.from_dict)

    @staticmethod
    def approve_member(account_community_id: int, key_ids: Any,
                       move_out_date: Optional[str] = None,
                       dry_run: Optional[bool] = None):
        body: dict = {"key_ids": list(key_ids)}
        if move_out_date is not None:
            body["move_out_date"] = move_out_date
        if dry_run is not None:
            body["dry_run"] = dry_run
        return ("POST",
                f"/v1/community/members/{_enc(account_community_id)}/approve",
                None, body, _m.WriteResult.from_dict)

    # -- bulk member writes ---------------------------------------------- #
    #
    # One request, many members. Every one answers 207 with a per-item verdict
    # (see models.BulkResult): the batch was processed, but individual items
    # may still have failed.

    @staticmethod
    def bulk_add_members(items: Any):
        return ("POST", "/v1/community/members/bulk-add", None,
                {"items": [dict(i) for i in items]}, _m.BulkResult.from_dict)

    @staticmethod
    def bulk_grant_keys(items: Any):
        return ("POST", "/v1/community/members/keys/bulk-grant", None,
                {"items": [dict(i) for i in items]}, _m.BulkResult.from_dict)

    @staticmethod
    def bulk_revoke_keys(items: Any):
        return ("POST", "/v1/community/members/keys/bulk-revoke", None,
                {"items": [dict(i) for i in items]}, _m.BulkResult.from_dict)

    @staticmethod
    def bulk_set_keys_disabled(items: Any, disabled: bool):
        return ("POST", "/v1/community/members/keys/bulk-disabled", None,
                {"items": [dict(i) for i in items], "disabled": bool(disabled)},
                _m.BulkResult.from_dict)

    @staticmethod
    def member_access_logs(account_community_id: int, window: str = "last_30"):
        return ("GET",
                f"/v1/community/members/{_enc(account_community_id)}/access-logs",
                {"window": window}, None, _m.MemberAccessLogPage.from_dict)

    @staticmethod
    def access_log(page: int = 0):
        return ("GET", "/v1/community/access-logs", {"page": page}, None,
                _m.AccessLogPage.from_dict)

    @staticmethod
    def gate_status_log(page: int = 0):
        return ("GET", "/v1/community/gate-status-log", {"page": page}, None,
                _m.GateStatusLogPage.from_dict)

    # -- hold opens ----------------------------------------------------- #

    @staticmethod
    def hold_opens():
        return ("GET", "/v1/community/hold-opens", None, None,
                _m.HoldOpens.from_dict)

    @staticmethod
    def set_hold_open(latch_id: str, state: bool):
        return ("PUT", f"/v1/community/latches/{_enc(latch_id)}/hold-open",
                None, {"state": bool(state)}, _m.ManualHoldOpenResult.from_dict)

    @staticmethod
    def add_hold_open_event(latch_id: str, start: str, end: str):
        return ("POST",
                f"/v1/community/latches/{_enc(latch_id)}/hold-open/events",
                None, {"start": start, "end": end},
                _m.HoldOpenEventAdded.from_dict)

    @staticmethod
    def remove_hold_open_event(latch_id: str, event_id: str):
        return ("DELETE",
                f"/v1/community/latches/{_enc(latch_id)}/hold-open/events/"
                f"{_enc(event_id)}",
                None, None, _m.HoldOpenEventRemoved.from_dict)

    @staticmethod
    def set_hold_open_disabled_until(latch_id: str, until: Optional[str]):
        # `until` is always sent, null included: an absent field is a 400
        # rather than an accidental resume.
        return ("PUT",
                f"/v1/community/latches/{_enc(latch_id)}/hold-open/"
                "disabled-until",
                None, {"until": until}, _m.HoldOpenDisabledUntil.from_dict)

    @staticmethod
    def add_hold_open_recurring(latch_id: str, days_of_the_week: str,
                                start_time: Optional[str] = None,
                                end_time: Optional[str] = None,
                                recurring_week: Optional[int] = None):
        body: dict = {"days_of_the_week": days_of_the_week}
        if start_time is not None:
            body["start_time"] = start_time
        if end_time is not None:
            body["end_time"] = end_time
        if recurring_week is not None:
            body["recurring_week"] = recurring_week
        return ("POST",
                f"/v1/community/latches/{_enc(latch_id)}/hold-open/recurring",
                None, body, _m.RecurringHoldOpen.from_dict)

    @staticmethod
    def update_hold_open_recurring(latch_id: str, temporal_date_id: str,
                                   days_of_the_week: Optional[str] = None,
                                   start_time: Optional[str] = None,
                                   end_time: Optional[str] = None,
                                   recurring_week: Optional[int] = None,
                                   clear_times: Optional[bool] = None):
        body: dict = {}
        if days_of_the_week is not None:
            body["days_of_the_week"] = days_of_the_week
        if start_time is not None:
            body["start_time"] = start_time
        if end_time is not None:
            body["end_time"] = end_time
        if recurring_week is not None:
            body["recurring_week"] = recurring_week
        if clear_times is not None:
            body["clear_times"] = clear_times
        return ("PATCH",
                f"/v1/community/latches/{_enc(latch_id)}/hold-open/recurring/"
                f"{_enc(temporal_date_id)}",
                None, body, _m.RecurringHoldOpen.from_dict)

    @staticmethod
    def remove_hold_open_recurring(latch_id: str, temporal_date_id: str):
        return ("DELETE",
                f"/v1/community/latches/{_enc(latch_id)}/hold-open/recurring/"
                f"{_enc(temporal_date_id)}",
                None, None, _m.RecurringHoldOpenRemoved.from_dict)

    # -- key access schedules -------------------------------------------- #
    #
    # Community keys only. A schedule on the community key is the
    # community-wide rule and cascades to every member key beneath it; an
    # individual member's key is refused with not_a_community_key (403).

    @staticmethod
    def key_schedules():
        return ("GET", "/v1/community/key-schedules", None, None,
                _m.KeySchedules.from_dict)

    @staticmethod
    def key_schedule(key_id: str):
        return ("GET", f"/v1/community/keys/{_enc(key_id)}/schedule",
                None, None, _m.KeySchedule.from_dict)

    @staticmethod
    def set_key_schedule(key_id: str, windows):
        # Whole-schedule replace: [] removes every restriction. Accepts
        # ScheduleWindow objects or plain dicts so callers can round-trip what
        # a read returned without converting.
        payload = [w.to_payload() if hasattr(w, "to_payload") else dict(w)
                   for w in (windows or [])]
        return ("PUT", f"/v1/community/keys/{_enc(key_id)}/schedule",
                None, {"windows": payload}, _m.KeySchedule.from_dict)

    # -- webhooks -------------------------------------------------------- #

    @staticmethod
    def webhook_event_types():
        return ("GET", "/v1/community/webhook-events", None, None,
                lambda d: list((d or {}).get("events") or []))

    @staticmethod
    def webhooks():
        return ("GET", "/v1/community/webhooks", None, None,
                lambda d: [_m.Webhook.from_dict(x)
                           for x in ((d or {}).get("webhooks") or [])])

    @staticmethod
    def create_webhook(url: str, events: Any, description: Optional[str] = None):
        body: dict = {"url": url, "events": list(events)}
        if description is not None:
            body["description"] = description
        return ("POST", "/v1/community/webhooks", None, body,
                _m.WebhookCreateResult.from_dict)

    @staticmethod
    def update_webhook(webhook_id: str, url: Optional[str] = None,
                       events: Any = None, active: Optional[bool] = None,
                       description: Optional[str] = None):
        body: dict = {}
        if url is not None:
            body["url"] = url
        if events is not None:
            body["events"] = list(events)
        if active is not None:
            body["active"] = active
        if description is not None:
            body["description"] = description
        return ("PATCH", f"/v1/community/webhooks/{_enc(webhook_id)}",
                None, body, _m.WebhookCreateResult.from_dict)

    @staticmethod
    def delete_webhook(webhook_id: str):
        return ("DELETE", f"/v1/community/webhooks/{_enc(webhook_id)}",
                None, None, _m.WriteResult.from_dict)

    @staticmethod
    def rotate_webhook_secret(webhook_id: str):
        return ("POST",
                f"/v1/community/webhooks/{_enc(webhook_id)}/rotate-secret",
                None, None, _m.WebhookSecret.from_dict)

    @staticmethod
    def test_webhook(webhook_id: str):
        return ("POST", f"/v1/community/webhooks/{_enc(webhook_id)}/test",
                None, None, _m.WriteResult.from_dict)

    @staticmethod
    def webhook_deliveries(webhook_id: str, limit: int = 50):
        return ("GET",
                f"/v1/community/webhooks/{_enc(webhook_id)}/deliveries",
                {"limit": limit}, None,
                lambda d: [_m.WebhookDelivery.from_dict(x)
                           for x in ((d or {}).get("deliveries") or [])])

    @staticmethod
    def retry_failed_deliveries(webhook_id: str, since: Optional[str] = None,
                                limit: int = 50):
        return ("POST",
                f"/v1/community/webhooks/{_enc(webhook_id)}/deliveries/"
                "retry-failed",
                {"since": since, "limit": limit}, None,
                _m.DeliveryReplayBatch.from_dict)

    @staticmethod
    def replay_delivery(webhook_id: str, delivery_id: str):
        return ("POST",
                f"/v1/community/webhooks/{_enc(webhook_id)}/deliveries/"
                f"{_enc(delivery_id)}/replay",
                None, None, _m.DeliveryReplay.from_dict)

    # -- community settings ---------------------------------------------- #
    #
    # `settings` is the settable surface; `read_only` is what Nimbio
    # provisions and reports for feature discovery. The PATCH is validated
    # whole before anything is written, so a bad key applies nothing.

    @staticmethod
    def settings():
        return ("GET", "/v1/community/settings", None, None,
                _m.CommunitySettings.from_dict)

    @staticmethod
    def update_settings(settings: Any):
        return ("PATCH", "/v1/community/settings", None,
                {"settings": dict(settings)}, _m.CommunitySettings.from_dict)

    # -- homes / units roster --------------------------------------------- #

    @staticmethod
    def homes(include_hidden: bool = True):
        # Always sent explicitly: the server's default is true, and false is a
        # meaningful choice rather than the absence of one.
        return ("GET", "/v1/community/homes",
                {"include_hidden": "true" if include_hidden else "false"},
                None,
                lambda d: [_m.Home.from_dict(h)
                           for h in ((d or {}).get("homes") or [])])

    @staticmethod
    def add_home(home_address: str):
        return ("POST", "/v1/community/homes", None,
                {"home_address": home_address}, _m.Home.from_dict)

    @staticmethod
    def home(home_id: str):
        return ("GET", f"/v1/community/homes/{_enc(home_id)}", None, None,
                _m.Home.from_dict)

    @staticmethod
    def update_home(home_id: str, home_address: Optional[str] = None,
                    owner_occupied: Optional[bool] = None,
                    hidden: Optional[bool] = None):
        body: dict = {}
        if home_address is not None:
            body["home_address"] = home_address
        if owner_occupied is not None:
            body["owner_occupied"] = owner_occupied
        if hidden is not None:
            body["hidden"] = hidden
        return ("PATCH", f"/v1/community/homes/{_enc(home_id)}", None, body,
                _m.Home.from_dict)

    @staticmethod
    def remove_home(home_id: str):
        return ("DELETE", f"/v1/community/homes/{_enc(home_id)}", None, None,
                _m.HomeRemoved.from_dict)

    @staticmethod
    def set_move_out_date(account_community_id: int,
                          move_out_date: Optional[str]):
        # `move_out_date` is always sent, null included: an absent field is a
        # 422 rather than an accidental no-op.
        return ("PUT",
                f"/v1/community/members/{_enc(account_community_id)}/"
                "move-out-date",
                None, {"move_out_date": move_out_date},
                _m.MoveOutDate.from_dict)

    # -- my member-open notification settings ----------------------------- #
    #
    # Scoped to the community MANAGER who owns the key, not to the community:
    # two keys owned by two managers of one community read and write two
    # different objects through these same four paths. All four return the
    # complete settings object.

    @staticmethod
    def my_notification_settings():
        return ("GET", "/v1/community/my-notification-settings", None, None,
                _m.NotificationSettings.from_dict)

    @staticmethod
    def set_my_notifications_enabled(enabled: bool):
        return ("PUT", "/v1/community/my-notification-settings", None,
                {"enabled": bool(enabled)}, _m.NotificationSettings.from_dict)

    @staticmethod
    def add_quiet_hours(days_of_the_week: str,
                        start_time: Optional[str] = None,
                        end_time: Optional[str] = None):
        # Both times omitted is how an all-day window is expressed; sending
        # explicit nulls would mean the same thing, but the server documents
        # omission, so keep the body minimal.
        body: dict = {"days_of_the_week": days_of_the_week}
        if start_time is not None:
            body["start_time"] = start_time
        if end_time is not None:
            body["end_time"] = end_time
        return ("POST", "/v1/community/my-notification-settings/quiet-hours",
                None, body, _m.NotificationSettings.from_dict)

    @staticmethod
    def remove_quiet_hours(quiet_hours_id: Any):
        return ("DELETE",
                "/v1/community/my-notification-settings/quiet-hours/"
                f"{_enc(quiet_hours_id)}",
                None, None, _m.NotificationSettings.from_dict)

    # -- guest links ------------------------------------------------------ #
    #
    # The responses here carry `token` and `url` — a working gate for anyone
    # holding them, from the LIST read as well as from create. Nothing in this
    # file logs a response body, and the models keep both out of their reprs.

    @staticmethod
    def guest_links(include_inactive: bool = True):
        # Always sent explicitly: the server's default is true, and false is a
        # meaningful choice rather than the absence of one.
        return ("GET", "/v1/community/guest-links",
                {"include_inactive": "true" if include_inactive else "false"},
                None,
                lambda d: [_m.GuestLink.from_dict(x)
                           for x in ((d or {}).get("guest_links") or [])])

    @staticmethod
    def create_guest_link(link_type: str, latch_ids: Any,
                          key_id: Optional[str] = None,
                          title: Optional[str] = None,
                          subtitle: Optional[str] = None,
                          extra_info: Optional[str] = None,
                          max_uses: Optional[int] = None,
                          expires_at: Optional[str] = None,
                          window_start: Optional[str] = None,
                          window_end: Optional[str] = None,
                          notify_on_use: Optional[bool] = None):
        body: dict = {"link_type": link_type, "latch_ids": list(latch_ids)}
        if key_id is not None:
            body["key_id"] = key_id
        if title is not None:
            body["title"] = title
        if subtitle is not None:
            body["subtitle"] = subtitle
        if extra_info is not None:
            body["extra_info"] = extra_info
        if max_uses is not None:
            body["max_uses"] = int(max_uses)
        if expires_at is not None:
            body["expires_at"] = expires_at
        if window_start is not None:
            body["window_start"] = window_start
        if window_end is not None:
            body["window_end"] = window_end
        if notify_on_use is not None:
            body["notify_on_use"] = bool(notify_on_use)
        return ("POST", "/v1/community/guest-links", None, body,
                _m.GuestLink.from_dict)

    @staticmethod
    def revoke_guest_link(guest_link_id: Any):
        return ("DELETE", f"/v1/community/guest-links/{_enc(guest_link_id)}",
                None, None, _m.GuestLink.from_dict)

    @staticmethod
    def guest_link_logs(guest_link_id: Optional[Any] = None, limit: int = 50,
                        offset: int = 0):
        return ("GET", "/v1/community/guest-links/logs",
                {"guest_link_id": guest_link_id, "limit": limit,
                 "offset": offset},
                None, _m.GuestLinkLogPage.from_dict)

    @staticmethod
    def guest_link_latch_exclusions():
        return ("GET", "/v1/community/guest-links/latch-exclusions", None, None,
                _m.GuestLinkLatchExclusions.from_dict)

    # -- directory access codes ------------------------------------------- #

    @staticmethod
    def access_codes():
        return ("GET", "/v1/community/access-codes", None, None,
                _m.AccessCodes.from_dict)

    @staticmethod
    def create_access_code(code: str, latch_ids: Any,
                           expires_in_hours: Optional[int] = None,
                           expires_in_days: Optional[int] = None,
                           temporal: Any = None):
        body: dict = {"code": code, "latch_ids": list(latch_ids)}
        if expires_in_hours is not None:
            body["expires_in_hours"] = int(expires_in_hours)
        if expires_in_days is not None:
            body["expires_in_days"] = int(expires_in_days)
        if temporal is not None:
            body["temporal"] = dict(temporal)
        return ("POST", "/v1/community/access-codes", None, body,
                _m.AccessCodeCreated.from_dict)

    @staticmethod
    def update_access_code(directory_access_code_id: Any,
                           disabled: Optional[bool] = None,
                           latch_ids: Any = None,
                           expires_in_hours: Optional[int] = None,
                           expires_in_days: Optional[int] = None,
                           temporal: Any = None):
        body: dict = {}
        if disabled is not None:
            body["disabled"] = bool(disabled)
        if latch_ids is not None:
            body["latch_ids"] = list(latch_ids)
        if expires_in_hours is not None:
            body["expires_in_hours"] = int(expires_in_hours)
        if expires_in_days is not None:
            body["expires_in_days"] = int(expires_in_days)
        if temporal is not None:
            body["temporal"] = dict(temporal)
        return ("PATCH",
                f"/v1/community/access-codes/{_enc(directory_access_code_id)}",
                None, body, _m.AccessCode.from_dict)

    @staticmethod
    def delete_access_code(directory_access_code_id: Any):
        return ("DELETE",
                f"/v1/community/access-codes/{_enc(directory_access_code_id)}",
                None, None, _m.AccessCodeDeleted.from_dict)

    @staticmethod
    def access_code_eligible_latches():
        return ("GET", "/v1/community/access-codes/eligible-latches", None,
                None, _m.AccessCodeEligibleLatches.from_dict)

    @staticmethod
    def access_code_logs(limit: int = 50, offset: int = 0):
        return ("GET", "/v1/community/access-codes/logs",
                {"limit": limit, "offset": offset}, None,
                _m.AccessCodeLogPage.from_dict)

    # The mode flip is its own endpoint, not a settings key: switching deletes
    # every code in the community, so it runs the same 409
    # `requires_confirmation` -> confirm=True handshake as the NFC-tag write.

    @staticmethod
    def access_code_mode():
        return ("GET", "/v1/community/access-codes/mode", None, None,
                _m.AccessCodeModeStatus.from_dict)

    @staticmethod
    def set_access_code_mode(mode: str, confirm: bool = False):
        # Only the literal `True` confirms. `bool()` would turn "false", "0"
        # or "no" — the kind of value that leaks in from an env var, a CLI
        # flag or a JSON string — into `true`, and this flag wipes every code
        # in the community. The server applies the same `is True` rule.
        body: dict = {"mode": str(mode), "confirm": confirm is True}
        return ("PUT", "/v1/community/access-codes/mode", None, body,
                _m.AccessCodeModeChange.from_dict)

    # -- GuestView Entry --------------------------------------------------- #
    #
    # Every one of these five returns the complete settings object, so the
    # writes never need a follow-up read.

    @staticmethod
    def guest_view_entry():
        return ("GET", "/v1/community/guest-view-entry", None, None,
                _m.GuestViewEntry.from_dict)

    @staticmethod
    def set_guest_view_entry_enabled(allowed: bool):
        # An explicit setter rather than a toggle: this call is retryable, and
        # a retried toggle would flip guest access back open.
        return ("PUT", "/v1/community/guest-view-entry", None,
                {"allowed": bool(allowed)}, _m.GuestViewEntry.from_dict)

    @staticmethod
    def set_guest_view_entry_latches(latch_ids: Any):
        # Whole-set replace, hence the PUT: an omitted latch loses guest
        # eligibility AND its schedule windows are deleted with it.
        return ("PUT", "/v1/community/guest-view-entry/eligible-latches", None,
                {"latch_ids": list(latch_ids)}, _m.GuestViewEntry.from_dict)

    @staticmethod
    def guest_view_entry_logs(limit: int = 50, offset: int = 0,
                              success: Optional[bool] = None):
        return ("GET", "/v1/community/guest-view-entry/logs",
                {"limit": limit, "offset": offset,
                 "success": None if success is None
                 else ("true" if success else "false")},
                None, _m.GuestViewEntryLogPage.from_dict)

    @staticmethod
    def add_guest_view_entry_schedule(latch_ids: Any, days_of_the_week: str,
                                      start_time: Optional[str] = None,
                                      end_time: Optional[str] = None):
        body: dict = {"latch_ids": list(latch_ids),
                      "days_of_the_week": days_of_the_week}
        if start_time is not None:
            body["start_time"] = start_time
        if end_time is not None:
            body["end_time"] = end_time
        return ("POST", "/v1/community/guest-view-entry/schedule", None, body,
                _m.GuestViewEntry.from_dict)

    @staticmethod
    def remove_guest_view_entry_schedule(schedule_id: Any):
        return ("DELETE",
                f"/v1/community/guest-view-entry/schedule/{_enc(schedule_id)}",
                None, None, _m.GuestViewEntry.from_dict)

    # -- GuestView short codes --------------------------------------------- #

    @staticmethod
    def short_codes():
        return ("GET", "/v1/community/short-codes", None, None,
                lambda d: [_m.ShortCode.from_dict(x)
                           for x in ((d or {}).get("short_codes") or [])])

    @staticmethod
    def create_short_code(code: Optional[str] = None,
                          latch_id: Optional[str] = None):
        body: dict = {}
        if code is not None:
            body["code"] = code
        if latch_id is not None:
            body["latch_id"] = latch_id
        return ("POST", "/v1/community/short-codes", None, body,
                _m.ShortCode.from_dict)

    @staticmethod
    def assign_short_code(code: str, latch_id: str):
        # Exclusive: the code routes to exactly one gate, so this detaches
        # whatever it pointed at before.
        return ("PUT", f"/v1/community/short-codes/{_enc(code)}", None,
                {"latch_id": latch_id}, _m.ShortCode.from_dict)

    # -- NFC tags ---------------------------------------------------------- #
    #
    # One PATCH does assign, unassign and disable. `disabled` is applied
    # before `latch_id`, and a write that would leave a Scan Only gate with no
    # working tag answers 409 `requires_confirmation` — a warning, retryable
    # with confirm=True, not a veto.

    @staticmethod
    def nfc_tags(search: Optional[str] = None, page: int = 1,
                 results_per_page: int = 50):
        return ("GET", "/v1/community/nfc-tags",
                {"search": search, "page": page,
                 "results_per_page": results_per_page},
                None, _m.NfcTagPage.from_dict)

    @staticmethod
    def nfc_tag(tag_id: Any):
        return ("GET", f"/v1/community/nfc-tags/{_enc(tag_id)}", None, None,
                _m.NfcTag.from_dict)

    @staticmethod
    def update_nfc_tag(tag_id: Any, disabled: Optional[bool] = None,
                       latch_id: Any = UNSET, confirm: Optional[bool] = None):
        # `latch_id=None` is a real instruction (detach), so the "leave it
        # alone" default has to be something else — hence the sentinel.
        body: dict = {}
        if disabled is not None:
            body["disabled"] = bool(disabled)
        if latch_id is not UNSET:
            body["latch_id"] = latch_id
        if confirm is not None:
            # Same rule as set_access_code_mode: only a literal True confirms.
            body["confirm"] = confirm is True
        return ("PATCH", f"/v1/community/nfc-tags/{_enc(tag_id)}", None, body,
                _m.NfcTag.from_dict)

    @staticmethod
    def nfc_scan_log(limit: int = 50, offset: int = 0,
                     result: Optional[str] = None,
                     tag_uid_hex: Optional[str] = None):
        return ("GET", "/v1/community/nfc-tags/scan-log",
                {"limit": limit, "offset": offset, "result": result,
                 "tag_uid_hex": tag_uid_hex},
                None, _m.NfcScanLogPage.from_dict)

    # -- sense lines ------------------------------------------------------- #
    #
    # A sense line id is an input number on a board, unique only within its
    # box, so addressing ONE of them needs `box_id` as well: it is a required
    # argument on `sense_line` and `update_sense_line` (the OpenAPI schema
    # marks it optional because the handler validates it, but omitting it is a
    # 422 `box_id_required`), and a genuine filter on the two list reads.

    @staticmethod
    def sense_lines(box_id: Optional[str] = None):
        return ("GET", "/v1/community/sense-lines", {"box_id": box_id}, None,
                _m.SenseLines.from_dict)

    @staticmethod
    def sense_line(sense_line_id: int, box_id: str):
        return ("GET", f"/v1/community/sense-lines/{_enc(sense_line_id)}",
                {"box_id": box_id}, None, _m.SenseLine.from_dict)

    @staticmethod
    def update_sense_line(sense_line_id: int, box_id: str,
                          sense_line_online: Optional[bool] = None,
                          latch_data_online: Optional[bool] = None):
        body: dict = {}
        if sense_line_online is not None:
            body["sense_line_online"] = bool(sense_line_online)
        if latch_data_online is not None:
            body["latch_data_online"] = bool(latch_data_online)
        return ("PATCH", f"/v1/community/sense-lines/{_enc(sense_line_id)}",
                {"box_id": box_id}, body, _m.SenseLine.from_dict)

    @staticmethod
    def sense_line_records(box_id: Optional[str] = None,
                           sense_line_id: Optional[int] = None,
                           limit: int = 50, offset: int = 0):
        return ("GET", "/v1/community/sense-lines/records",
                {"box_id": box_id, "sense_line_id": sense_line_id,
                 "limit": limit, "offset": offset},
                None, _m.SenseLineRecordPage.from_dict)

    # -- map and geofences -------------------------------------------------- #

    @staticmethod
    def map():
        return ("GET", "/v1/community/map", None, None,
                _m.CommunityMap.from_dict)

    @staticmethod
    def update_geofence(latch_id: str, enabled: Optional[bool] = None,
                        latitude: Optional[float] = None,
                        longitude: Optional[float] = None,
                        radius_meters: Optional[int] = None,
                        mode: Optional[str] = None):
        # Partial update: an omitted field keeps its stored value, which is
        # also why there is no way to clear a configured centre here.
        body: dict = {}
        if enabled is not None:
            body["enabled"] = bool(enabled)
        if latitude is not None:
            body["latitude"] = float(latitude)
        if longitude is not None:
            body["longitude"] = float(longitude)
        if radius_meters is not None:
            body["radius_meters"] = int(radius_meters)
        if mode is not None:
            body["mode"] = mode
        return ("PATCH", f"/v1/community/latches/{_enc(latch_id)}/geofence",
                None, body, _m.MapLatch.from_dict)

    # -- audit trails ------------------------------------------------------- #

    @staticmethod
    def change_logs(log_type: str, days: int = 30, limit: int = 500,
                    offset: int = 0):
        return ("GET", "/v1/community/change-logs",
                {"type": log_type, "days": days, "limit": limit,
                 "offset": offset},
                None, _m.ChangeLogPage.from_dict)

    @staticmethod
    def key_usage(date_from: str, date_to: str, page: int = 0):
        return ("GET", "/v1/community/key-usage",
                {"from": date_from, "to": date_to, "page": page}, None,
                _m.KeyUsageReport.from_dict)
