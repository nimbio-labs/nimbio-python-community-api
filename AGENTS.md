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

## Polling: conditional requests are ON by default (read before writing a loop)

Every GET automatically sends `If-None-Match` once it has seen an `ETag` for
that exact request. When the server answers `304 Not Modified` the SDK replays
the stored body — and **the monthly quota for that request is refunded**. So a
polling loop pays only for the reads where something actually changed.

```python
while True:
    status = client.community.gate_status()   # unchanged reads cost no quota
    ...
    time.sleep(10)

client.cache_stats()   # -> CacheStats(hits=341, misses=7, entries=1)
```

Facts an agent must not get wrong:

- **The per-minute rate limit is still charged in full.** Only the *monthly
  quota* is refunded. Do **not** shorten a poll interval because caching is on —
  a 304 is a real request, and 429 still applies.
- **No latency win.** The ETag is derived from the response body, so the server
  does the same work; the saving is bandwidth, parsing and quota.
- **It cannot serve stale data and needs no invalidation.** `max-age` is
  ignored; every read still asks the server, and a body is only ever reused when
  the server says 304. You never need to clear the cache after a write.
- **A 304 is invisible.** The returned object is freshly parsed and independent
  — no sentinel type, no flag. Mutating one result cannot affect the next read.
- Never cached: non-GET methods, the SSE stream, and anything the server
  doesn't hand an ETag for (`/v1/me` never will — its payload *is* your live
  usage counters).
- Opt out with `NimbioClient(api_key, cache=False)`; resize the bounded LRU with
  `cache_size=N` (default `DEFAULT_CACHE_SIZE`, 256 entries).

## The whole SDK surface (sync — drop the `with`/use `await` for async)

This is every method the SDK exposes: `/v1/me`, `/healthz`, the community
surface (identity, roster incl. the paged read, keys, messages, bulk member
writes, hold opens incl. recurring schedules, webhooks incl. delivery replays,
access schedules, community settings, the homes/units roster, this key owner's
member-open notification settings, guest access — guest links, access codes,
GuestView Entry and short codes — NFC tags, sense lines, the map and its
geofences, logs incl. the configuration change log and key-usage report, and the
live event stream), and the account surface
(`client.account.keys()` / `.open()`, added 0.2.0). **All 93 documented API
operations are wrapped.** Only the service's hidden `/v1/keys*` / `/v1/calls*`
endpoints stay unwrapped — call those over plain HTTPS if you need them.

