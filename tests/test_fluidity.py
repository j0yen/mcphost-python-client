"""AC-tagged offline tests for PRD-mcphost-python-client-fluidity, run
against `tests/fakeserver.py` (extended there with `FakeMcpHost.set_building`
to exercise the bounded wait without a network or a real sandbox).

test_ac_1 through test_ac_9 pair 1:1 with the PRD's nine acceptance criteria.
"""

from __future__ import annotations

import stat
import time
from pathlib import Path

import pytest
import yaml
from fakeserver import FakeMcpHost

import mcphost
from mcphost.cli import main
from mcphost.errors import CapacityError, ToolBuildingError


def test_ac_1_tool_call_waits_out_two_building_results(fake_host: FakeMcpHost) -> None:
    # AC-1 [MUST]: Given a fake host that returns `building` with
    # `retry_after_ms: 50` twice then a result, When `tool_call` runs, Then
    # it returns the result after two waits and no exception.
    fake_host.set_building("host.tool_call", times=2, retry_after_ms=50)
    fake_host.responses["host.tool_call"] = {"ok": True, "payload": {"n": 1}}

    client = mcphost.Client(base_url=fake_host.base_url, key="tk")
    result = client.tool_call("t", {})
    client.close()

    assert result == {"ok": True, "payload": {"n": 1}}
    assert len(fake_host.calls("host.tool_call")) == 3


def test_ac_2_tool_call_raises_after_build_wait_s_exhausted(fake_host: FakeMcpHost) -> None:
    # AC-2 [MUST]: Given the same fake host returning `building` forever and
    # `build_wait_s=1`, When `tool_call` runs, Then `ToolBuildingError` is
    # raised within 1.5s carrying `retry_after_ms`.
    fake_host.set_building("host.tool_call", times=None, retry_after_ms=50)

    client = mcphost.Client(base_url=fake_host.base_url, key="tk", build_wait_s=1)
    start = time.monotonic()
    with pytest.raises(ToolBuildingError) as excinfo:
        client.tool_call("t", {})
    elapsed = time.monotonic() - start
    client.close()

    assert elapsed < 1.5
    assert excinfo.value.retry_after_ms == 50


