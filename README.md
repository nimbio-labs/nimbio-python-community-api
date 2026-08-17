# nimbio-community-api

Official Python client for the **Nimbio community API** ([api.nimbio.com](https://api.nimbio.com)).

Manage a Nimbio community programmatically: read gate status, open gates, add and
manage members and their keys, send community messages, and pull access logs —
from sync **or** async Python, with full type hints.

```bash
pip install nimbio-community-api
```

- ✅ **Sync and async** — `NimbioClient` for any script, `AsyncNimbioClient` for asyncio.
- ✅ **Typed** — dataclass response models with autocomplete; ships `py.typed`.
- ✅ **Test vs live** — inferred automatically from your API key.
- ✅ **One dependency** — just [`httpx`](https://www.python-httpx.org/).
- ✅ **Built-in retries**, a clean exception hierarchy, and log pagination helpers.

---

## Quickstart

### Sync

```python
from nimbio_community_api import NimbioClient

with NimbioClient("nimbio_test_your_key_here") as client:
    print(client.me().account_id)

    for latch in client.community.gate_status().latches:
        print(latch.latch_name, "->", latch.status)

    # Open a gate. A test key simulates; a live key fires the gate.
    result = client.community.open("latch-id-123", note="front gate")
    print(result.result)  # "simulated" (test key) or "opened" (live key)
```

### Async

```python
import asyncio
from nimbio_community_api import AsyncNimbioClient

async def main():
    async with AsyncNimbioClient("nimbio_live_your_key_here", environment="dev") as client:
        me = await client.me()
        print(me.account_id)
        await client.community.open("latch-id-123")

asyncio.run(main())
```

The two clients have an **identical method surface** — the async version just
returns awaitables and exposes async iterators.

---

## Configuration

You can configure the client with arguments or environment variables. Precedence
is **arguments > environment variables > defaults**.

| Argument | Env var | Default | Notes |
|---|---|---|---|
| `api_key` | `NIMBIO_API_KEY` | — (required) | `nimbio_test_…` or `nimbio_live_…` |
| `environment` | `NIMBIO_ENV` | `"prod"` | `"prod"`, `"dev"`, or `"local"` |
| `base_url` | `NIMBIO_BASE_URL` | — | Overrides `environment` entirely |
| `timeout` | — | `30.0` | Seconds; the community open is synchronous (~15–18s) |
| `max_retries` | — | `2` | Retries 429 + 5xx with backoff, honoring `Retry-After` |

```python
# Picks up NIMBIO_API_KEY and NIMBIO_ENV from the environment:
client = NimbioClient()
```

### Environments vs. test/live

These are **two independent axes**:

- **Environment** = *which server* you talk to (`prod` → `api.nimbio.com`,
  `dev` → `api.nimbio.dev`, `local` → `localhost:8000`).
- **Test vs live** = *what the key does*, determined by the key itself. A
  `nimbio_test_*` key runs the full pipeline (auth, rate limits, scope checks,
  validation) but never fires a gate or sends a real message; a `nimbio_live_*`
  key performs the action. Check it without a network call via `client.mode`.

```python
client = NimbioClient("nimbio_test_...")
assert client.mode == "test"   # great as a guard before destructive calls
```

---

## API reference

### Top level

| Method | Returns | Description |
|---|---|---|
| `client.me()` | `Me` | Key metadata + live usage counters |
| `client.health()` | `Health` | Backend reachability (unauthenticated; never raises on 503) |
| `client.mode` | `"test"`/`"live"`/`None` | Key mode, derived locally |
| `client.close()` / `await client.aclose()` | — | Close the underlying HTTP client |

### `client.community` — reads

| Method | Returns |
|---|---|
| `gate_status()` | `GateStatus` — latest sensed state per latch |
| `members()` | `Members` — accepted / unaccepted / removed |
| `key_statuses()` | `KeyStatuses` — live key + latch state, hold-opens |
| `keys()` | `list[CommunityKey]` — keys with their access restrictions |

### `client.community` — writes

| Method | Returns |
|---|---|
| `open(latch_id, *, note=None, idempotency_key=None)` | `OpenResult` |
| `message(message)` | `WriteResult` |
| `add_member(phone_number, key_ids)` | `WriteResult` |
| `grant_keys(account_community_id, key_ids)` | `WriteResult` |
| `revoke_keys(account_community_id, key_ids, *, remove_member=False)` | `WriteResult` |
| `set_keys_disabled(account_community_id, key_ids, disabled)` | `WriteResult` |

### `client.community` — access schedules

Limit **when** a key may open its gates.

| Method | Returns |
|---|---|
| `key_schedules()` | `KeySchedules` — the community key(s) plus member keys that **have** a schedule; `.blocked` lists keys denied at all times |
| `key_schedule(key_id)` | `KeySchedule` |
| `set_key_schedule(key_id, windows)` | `KeySchedule` — replaces the **whole** schedule; `[]` removes the restriction |

```python
from nimbio_community_api import models

# Weekday daytime access only.
client.community.set_key_schedule("KEY_ID", [
    models.ScheduleWindow("MTWHF", "06:00", "18:00"),
])

# Remove every restriction.
client.community.set_key_schedule("KEY_ID", [])
```

`days_of_the_week` is a letter string from `MTWHFSU` — **`H` is Thursday**, `S`
is Saturday, `U` is Sunday. Times are `'HH:MM'` in each gate's own local time.

Four rules worth knowing before writing one:

- **The write replaces the entire schedule.** Send every window you want to
  keep; `[]` means "always allowed".
- **Windows cannot run past midnight.** `22:00`–`06:00` is rejected with
  `overnight_not_supported` — send two windows instead, the first ending
  `'24:00'` and the second starting `'00:00'` on the following day. Use
  `'24:00'` (the end-of-day sentinel), not `'23:59'`, or the two halves leave a
  one-minute gap every night.
- **A schedule on the community key applies to every member key beneath it.**
  Check `descendant_key_count` and `is_community_key` first.
- **A schedule covers every gate the key opens** — there is no per-gate
  override.

`restricted` means the key is genuinely time-limited. `permanently_blocked`
means windows are saved but the restriction is switched off, which denies every
open at every hour — a fault rather than a working schedule. Saving a schedule
repairs it.

### `client.community` — logs

| Method | Returns |
|---|---|
| `member_access_logs(account_community_id, *, window="last_30")` | `MemberAccessLogPage` |
| `access_log(*, page=0)` | `AccessLogPage` |
| `gate_status_log(*, page=0)` | `GateStatusLogPage` |
| `iter_access_log(*, start_page=0)` | iterator of `AccessLogEntry` (walks pages) |
| `iter_gate_status_log(*, start_page=0)` | iterator of `GateStatusLogEntry` |

`window` is one of `"last_30"`, `"30_60"`, `"60_90"`. The community-wide log
methods are paginated 1000 rows per page; the `iter_*` helpers walk every page
for you (and are `async for` iterators on the async client).

Every response object keeps the full decoded JSON on `.raw`, so any field not
yet surfaced as a typed attribute is still available.

---

## Error handling

Every non-2xx response raises a typed exception carrying the API's error
envelope (`code`, `message`, `request_id`, `status_code`).

```python
from nimbio_community_api import (
    NimbioClient, RateLimitError, PermissionDeniedError, GateNotOpenedError,
    APIError,
)

with NimbioClient("nimbio_live_...") as client:
    try:
        client.community.open("latch-id-123")
    except GateNotOpenedError:
        print("Gate did not confirm the open in time (504).")
    except PermissionDeniedError as e:
        print("Not allowed:", e.code)         # e.g. "open_denied"
    except RateLimitError as e:
        print("Slow down, retry after", e.retry_after, "s")
    except APIError as e:
        print(e.status_code, e.code, e.message, e.request_id)
```

Exception hierarchy:

```
NimbioError
├── NimbioConfigError            # missing key / bad environment (no request made)
├── APIConnectionError           # DNS/TCP/TLS failure
│   └── APITimeoutError          # request timed out
└── APIError                     # any HTTP >= 400 (has .status_code, .code, .request_id)
    ├── BadRequestError          # 400
    ├── AuthenticationError      # 401
    ├── PermissionDeniedError    # 403 (wrong scope, open denied, ...)
    ├── NotFoundError            # 404
    ├── RateLimitError           # 429 (has .retry_after)
    ├── GateNotOpenedError       # 504 did_not_open
    ├── UpstreamError            # 502 / 503
    └── ServerError              # other 5xx
```

---

## Bring your own HTTP client

Pass an existing `httpx` client to share connection pools, proxies, or custom
transports (useful for testing and advanced deployments):

```python
import httpx
from nimbio_community_api import NimbioClient

http = httpx.Client(timeout=10, proxies="http://localhost:8888")
client = NimbioClient("nimbio_test_...", http_client=http)
# You own `http`'s lifecycle when you pass it in; client.close() won't close it.
```

---

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest                                              # respx-mocked, no network
pytest --cov=nimbio_community_api --cov-report=term-missing   # with coverage
ruff check .
mypy
```

Common tasks are wrapped in a `Makefile` (run `make help` to list them):

```bash
make install     # pip install -e '.[dev]'
make test        # run the suite
make check       # lint + type-check + coverage (what CI runs)
make build       # build sdist + wheel
```

To run the suite across every installed Python (3.9–3.13) in isolated envs, use
[`tox`](https://tox.wiki):

```bash
tox              # all interpreters + lint + type
tox -e py311     # a single interpreter
```

The test suite is fully mocked with [`respx`](https://lundberg.github.io/respx/)
— it never touches the network — and covers every endpoint, the model parsers,
the error mapping, retries, and transport edge cases (100% line + branch
coverage; CI enforces a 95% floor).

> Dependency extras: `pip install -e '.[test]'` installs just the test runner;
> `'.[dev]'` adds ruff + mypy on top.

See [`AGENTS.md`](AGENTS.md) for an LLM/agent-oriented usage cheat sheet and
[`examples/`](examples/) for runnable scripts.

## License

MIT — see [LICENSE](LICENSE).

---

**About Nimbio** — [Nimbio](https://nimbio.com) is cellular gate and door access for gated
communities, apartment buildings, and commercial properties. Developer docs and integration guides:
[nimbio.com/developers](https://nimbio.com/developers/).
