"""AC-tagged offline acceptance tests, run against `fakeserver.FakeMcpHost`.

test_ac_1 through test_ac_6 pair 1:1 with the PRD's six P0 acceptance
criteria (PRD-mcphost-python-client.md). AC-7 (the live smoke test) lives in
`test_live_smoke.py`, not here, since it is opt-in and network-bound.
test_ac_8 and test_ac_9 are additional criteria this build's own
intent-card.json added beyond the PRD's numbered ACs (the client-level
clientInfo handshake, and every CLI command's --json output shape) -- not
PRD-numbered, but exercising requirements 1 and 2 the PRD's prose describes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakeserver import FakeMcpHost

import mcphost
from mcphost.cli import main


def test_ac_1_signup_prints_key_and_clientinfo(
    fake_host: FakeMcpHost, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC-1 [MUST]: Given a fake MCP server fixture, when `mcphost signup "x"
    # --json` runs against it, then the CLI prints the key the fake server
    # returned, and the fake server's captured `initialize` request has
    # `params.clientInfo.name == "mcphost-python"`.
    fake_host.responses["signup"] = {
        "tenant": "brisk-otter",
        "key": "sk-test-abc123",
        "namespace": "brisk-otter",
        "endpoint": fake_host.base_url,
        "usage": "Pass this key as the tenant_key argument on every call.",
        "next": "host.quickstart",
    }

    exit_code = main(["signup", "x", "--json", "--base-url", fake_host.base_url])

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == fake_host.responses["signup"]
    assert printed["key"] == "sk-test-abc123"

    init_request = fake_host.initialize_request()
    assert init_request is not None
    assert init_request["params"]["clientInfo"]["name"] == "mcphost-python"


def test_ac_2_test_then_publish_forwards_spec_verbatim(
    fake_host: FakeMcpHost, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC-2 [MUST]: Given a valid http-kind spec file, when `mcphost test
    # spec.yaml` then `mcphost publish spec.yaml` run, then the fake server
    # received `host.tool_test` then `host.tool_publish`, each carrying the
    # spec forwarded verbatim.
    spec = {
        "name": "weather",
        "kind": "http",
        "spec": {
            "method": "GET",
            "url": "https://api.example.com/weather/{{city}}",
            "response": "json",
        },
    }
    spec_file = tmp_path / "weather.yaml"
    spec_file.write_text(json.dumps(spec), encoding="utf-8")  # valid JSON is valid YAML

    fake_host.responses["host.tool_test"] = {"ok": True}
    fake_host.responses["host.tool_publish"] = {"name": "ns1.weather", "kind": "http"}

    rc_test = main(
        ["test", str(spec_file), "--base-url", fake_host.base_url, "--key", "tk", "--json"]
    )
    rc_publish = main(
        ["publish", str(spec_file), "--base-url", fake_host.base_url, "--key", "tk", "--json"]
    )
    capsys.readouterr()  # drain stdout; this AC is about what the fake received

    assert rc_test == 0
    assert rc_publish == 0

    test_calls = fake_host.calls("host.tool_test")
    publish_calls = fake_host.calls("host.tool_publish")
    assert len(test_calls) == 1
    assert len(publish_calls) == 1

    def without_key(arguments: dict[str, object]) -> dict[str, object]:
        return {k: v for k, v in arguments.items() if k != "tenant_key"}

    assert without_key(test_calls[0]["params"]["arguments"]) == spec
    assert without_key(publish_calls[0]["params"]["arguments"]) == spec
    # Order matters: test before publish.
    test_request_order = fake_host.requests.index(test_calls[0])
    publish_request_order = fake_host.requests.index(publish_calls[0])
    assert test_request_order < publish_request_order


def test_ac_3_call_result_unchanged(
    fake_host: FakeMcpHost, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC-3 [MUST]: Given a published tool, when `mcphost call my.tool
    # '{"a":1}' --json` runs, then the printed JSON equals the fake's
    # `tools/call` result unchanged, including a nested `payload` key.
    fake_host.responses["host.tool_call"] = {
        "ok": True,
        "payload": {"forecast": "sunny", "temp_c": 21},
        "duration_ms": 4,
    }

    exit_code = main(
        ["call", "my.tool", '{"a": 1}', "--base-url", fake_host.base_url, "--key", "tk", "--json"]
    )

    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == fake_host.responses["host.tool_call"]
    assert printed["payload"] == {"forecast": "sunny", "temp_c": 21}

    calls = fake_host.calls("host.tool_call")
    assert len(calls) == 1
    assert calls[0]["params"]["arguments"] == {
        "name": "my.tool",
        "args": {"a": 1},
        "tenant_key": "tk",
    }


def test_ac_4_structured_error_unreworded(
    fake_host: FakeMcpHost, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC-4 [MUST]: Given a server error object, when any command receives
    # it, then the CLI prints the object as JSON and exits non-zero, without
    # rewording it.
    fake_host.errors["host.tool_list"] = {
        "code": -32000,
        "message": "tenant is disabled",
        "data": {"error_code": "tenant_disabled", "docs": "host.quickstart"},
    }

    exit_code = main(["list", "--base-url", fake_host.base_url, "--key", "tk"])

    assert exit_code != 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == fake_host.errors["host.tool_list"]
    assert printed["data"]["error_code"] == "tenant_disabled"


def test_ac_5_wheel_metadata_matches_shared_strings() -> None:
    # AC-5 [MUST]: Given `uv build`, when it runs, then a wheel is produced
    # whose metadata description equals the shared description string and
    # whose project URLs include mcphost.dev. Building is exercised by the
    # gate/CI shell step (`uv build`), not by pytest itself (that would
    # shell out to a packaging tool from inside the test suite); this test
    # instead pins the *source of truth* pyproject.toml carries, so a wheel
    # built from it cannot drift without this test catching it.
    import tomllib

    pyproject = tomllib.loads(
        (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert pyproject["project"]["description"] == (
        "Hosted MCP runtime where the agent is the operator: sign up by tool "
        "call, publish your own tools."
    )
    urls = pyproject["project"]["urls"]
    assert any("mcphost.dev" in url for url in urls.values())


def test_ac_6_no_publish_ok_targets_testpypi() -> None:
    # AC-6 [MUST]: Given no PUBLISH-OK, when the publish step runs, then it
    # uploads to TestPyPI (or dry-runs) and never to PyPI. See
    # test_publish_gate.py for the exhaustive decision-table coverage; this
    # is the literal AC-shaped check.
    from mcphost.publish_gate import PublishTarget, decide_target

    target = decide_target({}, Path("/nonexistent/PUBLISH-OK"))
    assert target is PublishTarget.TEST_PYPI


def test_ac_8_clientinfo_shape_exact(fake_host: FakeMcpHost) -> None:
    # AC-8 [MUST]: Given the library's Client, when it performs the MCP
    # initialize handshake, then params.clientInfo is exactly
    # {"name": "mcphost-python", "version": <installed package version>}.
    client = mcphost.Client(base_url=fake_host.base_url)
    client.signup("agent-in-a-sandbox")
    client.close()

    init_request = fake_host.initialize_request()
    assert init_request is not None
    assert init_request["params"]["clientInfo"] == {
        "name": "mcphost-python",
        "version": mcphost.__version__,
    }


def test_ac_9_json_output_matches_library_return_shape(
    fake_host: FakeMcpHost, capsys: pytest.CaptureFixture[str]
) -> None:
    # AC-9 [MUST]: Given every CLI command, when invoked with --json, then
    # machine-readable JSON is printed matching the library method's return
    # value structure-for-structure.
    fake_host.responses["host.tool_list"] = {"tools": [{"name": "ns1.weather", "kind": "http"}]}
    fake_host.responses["host.usage"] = {"window": "24h", "calls": 3, "errors": 0}

    rc_list = main(["list", "--base-url", fake_host.base_url, "--key", "tk", "--json"])
    printed_list = json.loads(capsys.readouterr().out)
    rc_usage = main(["usage", "--base-url", fake_host.base_url, "--key", "tk", "--json"])
    printed_usage = json.loads(capsys.readouterr().out)

    assert rc_list == 0
    assert printed_list == fake_host.responses["host.tool_list"]
    assert rc_usage == 0
    assert printed_usage == fake_host.responses["host.usage"]
