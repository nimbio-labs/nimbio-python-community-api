# nimbio-community-api

Official Python client for the **Nimbio community API** ([api.nimbio.com](https://api.nimbio.com)).

Manage a Nimbio community programmatically: read gate status, open gates, add and
manage members and their keys, issue guest access (guest links, keypad codes,
GuestView Entry, short codes), manage NFC tags, diagnose the sense lines behind
gate status, configure gate geofences, send community messages, and pull access,
change and key-usage logs — from sync **or** async Python, with full type hints.

It wraps **every one of the API's 98 documented operations**.

```bash
pip install nimbio-community-api
```

- ✅ **Sync and async** — `NimbioClient` for any script, `AsyncNimbioClient` for asyncio.
- ✅ **Typed** — dataclass response models with autocomplete; ships `py.typed`.
- ✅ **Test vs live** — inferred automatically from your API key.
- ✅ **One dependency** — just [`httpx`](https://www.python-httpx.org/).
- ✅ **Built-in retries**, a clean exception hierarchy, and log pagination helpers.
- ✅ **Conditional requests, on by default** — repeated reads that haven't changed
  come back as `304 Not Modified` and are **refunded from your monthly quota**.

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
| `cache` | — | `True` | Conditional GETs (ETag / `If-None-Match`) — see below |
| `cache_size` | — | `256` | Max cached responses (LRU); only relevant when `cache=True` |
| `integration` | — | `None` | `"<slug>/<version>"` naming the product built on the SDK, e.g. `"home_assistant/0.4.1"`. Sent as `X-Nimbio-Integration` and appended to the User-Agent; a malformed value raises `ValueError` |

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

### Conditional requests (on by default)

This API is built for polling, and most of its GETs support conditional
requests. The client uses them automatically: it remembers the `ETag` of every
GET response that carries one, sends it back as `If-None-Match` on the next
identical read, and when the server answers `304 Not Modified` it replays the
stored body.

**A 304 refunds your monthly quota.** That is the point: a dashboard polling
gate status every ten seconds pays for the reads where something *changed*, not
for the ones where nothing did.

```python
client = NimbioClient("nimbio_live_...")

while True:
    status = client.community.gate_status()   # 304s cost no monthly quota
    render(status)
    time.sleep(10)

print(client.cache_stats())
# CacheStats(hits=341, misses=7, entries=1)
```

Three things worth knowing:

- **The per-minute rate limit is still charged.** Only the monthly quota is
  refunded. A 304 is a real request that did real work upstream, and that limit
  exists to protect the server — caching is not permission to poll faster.
- **The saving is on the wire, in the parse and in the quota — not in
  latency.** The API computes the ETag from the response body, so the backend
  still does the work; you just don't pay for or download the result.
- **It can never serve you stale data**, because it never answers without
  asking. `Cache-Control: max-age` is deliberately ignored — every read still
  goes to the server, and the cache supplies a body only when the server itself
  says nothing changed. That is also why no cache invalidation is needed after a
  write: the next read revalidates anyway.

A 304 is invisible: the returned object is a freshly parsed, independent value,
indistinguishable from a 200's, so mutating one result can never affect another.

`/v1/me`, `/v1/events/stream` and the call log are never cacheable server-side
(`/v1/me`'s payload *is* your live usage counters, so an ETag could never
match). The client doesn't hardcode any of that — it simply caches what the
server offers an ETag for, so it stays correct as the API changes.

Opting out and tuning:

```python
client = NimbioClient(api_key, cache=False)     # off entirely
client = NimbioClient(api_key, cache_size=32)   # smaller LRU bound
stats = client.cache_stats()                    # .hits / .misses / .entries
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

### `client.account` — your keys, open history and GuestView calls

These need an **account-scoped** key (a community key raises
`PermissionDeniedError`, code `not_account_key`).

| Method | Returns | Description |
|---|---|---|
| `keys(*, include_hidden=False)` | `list[AccountKey]` | Your keys, latches nested |
| `open(key_id, latch_id, *, note=None, idempotency_key=None)` | `OpenResult` | Open one of your gates |
| `stream_events(*, events=None, last_event_id=None, reconnect=True)` | iterator of `StreamEvent` / `StreamReset` | Live events about *you*: `directory_call.ringing`, `directory_call.ended` |
| `directory_calls(*, limit=20, before=None)` | `DirectoryCallPage` | GuestView calls that rang you, newest first; pass `.next_before` back as `before` |
| `iter_directory_calls(*, limit=20, before=None)` | iterator of `DirectoryCall` | Walks every page |
| `history(*, date_from=None, date_to=None, key_id=None, page=0)` | `OpenHistoryPage` | Opens on your keys (including keys you shared), newest first, 1000 per page |
| `iter_history(*, date_from=None, date_to=None, key_id=None, start_page=0)` | iterator of `AccountOpen` | Walks every page of the window |

Your open history is the app's History tab: every open on a key you own,
including opens on keys you shared with someone else, filed under *your* key.
`date_from`/`date_to` take a date or an ISO-8601 datetime; omit both for the
last 90 days (the retention floor). `opened_by.is_you` says whether you opened;
otherwise `opened_by.name` is who did, and `guest_link` is set for a guest-link
open. `open_type` and `result` are open vocabularies (`OPEN_HISTORY_TYPES` /
`OPEN_HISTORY_RESULTS` list the known names).

```python
with NimbioClient("nimbio_live_...") as client:   # an account key
    for row in client.account.iter_history(date_from="2026-10-01"):
        who = "You" if row.opened_by.is_you else (row.opened_by.name or "Someone")
        print(row.id, row.opened_at, row.latch.name, who, row.result)
```

To keep a local copy current, poll with `date_from` set about a minute behind
the newest row you hold and upsert by `id`, which is stable. A fresh open's
`result` arrives up to ~18s after the open (it reads `"unknown"` until then),
so a row you already stored can change.

Directory call events reach an account only once the feature is released for
it: until then both calls raise `NotFoundError` (`feature_not_enabled`), and
`client.me().key.has_capability("directory_call_events")` is False.

Ring a doorbell in your script when someone calls you from GuestView:

```python
from nimbio_community_api import NimbioClient
from nimbio_community_api.models import (
    DirectoryCallEnded, DirectoryCallRinging, StreamReset)

with NimbioClient("nimbio_live_...") as client:   # an account key
    for evt in client.account.stream_events():
        if isinstance(evt, StreamReset):
            continue  # missed a gap; client.account.directory_calls() has it
        if evt.type == "directory_call.ringing":
            call = DirectoryCallRinging.from_event(evt)
            who = (call.caller and call.caller.display_name) or "A visitor"
            gate = call.latch.name if call.latch else call.community.name
            ring_doorbell(f"{who} is calling from {gate}")
        elif evt.type == "directory_call.ended":
            ended = DirectoryCallEnded.from_event(evt)
            stop_ringing(ended.directory_call_id, ended.outcome)
```

`caller` is None for an anonymous guest; a signed-in caller may still have
either name missing. `outcome` (`opened`, `answered`, `missed`) is open — a
newer server may add a value, so keep a fallback branch. Answering still
happens in the Nimbio app; the stream only tells you the phone is ringing.
The stream reconnects and resumes exactly like `community.stream_events()`.

### `client.community` — reads

| Method | Returns |
|---|---|
| `info()` | `CommunityInfo` — identity, feature flags, latch ids, timezone. **Call this first** |
| `gate_status()` | `GateStatus` — latest sensed state per latch |
| `members()` | `Members` — accepted / unaccepted / removed |
| `members_page(*, bucket="accepted", page=1, size=100, search=None)` | `MembersPage` — one bucket, paged (1-indexed) and searchable |
| `member(account_community_id)` | `Member` — one member, with the `bucket` they are in |
| `messages(*, limit=50, offset=0)` | `MessagesPage` — messages already sent, newest first |
| `key_statuses()` | `KeyStatuses` — live key + latch state, hold-opens |
| `keys()` | `list[CommunityKey]` — keys with their access restrictions |

`info()` is the bootstrap read: `latch_id` values come from `info().latches`,
and `info().feature("hold_opens")` is how you branch **before** calling
something instead of interpreting a 403. Every time on this API is in the
community's local clock, which lives on its hardware — `info().timezone` is the
zone every latch agrees on, or `None` when they differ (then use each latch's
own). It is quota-exempt, so call it on startup and on every config refresh.

`members_page()` filters before it pages, so `total` counts the matches and
paging through a `search` never skips anyone. Prefer it over `members()` when
polling a large community: it ships far less data, and far fewer phone numbers.

### `client.community` — writes

| Method | Returns |
|---|---|
| `open(latch_id, *, note=None, idempotency_key=None)` | `OpenResult` |
| `message(message)` | `WriteResult` |
| `add_member(phone_number, key_ids)` | `WriteResult` |
| `approve_member(account_community_id, key_ids, *, move_out_date=None, dry_run=None)` | `WriteResult` |
| `grant_keys(account_community_id, key_ids)` | `WriteResult` |
| `revoke_keys(account_community_id, key_ids, *, remove_member=False)` | `WriteResult` |
| `set_keys_disabled(account_community_id, key_ids, disabled)` | `WriteResult` |
| `update_key(key_id, *, name=None, disabled=None)` | `KeyUpdateResult` — rename or disable a community key |

`approve_member()` closes the loop opened by the `member.requested` webhook —
the member is accepted, granted a key per id in `key_ids`, pushed to, and a
`member.approved` webhook fires. Approving someone already approved raises
`ConflictError` (409 `already_accepted`).

`update_key()` applies only the fields you send, so a rename never clobbers
`disabled`. **Disabling a community key denies every member key descended from
it** — sharing mints a child key, and disabled state is inherited down that
chain — so read `.descendant_key_count` on the result before you do it.

### `client.community` — bulk member writes

One request, many members — the roster-sync path. Every one takes `items`
(at most 100) and answers **207** with one entry per item, in request order.

| Method | Returns |
|---|---|
| `bulk_add_members(items)` | `BulkResult` — items are `{"phone_number", "key_ids"}` |
| `bulk_grant_keys(items)` | `BulkResult` — items are `{"account_community_id", "key_ids"}` |
| `bulk_revoke_keys(items)` | `BulkResult` — same item shape |
| `bulk_set_keys_disabled(items, disabled)` | `BulkResult` — `disabled` applies to the whole batch |

```python
result = client.community.bulk_grant_keys([
    {"account_community_id": 4021, "key_ids": ["KEY_ID"]},
    {"account_community_id": 4022, "key_ids": ["KEY_ID"]},
])
result.summary            # BulkSummary(total=2, succeeded=1, failed=1)
for item in result.failures:
    print(item.account_community_id, item.code, item.message)
```

**A 207 does not mean every item succeeded.** The batch was processed; each
item carries its own verdict, because the side effects an item fires (a push, a
webhook delivery) cannot be rolled back. Read `.summary.failed` or `.failures`,
never just the status code.

Everything is validated before anything is applied, so a foreign member or key,
an over-size batch or a repeated id rejects the **whole** batch with nothing
changed — that arrives as a raised `APIError` (422), not as a `BulkResult`.
Re-submitting is safe: grants are idempotent, an already-revoked key still
succeeds, and an already-accepted member fails with `already_member` while the
rest of the batch runs. Quota costs one unit **per item**.

### `client.community` — hold opens

| Method | Returns |
|---|---|
| `hold_opens()` | `HoldOpens` — per-latch state, one-time events, recurring schedules |
| `set_hold_open(latch_id, state)` | `ManualHoldOpenResult` — the manual toggle |
| `add_hold_open_event(latch_id, *, start, end)` | `HoldOpenEventAdded` — one-time window |
| `remove_hold_open_event(latch_id, event_id)` | `HoldOpenEventRemoved` — idempotent |
| `add_hold_open_recurring(latch_id, *, days_of_the_week, start_time=None, end_time=None, recurring_week=None)` | `RecurringHoldOpen` |
| `update_hold_open_recurring(latch_id, temporal_date_id, *, days_of_the_week=None, start_time=None, end_time=None, recurring_week=None, clear_times=None)` | `RecurringHoldOpen` |
| `remove_hold_open_recurring(latch_id, temporal_date_id)` | `RecurringHoldOpenRemoved` |
| `set_hold_open_disabled_until(latch_id, until)` | `HoldOpenDisabledUntil` — suspend/resume all schedules |

All of these need the community's Hold Opens feature; without it they raise
`PermissionDeniedError` (403 `hold_opens_disabled`). Check
`info().feature("hold_opens")` first.

```python
# Business hours at the front gate, in the gate's own local time.
schedule = client.community.add_hold_open_recurring(
    "LATCH_ID", days_of_the_week="MTWHF", start_time="08:00", end_time="18:00")

# Closed for the holiday — every schedule on this latch, suspended.
client.community.set_hold_open_disabled_until("LATCH_ID", "2026-12-26 06:00")
client.community.set_hold_open_disabled_until("LATCH_ID", None)   # resume now

client.community.remove_hold_open_recurring("LATCH_ID", schedule.temporal_date_id)
```

- `days_of_the_week` is letters from `MTWHFSU` — **`H` is Thursday**, `S`
  Saturday, `U` Sunday. A 1–127 bitmask is also accepted.
- Times are `'HH:MM'` **in the latch's own local time** (the `timezone` that
  `hold_opens()` reports for it), never UTC and no offset accepted. Omit both
  for an all-day schedule.
- A window **may not wrap past midnight**: `22:00`–`06:00` is refused. Split it
  into `22:00`–`24:00` plus `00:00`–`06:00`, and use `'24:00'` rather than
  `'23:59'` so the two halves leave no gap.
- `update_hold_open_recurring()` is a partial update. Times are explicit:
  `start_time` + `end_time` replace the window, `clear_times=True` removes it
  (making the schedule all-day), sending neither leaves it alone.
- `remove_hold_open_recurring()` is **deliberately not idempotent** — an id
  that is not on this latch raises `NotFoundError`, because succeeding silently
  would let you believe you had cancelled a schedule that is still holding a
  gate open.
- `until` is `'YYYY-MM-DD HH:MM'` in the latch's local time and is **required**:
  pass `None` to resume, so an empty body can never resume by accident. It is
  per latch, not per community.

### `client.community` — access schedules

Limit **when** the community's keys may open their gates.

**Community keys only.** A schedule on a community key *is* the community-wide
rule — it applies to every member key beneath it. An individual member's key
cannot be read or scheduled here and is refused with `not_a_community_key`
(403).

| Method | Returns |
|---|---|
| `key_schedules()` | `KeySchedules` — the community's own key(s), with only the windows in force today; `.blocked` lists keys denied at all times |
| `key_schedule(key_id)` | `KeySchedule` — every window, expired ones included, since a write replaces the whole schedule |
| `set_key_schedule(key_id, windows)` | `KeySchedule` — replaces the **whole** schedule; `[]` removes the restriction |

```python
from nimbio_community_api import models

# Weekday daytime access only, for everyone in the community.
community_key = client.community.key_schedules().keys[0]
client.community.set_key_schedule(community_key.key_id, [
    models.ScheduleWindow("MTWHF", "06:00", "18:00"),
])

# Remove every restriction.
client.community.set_key_schedule(community_key.key_id, [])
```

`descendant_key_count` is how many **live** member keys inherit the restriction —
check it before writing one. `inactive_window_count` (list only) is how many
windows were filtered out as expired.

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

### `client.community` — settings & feature discovery

| Method | Returns |
|---|---|
| `settings()` | `CommunitySettings` — the settable configuration, plus the `read_only` flags Nimbio provisions |
| `update_settings(settings)` | `CommunitySettings` — partial update; `.changed` names the keys applied |

```python
s = client.community.settings()

if s.feature("allow_hold_opens"):          # read_only flag
    client.community.hold_opens()

client.community.update_settings({
    "allow_directory_viewing": True,
    "member_term_custom": "Tenant",
    "member_term_custom_plural": "Tenants",
})
```

`read_only` is the reason to call the read: several endpoint families are gated
on those flags, and **without this call the only way to learn a feature is off
is to call it and get a 403**. `allow_hold_opens` false 403s the hold-open
family, `is_open_log_history_enabled` false 403s `access_log()` and
`gate_status_log()`, and `event_keys_enabled` is the *resolved* answer for event
keys — the settable `event_keys_override` (`inherit`/`allow`/`deny`) combined
with the property type's default. Use `.feature(name)`; an unknown flag reads
`False`.

Those flags and the two per-community caps (`event_key_max_window_hours`,
`limited_use_link_max_uses`) are provisioning decisions, not a gap in the API —
nobody changes them from the CM portal either. Sending one to
`update_settings()` is a 422 `invalid_setting` telling you to contact support.

Three rules for the patch:

- **It is all-or-nothing.** Only the keys you send are applied, but the whole
  patch is validated before anything is written, so a batch with one bad value
  applies **nothing**. You never have to reason about a half-applied profile.
- **An unknown key is rejected, never ignored** — 422 `invalid_setting` naming
  it. A typo cannot silently do nothing.
- **A custom label and a picker option are mutually exclusive per side.**
  Setting `member_term_custom` clears `member_terminology_option_id` and vice
  versa. Labels cap at 255 characters, icons at 64, control characters are
  refused, and `""`/`None` clears a custom label back to the default.

Unlike `info()`, `settings()` **is not quota-exempt** — it is setup-time
configuration, not something to poll.

### `client.community` — homes (unit roster)

The unit roster a property-management system treats as its system of record.

| Method | Returns |
|---|---|
| `homes(*, include_hidden=True)` | `list[Home]` — every unit with its resident count, by address |
| `add_home(home_address)` | `Home` — the created unit, whole |
| `home(home_id)` | `Home` — one unit **plus its residents** (`.members`) |
| `update_home(home_id, *, home_address=None, owner_occupied=None, hidden=None)` | `Home` — partial update |
| `remove_home(home_id)` | `HomeRemoved` — **detaches every resident** |
| `set_move_out_date(account_community_id, move_out_date)` | `MoveOutDate` — `None` clears |

```python
home = client.community.add_home("12 Elm St, Unit 3")
client.community.update_home(home.home_id, owner_occupied=True)

# Access lapses on its own instead of a CM remembering to revoke it.
client.community.set_move_out_date(4021, "2026-12-31")
client.community.set_move_out_date(4021, None)          # clear
```

`include_hidden` defaults to **true** — a roster sync wants the whole set; pass
`False` to match the portal's list. `.members` is populated only by `home()`;
the list read reports `member_count` alone.

`hidden` on `update_home()` is a **setter, not a toggle**, so a retried PATCH is
safe. Hiding a unit that still has residents attached is 409 `home_occupied`.

**`remove_home()` detaches every resident, irreversibly.** They stay members and
keep their keys, but they are no longer associated with any unit and *nothing
restores the association automatically* — you would have to re-add the home and
re-attach each resident by hand. The result reports `detached_member_count`;
call `home(home_id)` first if you want the blast radius before you commit:

```python
before = client.community.home(home_id)
if len(before.members) == 0:
    client.community.remove_home(home_id)
```

A test key reports the count it *would* detach and changes nothing.

### `client.community` — my notification settings

Member-open alerts and the quiet hours that suppress them.

| Method | Returns |
|---|---|
| `my_notification_settings()` | `NotificationSettings` — this manager's alerts + quiet hours |
| `set_my_notifications_enabled(enabled)` | `NotificationSettings` |
| `add_quiet_hours(days_of_the_week, start_time=None, end_time=None)` | `NotificationSettings` — appends one window |
| `remove_quiet_hours(quiet_hours_id)` | `NotificationSettings` — removes one window |

**These are scoped per community manager, not per community.** An API key acts
as its owning manager, so all four read and write *that person's* settings. A
community with several managers has several independent settings objects: two
keys owned by two managers of the same community return two different objects,
and turning `enabled` off through one does **not** stop the other's alerts.

All four return the **full** object, quiet hours included, so nothing needs a
follow-up read. `feature_available` false means the community disallows
member-open notifications entirely — all three writes then 403
`open_notifications_disabled`, and `enabled` has no effect.

```python
client.community.set_my_notifications_enabled(True)

# One window, 22:00 to 06:00 — it wraps past midnight on purpose.
settings = client.community.add_quiet_hours("MTWHF", "22:00", "06:00")
settings.quiet_hours[0].wraps_midnight        # True

client.community.remove_quiet_hours(settings.quiet_hours[0].quiet_hours_id)
```

**The midnight rule here is the opposite of the one on schedules.** The same
`'HH:MM'` field obeys three different rules across this API:

| Surface | Wraps past midnight? | `"24:00"` accepted? |
|---|---|---|
| `set_key_schedule()` | **No** — send two windows | n/a |
| `add_hold_open_recurring()` | **No** — split, using `"24:00"` | **Yes** |
| **`add_quiet_hours()`** | **Yes** — `22:00`–`06:00` is ONE window | **No** |

Carrying the hold-open idiom across fails **silently**: you get a window that
never suppresses anything. A `start_time` equal to its `end_time` is refused
too (422 `invalid_time`) — a zero-length window suppresses nothing. Omit both
times for an all-day window.

Quiet hours are **evaluated in the local timezone of the gate that was
opened** — each device carries its own — not the manager's timezone and not
UTC. A community with gates in two timezones suppresses each gate's alerts on
that gate's own clock. Getting this backwards is the other way a window
silently fails to suppress real alerts, so state it in your own UI too.

Windows are **additive**: one `add_quiet_hours()` appends one window, one
`remove_quiet_hours()` removes one. To replace a schedule, delete the windows
you no longer want. A `quiet_hours_id` belonging to a different manager —
including another manager of the same community — is 404 and deletes nothing.

### `client.community` — guest links

Access for someone who has no Nimbio account: a booking system can issue a
guest's gate link the moment a reservation is confirmed and kill it at
checkout, with nobody opening the portal.

| Method | Returns |
|---|---|
| `guest_links(*, include_inactive=True)` | `list[GuestLink]` — **includes working URLs** |
| `create_guest_link(link_type, latch_ids, *, key_id=None, title=None, subtitle=None, extra_info=None, max_uses=None, expires_at=None, window_start=None, window_end=None, notify_on_use=None)` | `GuestLink` |
| `revoke_guest_link(guest_link_id)` | `GuestLink` — **terminal, no un-revoke** |
| `guest_link_logs(*, guest_link_id=None, limit=50, offset=0)` | `GuestLinkLogPage` — guest PII |
| `guest_link_latch_exclusions()` | `GuestLinkLatchExclusions` — read-only |

> ⚠️ **A leaked listing is a leaked set of working gate links.** `token` and the
> ready-to-send `url` come back from **`guest_links()` as well as from
> `create_guest_link()`** — a link recovered from the list is exactly as usable
> as a fresh one. Anyone holding the URL can open the gate: no account, no key,
> no login. **Treat this response like a password and do not log it.** Logging
> responses at debug level is an ordinary thing to do, and it would write
> working gate links to disk.

That the list returns them is deliberate — it makes a lost URL recoverable —
which is exactly why the read deserves the same care as the write. `GuestLink`
keeps `token` and `url` out of its `repr` so a stray `print()` cannot leak one,
but `.raw` and any `json.dumps()` of it still carry them.

```python
link = client.community.create_guest_link(
    "limited_use", [latch_id], max_uses=4, title="Booking 8841 — Unit 4")
send_to_guest(link.url)                      # do not log this

# At checkout. Terminal — mint a new link to restore access.
client.community.revoke_guest_link(link.guest_link_id)
```

**The two link types take different limits.**

| `link_type` | Requires | Limit |
|---|---|---|
| `"event"` | `title`, `window_start`, `window_end` | Unlimited opens inside the window; the window may not exceed the community's cap (**8 hours** unless raised) nor have already ended |
| `"limited_use"` | `max_uses` | 1 to the community's cap (**20** by default); optional `expires_at` backstop defaults to — and is capped at — **30 days** |

**Datetimes** are ISO-8601. An offset (including `Z`) is honoured and **a naive
string is read as UTC** — communities carry no timezone of their own — and
everything returned is UTC. A datetime that does not parse is rejected outright
rather than quietly treated as absent.

`key_id` names the community key behind the link and may be omitted only when
the community has exactly one; that choice decides which gates the link could
ever reach. Every id in `latch_ids` must be openable by that key and must not
be excluded for the link type.

`.state` is computed live — `active`, `upcoming`, `expired`, `spent`,
`revoked`, or `feature_disabled` — so branch on it rather than re-deriving it
from timestamps. A spent link is neither revoked nor expired and is still dead.

**Exclusions: absence is permission.** `guest_link_latch_exclusions()` lists the
gates taken out of each link type, so an *empty* answer means every gate the
backing key opens is offerable. The list is **per link type** — a gate barred
from `event` links may still be fine for `limited_use` ones — and naming an
excluded gate is a 422, so check before creating:

```python
excluded = client.community.guest_link_latch_exclusions()
usable = [x for x in latch_ids if not excluded.is_excluded("event", x)]
```

It is **read-only on purpose**. The setter behind it narrows what a link type
may ever cover, which makes it a safety control rather than a configuration
knob, so exposing it to API callers was deliberately deferred — not forgotten.

> **An API key can mint an `event` link even when the community has event keys
> switched off.** That switch aims at *members* — it stops members minting event
> links — and has never applied to a manager acting on the management surface,
> so a settings flip cannot break links a manager handed out for tonight. An API
> key inherits that carve-out. **This is a real widening**: if your integration
> should honour the community setting, read `features.event_keys` from `info()`
> and branch on it yourself. The API will not do it for you.

`guest_link_logs()` is **guest PII** — rows carry the redeemer's IP address and
user agent, plus the display name of a signed-in account when the community
requires one. Handle and retain accordingly.

### `client.community` — access codes

Keypad and GuestView PINs.

| Method | Returns |
|---|---|
| `access_codes()` | `AccessCodes` — every code, **PINs masked** |
| `create_access_code(code, latch_ids, *, expires_in_hours=None, expires_in_days=None, temporal=None)` | `AccessCodeCreated` — **carries the PIN, once** |
| `update_access_code(directory_access_code_id, *, disabled=None, latch_ids=None, expires_in_hours=None, expires_in_days=None, temporal=None)` | `AccessCode` |
| `delete_access_code(directory_access_code_id)` | `AccessCodeDeleted` |
| `access_code_eligible_latches()` | `AccessCodeEligibleLatches` — the allowlist |
| `access_code_logs(*, limit=50, offset=0)` | `AccessCodeLogPage` |
| `access_code_mode()` | `AccessCodeModeStatus` — `per_member` / `single_entry` + `flip_preview` |
| `set_access_code_mode(mode, *, confirm=False)` | `AccessCodeModeChange` — **destructive; 409 until `confirm=True`** |

**The PIN comes back exactly once — from `create_access_code()`.** The list
read returns `code_masked` (asterisks) and `code_length`, and nothing reads the
cleartext back. If you lose a PIN, delete the code and mint a new one.
`AccessCodeCreated` keeps `code` out of its `repr` for the same reason
`GuestLink` hides its token.

```python
eligible = client.community.access_code_eligible_latches()
created = client.community.create_access_code(
    "481502", eligible.latch_ids[:1], expires_in_hours=24)
deliver_to_visitor(created.code)             # the only time you will see it

client.community.update_access_code(          # after the visit
    created.directory_access_code_id, disabled=True)
```

The list includes codes residents made themselves, matching the CM portal.
`.api_managed` is true for the codes **this API key** created, and those are the
only ones `update_access_code()` and `delete_access_code()` will touch — a
resident's code, or one in another community, answers 404 to both. Use
`codes.api_managed` for the subset you can act on.

**Three independent limits, doing different things:**

| Field | What it is | Evaluated in |
|---|---|---|
| `expires_in_hours` / `expires_in_days` | One absolute cutoff, computed **from the moment of the call** | UTC |
| `temporal` | A **recurring weekly** window (e.g. weekdays 09:00–17:00), which never expires on its own | **the gate's own local timezone** |

`expires_in_hours` and `expires_in_days` are **mutually exclusive** (both is a
422). A code may carry a cutoff *and* a weekly window, and then must satisfy
both. Omitting both makes a code that works until it is disabled or deleted.

`temporal`'s keys are `days_of_the_week`, **`start`**, **`end`** and
`recurring_week` — note `start`/`end`, not the `start_time`/`end_time` the
hold-open and GuestView Entry schedules use.

On update, omitted fields are left alone, and **there is no way to clear** an
existing cutoff or weekly window — to stop a code working, disable or delete
it. An empty body is a 400. The PIN itself cannot be changed. Re-sending
`expires_in_days=1` *extends* the code by a day, because the cutoff is
recomputed from now.

Every `latch_ids` entry must appear in `access_code_eligible_latches()` or the
call is rejected with `invalid_latch`. **That allowlist is set in the CM portal
only** — this API reads it and never changes it. `feature_enabled` mirrors the
community's Directory Access Codes setting; when it is false, writes return 403
`access_codes_disabled`.

Deleting a code stops the PIN immediately and takes its gate assignments with
it, but the **redemption log rows stay**, so the history of who came through the
gate survives the code. In `access_code_logs()`, `code_entered_masked` is
asterisks and never the typed digits — a successful attempt's entered code *is*
a working PIN — so correlate rows to your codes through
`directory_access_code_id`.

**Two access-code systems.** `access_code_mode()` says which one the community
runs. In `per_member` (the default) a GuestView visitor picks the member they are
visiting and types that member's PIN. In `single_entry` there is one "Enter
access code" field for the whole community: every member carries a 3-letter
**preamble** and the visitor types preamble + PIN (`ESM481502`). In that mode
list rows carry `preamble` / `entry_code_masked` (and the list itself
`access_code_mode`) and `create_access_code()` returns the full `entry_code` once — hand the visitor `entry_code` when it is
set, `code` otherwise.

**Switching modes deletes every access code in the community** — this key's,
other integrations', and the ones residents made in the app — and notifies the
affected members, so `set_access_code_mode()` is the same two-step handshake as
`update_nfc_tag()`: the first call answers 409 `requires_confirmation` with the
preview on `ConflictError.preview` (also readable up front as
`access_code_mode().flip_preview`), and nothing happens until you repeat with
`confirm=True`. It is deliberately **not** a key of `update_settings()`, which
refuses `access_code_mode` with a 422 pointing here.

```python
try:
    client.community.set_access_code_mode("single_entry")
except ConflictError as e:
    if e.code != "requires_confirmation":
        raise
    preview = models.AccessCodeModePreview.from_dict(e.preview)
    if ask_a_human(f"Delete {preview.codes_to_delete} codes held by "
                   f"{preview.members_affected} members?"):
        client.community.set_access_code_mode("single_entry", confirm=True)
```

### `client.community` — GuestView Entry

Letting a visitor at the gate open it from the community's guest directory.

| Method | Returns |
|---|---|
| `guest_view_entry()` | `GuestViewEntry` — the whole configuration |
| `set_guest_view_entry_enabled(allowed)` | `GuestViewEntry` — setter, not a toggle |
| `set_guest_view_entry_latches(latch_ids)` | `GuestViewEntry` — **REPLACES the whole set** |
| `guest_view_entry_logs(*, limit=50, offset=0, success=None)` | `GuestViewEntryLogPage` — visitor PII |
| `add_guest_view_entry_schedule(latch_ids, days_of_the_week, *, start_time=None, end_time=None)` | `GuestViewEntry` |
| `remove_guest_view_entry_schedule(schedule_id)` | `GuestViewEntry` |

All five return the **complete** settings object, so no write needs a follow-up
read.

> ⚠️ **`set_guest_view_entry_latches()` replaces the whole set** — that is why
> the API makes it a PUT. Any currently-eligible latch you leave out loses guest
> eligibility, **and its schedule windows are deleted along with it**. A caller
> who adds one gate by sending a one-element list silently destroys every other
> gate's schedule.

**Read-modify-write, always.** Build the list from what the read gave you, never
from memory:

```python
entry = client.community.guest_view_entry()
client.community.set_guest_view_entry_latches(entry.latch_ids + [new_latch_id])
```

`set_guest_view_entry_latches([])` removes GuestView Entry from every gate. A
latch outside the community is a 404 and nothing is written; the call requires
the feature to be on (403 `guest_view_entry_disabled` otherwise).

`set_guest_view_entry_enabled()` is an explicit **setter, not a toggle** — the
call is retryable, and a retried toggle would flip guest access back open.
Turning it off leaves the eligible-latch set and the schedule intact, so it is
the safe way to suspend guest access without losing the setup.

**The schedule is a whitelist of permitted times, so a latch with NO windows is
guest-accessible at any hour.** The first window you add is what starts
restricting it, and removing a latch's *last* window opens it back up around the
clock — removing a window **widens** access.

```python
# 9-to-5 at the front gate, in the gate's own local time.
client.community.add_guest_view_entry_schedule(
    [latch_id], "MTWHF", start_time="09:00", end_time="17:00")

entry = client.community.guest_view_entry()
client.community.remove_guest_view_entry_schedule(entry.schedule[0].schedule_id)
```

Each window is **evaluated in its latch's own local timezone**, at the moment a
visitor taps open — never UTC, never yours, never the community's.
`09:00`–`17:00` on a Los Angeles gate is 9-to-5 Pacific; the same window on a
New York gate is 9-to-5 Eastern. A latch whose timezone cannot be resolved skips
the check and stays available around the clock.

**The midnight rule here matches quiet hours, not schedules.** The same
`'HH:MM'` field obeys different rules across this API:

| Surface | Wraps past midnight? | `"24:00"` accepted? |
|---|---|---|
| `set_key_schedule()` | **No** — send two windows | n/a |
| `add_hold_open_recurring()` | **No** — split, using `"24:00"` | **Yes** |
| `add_quiet_hours()` | **Yes** — one window | **No** |
| **`add_guest_view_entry_schedule()`** | **Yes** — one window | **No** |

So `22:00`–`06:00` here is a single overnight window, and the days name the day
the window **starts** on. Times run `00:00`–`23:59`; `end_time=None` leaves the
window unbounded at the end. `days_of_the_week` is letters from `MTWHFSU` —
**H is tHursday, U is sUnday** — with no repeats and at least one day.

`guest_view_entry_logs()` rows **identify visitors**: name, phone number and
client IP of the person who stood at the gate. They read whether or not the
feature is currently on, so history survives it being switched off.

### `client.community` — short codes

The code on a gate placard that opens the community's guest directory.

| Method | Returns |
|---|---|
| `short_codes()` | `list[ShortCode]` |
| `create_short_code(*, code=None, latch_id=None)` | `ShortCode` — **permanent** |
| `assign_short_code(code, latch_id)` | `ShortCode` — **detaches the previous gate** |

```python
placard = client.community.create_short_code(latch_id=front_gate_id)
print(placard.short_code)                    # e.g. "Kp7Rx2Q"

# Moving the sign's code to a different gate, without reprinting the sign.
client.community.assign_short_code(placard.short_code, service_entrance_id)
```

> ⚠️ **`assign_short_code()` silently detaches the gate the code pointed at
> before.** Assignment is exclusive — a code routes to exactly one gate — and
> nothing warns you that the old gate just lost its code. The change takes
> effect for the next visitor who types it. Read `short_codes()` first if you
> need to know what you are about to detach.

Omit `code` and the server generates one (7 letters and digits), as the portal
does. Supply `code` to claim a specific one: 6–10 letters and digits, and
**short codes are unique across all of Nimbio, not just your community** — a
code in use anywhere raises `ConflictError` (409 `short_code_taken`), including
one differing only in letter case, since a placard is read by a person.
Generation retries on collision, so the generated path effectively never 409s.

**There is no way to delete a short code** — not through this API, and not
through the portal. A code you mint is permanent.

`latch_id` is optional on create and is `None` for a code that routes to the
directory without preselecting a gate. On assign, an unknown code and a code
owned by a different community both answer 404 `short_code_not_found`: the
namespace is global, so the API deliberately gives no way to tell those apart,
let alone to seize someone else's code.

### `client.community` — NFC tags

The fobs and cards that open a gate by being tapped against it.

| Method | Returns |
|---|---|
| `nfc_tags(*, search=None, page=1, results_per_page=50)` | `NfcTagPage` (1-based paging) |
| `nfc_tag(tag_id)` | `NfcTag` |
| `update_nfc_tag(tag_id, *, disabled=None, latch_id=UNSET, confirm=None)` | `NfcTag` — assign, unassign **or** disable |
| `nfc_scan_log(*, limit=50, offset=0, result=None, tag_uid_hex=None)` | `NfcScanLogPage` — every tap |

```python
# Kill a lost fob. `disabled` is a setter, never a toggle, so this never
# depends on state you read a moment ago — and re-sending it is a no-op.
try:
    client.community.update_nfc_tag(tag_id, disabled=True)
except ConflictError as e:
    if e.code != "requires_confirmation":
        raise
    # A Scan Only gate would be left with no working tag. That is a WARNING,
    # not a veto — revoking a stolen fob has to stay possible.
    client.community.update_nfc_tag(tag_id, disabled=True, confirm=True)
```

> ⚠️ **A write that would leave a Scan Only gate with no working tag answers
> 409 `requires_confirmation`.** Catching `ConflictError` and repeating the call
> with `confirm=True` is the intended flow, not an error path to log and bail
> out of.

One PATCH does all three jobs. Send `disabled`, `latch_id`, or both — neither is
422 `empty_patch`:

- `disabled=True` kills a fob and **takes effect for physical gate taps**: the
  next tap on any gate is refused. `disabled=False` revives it.
- `latch_id="<gate id>"` binds the tag to one of your gates — a tag opens the
  gate it is bound to, not a member's key. `latch_id=None` **detaches** it; the
  tag stays in the community for later reassignment. Omitting the argument
  leaves the binding alone, which is why its default is the `UNSET` sentinel
  rather than `None`.
- **Order matters when both are sent:** `disabled` is applied first, so
  `disabled=False, latch_id=...` revives and then binds in one call, while
  `disabled=True, latch_id=...` is refused 422 `conflicting_fields` — a dead fob
  cannot be routed to a gate.

`tag_uid_hex` is the fob's **physical, publicly readable UID — not a secret**.
It is how you join a tag to its rows in `nfc_scan_log()`. No cryptographic tag
material is ever returned by this API, `notes` are reported but cannot be set
here, and programming a blank fob is a separate operator-side job with a card
reader. An unknown tag and another community's tag are both 404
`tag_not_found`, so the API never confirms someone else's tag exists.

Scan-log rows carry the tapping member's first and last name where the tap
resolved to one (`.member_name`), which is what lets a security review
attribute a tap; the device's IP address and Nimbio-internal record ids are not
exposed.

### `client.community` — sense lines

The physical inputs that report whether a gate actually moved — the feedback
loop behind `gate_status()`, the gate-status log, and `sense_line.changed`.
**This is the surface that answers "why does this gate always report closed?"**

| Method | Returns |
|---|---|
| `sense_lines(*, box_id=None)` | `SenseLines` — `box_id` is an optional filter |
| `sense_line(sense_line_id, box_id)` | `SenseLine` — **`box_id` is required** |
| `update_sense_line(sense_line_id, box_id, *, sense_line_online=None, latch_data_online=None)` | `SenseLine` — **`box_id` is required** |
| `sense_line_records(*, box_id=None, sense_line_id=None, limit=50, offset=0)` | `SenseLineRecordPage` — raw transitions |

```python
# The one-line diagnosis: which inputs change nothing when they transition?
for line in client.community.sense_lines().not_reporting:
    print(line.box_name, line.sense_line_id,
          line.sense_line_online, line.latch_data_online)
```

Each sense line has two configuration flags and one derived answer:

- **`sense_line_online`** — whether the input is switched on at all. Off means
  raw transitions are **still recorded** (see `sense_line_records()`) but the
  server acts on none of them.
- **`latch_data_online`** — whether its readings may drive the gate status
  reported to the apps and to this API.
- **`reporting`** — true only when both are on, which is exactly the condition
  for a transition to update gate status or fire `sense_line.changed`. **A gate
  stuck on one status whose input has `reporting: False` is a configuration
  problem, not a stuck gate.**

`box_id` is **required** on `sense_line()` and `update_sense_line()` and
positional for that reason: a sense line id is an *input number on a board*,
unique only within its box, so two boxes in one community both have a "sense
line 1". Omitting it is a 422 `box_id_required`, not a guess at which box you
meant. On the two list reads it is a genuine filter — omit it for every box.

> ⚠️ **Switching either flag off freezes that gate's status at its last known
> value** — for every app, for `gate_status()`, and for the `sense_line.changed`
> event — and it affects hold-open logic that reads gate state. Turning a
> miswired input off is a legitimate repair; doing it by accident is not.

The PATCH writes **configuration only**, each value an explicit set rather than
a toggle (omitting both is 422 `no_fields`). The state → label wiring
(`status_map`) and the creation of sense lines are installer operations, and the
observed gate state itself is what the hardware reports — deliberately not
something an API key can fabricate.

`sense_line_records()` returns the **raw** transitions, and matters for one
specific reason: **rows are written even when a sense line is switched off**, so
a healthy stream here alongside a stale `gate_status()` is proof the wiring is
fine and the configuration is not. `status` is `None` when a state has no
configured meaning — an unmapped state is itself a finding, so those rows are
returned rather than dropped (`.unmapped` collects them). For the
human-readable, latch-oriented version of the same history, use
`gate_status_log()`.

### `client.community` — map and geofences

| Method | Returns |
|---|---|
| `map()` | `CommunityMap` — gates, coordinates, geofence config |
| `update_geofence(latch_id, *, enabled=None, latitude=None, longitude=None, radius_meters=None, mode=None)` | `MapLatch` |

```python
m = client.community.map()
for latch in m.unconfigured:                 # never had a fence centre
    centre = latch.suggested_center          # the device's own location
    client.community.update_geofence(
        latch.latch_id, latitude=centre.latitude, longitude=centre.longitude,
        radius_meters=m.min_radius_meters, mode="prompt", enabled=True)
```

> ⚠️ **A radius below `min_radius_meters` (100) is rejected with 422
> `radius_below_minimum` — not silently raised.** Android's Geofence API and
> iOS region monitoring both degrade below roughly 100 m, so a smaller fence
> would read as configured and never fire. **Do not "fix" this by clamping
> client-side**; the response echoes the effective `radius_meters` so you can
> confirm what is in force.

Coordinates are **WGS84 decimal degrees**; `radius_meters` is **metres**. Read
`min_radius_meters` and `geofence_modes` from the map response rather than
hardcoding them — they are what the server will enforce. `mode` is `prompt`
(notify on arrival, the member taps to open) or `auto_open`.

The write is a **partial update**, which is why it is a `PATCH`: only the fields
you send change. `latitude` and `longitude` move together — send both or
neither — and there is deliberately **no way to clear a configured centre**
here, because a silent clear would disable proximity behaviour on a real gate
with nothing to show for it. A body with nothing to change is 400
`nothing_to_update`.

A gate whose `geofence.center` is `None` has never had a fence configured; use
its `box_location` (or `.suggested_center`, which picks for you) as the starting
point.

> 🔒 **Gate coordinates are physical-security information.** This response says
> exactly where a property's entrances are. It is scoped to your community key;
> treating it as sensitive downstream is on you. Note also that **the map read
> consumes monthly quota**, unlike `gate_status()` — it is setup-time
> configuration that changes when a human moves a pin, not a poll substitute.

### `client.community` — change log and key usage

| Method | Returns |
|---|---|
| `change_logs(log_type, *, days=30, limit=500, offset=0)` | `ChangeLogPage` — configuration audit trail |
| `key_usage(date_from, date_to, *, page=0)` | `KeyUsageReport` — per-key usage history |

`change_logs()` is the **configuration** trail — who changed what, when. For the
*access* trail (who opened which gate) use `access_log()`; for physical
open/closed transitions use `gate_status_log()`. The two are easy to confuse: an
access log tells you a gate opened, this tells you someone rewrote the schedule
that let it open.

`log_type` is required and selects exactly one of four trails (see
`CHANGE_LOG_TYPES`): `hold_open`, `key_schedule`, `guest_view` or `guest_link`.
A `days` look-back above the 30-day retention cap is **clamped, not rejected**,
so read `.days` / `.date_from` / `.date_to` for the window actually used.

```python
report = client.community.key_usage("2026-06-01", "2026-06-10")
for row in report:
    who = row.user if not report.residential else f"{row.user} (household)"
```

> ⚠️ **Read `report_type` before reading any row's `user`.** Nimbio attributes an
> open differently by property type and **the server decides which rule
> applies** — there is no parameter for it, because getting it wrong would
> misreport who opened a gate. `"commercial"`: `user` is the **actual opener's**
> name. `"residential"`: `user` is `"<master key owner> Keychain"` — every open
> on a household's keys is attributed to the account holder, so you cannot tell
> which member of the household opened the gate. That groups; it does **not**
> anonymize — the account holder is named.

Dates are inclusive `'YYYY-MM-DD'` **in the community's own timezone**, not
yours (`.timezone` reports it). A window longer than `.max_range_days` is
clamped: `.clamped` says so, `.date_from`/`.date_to` are what was read, and
`.requested_from`/`.requested_to` what you asked for. Rows carry personal data
beyond `user` — `phone` and `location`.

### `client.community` — webhook deliveries

| Method | Returns |
|---|---|
| `webhook_deliveries(webhook_id, *, limit=50)` | `list[WebhookDelivery]` — attempts, newest first |
| `retry_failed_deliveries(webhook_id, *, since=None, limit=50)` | `DeliveryReplayBatch` — re-send every `failed` delivery |
| `replay_delivery(webhook_id, delivery_id)` | `DeliveryReplay` — re-send one |

`webhook_deliveries()` is how you tell a silently-broken receiver from one
Nimbio never fired at: `status` is `pending`/`delivered`/`failed`, and
`last_status_code` / `last_error` describe the most recent attempt.
`last_error` includes the first part of **your own** endpoint's response body,
which is worth knowing if your error pages carry anything sensitive.

> **A replay re-sends the original event, byte for byte.** The `event_id` is the
> original's — and the `X-Nimbio-Delivery` header carries the **event** id, not
> the delivery id. A consumer that de-duplicates on that header handles a replay
> correctly; **one that ignores it applies the event twice** — a second charge, a
> second gate open. Only `delivery_id` is new.

The replay is signed with the webhook's **current** secret and a fresh
`X-Nimbio-Timestamp`, so a delivery replayed after a secret rotation fails a
receiver still validating against the old one.

`retry_failed_deliveries()` re-sends only deliveries in the terminal `failed`
state, oldest first; `limit` is 1–100. Deliveries still `pending` are skipped
(`skipped_in_flight`) so a retry can never race Nimbio's own backoff and
double-fire, and candidates are de-duplicated by event id
(`skipped_duplicate_event`) — calling it twice in a row re-sends nothing the
second time. Read `replayed_count` for what was actually enqueued.

Both raise `ConflictError` (409) when the webhook is inactive or auto-disabled
(`webhook_disabled` — re-enable it with `update_webhook(webhook_id,
active=True)`), and `replay_delivery()` also when Nimbio is still retrying that
event itself (`delivery_in_flight`). **Test-mode keys enqueue nothing** and
return `result: "simulated"` — a replay POSTs a real event at your real
receiver.

### Known vocabularies

Capability and event-type names are plain strings, and a typo in one is a
silent `False` rather than an error — so the names ship with the package:

```python
from nimbio_community_api import (
    CAPABILITIES, STREAM_EVENT_TYPES, ACCOUNT_EVENT_TYPES,
    DIRECTORY_CALL_OUTCOMES, GUEST_LINK_TYPES, GUEST_LINK_STATES,
    GEOFENCE_MODES, CHANGE_LOG_TYPES, KEY_USAGE_REPORT_TYPES)

key = client.me().key
if key.has_capability("hold_opens"):        # or has_capability(key.capabilities, ...)
    ...
```

`CAPABILITIES` is the 22 capabilities a community-scoped key carries. An
account-scoped key has `constants.ACCOUNT_KEY_CAPABILITIES` instead — `open`,
plus `directory_call_events` once GuestView call events are released for the
account.

`STREAM_EVENT_TYPES` is the ten event types Nimbio delivers — there is one
event vocabulary, not two: a webhook subscribes to names from this same list,
and `stream_events()` yields them as `.type`. `ACCOUNT_EVENT_TYPES` is
the separate account stream's (`account.stream_events()`), and
`DIRECTORY_CALL_OUTCOMES` the values a directory call's `outcome` can take.

`GUEST_LINK_TYPES` is `("event", "limited_use")` — a typo there is loud (422),
so it is for autocomplete. `GUEST_LINK_STATES` is the six values a guest link's
live `.state` can take, and a typo *there* is **silent**: comparing against
`"actve"` leaves a dead link looking live. Use `GuestLink.active` for the common
case.

`GEOFENCE_MODES` is `("prompt", "auto_open")` and `CHANGE_LOG_TYPES` the four
audit trails `change_logs()` can read — both are argument vocabularies, so a
typo is a loud 422. `KEY_USAGE_REPORT_TYPES` is `("commercial", "residential")`,
and that one is not an argument at all: **the server chooses it**, and it
decides what each `key_usage()` row's `user` means.

All nine are **open sets**: the server may add to any of them at any time, and
nothing here rejects a name it does not recognise. The constants are a
convenience snapshot for autocomplete and typo-avoidance, not the source of
truth — for the live catalog from the server, call `webhook_event_types()`.

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

`ConflictError` (409) is usually **recoverable** — the API spends it on
conditions you are meant to catch and act on, not as a generic failure. Read
`.code`: `delivery_in_flight` (Nimbio is still retrying that webhook delivery
itself — wait rather than double-fire), `webhook_disabled` (re-enable it with
`update_webhook(webhook_id, active=True)`, then retry), `requires_confirmation`
(a warning, not a veto: repeat the call with `confirm=True`), and
`already_accepted` (that member is already approved).

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