```python
with NimbioClient("nimbio_test_...") as client:
    client.me()                       # -> Me           (account_id, key.usage…)
    client.health()                   # -> Health       (ok, wamp) — never raises on 503
    client.mode                       # -> "test" | "live" | None (no network)
    client.cache_stats()              # -> CacheStats   (hits, misses, entries; no network)

    # Reads (community-scoped key required)
    client.community.info()           # -> CommunityInfo — CALL THIS FIRST
    client.community.gate_status()    # -> GateStatus   (.latches: list[Latch])
    client.community.members()        # -> Members      (.accepted/.unaccepted/.removed)
    client.community.members_page(bucket="accepted", page=1, size=100,
                                  search="555-1234")   # -> MembersPage (paged, 1-indexed)
    client.community.member(ACCOUNT_COMMUNITY_ID)      # -> Member (+ .bucket, .status)
    client.community.key_statuses()   # -> KeyStatuses  (.keys, .hold_opens)
    client.community.keys()           # -> list[CommunityKey]
    client.community.messages(limit=50, offset=0)      # -> MessagesPage (sent, newest first)

    # Writes (test key = simulated, live key = real)
    client.community.open("LATCH_ID", note="...", idempotency_key="...")   # -> OpenResult
    client.community.message("text")                                       # -> WriteResult
    client.community.add_member("+15551234567", ["KEY_ID"])                # -> WriteResult
    client.community.approve_member(ACCOUNT_COMMUNITY_ID, ["KEY_ID"],
                                    move_out_date="2027-01-31")            # -> WriteResult
    client.community.grant_keys(ACCOUNT_COMMUNITY_ID, ["KEY_ID"])          # -> WriteResult
    client.community.revoke_keys(ACCOUNT_COMMUNITY_ID, ["KEY_ID"],
                                 remove_member=False)                      # -> WriteResult
    client.community.set_keys_disabled(ACCOUNT_COMMUNITY_ID, ["KEY_ID"],
                                       disabled=True)                      # -> WriteResult
    client.community.update_key("KEY_ID", name="New name", disabled=True)  # -> KeyUpdateResult

    # Bulk member writes — <=100 items, 207 with one entry PER ITEM
    client.community.bulk_add_members([{"phone_number": "+15551234567",
                                        "key_ids": ["KEY_ID"]}])           # -> BulkResult
    client.community.bulk_grant_keys([{"account_community_id": 4021,
                                       "key_ids": ["KEY_ID"]}])            # -> BulkResult
    client.community.bulk_revoke_keys([{"account_community_id": 4021,
                                        "key_ids": ["KEY_ID"]}])           # -> BulkResult
    client.community.bulk_set_keys_disabled([{"account_community_id": 4021,
                                              "key_ids": ["KEY_ID"]}], True)  # -> BulkResult

    # Hold opens (need the Hold Opens feature — else 403 hold_opens_disabled)
    client.community.hold_opens()                      # -> HoldOpens
    client.community.set_hold_open("LATCH_ID", True)   # -> ManualHoldOpenResult
    client.community.add_hold_open_event("LATCH_ID", start="2026-08-01 09:00",
                                         end="2026-08-01 10:00")  # -> HoldOpenEventAdded
    client.community.remove_hold_open_event("LATCH_ID", "EVENT_ID")
    client.community.add_hold_open_recurring("LATCH_ID", days_of_the_week="MTWHF",
                                             start_time="08:00", end_time="18:00")
    client.community.update_hold_open_recurring("LATCH_ID", "TEMPORAL_DATE_ID",
                                                clear_times=True)  # -> RecurringHoldOpen
    client.community.remove_hold_open_recurring("LATCH_ID", "TEMPORAL_DATE_ID")
    client.community.set_hold_open_disabled_until("LATCH_ID", "2026-12-25 23:59")
    client.community.set_hold_open_disabled_until("LATCH_ID", None)  # resume

    # Webhooks + deliveries
    client.community.webhooks()                        # -> list[Webhook]
    client.community.create_webhook("https://...", ["open.succeeded"])
    client.community.update_webhook("WEBHOOK_ID", active=True)
    client.community.webhook_deliveries("WEBHOOK_ID", limit=50)   # -> list[WebhookDelivery]
    client.community.retry_failed_deliveries("WEBHOOK_ID")        # -> DeliveryReplayBatch
    client.community.replay_delivery("WEBHOOK_ID", "DELIVERY_ID") # -> DeliveryReplay

    # Access schedules — limit WHEN a key may open its gates
    client.community.key_schedules()                # -> KeySchedules (.keys, .blocked)
    client.community.key_schedule("KEY_ID")         # -> KeySchedule
    client.community.set_key_schedule("KEY_ID", [   # REPLACES the whole schedule
        models.ScheduleWindow("MTWHF", "06:00", "18:00")])
    client.community.set_key_schedule("KEY_ID", []) # [] = always allowed

    # Community settings — the settable half, and read_only FEATURE DISCOVERY
    s = client.community.settings()                 # -> CommunitySettings
    s.feature("allow_hold_opens")                   # read_only flag -> bool
    s.setting("event_keys_override")                # settable value
    client.community.update_settings({              # PARTIAL, all-or-nothing
        "allow_directory_viewing": True,
        "member_term_custom": "Tenant"})            # unknown key -> 422, applies NOTHING

    # Homes / units roster
    client.community.homes(include_hidden=True)     # -> list[Home] (default: whole set)
    client.community.add_home("12 Elm St, Unit 3")  # -> Home (full resource)
    client.community.home("HOME_ID")                # -> Home (+ .members)
    client.community.update_home("HOME_ID", owner_occupied=True, hidden=False)
    client.community.remove_home("HOME_ID")         # DETACHES every resident
    client.community.set_move_out_date(ACCOUNT_COMMUNITY_ID, "2026-12-31")
    client.community.set_move_out_date(ACCOUNT_COMMUNITY_ID, None)   # clear

    # My member-open notifications — PER MANAGER (this key's owner), not per community
    client.community.my_notification_settings()          # -> NotificationSettings
    client.community.set_my_notifications_enabled(True)
    client.community.add_quiet_hours("MTWHF", "22:00", "06:00")  # ONE wrapping window
    client.community.remove_quiet_hours(QUIET_HOURS_ID)

    # Guest links — the response is SECRET MATERIAL, from the LIST too
    client.community.guest_links(include_inactive=True)     # -> list[GuestLink] w/ token+url
    client.community.create_guest_link("limited_use", ["LATCH_ID"], max_uses=4,
                                       title="Booking 8841")   # -> GuestLink (.url)
    client.community.create_guest_link("event", ["LATCH_ID"], title="Party",
                                       window_start="2026-08-20 18:00",
                                       window_end="2026-08-20 23:00")
    client.community.revoke_guest_link(GUEST_LINK_ID)       # TERMINAL — no un-revoke
    client.community.guest_link_logs(guest_link_id=None, limit=50, offset=0)  # guest PII
    client.community.guest_link_latch_exclusions()          # check BEFORE creating

    # Access codes — the PIN is returned ONCE, by create
    client.community.access_codes()                    # -> AccessCodes (PINs masked)
    client.community.create_access_code("481502", ["LATCH_ID"],
                                        expires_in_hours=24)  # -> .code, once
    client.community.update_access_code(CODE_ID, disabled=True)   # api_managed only
    client.community.delete_access_code(CODE_ID)                  # api_managed only
    client.community.access_code_eligible_latches()    # the CM-set allowlist
    client.community.access_code_logs(limit=50, offset=0)
    client.community.access_code_mode()                # per_member | single_entry + flip_preview
    client.community.set_access_code_mode("single_entry")  # 409 -> preview -> confirm=True

    # GuestView Entry — all five return the WHOLE settings object
    entry = client.community.guest_view_entry()             # -> GuestViewEntry
    client.community.set_guest_view_entry_enabled(True)     # setter, not a toggle
    client.community.set_guest_view_entry_latches(          # REPLACES the whole set
        entry.latch_ids + ["LATCH_ID"])                     # read-modify-write!
    client.community.add_guest_view_entry_schedule(["LATCH_ID"], "MTWHF",
                                                   start_time="09:00",
                                                   end_time="17:00")
    client.community.remove_guest_view_entry_schedule(SCHEDULE_ID)  # WIDENS access
    client.community.guest_view_entry_logs(success=True)    # visitor PII

    # Short codes — permanent; assignment is exclusive
    client.community.short_codes()                          # -> list[ShortCode]
    client.community.create_short_code(latch_id="LATCH_ID") # cannot be deleted, ever
    client.community.assign_short_code("Kp7Rx2Q", "LATCH_ID")  # DETACHES the old gate

    # NFC tags — one PATCH assigns, unassigns AND disables
    client.community.nfc_tags(search=None, page=1, results_per_page=50)
    client.community.nfc_tag(TAG_ID)                        # -> NfcTag
    client.community.update_nfc_tag(TAG_ID, disabled=True)  # 409 -> retry w/ confirm
    client.community.update_nfc_tag(TAG_ID, latch_id=None)  # detach (omit = leave)
    client.community.nfc_scan_log(tag_uid_hex="04a1…")      # taps; names people

    # Sense lines — why a gate reports what it reports. box_id REQUIRED on 2 of 4
    client.community.sense_lines()                     # -> SenseLines (.not_reporting)
    client.community.sense_line(1, "BOX_ID")           # box_id REQUIRED (positional)
    client.community.update_sense_line(1, "BOX_ID",    # FREEZES gate status if off
                                       sense_line_online=False)
    client.community.sense_line_records(box_id=None, sense_line_id=None)  # raw

    # Map + geofences — coordinates are physical-security info; map() costs quota
    client.community.map()                             # -> CommunityMap
    client.community.update_geofence("LATCH_ID", radius_meters=150,   # >= 100 m
                                     mode="prompt", enabled=True)

    # Audit reads
    client.community.change_logs("guest_link", days=30)   # CONFIG trail, not access
    client.community.key_usage("2026-06-01", "2026-06-10")  # read .report_type!

    # Logs (community must have Access Log History enabled)
    client.community.member_access_logs(ACCOUNT_COMMUNITY_ID, window="last_30")  # last_30|30_60|60_90
    client.community.access_log(page=0)             # -> AccessLogPage  (.logs, .has_more)
    client.community.gate_status_log(page=0)        # -> GateStatusLogPage
    for row in client.community.iter_access_log():  # auto-paginates all pages
        ...

    # Live events (SSE push — same payloads as webhooks, works behind NAT)
    for ev in client.community.stream_events(
            events=["sense_line.changed", "hold_open.changed"]):  # filter optional
        if isinstance(ev, models.StreamReset):
            ...  # gap not replayable: re-seed via gate_status()/hold_opens()
        else:
            ev.id, ev.type, ev.payload   # payload = event-specific fields
```

