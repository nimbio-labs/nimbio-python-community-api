# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**nimbio-python-community-api** is the official Python client for the Nimbio community API (`api.nimbio.com`). It is published to PyPI as **`nimbio-community-api`** (`pip install nimbio-community-api`) and imported as `nimbio_community_api`.

It wraps the `nimbio-public-api` service. It does **not** talk to kindlyWAMP or the database directly — everything goes over HTTPS to the public API.

## Naming (three distinct names — keep them straight)

| Thing | Name |
|-------|------|
| GitHub repo | `nimbio-python-community-api` (owner: `nimbio-labs`) |
| PyPI distribution | `nimbio-community-api` |
| Python import | `nimbio_community_api` |

## Tech Stack

- **Language**: Python 3.9+ (`from __future__ import annotations` everywhere → keep runtime 3.9-compatible)
- **Only runtime dependency**: `httpx`
- **Build backend**: hatchling (`src/` layout; version in `src/nimbio_community_api/_version.py`)
- **Tests**: pytest + `respx` (fully mocked — no network) + pytest-cov
- **Lint / types**: ruff + mypy

## Architecture

Two clients share one transport-agnostic core:

- `_base.py` — `BaseClient` (config resolution, headers, request prep, response decode/parse, error mapping, retry policy) and the `endpoints` registry, the **single source of truth** for the HTTP surface. Each endpoint returns `(method, path, params, json, parser)`.
- `_sync.py` — `NimbioClient` + `_SyncCommunity` (blocking, `httpx.Client`).
- `_async.py` — `AsyncNimbioClient` + `_AsyncCommunity` (asyncio, `httpx.AsyncClient`).
- `models.py` — tolerant dataclass response models; every one keeps the full payload on `.raw`.
- `_exceptions.py` — `NimbioError` hierarchy mapping the `{error:{code,message,request_id}}` envelope.
- `_environments.py` — `prod`/`dev`/`local` → base URL.

**When adding or changing an endpoint:** edit the `endpoints` registry in `_base.py` once, then add the thin wrapper to *both* `_SyncCommunity` and `_AsyncCommunity` (and a model in `models.py` if the shape is new). The sync and async wrappers must stay in lockstep.

Test vs live is **inferred from the API key prefix** (`nimbio_test_*` / `nimbio_live_*`), exposed as `client.mode` — it is not a constructor flag.

## Common commands

```bash
make install      # pip install -e '.[dev]'
make test         # pytest
make cov          # pytest with coverage
make check        # lint + type-check + coverage (what CI runs)
make build        # sdist + wheel
tox               # full matrix (py39-py313 + lint + type) in isolated envs
```

Keep coverage at/near 100% (CI enforces a 95% floor). `AGENTS.md` is the LLM/agent usage cheat sheet — update it when the public surface changes.

## Releasing

1. Bump `__version__` in `src/nimbio_community_api/_version.py` and add a dated section to `CHANGELOG.md`.
2. Update the customer-facing changelogs in `nimbioCore` (`nimbioCore/changelogs/python-sdk.md` and `nimbioCore/marketing-changelogs/python-sdk.md`).
3. Tag `vX.Y.Z` and push the tag — `.github/workflows/publish.yml` builds and publishes to PyPI via Trusted Publishing (OIDC; no stored token). A PyPI version cannot be re-uploaded, so only tag when ready.

## Related

- `nimbio-public-api` — the REST service this client wraps (endpoint contracts, auth, scope model).
- `nimbioCore/changelogs/python-sdk.md` + `nimbioCore/marketing-changelogs/python-sdk.md` — customer-facing changelogs.
- `CHANGELOG.md` (this repo) — technical changelog for GitHub releases.
