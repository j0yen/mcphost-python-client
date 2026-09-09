"""`mcphost` console script: signup, test, publish, call, list, usage.

Every command accepts `--json` for machine-readable stdout. A structured
server error (an :class:`mcphost.MCPHostError`) is printed as JSON --
exactly the object the server sent, never reworded -- and the process exits
non-zero. This is the one place in the package that decides how a result or
an error reaches a terminal; `mcphost.Client` itself never prints anything.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .client import DEFAULT_BASE_URL, Client
from .errors import MCPHostError
from .spec import SpecError, load_spec

#: Where a saved key lives by default -- a JSON object keyed by endpoint
#: origin (`scheme://host[:port]`), so one file serves several mcphost
#: hosts. Written (mode 0600) on `signup` unless `--no-save` is given, and
#: read automatically on every later command unless `--key`/$MCPHOST_KEY
#: override it (PRD-mcphost-python-client-fluidity requirement 2).
DEFAULT_CREDENTIALS_PATH = Path.home() / ".config" / "mcphost" / "credentials"

#: mcphost 0.1.0's key file: a single bearer key, unkeyed by endpoint,
#: written only with `--save-key` and read only with `--use-saved-key`.
#: Superseded by DEFAULT_CREDENTIALS_PATH; kept only so the name still
#: means something to anyone reading old issues/docs. Never read or
#: written by this version.
DEFAULT_KEY_PATH = Path.home() / ".config" / "mcphost" / "key"


def _endpoint_origin(base_url: str) -> str:
    """The credentials-file key for `base_url`: its scheme + host[:port],
    dropping the path (`/mcp`) so the same origin's key is found regardless
    of which endpoint path a caller passes."""
    parsed = urlsplit(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _load_credentials() -> dict[str, str]:
    """Read DEFAULT_CREDENTIALS_PATH as `{origin: key}`. Never raises --
    a missing, unreadable, or malformed file just means "no saved keys"."""
    try:
        raw = DEFAULT_CREDENTIALS_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def _write_credentials(creds: dict[str, str]) -> None:
    DEFAULT_CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_CREDENTIALS_PATH.write_text(json.dumps(creds, indent=2) + "\n", encoding="utf-8")
    DEFAULT_CREDENTIALS_PATH.chmod(0o600)


def _save_credential(origin: str, key: str) -> None:
    creds = _load_credentials()
    creds[origin] = key
    _write_credentials(creds)


def _remove_credential(origin: str) -> bool:
    """Delete `origin`'s saved key, if any. Returns whether one was removed."""
    creds = _load_credentials()
    if origin not in creds:
        return False
    del creds[origin]
    _write_credentials(creds)
    return True


