# Changelog

All notable changes to `nimbio-community-api` are documented here. This project
adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
