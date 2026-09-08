#!/usr/bin/env bash
# scripts/publish.sh — gated PyPI publish.
#
# Same convention pattern used elsewhere in this fleet: a build must never be
# one flag-flip away from landing on real PyPI. The actual decision (PyPI vs
# TestPyPI) is a pure function in src/mcphost/publish_gate.py, unit-tested in
# tests/test_publish_gate.py (AC-6) without ever shelling out or touching the
# network. This script is the thin, testable-by-inspection wrapper: it calls
# that decision function, prints which branch it took, and only then (never
# during this PRD's build) would perform the actual `uv publish`.
set -euo pipefail
cd "$(dirname "$0")/.."

target=$(uv run python -c '
from pathlib import Path
import os
from mcphost.publish_gate import decide_target
print(decide_target(os.environ, Path("PUBLISH-OK")).value)
')

echo "publish target: ${target}"

uv build

case "$target" in
  pypi)
    echo "PUBLISH-OK present: publishing to real PyPI"
    uv publish
    ;;
  testpypi)
    echo "no PUBLISH-OK marker/env: publishing to TestPyPI only"
    uv publish --publish-url https://test.pypi.org/legacy/
    ;;
  *)
    echo "unknown publish target: ${target}" >&2
    exit 2
    ;;
esac
