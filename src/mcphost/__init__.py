"""mcphost: a thin Python client + CLI over the hosted mcphost MCP server.

    import mcphost
    c = mcphost.Client()
    signup = c.signup("me")
    c.tool_publish({"name": "hello", "kind": "echo", "spec": {"type": "object"}})
    c.tool_call("hello", {"msg": "hi"})

Errors from the server (a JSON-RPC error whose `data.error_code` names the
failure) surface as :class:`mcphost.MCPHostError`, carrying the server's
error object unchanged -- see errors.py's docstring for why.
"""

from __future__ import annotations

from ._version import __version__
from .client import Client
from .errors import MCPHostError

__all__ = ["Client", "MCPHostError", "__version__"]