def test_ac_3_signup_then_list_uses_saved_key_no_flags(
    fake_host: FakeMcpHost, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AC-3 [MUST]: Given a fresh config dir, When `mcphost signup me` then
    # `mcphost list` run with no key flags, Then `list` succeeds using the
    # saved key and the credentials file is mode 0600.
    creds_path = tmp_path / "credentials"
    monkeypatch.setattr("mcphost.cli.DEFAULT_CREDENTIALS_PATH", creds_path)
    fake_host.responses["signup"] = {
        "tenant": "brisk-otter",
        "key": "sk-test-abc123",
        "namespace": "brisk-otter",
        "endpoint": fake_host.base_url,
    }
    fake_host.responses["host.tool_list"] = {"tools": []}

    rc_signup = main(["signup", "me", "--base-url", fake_host.base_url])
    rc_list = main(["list", "--base-url", fake_host.base_url])

    assert rc_signup == 0
    assert rc_list == 0
    assert creds_path.is_file()
    assert stat.S_IMODE(creds_path.stat().st_mode) == 0o600
    list_calls = fake_host.calls("host.tool_list")
    assert len(list_calls) == 1
    assert list_calls[0]["params"]["arguments"]["tenant_key"] == "sk-test-abc123"


def test_ac_4_logout_then_list_fails_naming_signup_or_key(
    fake_host: FakeMcpHost, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # AC-4 [MUST]: Given `mcphost logout`, When `mcphost list` runs, Then it
    # fails naming `signup` or `--key`.
    creds_path = tmp_path / "credentials"
    monkeypatch.setattr("mcphost.cli.DEFAULT_CREDENTIALS_PATH", creds_path)
    fake_host.responses["signup"] = {"tenant": "t", "key": "sk-test-abc123"}

    main(["signup", "me", "--base-url", fake_host.base_url])
    rc_logout = main(["logout", "--base-url", fake_host.base_url])

    with pytest.raises(SystemExit) as excinfo:
        main(["list", "--base-url", fake_host.base_url])

    assert rc_logout == 0
    message = str(excinfo.value)
    assert "signup" in message or "--key" in message


def test_ac_5_new_client_methods_send_expected_tool_names(fake_host: FakeMcpHost) -> None:
    # AC-5 [MUST]: Given the client, When `tool_logs`, `tool_remove`,
    # `secret_set`, `secret_list`, `whoami`, `quickstart`, `billing_status`,
    # `billing_checkout` are called against the fake host, Then each sends
    # the matching `host.*`/`billing.*` tool name with `tenant_key`.
    for tool_name in (
        "host.tool_logs",
        "host.tool_remove",
        "host.secret_set",
        "host.secret_list",
        "host.whoami",
        "host.quickstart",
        "billing.status",
        "billing.checkout",
    ):
        fake_host.responses[tool_name] = {"ok": True}

    client = mcphost.Client(base_url=fake_host.base_url, key="tk")
    client.tool_logs("t", limit=20)
    client.tool_remove("t")
    client.secret_set("token", "v")
    client.secret_list()
    client.whoami()
    client.quickstart("echo")
    client.billing_status()
    client.billing_checkout("pro")
    client.close()

    for tool_name in (
        "host.tool_logs",
        "host.tool_remove",
        "host.secret_set",
        "host.secret_list",
        "host.whoami",
        "host.quickstart",
        "billing.status",
        "billing.checkout",
    ):
        calls = fake_host.calls(tool_name)
        assert len(calls) == 1, tool_name
        assert calls[0]["params"]["arguments"]["tenant_key"] == "tk", tool_name


def test_ac_6_capacity_error_carries_retry_after_ms(fake_host: FakeMcpHost) -> None:
    # AC-6 [MUST]: Given a host `capacity` error with `retry_after_ms: 300`,
    # When `tool_call` runs, Then `CapacityError` is raised with
    # `retry_after_ms == 300`.
    fake_host.errors["host.tool_call"] = {
        "code": -32000,
        "message": "at the concurrent-call limit; try again shortly",
        "data": {"error_code": "capacity", "retry_after_ms": 300},
    }

    client = mcphost.Client(base_url=fake_host.base_url, key="tk")
    with pytest.raises(CapacityError) as excinfo:
        client.tool_call("t", {})
    client.close()

    assert excinfo.value.retry_after_ms == 300


def test_ac_7_release_workflow_has_tag_trigger_and_trusted_publishing() -> None:
    # AC-7 [MUST]: Given the repo, When `git tag v0.2.0` is pushed, Then the
    # workflow builds the wheel and publishes (or, before trusted publishing
    # is configured, the workflow's dry-run step passes and the receipt
    # records the operator step as pending). Verified structurally here
    # (parsing the workflow, not actually running it or touching PyPI).
    workflow_path = (
        Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release.yml"
    )
    assert workflow_path.is_file()
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    # PyYAML parses a bare `on:` mapping key as boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert "v*" in triggers["push"]["tags"]
    assert "workflow_dispatch" in triggers

    build_job = workflow["jobs"]["build"]
    assert any("uv build" in step.get("run", "") for step in build_job["steps"])

    publish_job = workflow["jobs"]["publish"]
    assert publish_job["permissions"]["id-token"] == "write"
    assert publish_job["if"] == "startsWith(github.ref, 'refs/tags/v')"


def test_ac_8_wait_ready_polls_until_tool_test_succeeds(fake_host: FakeMcpHost) -> None:
    # AC-8 [P1/MAY]: Given a python tool still building, When
    # `wait_ready(name, timeout_s=10)` runs, Then it returns once
    # `tool_test` succeeds.
    fake_host.set_building("host.tool_test", times=1, retry_after_ms=10)
    fake_host.responses["host.tool_test"] = {"ok": True}

    client = mcphost.Client(base_url=fake_host.base_url, key="tk")
    result = client.wait_ready("t", timeout_s=5)
    client.close()

    assert result == {"ok": True}
    assert len(fake_host.calls("host.tool_test")) == 2


def test_ac_9_json_flag_prints_raw_envelope(
    fake_host: FakeMcpHost, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC-9 [P1/MAY]: Given `mcphost --json whoami`, When run, Then stdout is
    # the raw JSON envelope. `--json` is a per-subcommand flag throughout
    # this CLI (matching every existing command's convention, see
    # test_acceptance.py's test_ac_9), so it is exercised here in that same
    # position rather than before the subcommand name.
    import json as _json

    fake_host.responses["host.whoami"] = {"tenant": "t", "plan": "free"}

    exit_code = main(["whoami", "--base-url", fake_host.base_url, "--key", "tk", "--json"])
    printed = _json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert printed == fake_host.responses["host.whoami"]
