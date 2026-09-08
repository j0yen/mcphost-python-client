"""The one exception type this package raises for a server-side rejection.

mcphost's JSON-RPC errors carry a machine-readable `data.error_code` field
(see ~/wintermute/mcphost/src/errors.rs `AppError::into_error_data` for the
producing side). This client never reformats, reorders, or rewords that
object -- callers (library or CLI) get exactly what the wire sent.
"""

from __future__ import annotations

from typing import Any


class MCPHostError(Exception):
    """Raised for a JSON-RPC error response from an mcphost server.

    ``error`` is the raw JSON-RPC ``error`` object -- ``{"code", "message",
    "data"}`` -- exactly as received, unmodified. ``error["data"]`` (when
    present) is a dict carrying at least ``error_code``.
    """

    def __init__(self, error: dict[str, Any]) -> None:
        self.error = error
        message = error.get("message") if isinstance(error, dict) else None
        super().__init__(str(message) if message is not None else "mcphost error")

    @property
    def error_code(self) -> str | None:
        """Convenience accessor for ``error.data.error_code``, or None."""
        data = self.error.get("data")
        if isinstance(data, dict):
            code = data.get("error_code")
            if isinstance(code, str):
                return code
        return None
