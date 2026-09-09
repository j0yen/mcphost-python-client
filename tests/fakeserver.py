"""An in-process fake mcphost server, just faithful enough to drive the
client and CLI offline: it speaks the same POST /mcp JSON-RPC shape the real
`rmcp` streamable-HTTP transport does in stateless/json-response mode (see
~/wintermute/mcphost/src/http.rs) -- no session IDs, one JSON body per
request -- and records every request it receives so a test can assert on
exactly what the client sent.

This lives in `tests/`, not `src/mcphost/`: it is test infrastructure, never
shipped in the wheel.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

PROTOCOL_VERSION = "2025-06-18"


class FakeMcpHost:
    """A minimal streamable-HTTP MCP server fixture.

    - `.requests`: every JSON-RPC request body received, in order.
    - `.responses[tool_name]`: the canned `structuredContent` result for a
      `tools/call` whose `params.name == tool_name` (default: `{}`).
    - `.errors[tool_name]`: when set, that call returns this JSON-RPC
      `error` object instead of a result.
    - `.set_building(tool_name, ...)`: that call returns a structured
      `{"status": "building", "retry_after_ms": ...}` result some number of
      times (or forever) before falling through to `.responses`/`.errors`
      for the same tool name -- mirrors mcphost's own `building_result`
      shape (~/wintermute/mcphost/src/kinds/python.rs), for exercising
      `Client.tool_call`'s bounded wait (PRD-mcphost-python-client-fluidity)
      without a network or a real sandbox.
    """

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.responses: dict[str, Any] = {}
        self.errors: dict[str, dict[str, Any]] = {}
        self.building: dict[str, dict[str, Any]] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_factory())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _handler_factory(self) -> type[BaseHTTPRequestHandler]:
        host = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                pass  # keep test output clean

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b""
                body: dict[str, Any] = json.loads(raw) if raw else {}
                host.requests.append(body)
                reply = host._dispatch(body)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
                self.end_headers()
                self.wfile.write(json.dumps(reply).encode("utf-8"))

        return Handler

    def _dispatch(self, body: dict[str, Any]) -> dict[str, Any]:
        request_id = body.get("id")
        method = body.get("method")
        if request_id is None:
            # A JSON-RPC notification (e.g. notifications/initialized): no
            # response is meaningfully awaited, but something valid must go
            # back over the wire.
            return {"jsonrpc": "2.0"}
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-mcphost", "version": "0.0.0"},
                },
            }
        if method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name")
            if tool_name in self.building:
                state = self.building[tool_name]
                remaining = state["remaining"]
                if remaining is None or remaining > 0:
                    if remaining is not None:
                        state["remaining"] = remaining - 1
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "structuredContent": {
                                "status": "building",
                                "retry_after_ms": state["retry_after_ms"],
                            }
                        },
                    }
            if tool_name in self.errors:
                return {"jsonrpc": "2.0", "id": request_id, "error": self.errors[tool_name]}
            result_value = self.responses.get(tool_name, {})
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"structuredContent": result_value},
            }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/mcp"

    def start(self) -> FakeMcpHost:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> FakeMcpHost:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def set_building(
        self, tool_name: str, *, times: int | None, retry_after_ms: int = 250
    ) -> None:
        """Make the next call(s) to `tool_name` return a `building` result.

        `times=None` means "forever" (until the test ends); an int counts
        down, after which calls fall through to `.responses`/`.errors` for
        the same tool name.
        """
        self.building[tool_name] = {"remaining": times, "retry_after_ms": retry_after_ms}

    # -- assertion helpers --------------------------------------------------

    def initialize_request(self) -> dict[str, Any] | None:
        return next((r for r in self.requests if r.get("method") == "initialize"), None)

    def calls(self, tool_name: str) -> list[dict[str, Any]]:
        """Every `tools/call` request whose `params.name == tool_name`, in order."""
        return [
            r
            for r in self.requests
            if r.get("method") == "tools/call" and r.get("params", {}).get("name") == tool_name
        ]
