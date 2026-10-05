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


def test_deepseek_uses_native_identity_not_inherited_codex_or_generic_identity(tmp_path, monkeypatch):
    cli = importlib.import_module("tsunagou.cli.app")
    monkeypatch.setenv("CODEX_THREAD_ID", "wrong-codex")
    monkeypatch.setenv("TSUNAGOU_HOST_CONVERSATION_ID", "wrong-generic")
    monkeypatch.delenv("DSH_SESSION_ID", raising=False)
    with pytest.raises(RuntimeError, match="host_conversation_required"):
        cli._profile_identity(tmp_path, "deepseek", "desktop")
    assert not (tmp_path / "host-identity.json").exists()
    monkeypatch.setenv("DSH_SESSION_ID", "actual-dsh-session")
    identity = cli._profile_identity(tmp_path, "deepseek", "headless")
    assert identity[1] == "actual-dsh-session"
    assert cli._profile_identity(tmp_path, "deepseek", "desktop") == identity
    monkeypatch.setenv("DSH_SESSION_ID", "another-session")
    with pytest.raises(RuntimeError, match="profile_conversation_conflict"):
        cli._profile_identity(tmp_path, "deepseek", "desktop")


def test_deepseek_private_routes_are_idempotent_and_refuse_other_projects(tmp_path, monkeypatch):
    from tsunagou.application.onboarding import write_deepseek_route

    monkeypatch.setenv("TSUNAGOU_ROUTING_DIR", str(tmp_path / "routes"))
    runtime = RuntimeContext(tmp_path, tmp_path / ".tsunagou/local", "project-a", {}, None, None)
    destination = tmp_path / ".tsunagou/bridges/deepseek-fixture"
    route = write_deepseek_route("native-private-id", runtime, destination)
    before = route.read_bytes(), route.stat().st_mtime_ns
    assert write_deepseek_route("native-private-id", runtime, destination) == route
    assert (route.read_bytes(), route.stat().st_mtime_ns) == before
    value = json.loads(route.read_bytes())
    assert value["session_file"] == str(destination / "bridge-session.json")
    assert "endpoint" not in value and "native-private-id" not in str(route)
    other = RuntimeContext(tmp_path / "other", tmp_path / "other/state", "project-b", {}, None, None)
    with pytest.raises(RuntimeError, match="host_route_project_conflict"):
        write_deepseek_route("native-private-id", other, destination)
    assert (route.read_bytes(), route.stat().st_mtime_ns) == before


def test_deepseek_prepare_only_configures_plugin_without_identity_or_daemon(tmp_path, monkeypatch):
    cli = importlib.import_module("tsunagou.cli.app")
    from tsunagou.platform.host_registration import REGISTERED, ConfigChange

    monkeypatch.delenv("DSH_SESSION_ID", raising=False)
    monkeypatch.setattr(cli, "_runtime_context", lambda: pytest.fail("prepare must not access project authority"))
    monkeypatch.setattr(cli, "_ensure_project_daemon", lambda: pytest.fail("prepare must not start daemon"))
    monkeypatch.setattr(cli, "_prepare_deepseek_desktop", lambda: ConfigChange(REGISTERED, (tmp_path / "cordis.patch.yml",)))
    result = CliRunner().invoke(cli.app, ["agent", "prepare", "--adapter", "deepseek"])
    assert result.exit_code == 0, result.output
    value = json.loads(result.output)
    assert value["status"] == "prepared" and value["creates_agent"] is False and value["host_ready"] is False
    assert value["next"] == "call_tsunagou_connect_in_original_conversation"


def test_desktop_config_uses_installed_runtime_and_keeps_node_available(tmp_path, monkeypatch):
    import os

    cli = importlib.import_module("tsunagou.cli.app")
    source = tmp_path / "source"
    (source / "src").mkdir(parents=True)
    (source / ".venv/Lib/site-packages").mkdir(parents=True)
    bridge = source / "packages/bridge-server/dist/server.js"
    bridge.parent.mkdir(parents=True)
    bridge.write_text("", encoding="utf-8")
    node = tmp_path / "node.exe"
    python = tmp_path / "installed-python.exe"
    node.touch()
    python.touch()
    install = tmp_path / "installation.json"
    install.write_text(json.dumps({"source_root": str(source), "python": str(python)}), encoding="utf-8")
    monkeypatch.setattr(cli, "running_source_root", lambda: source)
    monkeypatch.setattr(cli.shutil, "which", lambda _: str(node))
    monkeypatch.setattr("tsunagou.platform.runtime_context.installation_path", lambda: install)
    monkeypatch.setenv("TSUNAGOU_ROUTING_DIR", str(tmp_path / "routes"))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "must-not-travel")
    config = cli._deepseek_desktop_config()
    assert config["command"] == str(node)
    assert config["connect"]["command"] == str(python)
    environment = config["connect"]["env"]
    assert environment["PATH"].split(os.pathsep)[0] == str(node.parent)
    assert str(source / ".venv/Lib/site-packages") in environment["PYTHONPATH"].split(os.pathsep)
    assert "must-not-travel" not in json.dumps(config)


