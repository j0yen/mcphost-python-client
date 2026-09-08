"""Exhaustive coverage of the PUBLISH-OK decision table (AC-6's ground truth)."""

from __future__ import annotations

from pathlib import Path

from mcphost.publish_gate import PublishTarget, decide_target, publish_ok


def test_no_marker_no_env_targets_testpypi(tmp_path: Path) -> None:
    marker = tmp_path / "PUBLISH-OK"
    assert not marker.exists()
    assert publish_ok({}, marker) is False
    assert decide_target({}, marker) is PublishTarget.TEST_PYPI


def test_marker_file_present_targets_pypi(tmp_path: Path) -> None:
    marker = tmp_path / "PUBLISH-OK"
    marker.write_text("go", encoding="utf-8")
    assert publish_ok({}, marker) is True
    assert decide_target({}, marker) is PublishTarget.PYPI


def test_env_var_truthy_targets_pypi(tmp_path: Path) -> None:
    marker = tmp_path / "PUBLISH-OK"
    for value in ("1", "true", "True", "yes", "on"):
        assert decide_target({"PUBLISH_OK": value}, marker) is PublishTarget.PYPI


def test_env_var_falsy_targets_testpypi(tmp_path: Path) -> None:
    marker = tmp_path / "PUBLISH-OK"
    for value in ("0", "false", "", "no"):
        assert decide_target({"PUBLISH_OK": value}, marker) is PublishTarget.TEST_PYPI


def test_directory_named_publish_ok_does_not_count(tmp_path: Path) -> None:
    # Only a real file counts -- a same-named directory (e.g. left over from
    # an unrelated checkout) must not accidentally open the gate.
    marker = tmp_path / "PUBLISH-OK"
    marker.mkdir()
    assert publish_ok({}, marker) is False
