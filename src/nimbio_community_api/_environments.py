"""Environment -> base URL mapping for the Nimbio public API.

The Nimbio public API is deployed at two hosts:

- ``prod``  -> https://api.nimbio.com   (live production system)
- ``dev``   -> https://api.nimbio.dev   (staging / development system)

A third convenience target, ``local``, points at a service running on the
developer's machine (the FastAPI app on port 8000).

Whether a call runs in *test* or *live* mode is **not** an environment choice:
it is determined by the API key you authenticate with (a ``nimbio_test_*`` key
simulates side effects; a ``nimbio_live_*`` key performs them). Both key types
work against either environment.
"""

from __future__ import annotations

from typing import Dict

#: Canonical environment names accepted by the clients.
ENVIRONMENTS: Dict[str, str] = {
    "prod": "https://api.nimbio.com",
    "dev": "https://api.nimbio.dev",
    "local": "http://localhost:8000",
}

#: The environment used when none is specified.
DEFAULT_ENVIRONMENT = "prod"


def resolve_base_url(environment: str | None, base_url: str | None) -> str:
    """Resolve the effective base URL from an environment name or explicit URL.

    ``base_url`` always wins when provided. Otherwise ``environment`` is looked
    up in :data:`ENVIRONMENTS`. A trailing slash is stripped so callers can
    safely join ``"/v1/..."`` paths.
    """
    if base_url:
        return base_url.rstrip("/")
    env = (environment or DEFAULT_ENVIRONMENT).lower()
    try:
        return ENVIRONMENTS[env]
    except KeyError:
        valid = ", ".join(sorted(ENVIRONMENTS))
        raise ValueError(
            f"Unknown environment {environment!r}. "
            f"Use one of: {valid} — or pass base_url=... explicitly."
        ) from None
