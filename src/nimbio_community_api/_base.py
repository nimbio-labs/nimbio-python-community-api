"""Shared, transport-agnostic core for the sync and async clients.

This module owns everything that does *not* depend on whether I/O is blocking or
not: configuration resolution, header construction, URL building, response
decoding, error mapping, and the retry policy. The sync and async clients each
implement only the small send-loop that actually performs the HTTP round trip.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from . import _exceptions as exc
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
    ) -> None:
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

    def __repr__(self) -> str:
        # Deliberately never includes the API key, so it is safe to log.
        return (f"{type(self).__name__}(base_url={self.base_url!r}, "
                f"mode={self.mode!r})")

    # -- request preparation ------------------------------------------------ #

    def _headers(self) -> dict:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": f"nimbio-community-api-python/{__version__}",
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
            "User-Agent": f"nimbio-community-api-python/{__version__}",
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
    def gate_status():
        return ("GET", "/v1/community/gate-status", None, None,
                _m.GateStatus.from_dict)

    @staticmethod
    def members():
        return "GET", "/v1/community/members", None, None, _m.Members.from_dict

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

    # -- key access schedules -------------------------------------------- #

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
