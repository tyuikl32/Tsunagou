from __future__ import annotations

import importlib
import json
import os
import subprocess
import urllib.error
from pathlib import Path

import pytest
from typer.testing import CliRunner

cli_module = importlib.import_module("tsunagou.cli.app")


@pytest.fixture
def daemon_manifest(tmp_path: Path, monkeypatch):
    path = tmp_path / "endpoint.json"
    value = {"pid": 123456, "url": "http://127.0.0.1:1", "project_id": "project-a",
             "runtime_id": "runtime-a", "source_root": str(tmp_path), "daemon_registry": "retained.json"}
    path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(cli_module, "_endpoint_manifest", lambda _: path)
    monkeypatch.setattr(cli_module, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(cli_module, "_read_daemon_health", lambda _: {
        "status": "ok", "runtime": {**value, "project_ids": ["project-a", "project-b"]},
    })
    return path, value


def test_stop_unreachable_exited_pid_is_idempotent(daemon_manifest, monkeypatch):
    path, value = daemon_manifest

    def unreachable(_):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(cli_module, "_read_daemon_health", unreachable)
    monkeypatch.setattr(cli_module, "_daemon_process_running", lambda _: False)
    result = CliRunner().invoke(cli_module.app, ["daemon", "stop"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "already_stopped"
    assert json.loads(path.read_text(encoding="utf-8")) == value


@pytest.mark.parametrize("health_failure", ["unreachable", "different_runtime"])
def test_stop_never_kills_live_unverified_pid(daemon_manifest, monkeypatch, health_failure):
    def health(_):
        if health_failure == "unreachable":
            raise urllib.error.URLError("connection refused")
        return {"status": "ok", "runtime": {"pid": 123456, "runtime_id": "different", "project_ids": ["project-a"]}}

    monkeypatch.setattr(cli_module, "_read_daemon_health", health)
    monkeypatch.setattr(cli_module, "_daemon_process_running", lambda _: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("must not kill unverified PID"))
    result = CliRunner().invoke(cli_module.app, ["daemon", "stop"])
    assert result.exit_code == 4
    assert json.loads(result.output)["error"] == "daemon_identity_unverified"


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill result handling")
def test_stop_failed_taskkill_cannot_report_success(daemon_manifest, monkeypatch):
    monkeypatch.setattr(cli_module, "_daemon_process_running", lambda _: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 1, b"", b"access denied"))
    result = CliRunner().invoke(cli_module.app, ["daemon", "stop"])
    assert result.exit_code == 4
    assert json.loads(result.output)["error"] == "daemon_stop_failed"


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill result handling")
def test_stop_requires_observed_exit_after_successful_taskkill(daemon_manifest, monkeypatch):
    monkeypatch.setattr(cli_module, "_daemon_process_running", lambda _: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, b"", b""))
    times = iter([0.0, 6.0])
    monkeypatch.setattr(cli_module.time, "monotonic", lambda: next(times))
    result = CliRunner().invoke(cli_module.app, ["daemon", "stop"])
    assert result.exit_code == 4
    assert json.loads(result.output)["error"] == "daemon_stop_timeout"


def test_real_process_probe_does_not_mistake_current_process_for_exited():
    assert cli_module._daemon_process_running(os.getpid())
    with pytest.raises(ValueError, match="invalid_daemon_pid"):
        cli_module._daemon_process_running(0)


@pytest.mark.parametrize("alive", [False, True])
def test_status_distinguishes_exited_process_from_unreachable_live_process(daemon_manifest, monkeypatch, alive):
    def unreachable(_):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(cli_module, "_read_daemon_health", unreachable)
    monkeypatch.setattr(cli_module, "_daemon_process_running", lambda _: alive)
    result = CliRunner().invoke(cli_module.app, ["daemon", "status"])
    assert result.exit_code == (4 if alive else 3)
    assert json.loads(result.output)["status"] == ("unverified" if alive else "stopped")
