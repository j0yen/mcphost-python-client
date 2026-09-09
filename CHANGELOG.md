# Changelog

## 0.2.0

PRD-mcphost-python-client-fluidity: the client carries the key, waits out a build, and is one `pip install` away.

- `Client.tool_call` now waits out a `building` python-tool environment (result or `tool_building`-coded error), sleeping the host's `retry_after_ms` hint, bounded by a new `build_wait_s` constructor argument (default 30s). On exhaustion it raises `ToolBuildingError` carrying the last `retry_after_ms` instead of failing on the first `tool_building` state.
- The CLI persists the key returned by `signup` by default, keyed by endpoint origin, at `~/.config/mcphost/credentials` (mode `0600`), and reads it automatically on every later command against that endpoint. `--key`/`$MCPHOST_KEY` still override; `--no-save` opts out of persisting; `mcphost logout` removes the saved entry. `--save-key`/`--use-saved-key` are kept as no-op aliases for this release only.
- New library methods, mirroring the host's tenant surface: `tool_logs`, `tool_remove`, `secret_set`, `secret_list`, `whoami`, `quickstart`, `billing_status`, `billing_checkout`, and `wait_ready` (poll a python tool's environment until it stops `building`, for prewarming). New matching CLI subcommands: `logs`, `remove`, `secret set|list`, `whoami`, `quickstart`, `billing status|checkout`.
- `MCPHostError` gained `.data`, `.docs`, and `.retry_after_ms` accessors, and five subclasses keyed off the wire's `error_code`: `ToolBuildingError`, `ArgsInvalidError`, `SpecInvalidError`, `CapacityError`, `RateLimitedError`. Existing callers catching the base `MCPHostError` are unaffected.
- A `release.yml` GitHub Actions workflow builds the wheel on every push/`workflow_dispatch` and publishes to PyPI via trusted publishing on a `v*` tag. **Operator step pending**: PyPI trusted publishing is not yet configured for this repo (see the PRD's open question) — the `publish` job will fail at the PyPI auth step until that's done by hand under the `j0yen` account; the `build` job (exercised via `workflow_dispatch`) already proves the wheel builds.

## 0.1.0

Initial release: `mcphost` Python client + CLI (`signup`, `test`, `publish`, `call`, `list`, `usage`, `plans`).
