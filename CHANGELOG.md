# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.3] - 2026-10-23

### Fixed

- Hue parameters (`PropColorslider`, a 0-360 number) were treated as `#rrggbb` colors;
  Home Assistant rejected their state and the error dropped the WebPipe connection,
  leaving the integration unavailable. Parameter kinds are now decided by the value.
- An exception in one entity's update, or while handling one channel message, no longer
  drops the connection, and the reconnect loop keeps retrying after unexpected errors.

## [2.1.2] - 2026-10-23 — WebPipe edition

Forked from upstream 1.1.0. Works with the free SignalRGB plan.

### Changed

- **Transport**: replaced the `signalrgb` HTTP API client (Pro only) with a QWebChannel
  client for SignalRGB's local WebPipe channel (`webpipe.py`, `client.py`). State is pushed;
  nothing polls.
- **Power and brightness** act on every lighting endpoint's own brightness; turning off
  remembers each device's level (stored with HA's `Store`) and turning on restores it.
- Default port is now `16046`, the port of the bundled relay.
- `iot_class` is `local_push`; the `signalrgb` requirement is gone.

### Added

- `select` for the running effect.
- One entity per parameter of the running effect (`number`, `switch`, `select`, `text`),
  hidden automatically while the running effect doesn't have that parameter.
- Effect rotation `switch` and interval `number`.
- `windows/webpipe_relay.py`: forwards the localhost-only WebPipe to the LAN for allowed IPs.
- `windows/srgb.cmd`: command-line on/off/toggle/status/effect.
- Chinese README.

### Removed

- Tests for the HTTP API client, replaced by tests against a fake QWebChannel server.

## [Unreleased]

### Added

- Granular exception handling for `ConnectionError`, `APIError`, and `NotFoundError`
  from the SignalRGB SDK — clearer log messages when something goes wrong
- `make coverage`, `make typecheck`, and `make fix` targets
- `CHANGELOG.md` (this file)
- Pre-commit safety hooks: `check-json`, `check-toml`, `check-added-large-files`,
  `check-merge-conflict`, `detect-private-key`, `check-case-conflict`, `mixed-line-ending`

### Changed

- **Minimum Home Assistant version bumped to 2026.4.0** (requires Python 3.14.2+)
- Coordinator polling now uses `get_current_state()` — drops from 4 API round-trips
  per poll cycle to 2
- Type checking migrated from mypy to [ty](https://docs.astral.sh/ty/) (Astral's
  Rust-based type checker)
- Linting consolidated to ruff only — pylint removed
- CI migrated to [hyperb1iss/shared-workflows](https://github.com/hyperb1iss/shared-workflows):
  `python-ci.yml@v1` for lint + test, `github-release.yml@v1` for AI-authored release notes
- Ruff line-length bumped 88 → 100 to match the Astral stack conventions
- Entity IDs no longer explicitly set — HA auto-generates from `unique_id` + device
  name (fixes invalid entity IDs on HA 2026.02+ which rejected ULID-derived uppercase)
- Coordinator raises `UpdateFailed` instead of `HomeAssistantError` (the former is
  the correct exception type for `DataUpdateCoordinator.update_method`)

### Removed

- `pylint` and `mypy` dev dependencies (replaced by `ruff` + `ty`)
- Legacy `requirements.txt` (redundant with `pyproject.toml`)
- Explicit `entity_id` assignments in light, button, and select entities

### Fixed

- Pre-commit `ruff-format` hook had a files regex copy-pasted from HA core that
  excluded `custom_components/` — pre-commit wasn't actually formatting the source
- Pre-commit hook versions no longer diverge from `pyproject.toml` dev deps
- Missing trailing newline in `translations/en.json`

## [1.0.1] — 2025-07

### Changed

- Update all dependencies to latest versions

## [1.0.0] — 2025

### Added

- Migrate to the async SignalRGB client for non-blocking HA integration
- Move client initialization to executor to avoid blocking the event loop
  during SSL certificate operations
- `uv lock` step in the release process

### Changed

- Bump SignalRGB SDK dependency to v1.0.0
- Improve UI responsiveness with faster state updates

## [0.8.0] and earlier

See the [git history](https://github.com/hyperb1iss/signalrgb-homeassistant/commits/main)
and [releases page](https://github.com/hyperb1iss/signalrgb-homeassistant/releases) for
details on earlier versions.

[Unreleased]: https://github.com/hyperb1iss/signalrgb-homeassistant/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/hyperb1iss/signalrgb-homeassistant/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/hyperb1iss/signalrgb-homeassistant/compare/v0.8.0...v1.0.0
