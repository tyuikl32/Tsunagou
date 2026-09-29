"""Installation/connect timestamps describe observed phases, never host readiness."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from tsunagou.shared_kernel import time as wall_time

cli = importlib.import_module("tsunagou.cli.app")
runner = CliRunner()


def test_installation_info_is_offline_read_only_and_omits_unknown_times_and_private_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    path = tmp_path / ".tsunagou/installation.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "source_root": "installed-source", "commit": "recorded-commit", "installed_at": "2026-09-28T01:00:00.000Z",
        "session_id": "raw-session-sentinel", "thread_id": "raw-thread-sentinel", "secret_token": "secret-sentinel",
    }), encoding="utf-8")
    before = path.read_bytes(), path.stat().st_mtime_ns
    monkeypatch.setattr(cli, "_daemon_request", lambda *args, **kwargs: pytest.fail("installation query contacted daemon"))
    monkeypatch.setattr(cli, "_control_token", lambda: pytest.fail("installation query loaded a credential"))
    result = runner.invoke(cli.app, ["installation-info", "--json"])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["status"] == "installed" and value["commit"] == "recorded-commit"
    assert value["install_started_at"] is value["install_finished_at"] is value["duration_ms"] is None
    assert "sentinel" not in result.output
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_installation_info_with_no_registration_reports_unknown_values(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = runner.invoke(cli.app, ["--json", "installation-info"])
    assert result.exit_code == 0
    value = json.loads(result.output)
    assert value["status"] == "not_installed"
    assert value["source_root"] is value["install_started_at"] is value["duration_ms"] is None
    assert not (tmp_path / ".tsunagou").exists()


def connect_fixture(tmp_path, monkeypatch):
    destination = tmp_path / "conversation"
    destination.mkdir()
    (destination / "bridge-session.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("TSUNAGOU_HOST_CONVERSATION_ID", "private-thread-sentinel")
    monkeypatch.setattr(cli, "_runtime_context", lambda: SimpleNamespace(project_root=tmp_path, project_id="project-fixture"))
    monkeypatch.setattr(cli, "_ensure_project_daemon", lambda: None)
    monkeypatch.setattr(cli, "_control_token", lambda: "private-control-sentinel")
    monkeypatch.setattr(cli, "running_source_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "_write_bridge_config", lambda **kwargs: destination / "bridge-config.json")
    monkeypatch.setattr(cli, "_daemon_request", lambda *args, **kwargs: {"version": "0.1.0"})
    monkeypatch.setattr(cli, "_bridge_bootstrap", lambda *args: {
        "project_id": "project-fixture", "agent_id": "agent-fixture", "role": "worker",
        "session": {"status": "ready", "connection_epoch": 1, "session_id": "private-session-sentinel"},
        "host_binding": {"provider": "codex_desktop_app", "status": "ready", "thread_id": "private-thread-sentinel"},
    })
    args = ["agent", "connect", "--adapter", "codex", "--no-register-host", "--output-dir", str(destination)]
    return destination, args


def test_repeat_connect_preserves_first_connection_but_records_each_attempt(tmp_path, monkeypatch):
    destination, args = connect_fixture(tmp_path, monkeypatch)
    walls = iter([1000, 1100, 1200, 2000, 2100, 2200])
    monotonic = iter([10_000_000_000, 10_175_000_000, 11_000_000_000, 11_180_000_000])
    monkeypatch.setattr(wall_time, "now_ms", lambda: next(walls))
    monkeypatch.setattr(cli.time, "monotonic_ns", lambda: next(monotonic))
    first = runner.invoke(cli.app, args)
    assert first.exit_code == 0, first.output
    again = runner.invoke(cli.app, args)
    assert again.exit_code == 0, again.output
    a, b = json.loads(first.output), json.loads(again.output)
    assert a["connected_at"] == b["connected_at"] == "1970-01-01T00:00:01.100Z"
    assert a["connect_started_at"] == "1970-01-01T00:00:01.000Z"
    assert b["connect_started_at"] == "1970-01-01T00:00:02.000Z"
    assert b["enrolled_at"] == "1970-01-01T00:00:02.100Z"
    assert b["connect_finished_at"] == "1970-01-01T00:00:02.200Z"
    assert (a["duration_ms"], b["duration_ms"]) == (175, 180)
    assert b["status"] == "enrolled" and "original_conversation" in b["next"]
    assert "ready_at" not in b and "sentinel" not in first.output + again.output
    assert json.loads((destination / "connection.json").read_text(encoding="utf-8")) == b


def test_existing_connection_without_original_timestamp_keeps_it_unknown(tmp_path, monkeypatch):
    destination, args = connect_fixture(tmp_path, monkeypatch)
    (destination / "connection.json").write_text('{"status":"enrolled"}', encoding="utf-8")
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["connected_at"] is None


@pytest.mark.parametrize("after_enrollment", [False, True])
def test_failed_connect_has_attempt_times_and_only_observed_enrollment(tmp_path, monkeypatch, after_enrollment):
    destination, args = connect_fixture(tmp_path, monkeypatch)
    prior = destination / "connection.json"
    prior.write_text('{"connected_at":"2026-09-28T01:00:00.000Z"}', encoding="utf-8")
    before = prior.read_bytes(), prior.stat().st_mtime_ns

    def failure(*args):
        raise RuntimeError("daemon_unreachable" if after_enrollment else "bridge_bootstrap_failed")

    monkeypatch.setattr(cli, "_daemon_request" if after_enrollment else "_bridge_bootstrap", failure)
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 4
    value = json.loads(result.output)
    assert value["error"] == ("daemon_unreachable" if after_enrollment else "bridge_bootstrap_failed")
    assert bool(value["enrolled_at"]) == after_enrollment
    assert value["connect_started_at"].endswith("Z") and value["connect_finished_at"].endswith("Z")
    assert isinstance(value["duration_ms"], int) and value["duration_ms"] >= 0
    assert (prior.read_bytes(), prior.stat().st_mtime_ns) == before
