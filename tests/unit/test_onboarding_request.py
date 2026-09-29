from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tsunagou.application.onboarding import prepare_codex_request, read_codex_request
from tsunagou.platform.runtime_context import RuntimeContext


def test_prepare_observes_original_host_and_preserves_idempotent_private_request(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[2]
    runtime = RuntimeContext(tmp_path, tmp_path / ".tsunagou/local", "p", {}, None, source)

    class Host:
        def __init__(self, endpoint, thread):
            assert endpoint == "private-pipe" and thread == "original-conversation"

        def call_tool(self, name, args):
            assert name == "read_thread" and args["threadId"] == "original-conversation"
            return {"thread": {"id": args["threadId"]}}

        def close(self):
            pass

    monkeypatch.setattr("tsunagou.application.onboarding.NativeAppToolsClient", Host)
    env = {"CODEX_THREAD_ID": "original-conversation", "CODEX_APP_TOOLS_PIPE_PATH": "private-pipe"}
    path = prepare_codex_request(runtime, environ=env)
    stamp = path.stat().st_mtime_ns
    assert prepare_codex_request(runtime, environ=env) == path and path.stat().st_mtime_ns == stamp
    request = read_codex_request(path, runtime)
    assert request["conversation_id"] == "original-conversation" and request["created_at"].endswith("Z")
    assert "original-conversation" not in str(path)
    assert not any(key in request for key in ("secret_token", "control_token", "agent_id"))
    with pytest.raises(RuntimeError, match="project_mismatch"):
        read_codex_request(path, RuntimeContext(tmp_path, runtime.state_dir, "another", {}, None, source))


def test_missing_native_context_does_not_invent_an_identity(tmp_path):
    runtime = RuntimeContext(tmp_path, tmp_path / "state", "p", {}, None, None)
    with pytest.raises(RuntimeError, match="desktop_context_missing"):
        prepare_codex_request(runtime, environ={})
    assert not runtime.state_dir.exists()


@pytest.mark.parametrize("header,array", [
    ('[mcp_servers.tsunagou]', 'env_vars = [\n  "KEEP_ME"\n]\n'),
    ('[mcp_servers.tsunagou] # Shared server', '  env_vars = ["KEEP_ME"] # Preserve forwarding\n'),
])
def test_host_environment_registration_preserves_other_settings(tmp_path, monkeypatch, header, array):
    import tomllib

    from tsunagou.application.onboarding import configure_codex_host_environment

    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    path = tmp_path / "config.toml"
    path.write_text('model = "unchanged"\n[mcp_servers.other]\ncommand = "other"\n'
                    f'{header}\ncommand = "node"\n{array}'
                    '[mcp_servers.tsunagou.env]\nTSUNAGOU_ROUTING_DIR = "routes"\n', encoding="utf-8")
    assert configure_codex_host_environment()
    first = path.read_bytes()
    assert not configure_codex_host_environment()
    assert path.read_bytes() == first
    config = tomllib.loads(first.decode())
    assert config["model"] == "unchanged" and config["mcp_servers"]["other"] == {"command": "other"}
    assert config["mcp_servers"]["tsunagou"]["env_vars"] == ["KEEP_ME", "CODEX_APP_TOOLS_PIPE_PATH"]


def test_concurrent_codex_registration_preserves_shared_config(tmp_path, monkeypatch):
    import subprocess
    import threading
    import tomllib
    from concurrent.futures import ThreadPoolExecutor

    cli = importlib.import_module("tsunagou.cli.app")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_resolve_codex_executable", lambda: "codex-test")
    config_path = tmp_path / "config.toml"
    config_path.write_text('model = "preserve"\n', encoding="utf-8")
    bridge_path = tmp_path / "bridge.json"
    desired = {"command": "node", "args": ["bridge.js"], "env": {"TSUNAGOU_ROUTING_DIR": "routes"}}
    bridge_path.write_text(json.dumps(desired), encoding="utf-8")
    calls = []
    first_read = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    original_run = subprocess.run

    def run(command, **kwargs):
        if command[0] != "codex-test":
            return original_run(command, **kwargs)
        verb = command[2]
        calls.append(verb)
        if verb == "get":
            if not first_read.is_set():
                first_read.set()
                assert release_first.wait(3)
            registered = "mcp_servers" in tomllib.loads(config_path.read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(command, 0 if registered else 1,
                                               json.dumps({"transport": desired}) if registered else "", "")
        if verb == "add":
            config_path.write_text(config_path.read_text(encoding="utf-8")
                                   + '[mcp_servers.tsunagou]\ncommand = "node"\nargs = ["bridge.js"]\n'
                                   '[mcp_servers.tsunagou.env]\nTSUNAGOU_ROUTING_DIR = "routes"\n', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", run)

    def register_second():
        second_started.set()
        return cli._register_codex_mcp(profile="two", bridge_config_path=bridge_path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cli._register_codex_mcp, profile="one", bridge_config_path=bridge_path)
        assert first_read.wait(3)
        second = pool.submit(register_second)
        assert second_started.wait(3)
        try:
            # Keep the first registration in get: another conversation must not
            # read the half-updated global config and begin a second replacement.
            assert not second.done()
            assert calls == ["get"]
        finally:
            release_first.set()
        assert first.result(timeout=5) == "registered:tsunagou"
        assert second.result(timeout=5) == "unchanged:tsunagou"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert calls == ["get", "remove", "add", "get"]
    assert config["model"] == "preserve"
    assert config["mcp_servers"]["tsunagou"]["env_vars"] == ["CODEX_APP_TOOLS_PIPE_PATH"]


def test_shared_registration_removes_only_same_project_legacy_servers(tmp_path, monkeypatch):
    import hashlib
    import subprocess

    cli = importlib.import_module("tsunagou.cli.app")
    project_root = tmp_path / "project"
    project_root.mkdir()
    tag = hashlib.sha256(str(project_root.resolve()).encode("utf-8")).hexdigest()[:8]
    bridge_path = tmp_path / "bridge.json"
    bridge = {"command": "node", "args": ["bridge.js"], "env": {"TSUNAGOU_ROUTING_DIR": "routes"}}
    bridge_path.write_text(json.dumps(bridge), encoding="utf-8")
    monkeypatch.setattr(cli, "_resolve_codex_executable", lambda: "codex-test")
    monkeypatch.setattr(
        "tsunagou.application.onboarding.configure_codex_host_environment",
        lambda: False,
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command[2:])
        if command[2] == "get":
            return subprocess.CompletedProcess(command, 1, "", "")
        if command[2] == "list":
            body = [
                {"name": f"tsunagou-worker-{tag}", "transport": {
                    "command": "node", "args": ["bridge.js"], "env": {
                        "TSUNAGOU_PROJECT_ROOT": str(project_root),
                        "TSUNAGOU_SESSION_FILE": "old-session.json",
                    },
                }},
                {"name": "tsunagou-worker-ffffffff", "transport": {
                    "command": "node", "args": ["bridge.js"], "env": {
                        "TSUNAGOU_PROJECT_ROOT": str(tmp_path / "other"),
                        "TSUNAGOU_SESSION_FILE": "other-session.json",
                    },
                }},
                {"name": f"tsunagou-unrelated-{tag}", "transport": {
                    "command": "other", "args": ["bridge.js"], "env": {
                        "TSUNAGOU_PROJECT_ROOT": str(project_root),
                        "TSUNAGOU_SESSION_FILE": "not-tsunagou.json",
                    },
                }},
            ]
            return subprocess.CompletedProcess(command, 0, json.dumps(body), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli._register_codex_mcp(
        profile="worker", bridge_config_path=bridge_path, legacy_project_root=project_root,
    ) == "registered:tsunagou"
    assert [command for command in calls if command[:2] == ["remove", f"tsunagou-worker-{tag}"]] == [
        ["remove", f"tsunagou-worker-{tag}"]
    ]
    assert [command for command in calls if command[:2] == ["remove", "tsunagou-worker-ffffffff"]] == []
    assert [command for command in calls if command[:2] == ["remove", f"tsunagou-unrelated-{tag}"]] == []


def test_stop_does_not_kill_an_unrelated_service_at_reused_endpoint(tmp_path, monkeypatch):
    cli = importlib.import_module("tsunagou.cli.app")
    state = tmp_path / ".tsunagou/local"
    state.mkdir(parents=True)
    manifest = state / "endpoint.json"
    manifest.write_text(json.dumps({"url": "http://localhost", "pid": 123, "project_id": "expected", "runtime_id": "old"}))
    monkeypatch.setattr(cli, "_read_daemon_health", lambda _: {"status": "ok", "runtime": {
        "project_ids": ["different"], "pid": 123, "runtime_id": "new",
    }})
    monkeypatch.setattr(cli, "_daemon_process_running", lambda _: True)
    killed = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: killed.append(args))
    result = CliRunner().invoke(cli.app, ["daemon", "stop", "--coordination-root", str(tmp_path)])
    assert result.exit_code == 4 and "daemon_identity_unverified" in result.output
    assert killed == [] and manifest.is_file()
