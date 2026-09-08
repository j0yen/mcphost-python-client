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
from types import TracebackType
from typing import Any

import httpx

from ._version import __version__
from .errors import MCPHostError

DEFAULT_BASE_URL = "https://mcphost.dev/mcp"

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
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.key = key
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
            raise MCPHostError(response["error"])
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
            raise MCPHostError(response["error"])
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
        """
        return self._call(
            "host.tool_call", self._with_key({"name": name, "args": args or {}})
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
