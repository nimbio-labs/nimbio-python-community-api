# Changelog

All notable changes to `nimbio-community-api` are documented here. This project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
