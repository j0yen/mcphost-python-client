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
        data = self.data
        code = data.get("error_code")
        return code if isinstance(code, str) else None

    @property
    def data(self) -> dict[str, Any]:
        """``error.data`` if it is a dict, else ``{}`` -- never raises on a
        malformed/absent ``data`` field."""
        data = self.error.get("data") if isinstance(self.error, dict) else None
        return data if isinstance(data, dict) else {}

    @property
    def docs(self) -> str | None:
        """Convenience accessor for ``error.data.docs``, or None."""
        docs = self.data.get("docs")
        return docs if isinstance(docs, str) else None

    @property
    def retry_after_ms(self) -> int | None:
        """Convenience accessor for ``error.data.retry_after_ms``, or None.

        Meaningful on :class:`ToolBuildingError` and :class:`CapacityError`;
        harmless (just None) on every other subclass.
        """
        value = self.data.get("retry_after_ms")
        return value if isinstance(value, int) else None


class ToolBuildingError(MCPHostError):
    """``error_code == "tool_building"``, or raised by :meth:`Client.tool_call`
    itself once its ``build_wait_s`` budget is exhausted waiting on a
    ``building`` result."""


class ArgsInvalidError(MCPHostError):
    """``error_code == "args_invalid"`` -- a published tool's own
    ``args_schema`` rejected the call arguments."""


class SpecInvalidError(MCPHostError):
    """``error_code == "invalid_spec"`` -- ``host.tool_test``/``host.tool_publish``
    rejected the spec itself."""


class CapacityError(MCPHostError):
    """``error_code == "capacity"`` -- at the concurrent-call limit.
    ``retry_after_ms`` is set only when the host sends one."""


class RateLimitedError(MCPHostError):
    """``error_code == "rate_limited"``."""


_ERROR_CLASSES: dict[str, type[MCPHostError]] = {
    "tool_building": ToolBuildingError,
    "args_invalid": ArgsInvalidError,
    "invalid_spec": SpecInvalidError,
    "capacity": CapacityError,
    "rate_limited": RateLimitedError,
}


def build_error(error: dict[str, Any]) -> MCPHostError:
    """Construct the most specific :class:`MCPHostError` subclass for
    ``error``, keyed off ``error.data.error_code``. An unrecognized or
    missing code falls back to the base class -- callers that only ever
    caught :class:`MCPHostError` keep working unchanged (see the PRD's
    migration/compatibility note)."""
    data = error.get("data") if isinstance(error, dict) else None
    code = data.get("error_code") if isinstance(data, dict) else None
    cls = _ERROR_CLASSES.get(code, MCPHostError) if isinstance(code, str) else MCPHostError
    return cls(error)
