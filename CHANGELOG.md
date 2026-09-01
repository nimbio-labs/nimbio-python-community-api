# Changelog

All notable changes to `nimbio-community-api` are documented here. This project
adheres to [Semantic Versioning](https://semver.org/).

## [0.7.0] - 2026-09-01

Single-entry access codes: a community can now run one "Enter access code"
field for everyone instead of a PIN per member, and this release exposes the
mode switch and the new per-member preamble fields.

### Added

- **`community.access_code_mode()`** → `AccessCodeModeStatus` — whether the
  community runs `per_member` (the default: the visitor picks a member and
  types that member's PIN) or `single_entry` (every member carries a 3-letter
  **preamble** and the visitor types preamble + PIN, e.g. `ESM481502`), plus
  `.flip_preview` (`AccessCodeModePreview`): a dry run of switching to the
  other mode — `codes_to_delete`, `members_affected`,
  `members_to_assign_preamble`.
- **`community.set_access_code_mode(mode, *, confirm=False)`** →
  `AccessCodeModeChange`. **Switching is destructive**: it deletes **every**
  access code in the community — this key's, other integrations', and the ones
  residents made in the app — and notifies the affected members. So it is the
  same two-step handshake as `update_nfc_tag()`: without `confirm=True` the
  call is a dry run that raises `ConflictError` (409 `requires_confirmation`)
  with the preview, or returns `.changed == False` when the community is
  already in that mode. Repeat with `confirm=True` to flip; the result reports
  `.deleted_codes` and `.notified_members`. Test keys run the same handshake
  and then answer `.simulated` with `.would_change`. The flip is deliberately
  **not** a key of `update_settings()`, which refuses `access_code_mode` with a
  422 pointing at the new method.
- **`ConflictError.preview`** — the `error.preview` dict a
  `requires_confirmation` refusal may carry (`None` when it does not). Parse
  the mode flip's with `models.AccessCodeModePreview.from_dict(e.preview)`.
- `models.AccessCodeMode` (`Literal["per_member", "single_entry"]`).
- `AccessCode.preamble` / `.entry_code_masked` on list rows and
  `AccessCodeCreated.preamble` / `.entry_code` on the create result — set in
  `single_entry` mode, `None` in `per_member`. `entry_code` is the full string
  the visitor types and is returned once, like `code`; it is kept out of the
  `repr` for the same reason.
- `CommunitySettings.read_only["access_code_mode"]` — the mode, reported
  read-only by `settings()`.
- `CAPABILITIES` gains `"access_code_mode"` (22 names).
- `surface.json` now lists 95 operations.

## [0.6.0] - 2026-08-27

Full parity with the public REST API. The client now wraps **all 93 documented
API operations**, up from 32 at 0.5.0.

### Added

- **61 endpoints**, closing every gap against `nimbio-public-api` 0.11.0:
  - *Webhook deliveries* — `webhook_deliveries()`, `replay_delivery()`,
    `retry_failed_deliveries()`.
  - *Recurring hold opens* — `add_hold_open_recurring()`,
    `update_hold_open_recurring()`, `remove_hold_open_recurring()`,
    `set_hold_open_disabled_until()`.
  - *Community & roster* — `info()`, `members_page()`, `member()`, `messages()`,
    `approve_member()`, `update_key()`, `bulk_add_members()`,
    `bulk_grant_keys()`, `bulk_revoke_keys()`, `bulk_set_keys_disabled()`.
  - *Settings, homes & notifications* — `settings()`, `update_settings()`,
    `homes()`, `home()`, `add_home()`, `update_home()`, `remove_home()`,
    `set_move_out_date()`, `my_notification_settings()`,
    `set_my_notifications_enabled()`, `add_quiet_hours()`,
    `remove_quiet_hours()`.
  - *Guest access* — guest links, directory access codes, GuestView Entry and
    short codes (20 methods).
  - *Diagnostics, geography & audit* — NFC tags, sense lines, the community map
    and geofences, change logs and key usage (12 methods).
- **Transparent conditional requests, on by default.** The client stores the
  `ETag` from any GET that carries one and revalidates with `If-None-Match`. A
  `304` refunds the **monthly** quota, so polling integrations stop paying for
  unchanged data. Bounded LRU (256, `cache_size`), disable with `cache=False`,
  inspect with `cache_stats()`. The cache never answers on its own — every read
  still asks the server — so it cannot serve stale data and needs no
  write-invalidation.
- **`ConflictError`** for HTTP 409, which this API uses for actionable states
  (`delivery_in_flight`, `webhook_disabled`, `requires_confirmation`) rather
  than generic failure.
- **`constants` module** — `CAPABILITIES`, `ACCOUNT_KEY_CAPABILITIES`,
  `STREAM_EVENT_TYPES`, `GUEST_LINK_TYPES`, `GUEST_LINK_STATES`,
  `GEOFENCE_MODES`, `CHANGE_LOG_TYPES`, `KEY_USAGE_REPORT_TYPES`, and
  `has_capability()`. Convenience snapshots, not closed sets — an unrecognised
  value is still accepted.
- `surface.json` + a test that regenerates it from the `endpoints` registry, so
  the client's HTTP surface is machine-readable and cannot silently go stale.
  Consumed by `nimbioCore`'s `./nimbio.sh sdk-parity`.

### Notes

- Guest-link responses carry `token` and a working `url` — **from the list call
  as well as create**. Treat them as secret material and do not log them.
- `set_guest_view_entry_latches()` replaces the whole set; omitted latches lose
  eligibility and their schedule windows.
- `remove_home()` detaches every resident, irreversibly.
- Quiet-hours windows **may** wrap past midnight and reject `"24:00"` — the
  opposite of recurring hold opens and key schedules.
- `box_id` is required when addressing a single sense line, despite the OpenAPI
  schema marking it optional.

## [0.5.0] - 2026-08-26

### Changed
- **Breaking: `key_schedules()`, `key_schedule()` and `set_key_schedule()` are
  community-keys-only.** A community manager is not permitted to change one
  member's key schedule. `key_schedules()` now returns the community's own
  key(s) and nothing else, and passing a member's `key_id` to either
  single-key method raises `PermissionDeniedError` with
  `code == "not_a_community_key"`. Nothing you could legitimately do is lost: a
  schedule on the community key already cascades to every member key beneath
  it, which is how a community-wide rule is expressed. Tracks the same
  narrowing in the REST API — see the Public API notes for why this was taken
  as a break rather than a deprecation.
- `KeySchedule.descendant_key_count` counts only **live** member keys. It
  previously included revoked and hidden ones, overstating how many members a
  restriction actually reaches.

### Added
- `KeySchedule.inactive_window_count` — how many windows the list endpoint left
  out because their date range no longer covers today. `key_schedules()`
  returns only what is in force; `key_schedule(key_id)` still returns every
  window, expired ones included, because `set_key_schedule()` replaces the
  whole schedule.

## [0.4.0] - 2026-08-17

### Added
- Key access schedules: `client.community.key_schedules()`,
  `key_schedule(key_id)` and `set_key_schedule(key_id, windows)` (sync and
  async) — limit which days and times a key may open its gates.
  `set_key_schedule` replaces the whole schedule; `[]` removes the restriction
  entirely. New `KeySchedule`, `KeySchedules` and `ScheduleWindow` models;
  `ScheduleWindow` round-trips, so windows read back from the API can be sent
  straight back. `key_schedules().blocked` collects keys denied at **all**
  times because a saved schedule is switched off — the windows in that state
  block rather than restrict, so it is worth surfacing. Reads are
  quota-exempt. Mirrors the npm SDK's `keySchedules()` (released together).

  Two server rules the models cannot express, so they are documented instead:
  a window cannot run past midnight (`22:00`-`06:00` raises
  `overnight_not_supported` — send two windows), and a schedule on the
  community key cascades to every member key beneath it (check
  `descendant_key_count`).

## [0.3.0] - 2026-07-31

### Added
- Live event stream: `client.community.stream_events()` (sync and async) —
  Server-Sent Events from `GET /v1/events/stream`, carrying the exact webhook
  event payloads (`sense_line.changed`, `hold_open.changed`, `open.*`,
  `device.*`, `member.*`, `directory.call`) over an outbound connection, so
  integrations behind NAT get live push without exposing an endpoint.
  Automatic reconnect with exponential backoff resumes from the last seen
  event id; a `StreamReset` marker is yielded when the server cannot replay a
  gap (re-seed via the status reads). New `StreamEvent` / `StreamReset`
  models. Optional `events=[...]` server-side filter and
  `reconnect=False` single-connection mode.

## [0.2.0] - 2026-07-28

### Added
- Account surface for account-scoped (member) keys: `client.account.keys()`
  (your keys with latches nested) and `client.account.open(key_id, latch_id)`
  — sync + async. Enables member-key integrations (e.g. Home Assistant)
  without bespoke HTTP.
- Hold-open control surface: `client.community.hold_opens()`,
  `set_hold_open(latch_id, state)` (manual toggle),
  `add_hold_open_event(latch_id, start=..., end=...)` (one-time timed window),
  and `remove_hold_open_event(latch_id, event_id)` — with typed `HoldOpens` /
  `ManualHoldOpenResult` / `HoldOpenEventAdded` / `HoldOpenEventRemoved`
  models. Available on both the sync and async clients.
- Webhook self-management: `webhook_event_types()`, `webhooks()`,
  `create_webhook()`, `update_webhook()`, `delete_webhook()`,
  `rotate_webhook_secret()`, and `test_webhook()`. The signing secret is
  returned once on create/rotate.
- New `nimbio_community_api.webhooks` module for verifying webhook
  deliveries: `compute_signature`, `verify_signature`, `construct_event`, and
  `WebhookSignatureError` — Stripe-style `sha256=<hex>` HMAC over
  `"{timestamp}.{body}"` with a replay-tolerance window.
- `me().key` now carries `type` (`"account"` | `"community"`),
  `community_id`, and a `capabilities` list for feature discovery.
- `Latch.possible_statuses` — the latch's configured status vocabulary
  (`PossibleStatus(status, transient)`) from `community.gate_status()`, for
  classifying a latch without hardcoding label sets.

### Notes
- Gate-status, key-statuses, hold-opens reads and `/v1/me` no longer consume
  the key's monthly quota server-side (per-minute limit still applies), so
  polling integrations can re-sync freely.

## [0.1.0] - 2026-06-30

### Added
- Initial release.
- Synchronous `NimbioClient` and asynchronous `AsyncNimbioClient`, sharing one
  request/parse/retry core.
- `client.me()`, `client.health()`, and the `client.community.*` namespace
  covering gate status, members, key statuses, keys, opens, messages, member
  key management, and access/gate-status logs.
- Typed, tolerant dataclass response models (`.raw` always retained); ships
  `py.typed`.
- Environment selection (`prod` / `dev` / `local`) plus `base_url` override;
  test-vs-live mode inferred from the API key (`client.mode`).
- Configuration via arguments or `NIMBIO_API_KEY` / `NIMBIO_ENV` /
  `NIMBIO_BASE_URL`.
- Typed exception hierarchy mapping the API error envelope, with automatic
  retries (429 + 5xx, honoring `Retry-After`).
- Log pagination helpers (`iter_access_log`, `iter_gate_status_log`).

[Unreleased]: https://github.com/nimbio-labs/nimbio-python-community-api/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nimbio-labs/nimbio-python-community-api/releases/tag/v0.1.0
