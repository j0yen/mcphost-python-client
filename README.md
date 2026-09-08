# mcphost

> Hosted MCP runtime where the agent is the operator: sign up by tool call, publish your own tools.

A thin Python client and CLI over the hosted [mcphost](https://mcphost.dev) MCP server. It is a faithful client only — every command maps 1:1 to an existing server tool (`signup`, `host.tool_test`, `host.tool_publish`, `host.tool_call`, `host.tool_list`, `host.usage`, `billing.plans`); nothing here changes or extends the server.

## Quickstart

```bash
pip install mcphost
mcphost signup "me" --json
# {"tenant": "...", "key": "...", "namespace": "...", "endpoint": "https://mcphost.dev/mcp", ...}

mcphost publish hello.yaml --key <key> --json
mcphost call hello '{"msg": "hi"}' --key <key> --json
```

`hello.yaml`, an `echo`-kind spec:

```yaml
name: hello
kind: echo
spec:
  type: object
  properties:
    msg: {type: string}
  required: [msg]
```

As a library:

```python
import mcphost

client = mcphost.Client()                       # base_url defaults to https://mcphost.dev/mcp
signup = client.signup("agent-in-a-sandbox")     # client.key is now set from signup["key"]
client.tool_publish({"name": "hello", "kind": "echo", "spec": {"type": "object"}})
client.tool_call("hello", {"msg": "hi"})
```

## CLI reference

Every command accepts `--json` (machine-readable stdout), `--base-url` (default `https://mcphost.dev/mcp`, or `$MCPHOST_BASE_URL`), and `--key` (or `$MCPHOST_KEY`).

| command | maps to |
|---|---|
| `mcphost signup <name> [--save-key]` | `signup` |
| `mcphost test <spec.yaml>` | `host.tool_test` |
| `mcphost publish <spec.yaml>` | `host.tool_publish` |
| `mcphost call <tool> '<json-args>'` | `host.tool_call` |
| `mcphost list` | `host.tool_list` |
| `mcphost usage [--window 24h]` | `host.usage` |

`signup --save-key` stores the returned key at `~/.config/mcphost/key` (mode `0600`); this is off by default, and `mcphost` never reads that file unless a command is run with `--use-saved-key` and no `--key`/`$MCPHOST_KEY` is set. Signup itself never touches disk.

## Error handling contract

A server-side rejection is a JSON-RPC error whose `error.data.error_code` names the failure (see mcphost's own `AppError` taxonomy). This client's library methods raise `mcphost.MCPHostError`, whose `.error` attribute is that JSON-RPC error object exactly as received — unmodified, unreworded, key order preserved. `.error_code` is a convenience accessor for `.error["data"]["error_code"]`.

The CLI never reformats this: on an `MCPHostError`, it prints `json.dumps(exc.error, indent=2)` to stdout and exits non-zero, in every mode (`--json` or not) — the error itself already is the structured, machine-readable form.

## Transport

The client speaks exactly the two JSON-RPC shapes mcphost's streamable-HTTP transport needs — `initialize` and `tools/call` — as plain `POST /mcp` requests with `Content-Type: application/json` and `Accept: application/json, text/event-stream`. mcphost runs its transport stateless with JSON (not SSE) responses, so no `Mcp-Session-Id` bookkeeping is required. The `initialize` handshake sends `clientInfo = {"name": "mcphost-python", "version": "<installed package version>"}`, the attribution signal the loop's funnel keys on.

The tenant key `signup` returns is threaded as the `tenant_key` argument on every call after that (never as an `Authorization` header, never via reconnect) — mcphost's own key-as-argument convention.

A minimal `httpx`-based implementation is used rather than the reference MCP Python SDK: the SDK pulls in a much larger dependency surface than the two request shapes this client actually needs.

## Packaging

- Distributed on PyPI as **`mcphost`**. If that name is ever unavailable at publish time, the fallback is **`mcphost-client`** (the import name stays `mcphost` either way if PyPI allows it, or `mcphost_client` if it does not — check the package actually installed with `pip show`).
- `uv build` produces a wheel; `scripts/publish.sh` gates the real-PyPI upload behind a `PUBLISH-OK` marker file or a truthy `PUBLISH_OK` environment variable (see `src/mcphost/publish_gate.py`). Absent that marker, publishing targets TestPyPI only.

## Acceptance tests

Each PRD acceptance criterion (`PRD-mcphost-python-client.md`) pairs with an offline pytest node run against `tests/fakeserver.py`:

| AC | criterion | test node id |
|---|---|---|
| 1 | `signup --json` prints the fake's key; `initialize.clientInfo.name == "mcphost-python"` | `tests/test_acceptance.py::test_ac_1_signup_prints_key_and_clientinfo` |
| 2 | `test spec.yaml` then `publish spec.yaml` forward the spec verbatim to `host.tool_test` then `host.tool_publish` | `tests/test_acceptance.py::test_ac_2_test_then_publish_forwards_spec_verbatim` |
| 3 | `call my.tool '{"a":1}' --json` prints the fake's `tools/call` result unchanged, incl. `result.payload` | `tests/test_acceptance.py::test_ac_3_call_result_unchanged` |
| 4 | a structured server error is printed as JSON, unreworded, non-zero exit | `tests/test_acceptance.py::test_ac_4_structured_error_unreworded` |
| 5 | `uv build` wheel metadata description + project URLs match the shared strings | `tests/test_acceptance.py::test_ac_5_wheel_metadata_matches_shared_strings` |
| 6 | no `PUBLISH-OK` → publish targets TestPyPI/dry-run, never real PyPI | `tests/test_acceptance.py::test_ac_6_no_publish_ok_targets_testpypi`, `tests/test_publish_gate.py` |
| 7 (P1) | `MCPHOST_LIVE_TEST=1` runs signup→test→publish→call against real mcphost.dev, prints four timings | `tests/test_live_smoke.py::test_ac_7_live_signup_test_publish_call_against_mcphost_dev` (skipped by default — network + real tenant, opt-in only) |

Two extra intent-card ACs, not in the PRD's numbered list but derived during intake, are covered the same way: `test_ac_8_clientinfo_shape_exact` (exact `clientInfo` shape) and `test_ac_9_json_output_matches_library_return_shape` (every `--json` command matches its library method's return shape).

```bash
uv run pytest -k "test_ac"     # just the AC-tagged suite: 8 passed, 1 skipped
```

## Development

```bash
uv run pytest        # offline suite; the fake server fixture is tests/fakeserver.py
uv run ruff check .
uv run mypy src
```

The one live test (`tests/test_live_smoke.py`, AC-7) is skipped unless `MCPHOST_LIVE_TEST=1` is set, in which case it runs signup → test → publish → call against the real `https://mcphost.dev` and prints the four timings.
