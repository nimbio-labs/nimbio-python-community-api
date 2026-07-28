"""Nimbio community API — the official Python client.

A small, typed wrapper over the Nimbio public REST API (https://api.nimbio.com)
for community managers: read gate status, manage members and keys, issue opens,
send messages, and pull access logs.

Quickstart (sync)::

    from nimbio_community_api import NimbioClient

    with NimbioClient("nimbio_test_...") as client:   # mode is inferred from the key
        print(client.me().account_id)
        for latch in client.community.gate_status().latches:
            print(latch.latch_name, latch.status)

Quickstart (async)::

    import asyncio
    from nimbio_community_api import AsyncNimbioClient

    async def main():
        async with AsyncNimbioClient("nimbio_live_...", environment="dev") as client:
            await client.community.open("latch-id-123", note="front gate")

    asyncio.run(main())

Pick an environment with ``environment="prod"`` (default), ``"dev"``, or
``"local"`` — or override entirely with ``base_url=...``. Whether a call is a
real (live) or simulated (test) action is determined by the API key itself.
"""

from __future__ import annotations

from . import models, webhooks
from ._async import AsyncNimbioClient
from ._environments import DEFAULT_ENVIRONMENT, ENVIRONMENTS
from ._exceptions import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    GateNotOpenedError,
    NimbioConfigError,
    NimbioError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    UpstreamError,
)
from ._sync import NimbioClient
from ._version import __version__

__all__ = [
    "__version__",
    # clients
    "NimbioClient",
    "AsyncNimbioClient",
    # environments
    "ENVIRONMENTS",
    "DEFAULT_ENVIRONMENT",
    # models module (typed response objects)
    "models",
    # webhook delivery verification (HMAC)
    "webhooks",
    # exceptions
    "NimbioError",
    "NimbioConfigError",
    "APIError",
    "APIConnectionError",
    "APITimeoutError",
    "BadRequestError",
    "AuthenticationError",
    "PermissionDeniedError",
    "NotFoundError",
    "RateLimitError",
    "GateNotOpenedError",
    "UpstreamError",
    "ServerError",
]
