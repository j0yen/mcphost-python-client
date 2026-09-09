"""A minimal streamable-HTTP MCP client, scoped to exactly the two request
shapes mcphost needs: ``initialize`` and ``tools/call``, both as plain
``POST /mcp`` JSON bodies (the mcphost server runs `rmcp`'s streamable-HTTP
transport stateless and with ``with_json_response(true)`` -- see
~/wintermute/mcphost/src/http.rs -- so no SSE stream and no
``Mcp-Session-Id`` bookkeeping is required; every request is a self-contained
JSON-RPC call over the same endpoint).

The reference MCP Python SDK is not used here: it pulls in a much larger
dependency surface (anyio, sse-starlette, pydantic, ...) than this thin
client needs, and the PRD explicitly allows a minimal httpx implementation
of just the request shapes actually used.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

import httpx

from ._version import __version__
from .errors import MCPHostError, ToolBuildingError, build_error

DEFAULT_BASE_URL = "https://mcphost.dev/mcp"

#: `tool_call`'s default wait budget (seconds) for a `building` python-tool
#: environment (PRD-mcphost-python-client-fluidity requirement 1).
DEFAULT_BUILD_WAIT_S = 30.0

#: Used when a `building` result/error carries no `retry_after_ms` of its own.
_DEFAULT_RETRY_AFTER_MS = 250

#: Sent as `clientInfo.name` on every `initialize` handshake -- the
#: attribution signal PRD-mcphost-tenant-attribution's funnel keys on.
CLIENT_NAME = "mcphost-python"

#: The MCP protocol revision this client speaks. mcphost negotiates down to
#: whatever it actually supports and tells us via the `initialize` response
#: (`result.protocolVersion`) and the `MCP-Protocol-Version` response header;
#: we echo that value back on every later request rather than re-asserting
#: our own, matching the compat behavior mcphost's own tests exercise
#: (~/wintermute/mcphost/tests/compat_ac11_ac12_claude_sdk_replay.rs).
_REQUESTED_PROTOCOL_VERSION = "2025-06-18"


class Client:
    """A tenant's view of one mcphost host.

    ``key`` is the tenant's bearer key (returned by :meth:`signup`). Every
    tool call after signup carries it as the ``tenant_key`` argument -- this
    client never sends it as an ``Authorization`` header and never
    reconnects to attach it, matching mcphost's own key-as-argument
    convention (~/wintermute/mcphost/src/handler.rs
    ``resolve_tenant_key_auth``).
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        key: str | None = None,
        *,
        timeout: float = 30.0,
        build_wait_s: float = DEFAULT_BUILD_WAIT_S,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.key = key
        self.build_wait_s = build_wait_s
        self._ids = itertools.count(1)
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._protocol_version: str | None = None
        self._initialized = False

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- wire plumbing --------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._protocol_version:
            headers["MCP-Protocol-Version"] = self._protocol_version
        return headers

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        response = self._http.post(self.base_url, json=body, headers=self._headers())
        response.raise_for_status()
        if not self._protocol_version:
            negotiated = response.headers.get("MCP-Protocol-Version")
            if negotiated:
                self._protocol_version = negotiated
        payload: Any = response.json()
        if not isinstance(payload, dict):
            raise MCPHostError(
                {"code": -32000, "message": f"non-object JSON-RPC response: {payload!r}"}
            )
        return payload

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        request = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "initialize",
            "params": {
                "protocolVersion": _REQUESTED_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": __version__},
            },
        }
        response = self._post(request)
        if "error" in response:
            raise build_error(response["error"])
        self._initialized = True
        # `notifications/initialized` is a JSON-RPC notification (no `id`,
        # no response body expected) -- best-effort, matching the sequence
        # mcphost's own compat tests replay. A server that ignores it is
        # unaffected either way.
        self._http.post(
            self.base_url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers=self._headers(),
        )

    def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._ensure_initialized()
        request = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        response = self._post(request)
        if "error" in response:
            raise build_error(response["error"])
        result = response.get("result", {})
        if isinstance(result, dict) and "structuredContent" in result:
            structured = result["structuredContent"]
            return dict(structured) if isinstance(structured, dict) else {"value": structured}
        return dict(result) if isinstance(result, dict) else {"value": result}

    def _with_key(self, args: dict[str, Any]) -> dict[str, Any]:
        merged = dict(args)
        if self.key is not None:
            merged["tenant_key"] = self.key
        return merged

    def _poll_building(
        self,
        call: Callable[[], dict[str, Any]],
        *,
        wait_s: float,
        raise_on_exhaustion: bool,
    ) -> dict[str, Any]:
        """Call ``call()`` repeatedly while the host reports ``building``,
        waiting the host's own ``retry_after_ms`` hint between attempts, up
        to ``wait_s`` total. mcphost returns a python tool's still-building
        environment as a structured ``{"status": "building",
        "retry_after_ms": ...}`` *result* (see
        ~/wintermute/mcphost/src/kinds/python.rs ``building_result``); a
        ``tool_building``-coded *error* is handled the same way as a
        belt-and-suspenders case (mcphost's own history: that used to be
        the only shape a caller saw).

        A genuine :class:`ToolBuildingError` that is still current when the
        budget runs out is always re-raised -- ``raise_on_exhaustion`` only
        controls what happens when the budget runs out while the *last*
        thing seen was a still-``building`` result: raise a fresh
        :class:`ToolBuildingError` (``tool_call``) or just return that last
        result (``wait_ready`` -- a softer, prewarm-only contract).
        """
        deadline = time.monotonic() + wait_s
        retry_after_ms = _DEFAULT_RETRY_AFTER_MS
        while True:
            try:
                result = call()
            except ToolBuildingError as exc:
                retry_after_ms = exc.retry_after_ms or _DEFAULT_RETRY_AFTER_MS
                if time.monotonic() >= deadline:
                    raise
                time.sleep(retry_after_ms / 1000)
                continue
            if result.get("status") != "building":
                return result
            retry_after_ms = result.get("retry_after_ms") or _DEFAULT_RETRY_AFTER_MS
            if time.monotonic() >= deadline:
                if raise_on_exhaustion:
                    raise ToolBuildingError(
                        {
                            "code": -32000,
                            "message": "tool is still building after the wait budget",
                            "data": {
                                "error_code": "tool_building",
                                "retry_after_ms": retry_after_ms,
                            },
                        }
                    )
                return result
            time.sleep(retry_after_ms / 1000)

    # -- public API -------------------------------------------------------

    def signup(self, display_name: str) -> dict[str, Any]:
        """Create a tenant. Unauthenticated -- no key required or sent."""
        result = self._call("signup", {"name": display_name})
        key = result.get("key")
        if isinstance(key, str):
            self.key = key
        return result

    def tool_test(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Dry-run ``spec`` via ``host.tool_test`` without publishing it.

        ``spec`` is forwarded verbatim (plus ``tenant_key``) -- this client
        performs no client-side re-validation beyond what :func:`mcphost.spec.load_spec`
        already did (valid YAML/JSON), per the PRD's non-goals.
        """
        return self._call("host.tool_test", self._with_key(spec))

    def tool_publish(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Publish ``spec`` via ``host.tool_publish``, forwarded verbatim."""
        return self._call("host.tool_publish", self._with_key(spec))

    def tool_call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke an already-published tool by its local name.

        Mirrors mcphost's own ``host.tool_call`` argument shape exactly:
        ``{"name": ..., "args": ..., "tenant_key": ...}`` (see
        ~/wintermute/mcphost/src/handler.rs ``host_tool_call``, which reads
        the inner call arguments from the key ``args``, not ``arguments``).

        A python tool whose environment is still building is waited out,
        bounded by ``self.build_wait_s`` (constructor argument, default 30s),
        sleeping the host's own ``retry_after_ms`` hint between attempts
        (250ms when the host sends none). On exhaustion, raises
        :class:`mcphost.errors.ToolBuildingError` carrying the last
        ``retry_after_ms`` seen. Every other error raises as before.
        """
        call_args = self._with_key({"name": name, "args": args or {}})
        return self._poll_building(
            lambda: self._call("host.tool_call", call_args),
            wait_s=self.build_wait_s,
            raise_on_exhaustion=True,
        )

    def tool_list(self) -> dict[str, Any]:
        """List this tenant's published tools."""
        return self._call("host.tool_list", self._with_key({}))

    def usage(self, window: str | None = None) -> dict[str, Any]:
        """Calls/errors/duration percentiles for this tenant over ``window``."""
        args: dict[str, Any] = {"window": window} if window is not None else {}
        return self._call("host.usage", self._with_key(args))

    def plans(self) -> dict[str, Any]:
        """The plan catalog. Works whether or not a key is set."""
        return self._call("billing.plans", self._with_key({}))

    def tool_logs(self, name: str, limit: int | None = None) -> dict[str, Any]:
        """Recent log lines for a published tool, via ``host.tool_logs``."""
        args: dict[str, Any] = {"name": name}
        if limit is not None:
            args["limit"] = limit
        return self._call("host.tool_logs", self._with_key(args))

    def tool_remove(self, name: str) -> dict[str, Any]:
        """Remove a published tool, via ``host.tool_remove``."""
        return self._call("host.tool_remove", self._with_key({"name": name}))

    def secret_set(self, name: str, value: str) -> dict[str, Any]:
        """Set a tenant secret (referenced by a spec as ``secret.<name>``),
        via ``host.secret_set``."""
        return self._call("host.secret_set", self._with_key({"name": name, "value": value}))

    def secret_list(self) -> dict[str, Any]:
        """List this tenant's secret names (never values), via
        ``host.secret_list``."""
        return self._call("host.secret_list", self._with_key({}))

    def whoami(self) -> dict[str, Any]:
        """This tenant's identity/namespace, via ``host.whoami``."""
        return self._call("host.whoami", self._with_key({}))

    def quickstart(self, kind: str) -> dict[str, Any]:
        """A filled-in working example spec for ``kind``, via
        ``host.quickstart``."""
        return self._call("host.quickstart", self._with_key({"kind": kind}))

    def billing_status(self) -> dict[str, Any]:
        """This tenant's current plan/usage, via ``billing.status``."""
        return self._call("billing.status", self._with_key({}))

    def billing_checkout(self, plan: str | None = None) -> dict[str, Any]:
        """A checkout link for ``plan`` (or the host's default), via
        ``billing.checkout``."""
        args: dict[str, Any] = {"plan": plan} if plan is not None else {}
        return self._call("billing.checkout", self._with_key(args))

    def wait_ready(self, name: str, timeout_s: float = DEFAULT_BUILD_WAIT_S) -> dict[str, Any]:
        """Poll ``host.tool_test`` on the published tool ``name`` until its
        environment stops reporting ``building``, for a caller that wants to
        prewarm a python tool ahead of its first real :meth:`tool_call`
        rather than pay that wait inside the call itself. Unlike
        :meth:`tool_call`, this never raises on a timeout -- it just returns
        whatever the last poll saw (still ``building``, or ready).
        """
        test_args = self._with_key({"name": name, "args": {}})
        return self._poll_building(
            lambda: self._call("host.tool_test", test_args),
            wait_s=timeout_s,
            raise_on_exhaustion=False,
        )