`stream_events()` blocks forever by default (auto-reconnect with backoff,
resuming from the last seen event id); pass `reconnect=False` to consume one
connection and return. HTTP errors raise (`RateLimitError` with code
`stream_limit` = too many concurrent streams; the cap is 3 per key).
Connecting charges one per-minute request; delivered events are quota-free.

Async is identical with `await`, and the iterators are `async for`:

```python
async with AsyncNimbioClient("nimbio_test_...") as client:
    me = await client.me()
    await client.community.open("LATCH_ID")
    async for row in client.community.iter_access_log():
        ...
```

## Bulk writes: a 207 is not a success (read before batching)

- Every `bulk_*` call answers **207** with one entry per input item, in request
  order. **That is not "all succeeded"** — read `result.summary.failed` or
  iterate `result.failures`, never the status code. Each item echoes the id it
  was addressed by, so failures can be zipped back and re-submitted.
- A whole-batch rejection (foreign member/key, >100 items, repeated id) applies
  **nothing** and raises `APIError` (422) instead of returning a `BulkResult`.
- Re-submitting is safe: grants are idempotent (`granted["exists"]`), an
  already-revoked key still succeeds
  (`already_revoked_community_key_ids`), and an already-accepted member fails
  with `already_member` while the rest of the batch runs.
- `bulk_set_keys_disabled` has no "already in the desired state" reading: a key
  the member does not hold is a per-item `key_not_held`, because enabling a key
  someone lacks needs a grant, not a toggle.
- On a bulk result `simulated` is an explicit **flag**, not the `result` string
  (which stays `"batch_processed"` in both modes).
- Quota: one monthly unit **per item**, one call against the per-minute limit.

## Hold opens (read before scheduling one)

- All hold-open writes need the community's Hold Opens feature — otherwise
  `PermissionDeniedError` (403 `hold_opens_disabled`). Check
  `info().feature("hold_opens")` first.
- `days_of_the_week` is `MTWHFSU` — **`H` is Thursday**, `S` Saturday, `U`
  Sunday. A 1–127 bitmask also works.
- Times are `'HH:MM'` **in the latch's own local time** (the `timezone` from
  `hold_opens()`), never UTC. Omit both times for an all-day schedule.
- A window **cannot wrap past midnight**. Split `22:00`–`06:00` into
  `22:00`–`24:00` plus `00:00`–`06:00`; use `'24:00'`, not `'23:59'`, or the
  halves leave a gap.
- `update_hold_open_recurring` is a partial update: `start_time`+`end_time`
  replace the window, `clear_times=True` removes it, neither leaves it alone.
- `remove_hold_open_recurring` is **deliberately NOT idempotent** — an unknown
  id raises `NotFoundError`, so you can never believe you cancelled a schedule
  that is still holding a gate open.
- `set_hold_open_disabled_until(latch_id, until)` suspends **every** schedule on
  that latch (and releases an active hold) until `'YYYY-MM-DD HH:MM'` latch-local;
  `until` is required, pass `None` to resume. Per latch, not per community.

## Webhook replays (read before replaying one)

