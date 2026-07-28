"""Verify Nimbio community-webhook deliveries.

Nimbio signs every webhook POST with a Stripe-style HMAC so the receiver can
prove it came from Nimbio and is not a replay. The delivery request carries:

- ``X-Nimbio-Signature``:  ``sha256=<hex HMAC-SHA256 over "{timestamp}.{body}">``
- ``X-Nimbio-Timestamp``:  unix seconds when the delivery was signed
- ``X-Nimbio-Event``:      the event type (e.g. ``sense_line.changed``)
- ``X-Nimbio-Delivery``:   unique id for this delivery attempt's event
- ``X-Nimbio-Webhook-Id``: the webhook registration the delivery belongs to

The signing secret is returned exactly once when the webhook is created (or
its secret rotated). Typical usage in a receiver::

    from nimbio_community_api.webhooks import construct_event

    event = construct_event(
        body=request_body_bytes,
        signature=request.headers["X-Nimbio-Signature"],
        timestamp=request.headers["X-Nimbio-Timestamp"],
        secret=stored_secret,
    )   # raises WebhookSignatureError if the delivery isn't authentic
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional, Union

__all__ = [
    "WebhookSignatureError",
    "verify_signature",
    "construct_event",
    "DEFAULT_TOLERANCE_SECONDS",
]

# Reject deliveries whose signing timestamp is further than this from now —
# bounds the replay window without breaking on modest clock skew.
DEFAULT_TOLERANCE_SECONDS = 300


class WebhookSignatureError(Exception):
    """The delivery could not be authenticated (bad signature, malformed
    header, or a timestamp outside the replay tolerance)."""


def _to_bytes(body: Union[bytes, str]) -> bytes:
    return body.encode("utf-8") if isinstance(body, str) else bytes(body)


def compute_signature(secret: str, timestamp: Union[str, int],
                      body: Union[bytes, str]) -> str:
    """The expected ``X-Nimbio-Signature`` value for a payload:
    ``sha256=<hex HMAC-SHA256(secret, "{timestamp}." + body)>``."""
    signed = f"{timestamp}.".encode("utf-8") + _to_bytes(body)
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def verify_signature(secret: str, timestamp: Union[str, int],
                     body: Union[bytes, str], signature: str, *,
                     tolerance_seconds: Optional[int] = DEFAULT_TOLERANCE_SECONDS,
                     now: Optional[float] = None) -> bool:
    """True iff ``signature`` authenticates ``body`` at ``timestamp``.

    Constant-time comparison. When ``tolerance_seconds`` is not None, the
    timestamp must also be within that many seconds of ``now`` (default: the
    current time) — pass ``tolerance_seconds=None`` to skip the replay check
    (e.g. when re-verifying stored deliveries).
    """
    if not isinstance(signature, str) or not signature:
        return False
    expected = compute_signature(secret, timestamp, body)
    if not hmac.compare_digest(expected, signature.strip()):
        return False
    if tolerance_seconds is not None:
        try:
            ts = float(str(timestamp))
        except (TypeError, ValueError):
            return False
        reference = time.time() if now is None else float(now)
        if abs(reference - ts) > tolerance_seconds:
            return False
    return True


def construct_event(body: Union[bytes, str], signature: str,
                    timestamp: Union[str, int], secret: str, *,
                    tolerance_seconds: Optional[int] = DEFAULT_TOLERANCE_SECONDS,
                    now: Optional[float] = None) -> Dict[str, Any]:
    """Verify a delivery and return the decoded event envelope.

    The envelope is ``{"event": <type>, "id": <event id>, "community_id": ...,
    "occurred_at": <ISO 8601>, "data": {...}}``. Raises
    :class:`WebhookSignatureError` when authentication fails and
    ``ValueError`` when the body is not valid JSON.
    """
    if not verify_signature(secret, timestamp, body, signature,
                            tolerance_seconds=tolerance_seconds, now=now):
        raise WebhookSignatureError(
            "Webhook signature verification failed (wrong secret, altered "
            "payload, or timestamp outside the replay tolerance)")
    decoded = json.loads(_to_bytes(body).decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("Webhook body is not a JSON object")
    return decoded
