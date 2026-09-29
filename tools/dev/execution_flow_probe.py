"""Fresh daemon process + two HTTP workers + real Node MCP begin/submit probe.

Creates its own temporary Git project; never reads a user's project credentials.
Only the redacted report leaves that private project. No Desktop wake claim.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import format_timestamp, now_ms


def run(output: Path) -> None:
    source = Path(__file__).resolve().parents[2]
    root = Path(tempfile.mkdtemp(prefix="tsunagou-fx2-process-"))
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TSUNAGOU_", "CODEX_"))}
    env.update(TSUNAGOU_PROJECT_ROOT=str(root), TSUNAGOU_STATE_DIR=str(root / ".tsunagou/local"))
    report: dict = {"started_at": format_timestamp(now_ms()), "project_root": str(root), "steps": [], "status": "running"}
    registry = json.loads(files("tsunagou.protocol_data").joinpath("registry/commands.json").read_text(encoding="utf-8"))
    running = False
    endpoint = {}

    def cli(*args: str) -> dict:
        started = now_ms()
        result = subprocess.run([sys.executable, "-m", "tsunagou", *args], cwd=source, env=env, capture_output=True, text=True, timeout=40)
        report["steps"].append(
            {
                "cli": list(args),
                "started_at": format_timestamp(started),
                "finished_at": format_timestamp(now_ms()),
                "exit_code": result.returncode,
            }
        )
        if result.returncode:
            raise RuntimeError("cli_failed:" + " ".join(args[:2]) + ":" + result.stdout[-300:])
        return json.loads(result.stdout)

    def request(path: str, *, body: dict | None = None, who: dict | None = None, token: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if who:
            headers.update(
                {
                    "Authorization": "Bearer " + who["secret_token"],
                    "Tsunagou-Session-Id": who["session_id"],
                    "Tsunagou-Connection-Epoch": str(who["connection_epoch"]),
                }
            )
        elif token:
            headers["Authorization"] = "Bearer " + token
        try:
            with urlopen(
                Request(endpoint["url"] + path, data=json.dumps(body).encode() if body is not None else None, headers=headers), timeout=20
            ) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def command(kind: str, payload: dict, who: dict | None = None, *, token: str | None = None, expected: int = 200) -> dict:
        command_id, started = new_id(), now_ms()
        status, body = request(
            "/api/v1/commands/" + kind,
            body={
                "command_id": command_id,
                "protocol_version": registry["protocol_version"],
                "schema_bundle_digest": registry["schema_bundle_digest"],
                "payload": payload,
            },
            who=who,
            token=token,
        )
        detail = body.get("detail", {})
        report["steps"].append(
            {
                "command": kind,
                "command_id": command_id,
                "http_status": status,
                "started_at": format_timestamp(started),
                "finished_at": format_timestamp(now_ms()),
                "actor_id": who["agent_id"] if who else None,
                "error_code": detail.get("code"),
            }
        )
        assert status == expected, (kind, status, detail)
        return body.get("result", detail)

    def page(kind: str) -> dict:
        status, body = request(f"/api/v1/projects/{endpoint['project_id']}/{kind}")
        assert status == 200
        return body

    try:
        endpoint = cli("daemon", "start", "--coordination-root", str(root), "--port", "0")
        running = True
        control = (root / ".tsunagou/local/control.token").read_text(encoding="utf-8").strip()

        def enroll(name: str) -> dict:
            identity = {"installation_id": "fx2-http-probe", "conversation_evidence": {"conversation_id": name}}
            ticket = command("agent.ticket.create.user", {"kind": "worker", **identity}, token=control)
            return command(
                "agent.enroll",
                {
                    **identity,
                    "probe_payload": {
                        "baseline": {
                            cap: {"status": "supported", "evidence_refs": ["fixture:http-probe"]} for cap in ADMISSION_CAPABILITIES
                        }
                    },
                },
                token=ticket["secret"],
            )

        main, first, second = (enroll(name) for name in ("main", "worker-one", "worker-two"))
        command("authority.appoint", {"agent_id": main["agent_id"]}, token=control)
        task = command(
            "task.create",
            {"title": "process ownership", "objective": "restart and reclaim", "execution_scope": {"roots": ["coordination"]}},
            main,
        )
        task_id = task["task_id"]
        command("workspace.select", {"task_id": task_id, "driver_kind": "shared"}, main)
        command("task.ready", {"task_id": task_id}, main)
        published = command("task.publish", {"task_id": task_id}, main)
        payload = {"task_id": task_id, "expected_task_revision": published["revision"]}

        def compete(actor: dict) -> tuple[dict, dict | None]:
            status, body = request(
                "/api/v1/commands/task.begin",
                body={
                    "command_id": new_id(),
                    "protocol_version": registry["protocol_version"],
                    "schema_bundle_digest": registry["schema_bundle_digest"],
                    "payload": payload,
                },
                who=actor,
            )
            assert status in {200, 409}, (status, body)
            return actor, body.get("result")

        with ThreadPoolExecutor(max_workers=2) as pool:
            contenders = list(pool.map(compete, (first, second)))
        assert sum(result is not None for _, result in contenders) == 1
        owner, started = next((actor, result) for actor, result in contenders if result)
        successor = second if owner == first else first
        assert started is not None
        report["race"] = {"winner_agent_id": owner["agent_id"], "other_agent_id": successor["agent_id"], **started}
        old_pid = endpoint["pid"]
        cli("daemon", "stop", "--coordination-root", str(root))
        running = False
        endpoint = cli("daemon", "start", "--coordination-root", str(root), "--port", "0")
        running = True
        assert endpoint["pid"] != old_pid
        report["restart"] = {"old_pid": old_pid, "new_pid": endpoint["pid"]}
        assert next(row for row in page("tasks")["items"] if row["task_id"] == task_id)["status"] == "running"
        command("task.submit", {"task_id": task_id, "attempt_id": started["attempt_id"], "summary": "old grant"}, owner, expected=403)
        command("task.begin", {"task_id": task_id, "expected_task_revision": started["revision"]}, successor, expected=403)
        resumed = command("task.begin", {"task_id": task_id, "expected_task_revision": started["revision"]}, owner)
        assert resumed == started
        recovered = command(
            "task.recover",
            {
                "task_id": task_id,
                "expected_attempt_id": started["attempt_id"],
                "disposition": "reopen",
                "reason": "explicit test reassignment",
            },
            main,
        )
        fresh = command("task.begin", {"task_id": task_id, "expected_task_revision": recovered["revision"]}, successor)
        assert fresh["attempt_id"] != started["attempt_id"]
        command("task.submit", {"task_id": task_id, "attempt_id": started["attempt_id"], "summary": "late old owner"}, owner, expected=403)
        (root / "proof.txt").write_text("new owner completed after restart\n", encoding="utf-8")
        submitted = command("task.submit", {"task_id": task_id, "attempt_id": fresh["attempt_id"], "summary": "done"}, successor)
        assert submitted["workspace_result_ref"]
        command("task.review.accept", {"task_id": task_id, "result_id": submitted["result_id"], "result_digest": submitted["digest"]}, main)
        report["resources"] = page("resources")
        report["task"] = next(row for row in page("tasks")["items"] if row["task_id"] == task_id)
        assert report["task"]["status"] == "completed"
        configs = []
        for name, role in (("fx2-main", "main"), ("fx2-worker", "worker")):
            env["TSUNAGOU_HOST_CONVERSATION_ID"] = "test-fixture:" + name
            configs.append(cli("agent", "connect", "--adapter", "codex", "--profile", name,
                               "--role", role, "--no-register-host")["bridge_config"])
        bridge = subprocess.run(
            [
                "node",
                str(source / "packages/bridge-server/scripts/smoke-two-bridges.mjs"),
                "--project-root",
                str(root),
                "--main-config",
                configs[0],
                "--worker-config",
                configs[1],
            ],
            cwd=source,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert bridge.returncode == 0, bridge.stderr[-1000:]
        report["mcp"] = json.loads(bridge.stdout)
        history_items = []
        query = {"limit": "200"}
        while True:
            status, history = request(f"/api/v1/projects/{endpoint['project_id']}/history?{urlencode(query)}", token=control)
            assert status == 200
            history_items.extend(history["items"])
            if not history.get("next_cursor"):
                break
            query["cursor"] = history["next_cursor"]
        report["event_refs"] = [
            {"event_id": row["source_event_id"], "action": row["action"], "occurred_at": row["occurred_at"]}
            for row in history_items
            if row["action"] in {"task.begin", "task.submit", "task.recover", "task.review.accept"}
        ]
        report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        if running:
            cli("daemon", "stop", "--coordination-root", str(root))
        report["finished_at"] = format_timestamp(now_ms())
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "report": str(output), "project_root": str(root)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