def test_deepseek_registration_failure_is_not_reported_as_enrolled(tmp_path, monkeypatch):
    cli = importlib.import_module("tsunagou.cli.app")
    from tsunagou.platform.host_registration import FAILED, Registration

    config = tmp_path / "bridge.json"
    config.write_text(json.dumps({"env": {"TSUNAGOU_PROJECT_ROOT": str(tmp_path)}}), encoding="utf-8")
    monkeypatch.setattr(cli.host_registration, "register", lambda *args, **kwargs: Registration(
        adapter="deepseek", label="DeepSeek Harness", status=FAILED, name="tsunagou"))
    with pytest.raises(RuntimeError, match="deepseek_host_registration_failed"):
        cli._register_host_mcp(adapter="deepseek", profile="headless", bridge_config_path=config)


def test_daemon_launch_failure_keeps_the_specific_public_error(monkeypatch, tmp_path):
    import subprocess

    cli = importlib.import_module("tsunagou.cli.app")
    runtime = RuntimeContext(tmp_path, tmp_path / "state", "project", {}, None, None)
    monkeypatch.setattr(cli, "_runtime_context", lambda: runtime)

    def unavailable(*args, **kwargs):
        raise RuntimeError("daemon_endpoint_not_configured")

    monkeypatch.setattr(cli, "_daemon_request", unavailable)
    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 1, '{"status":"error","error":"daemon_launch_failed","os_error":5}', "private stderr"))
    with pytest.raises(RuntimeError, match="^daemon_launch_failed:os_error_5$"):
        cli._ensure_project_daemon()


@pytest.mark.parametrize("explicit_role,expected_code", [(None, 0), ("main", 0), ("worker", 4)])
def test_deepseek_connect_preserves_existing_main_unless_role_is_explicit(tmp_path, monkeypatch, explicit_role, expected_code):
    cli = importlib.import_module("tsunagou.cli.app")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    native = "native-session"
    monkeypatch.setenv("DSH_SESSION_ID", native)
    monkeypatch.setenv("TSUNAGOU_ROUTING_DIR", str(tmp_path / "routes"))
    destination = tmp_path / ".tsunagou/bridges/existing"
    destination.mkdir(parents=True)
    (destination / "bridge-session.json").write_text("{}", encoding="utf-8")
    (destination / "host-identity.json").write_text(json.dumps({
        "adapter": "deepseek", "profile": "old", "installation_id": "existing-installation", "conversation_id": native,
    }), encoding="utf-8")
    runtime = RuntimeContext(tmp_path, tmp_path / ".tsunagou/local", "project-a", {}, None, tmp_path)
    monkeypatch.setattr(cli, "_runtime_context", lambda: runtime)
    monkeypatch.setattr(cli, "_ensure_project_daemon", lambda: None)
    monkeypatch.setattr(cli, "_control_token", lambda: "private-token")
    monkeypatch.setattr(cli, "running_source_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "_invoke_command", lambda *args, **kwargs: pytest.fail("must not reenroll or change role"))
    monkeypatch.setattr(cli, "_daemon_request", lambda *args, **kwargs: {"version": "fixture"})

    def bootstrap(config, request):
        assert json.loads(request.read_bytes())["conversation_id"] == native
        assert json.loads(config.read_bytes())["env"]["TSUNAGOU_HOST_META_KEY"] == "tsunagou.hostSessionId"
        return {"project_id": "project-a", "agent_id": "existing-agent", "role": "main",
                "session": {"status": "ready", "connection_epoch": 3}}

    monkeypatch.setattr(cli, "_bridge_bootstrap", bootstrap)
    args = ["agent", "connect", "--adapter", "deepseek", "--profile", "desktop", "--no-register-host",
            "--output-dir", str(destination)]
    if explicit_role:
        args += ["--role", explicit_role]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == expected_code, result.output
    value = json.loads(result.output)
    if expected_code == 0:
        assert value["status"] == "enrolled" and value["agent_id"] == "existing-agent" and value["role"] == "main"
        assert value["installation_id"] == "existing-installation" and value["host_ready"] is False
        assert "launch_command" not in value and "private-token" not in result.output
        managed = json.loads((tmp_path / ".tsunagou/hosts/deepseek-wake/managed.json").read_text())
        assert managed["bindings"] == [{"project_id": "project-a", "agent_id": "existing-agent", "session_id": native}]
        assert managed["key"] not in result.output
        assert value["wake_configuration"] == "configured_unverified"
    else:
        assert value["error"] == "current_agent_is_main:explicit_revoke_required"
        assert not (tmp_path / ".tsunagou/hosts/deepseek-wake/managed.json").exists()
