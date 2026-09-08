"""Load a publish/test spec file.

Per the PRD's non-goals, this package does no client-side spec validation
beyond "is this valid YAML/JSON, and is the top level an object" -- the
whole point of `host.tool_test`/`host.tool_publish` is that the server is
the single source of truth for whether a spec is acceptable. YAML is a
superset of JSON for the subset of syntax any real spec file uses, so both
`.yaml`/`.yml` and `.json` extensions load through the same YAML parser;
the extension is not actually inspected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class SpecError(ValueError):
    """The spec file could not be parsed, or did not parse to an object."""


def load_spec(path: str | Path) -> dict[str, Any]:
    """Parse ``path`` as YAML or JSON and return the top-level mapping."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"could not read spec file {p}: {exc}") from exc
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SpecError(f"{p} is not valid YAML/JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SpecError(f"{p} must parse to a mapping (object), got {type(loaded).__name__}")
    return loaded