def _print_result(result: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
        return
    for key, value in result.items():
        print(f"{key}: {json.dumps(value) if isinstance(value, dict | list) else value}")


def _print_error(error: dict[str, Any]) -> None:
    # AC4: printed unchanged -- no reordering beyond what json.dumps does for
    # a dict (key order is preserved; this is not a reshaping), no reworded
    # message, no collapsing to a bare string.
    print(json.dumps(error, indent=2))


def _resolve_key(args: argparse.Namespace) -> str | None:
    """`--key` and $MCPHOST_KEY override; otherwise the key saved for
    `args.base_url`'s origin, if any. `--use-saved-key` is a deprecated,
    now-no-op alias -- the saved key is always tried by default, matching
    every command after `signup` carrying it without the caller doing
    anything (requirement 1)."""
    if args.key:
        return str(args.key)
    env_key = os.environ.get("MCPHOST_KEY")
    if env_key:
        return env_key
    return _load_credentials().get(_endpoint_origin(args.base_url))


def _require_key(args: argparse.Namespace) -> str | None:
    """Like `_resolve_key`, but exits with a message naming `signup` and
    `--key` when nothing was found (AC4) -- for every command that needs a
    tenant key. `plans` and `signup` itself don't call this."""
    key = _resolve_key(args)
    if key is None:
        raise SystemExit(
            f"no key found for {_endpoint_origin(args.base_url)} -- run "
            f"`mcphost signup <name>` first, or pass --key/$MCPHOST_KEY"
        )
    return key


def _client(args: argparse.Namespace, *, require_key: bool = True) -> Client:
    key = _require_key(args) if require_key else _resolve_key(args)
    return Client(base_url=args.base_url, key=key)


def _cmd_signup(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args, require_key=False) as client:
        result = client.signup(args.name)
    key = result.get("key")
    if isinstance(key, str) and not args.no_save:
        _save_credential(_endpoint_origin(args.base_url), key)
    return result


def _cmd_logout(args: argparse.Namespace) -> dict[str, Any]:
    origin = _endpoint_origin(args.base_url)
    removed = _remove_credential(origin)
    return {"origin": origin, "removed": removed}


def _cmd_test(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_spec(args.spec_file)
    with _client(args) as client:
        return client.tool_test(spec)


def _cmd_publish(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_spec(args.spec_file)
    with _client(args) as client:
        return client.tool_publish(spec)


def _cmd_call(args: argparse.Namespace) -> dict[str, Any]:
    try:
        call_args = json.loads(args.json_args)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid JSON arguments: {exc}") from exc
    if not isinstance(call_args, dict):
        raise SystemExit("call arguments must be a JSON object")
    with _client(args) as client:
        return client.tool_call(args.tool, call_args)


def _cmd_list(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.tool_list()


def _cmd_usage(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.usage(args.window)


def _cmd_logs(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.tool_logs(args.tool, args.limit)


def _cmd_remove(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.tool_remove(args.tool)


def _cmd_secret_set(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.secret_set(args.name, args.value)


def _cmd_secret_list(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.secret_list()


def _cmd_whoami(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.whoami()


def _cmd_quickstart(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.quickstart(args.kind)


def _cmd_billing_status(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.billing_status()


def _cmd_billing_checkout(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        return client.billing_checkout(args.plan)


def _add_common_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--json", action="store_true", help="print machine-readable JSON")
    sp.add_argument("--base-url", default=os.environ.get("MCPHOST_BASE_URL", DEFAULT_BASE_URL))
    sp.add_argument(
        "--key", default=None, help="tenant key (overrides MCPHOST_KEY and the saved key)"
    )
    sp.add_argument(
        "--use-saved-key",
        action="store_true",
        help=(
            "deprecated, no-op: the saved key (from `signup`) is now always tried "
            "automatically; kept for one release for scripts that still pass it"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcphost", description="Client for a hosted mcphost server."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_signup = sub.add_parser("signup", help="create a tenant and receive a bearer key")
    p_signup.add_argument("name", help="display name")
    p_signup.add_argument(
        "--save-key",
        action="store_true",
        help=(
            f"deprecated, no-op: saving to {DEFAULT_CREDENTIALS_PATH} is now the default; "
            "use --no-save to opt out"
        ),
    )
    p_signup.add_argument(
        "--no-save",
        action="store_true",
        help=f"do not store the returned key at {DEFAULT_CREDENTIALS_PATH}",
    )
    _add_common_args(p_signup)
    p_signup.set_defaults(func=_cmd_signup)

    p_logout = sub.add_parser("logout", help="remove the saved key for --base-url's endpoint")
    _add_common_args(p_logout)
    p_logout.set_defaults(func=_cmd_logout)

    p_test = sub.add_parser("test", help="dry-run a spec via host.tool_test, without publishing")
    p_test.add_argument("spec_file", help="path to a YAML or JSON spec file")
    _add_common_args(p_test)
    p_test.set_defaults(func=_cmd_test)

    p_publish = sub.add_parser("publish", help="publish a spec via host.tool_publish")
    p_publish.add_argument("spec_file", help="path to a YAML or JSON spec file")
    _add_common_args(p_publish)
    p_publish.set_defaults(func=_cmd_publish)

    p_call = sub.add_parser("call", help="invoke a published tool")
    p_call.add_argument("tool", help="local tool name")
    p_call.add_argument("json_args", help="JSON object of call arguments, e.g. '{\"a\": 1}'")
    _add_common_args(p_call)
    p_call.set_defaults(func=_cmd_call)

    p_list = sub.add_parser("list", help="list this tenant's published tools")
    _add_common_args(p_list)
    p_list.set_defaults(func=_cmd_list)

    p_usage = sub.add_parser("usage", help="calls/errors/duration percentiles for this tenant")
    p_usage.add_argument("--window", default=None, help='e.g. "24h" (server default if omitted)')
    _add_common_args(p_usage)
    p_usage.set_defaults(func=_cmd_usage)

    p_logs = sub.add_parser("logs", help="recent log lines for a published tool")
    p_logs.add_argument("tool", help="local tool name")
    p_logs.add_argument(
        "--limit", type=int, default=None, help="max lines (server default if omitted)"
    )
    _add_common_args(p_logs)
    p_logs.set_defaults(func=_cmd_logs)

    p_remove = sub.add_parser("remove", help="remove a published tool")
    p_remove.add_argument("tool", help="local tool name")
    _add_common_args(p_remove)
    p_remove.set_defaults(func=_cmd_remove)

    p_secret = sub.add_parser("secret", help="manage tenant secrets")
    secret_sub = p_secret.add_subparsers(dest="secret_command", required=True)

    p_secret_set = secret_sub.add_parser("set", help="set a secret's value")
    p_secret_set.add_argument("name", help="secret name, referenced by a spec as secret.<name>")
    p_secret_set.add_argument("value", help="secret value")
    _add_common_args(p_secret_set)
    p_secret_set.set_defaults(func=_cmd_secret_set)

    p_secret_list = secret_sub.add_parser("list", help="list this tenant's secret names")
    _add_common_args(p_secret_list)
    p_secret_list.set_defaults(func=_cmd_secret_list)

    p_whoami = sub.add_parser("whoami", help="this tenant's identity/namespace")
    _add_common_args(p_whoami)
    p_whoami.set_defaults(func=_cmd_whoami)

    p_quickstart = sub.add_parser("quickstart", help="a filled-in working example spec")
    p_quickstart.add_argument("kind", help='e.g. "echo", "http", "python"')
    _add_common_args(p_quickstart)
    p_quickstart.set_defaults(func=_cmd_quickstart)

    p_billing = sub.add_parser("billing", help="plan status and checkout")
    billing_sub = p_billing.add_subparsers(dest="billing_command", required=True)

    p_billing_status = billing_sub.add_parser("status", help="this tenant's plan/usage")
    _add_common_args(p_billing_status)
    p_billing_status.set_defaults(func=_cmd_billing_status)

    p_billing_checkout = billing_sub.add_parser("checkout", help="a checkout link")
    p_billing_checkout.add_argument(
        "--plan", default=None, help="plan name (server default if omitted)"
    )
    _add_common_args(p_billing_checkout)
    p_billing_checkout.set_defaults(func=_cmd_billing_checkout)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except MCPHostError as exc:
        _print_error(exc.error)
        return 1
    except SpecError as exc:
        print(json.dumps({"error_code": "invalid_spec_file", "message": str(exc)}, indent=2))
        return 1
    _print_result(result, as_json=args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
