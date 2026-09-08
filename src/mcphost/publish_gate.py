"""The PUBLISH-OK gate: decides where `scripts/publish.sh` uploads.

Same convention pattern used elsewhere in this fleet (see the mqo/registry
publish gates): a build is never one flag-flip away from landing on real
PyPI. Absent an explicit, deliberate `PUBLISH-OK` marker (a file in the
project root, or the `PUBLISH_OK` environment variable set to a truthy
value), every publish attempt is routed to TestPyPI -- never real PyPI.

Kept as a pure function of (env mapping, marker-file existence) so it is
testable without ever invoking `uv publish` or touching the network (AC6:
"verified by inspecting the script's branch decision logic directly, not by
performing any network upload").
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from pathlib import Path

_TRUTHY = {"1", "true", "yes", "on"}


class PublishTarget(Enum):
    PYPI = "pypi"
    TEST_PYPI = "testpypi"


def _env_truthy(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name, "")
    return value.strip().lower() in _TRUTHY


def publish_ok(env: Mapping[str, str], marker_path: Path) -> bool:
    """True only when the marker file exists or `PUBLISH_OK` is truthy."""
    return marker_path.is_file() or _env_truthy(env, "PUBLISH_OK")


def decide_target(env: Mapping[str, str], marker_path: Path) -> PublishTarget:
    """Where `scripts/publish.sh` should upload, given the current gate state."""
    return PublishTarget.PYPI if publish_ok(env, marker_path) else PublishTarget.TEST_PYPI