- **A replay re-sends the ORIGINAL event id and payload, byte for byte.** The
  `X-Nimbio-Delivery` header carries the **event** id, not the delivery id. A
  consumer that de-duplicates on that header is fine; **one that ignores it
  applies the event twice** — a second charge, a second gate open. Only
  `delivery_id` is new.
- The replay is signed with the webhook's **current** secret, so a delivery
  replayed after a secret rotation fails a receiver still checking the old one.
- `retry_failed_deliveries` re-sends only deliveries in the terminal `failed`
  state, oldest first; `limit` is 1–100 (default 50), candidates are
  de-duplicated by `event_id`, and pending deliveries are skipped. Read
  `replayed_count` / `skipped_in_flight` / `skipped_duplicate_event` for what
  actually happened.
- Both raise `ConflictError` (409): `webhook_disabled` (fix it yourself with
  `update_webhook(webhook_id, active=True)`) or, for a single replay,
  `delivery_in_flight` (Nimbio is still retrying — wait).
- **Test-mode keys enqueue nothing** and return `result: "simulated"`. A live
  replay POSTs a real event at your real receiver.

## Guest links are SECRET MATERIAL — and the LIST returns them too (read first)

- `token` and the ready-to-send `url` come back from **`guest_links()` as well
  as from `create_guest_link()`**. A link recovered from the list is exactly as
  usable as a fresh one: anyone holding the URL opens the gate — **no account,
  no key, no login**.
- **Treat the response like a password and do not log it.** Logging responses at
  debug level is an ordinary thing to do, and here it writes working gate links
  to disk. `GuestLink` keeps `token`/`url` out of its `repr` so a stray
  `print()` cannot leak one, but `.raw` and `json.dumps()` still carry them.
- That the list returns them is deliberate (a lost URL stays recoverable) — which
  is why the *read* needs the same care as the write.
- **The two types take different limits.** `event` requires `title`,
  `window_start`, `window_end`; unlimited opens inside the window, which may not
  exceed the community's cap (**8h** unless raised) nor have already ended.
  `limited_use` requires `max_uses` (1 to the cap, **20** default) and takes an
  optional `expires_at` backstop defaulting to and capped at **30 days**.
- **Datetimes:** ISO-8601; an offset (`Z` included) is honoured and **a naive
  string is read as UTC** — communities carry no timezone. Everything returned
  is UTC. A datetime that does not parse is **rejected**, not ignored.
- `key_id` names the backing community key and may be omitted only when the
  community has exactly one. Every `latch_ids` entry must be openable by that
  key and not excluded for the link type.
- `.state` is computed live: `active`, `upcoming`, `expired`, `spent`,
  `revoked`, `feature_disabled`. Branch on it, not on the timestamps — a spent
  link is neither revoked nor expired and is still dead. `.active` is the
  shorthand.
- **Exclusions: absence is permission.** An empty
  `guest_link_latch_exclusions()` means every gate the key opens is offerable.
  Per link type — barred from `event` may still be fine for `limited_use`.
  Naming an excluded gate is a 422, so check first. It is **read-only on
  purpose**: the setter narrows what a link type may ever cover, which makes it
  a safety control, so exposing it was deliberately deferred — not a gap.
- **An API key can mint an `event` link even when the community has event keys
  switched off.** That switch aims at *members*; a manager on the management
  surface was always exempt, and an API key inherits the carve-out. **A real
  widening** — to honour the community setting, read `features.event_keys` from
  `info()` and branch yourself.
- `revoke_guest_link()` is **terminal**: no un-revoke, mint a new link instead.
  Revoking twice is a no-op success, so retries are safe.
