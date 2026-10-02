"""Real CLI subprocesses for local runtime discovery and onboarding foundations."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_background_daemon_survives_starting_cli_and_resolves_from_subdirectory(tmp_path: Path):
    root = tmp_path / "business"
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    child = root / "src/nested"
    child.mkdir(parents=True)
    env = {name: value for name, value in os.environ.items() if not name.startswith("TSUNAGOU_")}
    # This test strips the TSUNAGOU_ slate to prove the daemon is found without project
    # env. The machine-level index is a different concern: without keeping its override,
    # the client below registers a throwaway project into the developer's home directory.
    if os.environ.get("TSUNAGOU_PROJECT_INDEX"):
        env["TSUNAGOU_PROJECT_INDEX"] = os.environ["TSUNAGOU_PROJECT_INDEX"]

    def cli(*args, cwd=root):
        result = subprocess.run([sys.executable, "-m", "tsunagou", *args], cwd=cwd, env=env,
                                capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr or result.stdout
        return json.loads(result.stdout)

    started = cli("daemon", "start")
    try:
        assert started["status"] == "started" and started["started_at"].endswith("Z")
        # The start process has exited; this is a new process with no project env.
        health = cli("--json", "doctor", cwd=child)
        assert health["runtime"]["pid"] == started["pid"]
        assert health["runtime"]["runtime_id"] == started["runtime_id"]
        assert health["runtime"]["project_ids"] == [started["project_id"]]
        again = cli("--project-root", str(root), "daemon", "start", cwd=tmp_path)
        assert again["status"] == "already_running" and again["pid"] == started["pid"]
        status = cli("daemon", "status", cwd=child)
        assert status["status"] == "running"
    finally:
        stopped = cli("daemon", "stop", cwd=child)
        assert stopped["project_ids"] == [started["project_id"]]


def test_one_connect_and_shared_mcp_keep_two_host_conversations_separate(tmp_path: Path):
    from tsunagou.application.onboarding import conversation_key
    from tsunagou.platform.private_files import write_private_bytes

    source = Path(__file__).resolve().parents[2]
    root = tmp_path / "business"
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    nested = root / "nested"
    nested.mkdir()
    env = {name: value for name, value in os.environ.items() if not name.startswith(("TSUNAGOU_", "CODEX_"))}
    # Keep the machine-index override: this test is not about where the machine records
    # its projects, and dropping it would write a throwaway line into the user's home.
    if os.environ.get("TSUNAGOU_PROJECT_INDEX"):
        env["TSUNAGOU_PROJECT_INDEX"] = os.environ["TSUNAGOU_PROJECT_INDEX"]
    env["TSUNAGOU_ROUTING_DIR"] = str(tmp_path / "routes")

    def cli(*args):
        result = subprocess.run([sys.executable, "-m", "tsunagou", "--project-root", str(root), *args],
                                cwd=nested, env=env, capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stderr or result.stdout
        return json.loads(result.stdout)

    project = cli("project", "init", "--coordination-root", str(root))
    requests = []
    connected = []
    try:
        for name, role in (("fixture-original-a", "main"), ("fixture-original-b", "worker")):
            request = root / ".tsunagou/local/onboarding" / conversation_key(name) / "request.json"
            write_private_bytes(request, json.dumps({
                "format_version": 1, "adapter": "codex", "project_id": project["project_id"],
                "project_root": str(root), "source_root": str(source), "installation_id": "codex:desktop",
                "conversation_id": name, "endpoint": "fixture-pipe", "host_generation": conversation_key("fixture-pipe"),
            }).encode())
            requests.append(str(request))
            args = ["agent", "connect", "--adapter", "codex", "--request-file", str(request), "--role", role, "--no-register-host"]
            first = cli(*args)
            again = cli(*args)
            assert first["agent_id"] == again["agent_id"] and first["role"] == role
            assert first["status"] == "enrolled" and first["next"] == "call_context__project_read_in_original_conversation"
            assert first["connected_at"] == again["connected_at"] == first["enrolled_at"]
            for observed in (first, again):
                assert observed["connect_started_at"] <= observed["enrolled_at"] <= observed["connect_finished_at"]
                assert observed["connect_started_at"].endswith("Z") and observed["duration_ms"] >= 0
                assert "ready_at" not in observed and "session_id" not in observed["session"]
            assert first["connect_finished_at"] <= again["connect_started_at"]
            assert json.loads((request.parent / "connection.json").read_text(encoding="utf-8")) == again
            connected.append(first)
        assert connected[0]["agent_id"] != connected[1]["agent_id"]
        exercised = subprocess.run([
            "node", str(source / "packages/bridge-server/scripts/smoke-shared-host.mjs"),
            connected[0]["bridge_config"], *requests,
        ], cwd=nested, env=env, capture_output=True, text=True, timeout=45)
        assert exercised.returncode == 0, exercised.stderr or exercised.stdout
        assert json.loads(exercised.stdout)["same_process_calls"] == 20
        agents = cli("agent", "list", "--json")
        assert {row["role"] for row in agents["items"]} == {"main", "worker"}
        assert all(row["last_activity_at"].endswith("Z") and row["session_status"] == "ready" for row in agents["items"])
        with sqlite3.connect(root / ".tsunagou/local/state.sqlite3") as conn:
            assert conn.execute("SELECT COUNT(*) FROM commands WHERE command_kind='agent.enroll'").fetchone()[0] == 2
            # One reconnect per real host generation change, none for ordinary reads.
            assert conn.execute("SELECT COUNT(*) FROM commands WHERE command_kind='session.reconnect'").fetchone()[0] == 2
    finally:
        cli("daemon", "stop")


def test_deepseek_native_connect_preserves_identity_and_role_without_an_overlay(tmp_path: Path):
    """Exercise real CLI/daemon/bridge boundaries; Desktop loading is verified separately."""
    from tsunagou.application.onboarding import conversation_key

    root = tmp_path / "deepseek-project"
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("TSUNAGOU_", "CODEX_", "DSH_"))}
    if os.environ.get("TSUNAGOU_PROJECT_INDEX"):
        env["TSUNAGOU_PROJECT_INDEX"] = os.environ["TSUNAGOU_PROJECT_INDEX"]
    env["TSUNAGOU_ROUTING_DIR"] = str(tmp_path / "routes")
    # A generic or another vendor's inherited ID must not select this route.
    env["CODEX_THREAD_ID"] = "unrelated-codex"
    env["TSUNAGOU_HOST_CONVERSATION_ID"] = "unrelated-generic"

    def cli(*args):
        result = subprocess.run([sys.executable, "-m", "tsunagou", "--project-root", str(root), *args],
                                cwd=root, env=env, capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stderr or result.stdout
        return json.loads(result.stdout)

    cli("project", "init", "--coordination-root", str(root))
    args = ["agent", "connect", "--adapter", "deepseek", "--profile", "desktop", "--no-register-host"]
    try:
        connected = []
        for name, explicit_role in (("native-dsh-a", "main"), ("native-dsh-b", None)):
            env["DSH_SESSION_ID"] = name
            first = cli(*args, *(["--role", explicit_role] if explicit_role else []))
            again = cli(*args)
            assert first["agent_id"] == again["agent_id"]
            assert first["role"] == again["role"] == (explicit_role or "worker")
            assert first["status"] == "enrolled" and first["host_ready"] is False
            assert first["session"]["status"] == "ready" and "launch_command" not in first
            config = json.loads(Path(first["bridge_config"]).read_bytes())
            assert set(config["env"]) == {"TSUNAGOU_ROUTING_DIR", "TSUNAGOU_HOST_META_KEY"}
            route_path = tmp_path / "routes" / (conversation_key(name) + ".json")
            route = json.loads(route_path.read_bytes())
            assert route["conversation_id"] == name and "endpoint" not in route
            assert not (Path(route["state_dir"]) / "dsh-overlay.yml").exists()
            connected.append(first)
        assert connected[0]["agent_id"] != connected[1]["agent_id"]
        assert not (tmp_path / "routes" / (conversation_key("unrelated-codex") + ".json")).exists()
        with sqlite3.connect(root / ".tsunagou/local/state.sqlite3") as conn:
            assert conn.execute("SELECT COUNT(*) FROM commands WHERE command_kind='agent.enroll'").fetchone()[0] == 2
    finally:
        cli("daemon", "stop")
