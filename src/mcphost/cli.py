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

from .client import DEFAULT_BASE_URL, Client
from .errors import MCPHostError
from .spec import SpecError, load_spec

#: Where `mcphost signup --save-key` writes the returned key, if asked to.
#: Never read or written unless the caller explicitly opts in (--save-key /
#: --use-saved-key) -- signup does not persist anything by default.
DEFAULT_KEY_PATH = Path.home() / ".config" / "mcphost" / "key"


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
    if args.key:
        return str(args.key)
    env_key = os.environ.get("MCPHOST_KEY")
    if env_key:
        return env_key
    if args.use_saved_key and DEFAULT_KEY_PATH.is_file():
        return DEFAULT_KEY_PATH.read_text(encoding="utf-8").strip()
    return None


def _client(args: argparse.Namespace) -> Client:
    return Client(base_url=args.base_url, key=_resolve_key(args))


def _cmd_signup(args: argparse.Namespace) -> dict[str, Any]:
    with _client(args) as client:
        result = client.signup(args.name)
    if args.save_key:
        key = result.get("key")
        if isinstance(key, str):
            DEFAULT_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
            DEFAULT_KEY_PATH.write_text(key, encoding="utf-8")
            DEFAULT_KEY_PATH.chmod(0o600)
    return result


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


def _add_common_args(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--json", action="store_true", help="print machine-readable JSON")
    sp.add_argument("--base-url", default=os.environ.get("MCPHOST_BASE_URL", DEFAULT_BASE_URL))
    sp.add_argument(
        "--key", default=None, help="tenant key (overrides MCPHOST_KEY and the saved key)"
    )
    sp.add_argument(
        "--use-saved-key",
        action="store_true",
        help=f"fall back to the key saved at {DEFAULT_KEY_PATH} when --key/MCPHOST_KEY are unset",
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
        help=f"store the returned key at {DEFAULT_KEY_PATH} (mode 0600); off by default",
    )
    _add_common_args(p_signup)
    p_signup.set_defaults(func=_cmd_signup)

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