- `guest_link_logs()` is **guest PII** (redeemer IP, user agent, and a
  signed-in account's display name).

## Access codes: the PIN is returned exactly once (read before minting one)

- `create_access_code()` is the **only** call that ever returns the cleartext
  PIN. `access_codes()` shows `code_masked`/`code_length` and nothing reads it
  back. Lost PIN = delete and mint a new one. `AccessCodeCreated` hides `.code`
  from its `repr`.
- `.api_managed` marks the codes **this key** created. `update_access_code()`
  and `delete_access_code()` touch only those; a resident's code, or one in
  another community, is a 404 to both. `codes.api_managed` is the actionable
  subset.
- **Three limits, doing different things.** `expires_in_hours` /
  `expires_in_days` are **mutually exclusive** (both is 422) and set one
  absolute cutoff computed **in UTC from the moment of the call**. `temporal` is
  a **recurring weekly** window evaluated in **the gate's own local timezone**
  and never expires. Both together = must satisfy both. Neither = works until
  disabled or deleted.
- `temporal`'s keys are `days_of_the_week`, **`start`**, **`end`**,
  `recurring_week` — `start`/`end`, *not* the `start_time`/`end_time` used by
  hold opens and GuestView Entry.
- On update, omitted fields are left alone and **there is no way to clear** a
  cutoff or window — disable or delete instead. Empty body = 400. The PIN cannot
  be changed. Re-sending `expires_in_days=1` **extends** the code, because the
  cutoff is recomputed from now.
- Every `latch_ids` entry must be in `access_code_eligible_latches()` or the
  call is `invalid_latch`. That allowlist is **CM-portal-only**; the API reads
  it, never writes it. `feature_enabled` false ⇒ writes 403
  `access_codes_disabled`.
- Deleting stops the PIN immediately but **keeps the log rows**.
  `code_entered_masked` is always asterisks — a successful attempt's digits
  *are* a working PIN — so correlate through `directory_access_code_id`.

## Access-code mode: the flip DELETES EVERY CODE (read before switching)

- `access_code_mode()` says which system the community runs. `per_member`
  (default): a GuestView visitor picks the member and types **that member's**
  PIN. `single_entry`: one "Enter access code" field for the whole community;
  every member has a 3-letter **preamble** and the visitor types preamble + PIN
  (`ESM481502`). In that mode `access_codes()` rows carry `preamble` /
  `entry_code_masked`, and `create_access_code()` returns the full `entry_code`
  **once** — deliver `entry_code` when set, `code` otherwise. The list also
  reports `.access_code_mode`, so one call tells you how to present the rows.
- **`set_access_code_mode()` deletes every access code in the community** in
  either direction — this key's, other integrations', and residents' own — and
  notifies every affected member by push plus a community-wide message.
  Switching to `single_entry` also assigns preambles. Log rows survive.
- It is the **NFC-style handshake**: the first call (no `confirm`) is a dry run
  — `.changed == False` if already in that mode, else 409
  `requires_confirmation` with the counts on `ConflictError.preview`
  (`codes_to_delete`, `members_affected`, `members_to_assign_preamble`; also
  readable up front as `access_code_mode().flip_preview`). **Show them to a
  human**, then repeat with `confirm=True`. Never pass `confirm=True` on the
  first call.
- It is **not** a settings key: `update_settings({"access_code_mode": ...})`
  is a 422 pointing at `set_access_code_mode()`. Read it as
  `settings().read_only["access_code_mode"]`.
- Test keys run the same 409 handshake; `confirm=True` then returns
  `.simulated` with `.would_change` (the preview) and deletes nothing.
- Unknown mode: 422 `invalid_mode`. The mode routes are **not** gated on the
  Directory Access Codes setting — they work while the feature is off.

```python
try:
    client.community.set_access_code_mode("single_entry")
except ConflictError as e:
    if e.code != "requires_confirmation":
        raise
    preview = models.AccessCodeModePreview.from_dict(e.preview)
    # ask the human: preview.codes_to_delete, preview.members_affected
    client.community.set_access_code_mode("single_entry", confirm=True)
```

## GuestView Entry: the latch write REPLACES everything (read before writing)

- **`set_guest_view_entry_latches()` replaces the whole set** — hence the PUT.
  Any currently-eligible latch you omit loses eligibility **and its schedule
  windows are deleted with it**. Adding one gate by sending a one-element list
  silently destroys every other gate's schedule.
- **Always read-modify-write**: `entry = guest_view_entry()` then
  `set_guest_view_entry_latches(entry.latch_ids + [new_id])`. `[]` removes
  GuestView Entry from every gate. A foreign latch is a 404 and nothing is
  written; needs the feature on (403 `guest_view_entry_disabled`).
- `set_guest_view_entry_enabled()` is a **setter, not a toggle** — the call is
  retryable and a retried toggle would flip guest access back open. Switching
  off leaves the latch set and schedule intact, so it is the safe way to
  suspend.
- **The schedule is a whitelist of permitted times.** A latch with **no**
  windows is guest-accessible at **any** hour; the first window restricts it,
  and removing a latch's *last* window **widens** access back to 24/7.
- Windows are evaluated in **each latch's own local timezone**, at the moment
  the visitor taps open — never UTC, never yours, never the community's.
- **Midnight rule: matches quiet hours, not schedules.**

| Surface | Wraps past midnight? | `"24:00"` accepted? |
|---|---|---|
| `set_key_schedule()` | **No** — send two windows | n/a |
| `add_hold_open_recurring()` | **No** — split, using `"24:00"` | **Yes** |
| `add_quiet_hours()` | **Yes** — one window | **No** |
| **`add_guest_view_entry_schedule()`** | **Yes** — one window | **No** |

- So `22:00`–`06:00` is ONE window here, days name the day it **starts**, times
  run `00:00`–`23:59`, and `end_time=None` leaves it unbounded. Adding is
  additive; `.created_schedule_ids` holds one id per latch.
- All five calls return the **whole** settings object — never follow one with a
  GET. `guest_view_entry_logs()` rows **identify visitors** (name, phone, IP)
  and read whether or not the feature is currently on.

## Short codes are permanent, and assignment is exclusive

- **There is no way to delete a short code** — not through this API, not through
  the portal. A code you mint is permanent.
- **`assign_short_code()` silently detaches the gate the code pointed at
  before.** A code routes to exactly one gate; nothing warns you the old gate
  lost its code, and the change lands for the next visitor who types it. Read
  `short_codes()` first if you need to know what you are detaching.
- Omit `code` and the server generates one (7 alphanumerics) and effectively
  never 409s. Supply `code` to claim one: 6–10 alphanumerics, **unique across
  all of Nimbio**, so a code in use anywhere — including one differing only in
  letter case — is `ConflictError` (`short_code_taken`).
- `latch_id` is optional; `None` means the code opens the directory without
  preselecting a gate. On assign, an unknown code and another community's code
  are the same 404 `short_code_not_found` — the namespace is global, so the API
  gives no way to tell them apart or to seize someone else's code.

## NFC tags: the 409 is a warning, not a veto (read before disabling one)

- One PATCH does all three jobs. Send `disabled`, `latch_id`, or both — neither
  is 422 `empty_patch`.
- **`disabled` is an explicit setter, never a toggle**, so revoking a stolen fob
  never depends on state you read a moment ago, and re-sending is a no-op.
  `disabled=True` **takes effect for physical gate taps**: the next tap on any
  gate is refused.
- `latch_id="<gate id>"` binds the tag to a gate (a tag opens the gate it is
  bound to, not a member's key); `latch_id=None` **detaches** it and leaves it
  in the community for later reassignment. **Omitting the argument leaves the
  binding alone** — that is why its default is the `UNSET` sentinel, not `None`.
- **Order matters when both are sent:** `disabled` is applied first, so
  `disabled=False, latch_id=…` revives then binds in one call, while
  `disabled=True, latch_id=…` is 422 `conflicting_fields` — a dead fob cannot be
  routed to a gate.
- **A write that would leave a Scan Only gate with no working tag is 409
  `requires_confirmation` — a warning, not a refusal.** Catch `ConflictError`
  and repeat with `confirm=True`. It is deliberately not a hard block, because
  revoking a stolen fob has to stay possible:

```python
try:
    client.community.update_nfc_tag(tag_id, disabled=True)
except ConflictError as e:
    if e.code != "requires_confirmation":
        raise
    client.community.update_nfc_tag(tag_id, disabled=True, confirm=True)
```

- `tag_uid_hex` is the fob's **physical, publicly readable UID — not a secret**,
  and the join key to `nfc_scan_log()`. No cryptographic tag material is ever
  returned; `notes` are readable but **not settable**; programming a blank fob
  is an operator job with a card reader.
- Unknown tags and other communities' tags are both 404 `tag_not_found`. Scan-log
  rows **name the tapping member** where the tap resolved to one.

## Sense lines: `reporting: false` explains a "stuck" gate (read before writing)

- A sense line is a physical input reporting whether a gate moved — the feedback
  loop behind `gate_status()`, the gate-status log and `sense_line.changed`.
- Two flags, one derived answer: `sense_line_online` (is the input on at all),
  `latch_data_online` (may its readings drive gate status), and **`reporting`**,
  true only when both are — exactly the condition for a transition to change
  anything. **A gate frozen on one status with `reporting: false` is a
  CONFIGURATION problem, not a stuck gate.** `sense_lines().not_reporting` lists
  those inputs directly.
- **`box_id` is REQUIRED on `sense_line()` and `update_sense_line()`** and is
  positional there: a sense line id is an *input number on a board*, unique only
  within its box, so "sense line 1" is ambiguous without it (422
  `box_id_required`). On `sense_lines()` and `sense_line_records()` it is a
  genuine optional filter.
- **Switching either flag off FREEZES that gate's status at its last known
  value** for every app, for `gate_status()`, and for `sense_line.changed`, and
  affects hold-open logic reading gate state. Each flag is an explicit set, not
  a toggle; omitting both is 422 `no_fields`.
- The PATCH writes **configuration only**. `status_map` and the creation of
  sense lines are installer operations, and observed gate state is what the
  hardware reports — an API key cannot fabricate it.
- `sense_line_records()` is the raw transitions, and **rows are written even
  when a line is switched off**: a healthy stream here beside a stale
  `gate_status()` proves the wiring is fine and the configuration is not.
  `status: None` = a state with no configured meaning, which is a finding, not a
  row to drop (`.unmapped`).

## Geofences: 100 m is a floor, not a suggestion (read before writing one)

- **A `radius_meters` below `min_radius_meters` (100) is REJECTED with 422
  `radius_below_minimum` — not silently raised.** Android's Geofence API and
  iOS region monitoring both degrade below ~100 m, so a smaller fence would read
  as configured and never fire. **Do not clamp client-side to dodge the 422.**
- Partial update: only the fields you send change. `latitude`/`longitude` move
  together — both or neither — and there is **no way to clear a configured
  centre**, because a silent clear would kill proximity behaviour on a real gate
  with nothing to show for it. An empty body is 400 `nothing_to_update`.
- Coordinates are WGS84 decimal degrees; radii are metres. Read
  `min_radius_meters` and `geofence_modes` off `map()` rather than hardcoding.
  `mode` is `prompt` (notify, member taps) or `auto_open`.
- Enabling a fence needs a centre: a gate with `geofence.center: None` never had
  one — use `.suggested_center` (its device's location). `.unconfigured` lists
  them.
- **`map()` coordinates say exactly where a property's entrances are.** Treat the
  response as physical-security information. It also **consumes monthly quota**,
  unlike `gate_status()` — it is setup-time configuration, not a poll.

## Key usage: `report_type` decides what `user` means (read before reporting)

- **The server chooses `report_type` from the community's property type — there
  is no parameter for it.** `"commercial"`: `user` is the **actual opener**.
  `"residential"`: `user` is `"<master key owner> Keychain"`, so every open on a
  household's keys is attributed to the account holder and you **cannot** tell
  which member opened the gate. That groups; it does **not** anonymize.
- Dates are inclusive `'YYYY-MM-DD'` in the **community's** timezone (`.timezone`),
  not yours. A window over `.max_range_days` is **clamped**: read `.date_from` /
  `.date_to` (used) against `.requested_from` / `.requested_to` (asked), with
  `.clamped` saying so. Rows carry `phone` and `location` too.
- `change_logs()` is the **configuration** trail — who rewrote the schedule —
  not the access trail (`access_log()`) and not physical transitions
  (`gate_status_log()`). `log_type` is required and picks one of four:
  `hold_open`, `key_schedule`, `guest_view`, `guest_link`. `days` above the
  30-day retention cap is **clamped, not rejected** — read `.days`/`.date_from`/
  `.date_to`.

## Known vocabularies (don't hand-type these)

```python
from nimbio_community_api import (
    CAPABILITIES, STREAM_EVENT_TYPES, GUEST_LINK_TYPES, GUEST_LINK_STATES,
    GEOFENCE_MODES, CHANGE_LOG_TYPES, KEY_USAGE_REPORT_TYPES, has_capability)

client.me().key.has_capability("hold_opens")     # or has_capability(caps, "...")
```

`CAPABILITIES` — the 22 names a community-scoped key carries (`open`,
`gate_status`, `key_statuses`, `hold_opens`, `webhooks`, `members`, `messages`,
`access_logs`, `key_schedules`, `key_usage`, `change_logs`, `homes`,
`short_codes`, `guest_view_entry`, `access_codes`, `guest_links`, `map`,
`open_notifications`, `settings`, `sense_lines`, `nfc_tags`,
`access_code_mode`). An account-scoped key has only `open`.

`STREAM_EVENT_TYPES` — the ten event types Nimbio delivers. There is **one**
event vocabulary, not two: a webhook subscribes to names from this same list,
and `stream_events()` yields them as `.type`.

`GUEST_LINK_TYPES` — `("event", "limited_use")`. A typo is loud (422), so this
one is for autocomplete.

`GUEST_LINK_STATES` — the six values `GuestLink.state` can take (`active`,
`upcoming`, `expired`, `spent`, `revoked`, `feature_disabled`). A typo **here**
is silent: `"actve"` is a False that leaves a dead link looking live. Use
`GuestLink.active` for the common case.

`GEOFENCE_MODES` — `("prompt", "auto_open")`, and `CHANGE_LOG_TYPES` — the four
audit trails `change_logs()` reads. Both are argument vocabularies, so a typo is
a loud 422.

`KEY_USAGE_REPORT_TYPES` — `("commercial", "residential")`. **Not an argument**:
the server picks it, and it decides what each `key_usage()` row's `user` means.

All seven constants are **open sets** and a convenience snapshot only — the
server may add to any of them, nothing in this SDK rejects a name it does not
recognise, and `webhook_event_types()` is the authoritative runtime catalog.

## Access schedules (read before writing one)

- `days_of_the_week` letters are `MTWHFSU` — **`H` is Thursday**, `S` Saturday,
  `U` Sunday. Times are `'HH:MM'` in each gate's own local time.
- `set_key_schedule` **replaces** the whole schedule. Send every window you
  want to keep. `[]` removes the restriction.
- A window **cannot run past midnight**: `22:00`–`06:00` raises
  `BadRequestError` (`overnight_not_supported`). Send two windows — first ends
  `'24:00'` (end-of-day sentinel, end only), second starts `'00:00'` next day.
  Never end one at `'23:59'`: that drops the last minute of the day.
- A schedule on the community key cascades to **every** member key beneath it.
  Check `.is_community_key` and `.descendant_key_count` before writing.
- A schedule applies to **every** gate the key opens; no per-gate override.
- `.permanently_blocked` means windows are saved but the restriction is off —
  the key is denied at all times. That is a fault, not a schedule; saving fixes
  it. `key_schedules().blocked` lists them.

## Quiet hours: the midnight rule is INVERTED here (read before adding one)

The same-looking `'HH:MM'` field obeys three different rules across this API,
and two of them are already in your head from the sections above:

| Surface | Wraps past midnight? | `"24:00"` accepted? |
|---|---|---|
| `set_key_schedule()` | **No** — send two windows | n/a |
| `add_hold_open_recurring()` | **No** — split, using `"24:00"` | **Yes** |
| **`add_quiet_hours()`** | **Yes** — `22:00`–`06:00` is ONE window | **No** |

- Carrying the hold-open idiom across **fails silently**: you get a window that
  never suppresses anything. Send `22:00`–`06:00` as one window.
- `start_time == end_time` is refused (422 `invalid_time`) — a zero-length
  window suppresses nothing. Omit both times for an all-day window.
- Windows are evaluated in the **local timezone of the gate that was opened**,
  not the manager's and not UTC. Two-timezone communities suppress each gate on
  its own clock.
- `days_of_the_week` names the day the window **starts** on.
- These settings are **per community manager** — the account that owns the API
  key. Another manager of the same community has their own `enabled` flag and
  their own windows; you cannot see or change them, and their ids are 404 here.
- Adding is **additive** (one call, one window). Replace a schedule by deleting
  the windows you no longer want. All four calls return the whole object.
- `feature_available` false = the community disallows the feature: the three
  writes 403 `open_notifications_disabled` and `enabled` has no effect.

## Homes: `remove_home()` detaches residents (read before deleting one)

- Deleting a home **detaches every resident attached to it**. They stay members
  and keep their keys, but they lose their unit association and **nothing
  restores it automatically** — you would re-add the home and re-attach each
  resident by hand.
- Read `.detached_member_count` on the result for what happened; call
  `home(home_id)` first for `.members` if you want to know beforehand.
- A test key reports the count it *would* detach and changes nothing.
- `hidden` on `update_home()` is a **setter, not a toggle** — retrying is safe.
  Hiding a unit with residents still attached is 409 `home_occupied`.
- `homes()` defaults to `include_hidden=True` (a roster sync wants the whole
  set); `False` matches the CM portal's list.

## Settings: the patch is all-or-nothing, and unknown keys are rejected

- `update_settings()` applies only the keys you send, but validates the **whole**
  patch first — one bad value applies **nothing**. `.changed` names what landed.
- An unknown key is **rejected**, never ignored: 422 `invalid_setting` naming it.
- `allow_hold_opens`, `is_open_log_history_enabled`, `allow_guest_view_entry`
  and the caps `event_key_max_window_hours` / `limited_use_link_max_uses` are
  **read-only** provisioning decisions — detect them under `.read_only`, and
  contact Nimbio to change one. Sending one to the patch is a 422.
- `access_code_mode` is read-only here too, but for a different reason: the
  flip deletes every access code, so it has its own confirm handshake in
  `set_access_code_mode()`. Sending it to the patch is a 422 pointing there.
- `.feature(name)` on the read is the alternative to calling a gated endpoint
  and interpreting its 403 — that is the reason `settings()` is worth calling.
- Per terminology side, a custom label and a picker option are **mutually
  exclusive**: setting one clears the other. `""`/`None` clears a custom label.
- Unlike `info()`, `settings()` **consumes monthly quota**; don't poll it.
  `my_notification_settings()` does not.

## ID vocabulary (important)

- **`latch_id`** — from `info().latches[i].latch_id` (or
  `gate_status().latches[i].latch_id`; same ids).
- **`key_id`** (community key id) — from `keys()[i].id` or `key_statuses()`.
  Used everywhere keys are granted/revoked/disabled.
- **`account_community_id`** — a member's id, from
  `members().accepted[i].account_community_id` or `members_page()`, and carried
  on a `member.requested` webhook. Used to address a member.
- **`temporal_date_id`** — a recurring hold-open schedule, from
  `add_hold_open_recurring(...).temporal_date_id` or `hold_opens()` under
  `recurring[]`.
- **`delivery_id`** / **`event_id`** — from `webhook_deliveries()`. Replays
  keep the `event_id` and mint a new `delivery_id`.
- **`home_id`** — a unit, from `homes()[i].home_id` or `add_home(...).home_id`.
- **`quiet_hours_id`** — one of *your own* quiet-hours windows, from
  `my_notification_settings().quiet_hours[i].quiet_hours_id`. Another manager's
  id is a 404 here, even within the same community.
- **`guest_link_id`** — a guest link, from `guest_links()[i].guest_link_id` or
  `create_guest_link(...).guest_link_id`. Another community's id is a 404,
  identical to an unknown one.
- **`directory_access_code_id`** — an access code, from `access_codes()` or
  `create_access_code(...)`. Only `api_managed` ones are addressable by this
  API's update and delete.
- **`schedule_id`** — one GuestView Entry window, from
  `guest_view_entry().schedule[i].schedule_id` (or `.created_schedule_ids`
  after adding one).
- **`short_code`** — the code itself is the id (`short_codes()[i].short_code`),
  and the namespace is **global across Nimbio**, not per community.
- **`tag_id`** — an NFC tag, from `nfc_tags()[i].tag_id`. Distinct from
  **`tag_uid_hex`**, the fob's physical (public, non-secret) UID, which is what
  joins a tag to its `nfc_scan_log()` rows.
- **`box_id`** — a Nimbio device, from `sense_lines().boxes[i].box_id` or
  `map().boxes[i].box_id`. **Required** to address a single sense line.
- **`sense_line_id`** — an *input number on a board* (1, 2, …), **unique only
  within its box**: it is not a global id, which is why it never travels
  without a `box_id`.

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
    APIError, AuthenticationError, ConflictError, PermissionDeniedError,
    RateLimitError, GateNotOpenedError,
)

try:
    client.community.open("LATCH_ID")
except GateNotOpenedError:        # 504 — gate didn't confirm in time
    ...
except PermissionDeniedError as e:  # 403 — wrong scope / open denied / not a community key
    print(e.code)                 # machine code, e.g. "open_denied", "not_community_key"
except ConflictError as e:        # 409 — usually RECOVERABLE, act on e.code
    print(e.code)                 # delivery_in_flight | webhook_disabled |
                                  # requires_confirmation | already_accepted
except RateLimitError as e:       # 429
    print(e.retry_after)          # seconds, may be None
except APIError as e:             # any other HTTP >= 400
    print(e.status_code, e.code, e.message, e.request_id)
```

`ConflictError` is the one to catch rather than retry blindly:
`delivery_in_flight` means wait (Nimbio is still retrying that delivery),
`webhook_disabled` means re-enable the webhook first, `requires_confirmation`
means repeat the call with `confirm=True`, and `already_accepted` means the
member is already approved.

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
- Caching is on by default and safe to leave on, but it is **not** a licence to
  poll harder — the per-minute rate limit is unchanged. Check `cache_stats()`
  to confirm you are actually earning the quota refunds.
- `update_sense_line()` changes what a **real gate reports**: switching either
  flag off freezes that gate's status for every app and for `gate_status()`.
  `update_nfc_tag(disabled=True)` refuses the next **physical tap** on any gate.
  Neither is reversible by "just reading again" — read first, write once.
- `remove_home()` is the most destructive call on this surface: it detaches
  every resident from the unit, and nothing undoes that. Read
  `home(home_id).members` first, and prefer a test key to see
  `detached_member_count` before you commit.
- **Never log a guest-link response**, from create *or* from `guest_links()`:
  `token`/`url` are a working gate for anyone who reads the log. The same goes
  for `create_access_code()`, the only call that returns a live PIN.
- `set_guest_view_entry_latches()` is destructive **by omission** — it deletes
  the schedule windows of every latch you leave out. Read
  `guest_view_entry().latch_ids`, modify that list, send it back. Never compose
  the list from memory.
- `assign_short_code()` detaches the previous gate with no warning, and a short
  code can never be deleted once minted.
- Guest-link and access-code logs are **PII** (visitor names, phone numbers, IP
  addresses, user agents). Do not fan them out into your own logs.
