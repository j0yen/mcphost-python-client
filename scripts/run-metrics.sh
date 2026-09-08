#!/usr/bin/env bash
# run-metrics.sh — READ-ONLY harness. Emits normalized metrics.json for the loop.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
ruff_errors=$(uv run ruff check --quiet . 2>/dev/null | wc -l | tr -d ' ')
mypy_errors=$(uv run mypy src 2>/dev/null | grep 'error:' | wc -l | tr -d ' ')
uv run pytest -q 2>/dev/null; tests_failing=$?
cat > .pybuilder/metrics.json <<JSON
{ "ruff_errors": ${ruff_errors:-0},
  "mypy_errors": ${mypy_errors:-0},
  "tests_failing": ${tests_failing:-0},
  "coverage_pct": 0,
  "coverage_min": 0 }
JSON
echo "wrote .pybuilder/metrics.json"
