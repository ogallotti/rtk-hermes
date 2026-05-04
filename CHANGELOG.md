# Changelog

All notable changes to `rtk-hermes` are documented here.

## 1.2.3 - 2026-05-04

### Fixed

- Avoid rewriting terminal commands for SSH, Docker and remote/sandbox backends by default. Rewritten commands require `rtk` to exist in the execution backend, not just beside Hermes.
- Added `RTK_HERMES_BACKENDS` so users can opt into `ssh`, `docker` or `all` when those backends have `rtk` installed.

## 1.2.2 - 2026-05-02

### Changed

- Installation docs now handle Debian/Ubuntu PEP 668 environments, Hermes shims and Hermes virtualenvs created without `pip`.
- Added `uv pip install --python ...` as the safe fallback for pip-less Hermes virtualenvs.

## 1.2.1 - 2026-05-02

### Changed

- PyPI is now the primary install path again because `1.2.0` was successfully published through Trusted Publishing.
- Release documentation now reflects the permanent tokenless PyPI publishing workflow.

## 1.2.0 - 2026-05-02

### Added

- Runtime configuration through environment variables:
  - `RTK_HERMES_MODE=rewrite|suggest|off`
  - `RTK_HERMES_TIMEOUT_MS=<milliseconds>`
  - `RTK_HERMES_PREVIEW_MARKER=true|false`
- Visible RTK terminal preview marker: rewritten commands now default to `: RTK && <rewritten-command>`.
- `/rtk` slash command support when the running Hermes version exposes plugin command registration.
- In-process metrics for attempted rewrites, applied rewrites, suggestions, denied commands, timeouts and errors.
- CI workflow for Python 3.9 through 3.13.
- Contributor, security and troubleshooting documentation.

### Changed

- Documentation now treats the GitHub release wheel as the primary install path until PyPI is updated beyond `1.0.0`.
- Plugin remains conservative: no `transform_terminal_output` or `transform_tool_result` compaction is enabled by default.
- The plugin skips commands that already start with `rtk ` or the RTK preview marker.

### Security

- Metrics never store raw command strings, reducing the risk of leaking shell input or secrets.

## 1.1.0 - 2026-05-02

### Fixed

- Corrected the pip entry point from `rtk_hermes:register` to `rtk_hermes`, matching Hermes' plugin loader behavior.
- Documented Hermes v0.11+ opt-in plugin configuration through `plugins.enabled`.
- Documented installation into the Python environment that actually runs Hermes.
- Accepted `rtk rewrite` exit code `3` as a valid rewrite when stdout contains a rewritten command.

## 1.0.0 - 2026-04-05

### Added

- Initial Hermes `pre_tool_call` plugin.
- Delegation to `rtk rewrite` for terminal command rewriting.
- Fail-open behavior when RTK is unavailable or no rewrite exists.
