"""AC-7 [P1/MAY] — the one opt-in live test against the real mcphost.dev.

Given MCPHOST_LIVE_TEST is unset, this module is skipped entirely -- no
network call is attempted. Given it is set to a truthy value, it runs
signup -> test -> publish -> call against the real host and reports the
four step timings, mirroring the P1 `mcphost quickstart` requirement this
PRD deferred. This is deliberately thin: P1, "do not spend much time here."
"""

from __future__ import annotations

import os
import time

import pytest

import mcphost

LIVE = os.environ.get("MCPHOST_LIVE_TEST", "").strip().lower() in {"1", "true", "yes", "on"}

pytestmark = pytest.mark.skipif(
    not LIVE, reason="set MCPHOST_LIVE_TEST=1 to run the live smoke test against mcphost.dev"
)


def test_ac_7_live_signup_test_publish_call_against_mcphost_dev() -> None:
    # AC-7 [MAY]: Given the live flag set, when a signup->test->publish->call
    # sequence runs against mcphost.dev, then it completes and each step's
    # timing is reported.
    client = mcphost.Client()
    timings: dict[str, float] = {}

    start = time.monotonic()
    client.signup("mcphost-python-client-live-smoke")
    timings["signup"] = time.monotonic() - start

    spec = {
        "name": "smoke_echo",
        "kind": "echo",
        "spec": {"type": "object", "properties": {"msg": {"type": "string"}}},
    }

    start = time.monotonic()
    client.tool_test(spec)
    timings["test"] = time.monotonic() - start

    start = time.monotonic()
    client.tool_publish(spec)
    timings["publish"] = time.monotonic() - start

    start = time.monotonic()
    client.tool_call("smoke_echo", {"msg": "hello"})
    timings["call"] = time.monotonic() - start

    client.close()

    print("live smoke timings (s):", timings)
    assert set(timings) == {"signup", "test", "publish", "call"}
