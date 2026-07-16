# AGENTS.md — using `nimbio-community-api` from an LLM/agent

This is a compact, copy-pasteable reference for coding agents and quick sessions.
Everything here is real and current with the package.

## Install & import

```bash
pip install nimbio-community-api
```

```python
from nimbio_community_api import NimbioClient            # sync
from nimbio_community_api import AsyncNimbioClient        # async
```

## Authenticate

A key is required. It looks like `nimbio_test_<22 chars>` or `nimbio_live_<22 chars>`.

```python
client = NimbioClient("nimbio_test_...")                 # explicit
client = NimbioClient()                                  # reads NIMBIO_API_KEY
client = NimbioClient("nimbio_live_...", environment="dev")
client = NimbioClient("nimbio_test_...", base_url="http://localhost:8000")
```

- `environment`: `"prod"` (default → api.nimbio.com), `"dev"` (→ api.nimbio.dev),
  `"local"` (→ localhost:8000). Or set `base_url` to override.
- **test vs live is the KEY, not a flag.** A `nimbio_test_*` key never fires a
  gate / sends a real message. Check with `client.mode` → `"test"` | `"live"`.
- Env vars: `NIMBIO_API_KEY`, `NIMBIO_ENV`, `NIMBIO_BASE_URL`.

## The whole SDK surface (sync — drop the `with`/use `await` for async)

This is every method the SDK exposes. Note the SDK is **community-scoped by
design**: it covers `/v1/me`, `/healthz`, and the whole `/v1/community/*`
surface, but deliberately does not wrap the service's Account surface
(`/v1/account/keys`, `/v1/account/keys/{key_id}/latches/{latch_id}/open`, or the
hidden `/v1/keys*` / `/v1/calls*` endpoints). That gap is intentional and
expected to stay (as of 2026-07-16) — call those endpoints over plain HTTPS if
you need them.

```python
with NimbioClient("nimbio_test_...") as client:
    client.me()                       # -> Me           (account_id, key.usage…)
    client.health()                   # -> Health       (ok, wamp) — never raises on 503
    client.mode                       # -> "test" | "live" | None (no network)

    # Reads (community-scoped key required)
    client.community.gate_status()    # -> GateStatus   (.latches: list[Latch])
    client.community.members()        # -> Members      (.accepted/.unaccepted/.removed)
    client.community.key_statuses()   # -> KeyStatuses  (.keys, .hold_opens)
    client.community.keys()           # -> list[CommunityKey]

    # Writes (test key = simulated, live key = real)
    client.community.open("LATCH_ID", note="...", idempotency_key="...")   # -> OpenResult
    client.community.message("text")                                       # -> WriteResult
    client.community.add_member("+15551234567", ["KEY_ID"])                # -> WriteResult
    client.community.grant_keys(ACCOUNT_COMMUNITY_ID, ["KEY_ID"])          # -> WriteResult
    client.community.revoke_keys(ACCOUNT_COMMUNITY_ID, ["KEY_ID"],
                                 remove_member=False)                      # -> WriteResult
    client.community.set_keys_disabled(ACCOUNT_COMMUNITY_ID, ["KEY_ID"],
                                       disabled=True)                      # -> WriteResult

    # Logs (community must have Access Log History enabled)
    client.community.member_access_logs(ACCOUNT_COMMUNITY_ID, window="last_30")  # last_30|30_60|60_90
    client.community.access_log(page=0)             # -> AccessLogPage  (.logs, .has_more)
    client.community.gate_status_log(page=0)        # -> GateStatusLogPage
    for row in client.community.iter_access_log():  # auto-paginates all pages
        ...
```

Async is identical with `await`, and the iterators are `async for`:

```python
async with AsyncNimbioClient("nimbio_test_...") as client:
    me = await client.me()
    await client.community.open("LATCH_ID")
    async for row in client.community.iter_access_log():
        ...
```

## ID vocabulary (important)

- **`latch_id`** — from `gate_status().latches[i].latch_id`.
- **`key_id`** (community key id) — from `keys()[i].id` or `key_statuses()`.
  Used everywhere keys are granted/revoked/disabled.
- **`account_community_id`** — a member's id, from
  `members().accepted[i].account_community_id`. Used to address a member.

## Return values

Every model exposes typed attributes **and** the full payload on `.raw`. Writes
return a `WriteResult` whose `.result` is the outcome string
(`"member_added"`, `"keys_granted"`, `"sent"`, or `"simulated"`); extra fields
are reachable with `result["field"]`, `result.get("field")`, or `result.raw`.

```python
r = client.community.add_member("+15551234567", ["KEY_ID"])
r.result            # "member_added" (live) or "simulated" (test)
r.simulated         # True on a test key
r.get("account_community_id")
```

## Errors (always wrap network/side-effecting calls)

```python
from nimbio_community_api import (
    APIError, AuthenticationError, PermissionDeniedError,
    RateLimitError, GateNotOpenedError,
)

try:
    client.community.open("LATCH_ID")
except GateNotOpenedError:        # 504 — gate didn't confirm in time
    ...
except PermissionDeniedError as e:  # 403 — wrong scope / open denied / not a community key
    print(e.code)                 # machine code, e.g. "open_denied", "not_community_key"
except RateLimitError as e:       # 429
    print(e.retry_after)          # seconds, may be None
except APIError as e:             # any other HTTP >= 400
    print(e.status_code, e.code, e.message, e.request_id)
```

`APIError` always has `.status_code`, `.code`, `.message`, `.request_id`.
Config problems (missing key, bad environment) raise `NimbioConfigError`
*before* any request. Network failures raise `APIConnectionError` /
`APITimeoutError`.

## Safety tips for agents

- Default to a **test key** while iterating; `assert client.mode == "test"` to
  hard-stop accidental live opens.
- `open()` and member writes are **side-effecting** with a live key. Read first
  (`gate_status`, `members`, `keys`) to discover valid ids before writing.
- The community `open` is **synchronous** and can take ~15–18s; the default
  client timeout (30s) already accounts for this.
