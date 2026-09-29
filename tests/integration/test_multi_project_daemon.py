"""Real HTTP, independent roots/credentials and one restarted daemon process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def test_two_projects_share_process_but_not_agents_or_authority(tmp_path: Path) -> None:
    roots = [tmp_path / "first", tmp_path / "second"]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TSUNAGOU_", "CODEX_"))}
    for root in roots:
        subprocess.run(["git", "init", "--quiet", str(root)], check=True)

    def cli(root: Path, *args: str) -> dict:
        result = subprocess.run([sys.executable, "-m", "tsunagou", *args], cwd=root, env=env,
                                capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stdout or result.stderr
        return json.loads(result.stdout)

    initial = cli(roots[0], "daemon", "start")
    stopped = False
    try:
        attached = cli(roots[1], "daemon", "start", "--reuse", str(roots[0]))
        assert attached["pid"] == initial["pid"] and attached["url"] == initial["url"]
        ids = {initial["project_id"], attached["project_id"]}
        assert len(ids) == 2
        again = cli(roots[1], "daemon", "start", "--reuse", str(roots[0]))
        assert again["runtime_id"] == initial["runtime_id"]
        for root in roots:
            assert set(cli(root, "--json", "doctor")["runtime"]["project_ids"]) == ids
        connections = []
        for i, root in enumerate(roots):
            env["TSUNAGOU_HOST_CONVERSATION_ID"] = f"fixture-project-{i}"
            connections.append(cli(root, "agent", "connect", "--adapter", "codex", "--role", "main", "--no-register-host"))
        assert connections[0]["agent_id"] != connections[1]["agent_id"]
        for i, root in enumerate(roots):
            agents = cli(root, "agent", "list", "--json")["items"]
            assert len(agents) == 1 and agents[0]["agent_id"] == connections[i]["agent_id"]
            assert agents[0]["role"] == "main"

        token_a = (roots[0] / ".tsunagou/local/control.token").read_text(encoding="utf-8").strip()
        token_b = (roots[1] / ".tsunagou/local/control.token").read_text(encoding="utf-8").strip()
        assert token_a != token_b

        def denied(path: str, headers: dict, status: int, code: str, *, body: dict | None = None):
            request = urllib.request.Request(initial["url"] + path, headers=headers,
                                             data=json.dumps(body).encode() if body else None)
            try:
                urllib.request.urlopen(request, timeout=5)
                raise AssertionError("request unexpectedly accepted")
            except urllib.error.HTTPError as exc:
                assert exc.code == status
                assert json.load(exc)["detail"]["code"] == code

        denied("/api/v1/decisions", {}, 400, "project_context_required")
        denied(f'/api/v1/projects/{initial["project_id"]}/agents', {"Tsunagou-Project-Id": attached["project_id"]},
               400, "project_context_conflict")
        denied("/api/v1/checkpoints", {"Tsunagou-Project-Id": attached["project_id"], "Authorization": f"Bearer {token_a}"},
               401, "authentication_failed")
        # Registering more projects needs the daemon owner's U credential.
        denied("/api/v1/daemon/projects", {"Authorization": f"Bearer {token_b}", "Content-Type": "application/json"},
               401, "authentication_failed", body={"project_root": str(roots[1]), "state_dir": str(roots[1] / '.tsunagou/local')})
        result = cli(roots[1], "daemon", "stop")
        stopped = True
        assert set(result["project_ids"]) == ids
        restarted = cli(roots[1], "daemon", "start")
        stopped = False
        assert restarted["runtime_id"] != initial["runtime_id"]
        for i, root in enumerate(roots):
            health = cli(root, "--json", "doctor")
            assert set(health["runtime"]["project_ids"]) == ids
            assert health["runtime"]["pid"] == restarted["pid"]
            env["TSUNAGOU_HOST_CONVERSATION_ID"] = f"fixture-project-{i}"
            connected = cli(root, "agent", "connect", "--adapter", "codex", "--role", "main", "--no-register-host")
            assert connected["agent_id"] == connections[i]["agent_id"]
    finally:
        if not stopped:
            cli(roots[0], "daemon", "stop")
