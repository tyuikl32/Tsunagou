"""Run the public-entry M1 smoke flow in a fresh temporary Git project.

The runner deliberately uses the CLI, the daemon HTTP endpoint through the CLI,
and two stdio MCP bridge processes. It does not import or instantiate domain
services, so a passing run is evidence for the product entrypoints rather than
an in-process unit test.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
BRIDGE_SCRIPT = ROOT / "packages" / "bridge-server" / "scripts" / "smoke-two-bridges.mjs"


def run(command: list[str], *, env: dict[str, str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd or ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command_failed:{' '.join(command)}\n"
            f"stdout={completed.stdout[-4000:]}\n"
            f"stderr={completed.stderr[-4000:]}"
        )
    return completed.stdout.strip()


def json_output(command: list[str], *, env: dict[str, str], cwd: Path | None = None) -> dict[str, Any]:
    raw = run(command, env=env, cwd=cwd)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid_json_output:{raw[-1000:]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("json_object_required")
    return value


def cli(*args: str) -> list[str]:
    return [PYTHON, "-m", "tsunagou", *args]


def http_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=5) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("http_json_object_required")
    return value


def expect_user_only_rejection(url: str, command_kind: str, payload: dict[str, Any], session: dict[str, Any]) -> None:
    registry = json.loads(
        (ROOT / "src" / "tsunagou" / "protocol_data" / "registry" / "commands.json").read_text(encoding="utf-8")
    )
    body = json.dumps({
        "command_id": f"worker-boundary-{command_kind}-{uuid4()}",
        "protocol_version": registry["protocol_version"],
        "schema_bundle_digest": registry["schema_bundle_digest"],
        "payload": payload,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/api/v1/commands/{command_kind}", data=body, method="POST",
        headers={
            "Authorization": f"Bearer {session['secret_token']}",
            "Tsunagou-Session-Id": str(session["session_id"]),
            "Tsunagou-Connection-Epoch": str(session["connection_epoch"]),
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise RuntimeError(f"wrong_user_only_status:{command_kind}:{exc.code}") from exc
        return
    raise RuntimeError(f"worker_command_succeeded:{command_kind}")

def main() -> int:
    parser = argparse.ArgumentParser(description="Run Tsunagou's public M1 standalone smoke flow.")
    parser.add_argument("--keep", action="store_true", help="keep the temporary project after the run")
    parser.add_argument("--skip-build", action="store_true", help="use the existing bridge dist output")
    args = parser.parse_args()

    if not BRIDGE_SCRIPT.is_file():
        raise RuntimeError(f"bridge_smoke_script_missing:{BRIDGE_SCRIPT}")
    bridge_entry = ROOT / "packages" / "bridge-server" / "dist" / "server.js"
    if not bridge_entry.is_file() and not args.skip_build:
        run(["corepack", "pnpm", "--filter", "@tsunagou/bridge-server", "run", "build"], env=os.environ.copy())
    if not bridge_entry.is_file():
        raise RuntimeError(f"bridge_dist_missing:{bridge_entry}")

    temporary = Path(tempfile.mkdtemp(prefix="tsunagou-m1-smoke-"))
    try:
        run(["git", "init", "--quiet", str(temporary)], env=os.environ.copy())
        state_dir = temporary / ".tsunagou" / "local"
        base_env = os.environ.copy()
        base_env.update({
            "PYTHONPATH": str(ROOT / "src"),
            "TSUNAGOU_PROJECT_ROOT": str(temporary),
            "TSUNAGOU_STATE_DIR": str(state_dir),
        })

        project = json_output(
            cli("project", "init", "--coordination-root", str(temporary), "--name", "M1 smoke", "--objective", "public flow"),
            env=base_env,
        )
        checkpoint_failure_marker = temporary / ".tsunagou" / "checkpoint-failure.once"
        checkpoint_failure_marker.write_text("fail once\n", encoding="utf-8")
        base_env["TSUNAGOU_TEST_FAIL_CHECKPOINT_MARKER"] = str(checkpoint_failure_marker)
        run(cli("daemon", "start", "--coordination-root", str(temporary), "--port", "0"), env=base_env)
        try:
            main_dir = temporary / ".tsunagou" / "bridges" / "main"
            worker_dir = temporary / ".tsunagou" / "bridges" / "worker"
            main_enrollment = json_output(
                cli("agent", "enroll", "--adapter", "codex", "--mode", "attach",
                    "--installation-id", "m1-main", "--conversation-id", "m1-main-conversation",
                    "--output-dir", str(main_dir)),
                env=base_env,
            )
            worker_enrollment = json_output(
                cli("agent", "enroll", "--adapter", "opencode", "--mode", "attach",
                    "--installation-id", "m1-worker", "--conversation-id", "m1-worker-conversation",
                    "--output-dir", str(worker_dir)),
                env=base_env,
            )
            main_config = Path(str(main_enrollment["bridge_config"]))
            worker_config = Path(str(worker_enrollment["bridge_config"]))
            contexts = json_output(
                ["node", str(BRIDGE_SCRIPT), "--project-root", str(temporary),
                 "--main-config", str(main_config), "--worker-config", str(worker_config), "--context-only"],
                env=os.environ.copy(),
            )
            main_agent_id = str(contexts["main"]["agent_id"])
            if contexts["main"].get("role") != "worker":
                raise RuntimeError("new_main_must_start_as_worker")
            endpoint_manifest = json.loads((state_dir / "endpoint.json").read_text(encoding="utf-8"))
            worker_session = json.loads((worker_dir / "bridge-session.json").read_text(encoding="utf-8"))
            expect_user_only_rejection(
                str(endpoint_manifest["url"]), "authority.appoint", {"agent_id": main_agent_id}, worker_session,
            )
            expect_user_only_rejection(
                str(endpoint_manifest["url"]), "project.completion.confirm", {}, worker_session,
            )
            run(cli("agent", "appoint", main_agent_id), env=base_env)
            running = json_output(
                ["node", str(BRIDGE_SCRIPT), "--project-root", str(temporary),
                 "--main-config", str(main_config), "--worker-config", str(worker_config), "--stop-after-start"],
                env=os.environ.copy(),
            )
            run(cli("daemon", "stop", "--coordination-root", str(temporary)), env=base_env)
            run(cli("daemon", "start", "--coordination-root", str(temporary), "--port", "0"), env=base_env)
            stale = json_output(
                ["node", str(BRIDGE_SCRIPT), "--project-root", str(temporary),
                 "--main-config", str(main_config), "--worker-config", str(worker_config), "--stale-check",
                 "--task-id", str(running["task_id"]), "--attempt-id", str(running["attempt_id"])],
                env=os.environ.copy(),
            )
            if stale.get("stale_execution") != "rejected":
                raise RuntimeError(f"stale_execution_not_rejected:{stale}")
            collaboration = json_output(
                ["node", str(BRIDGE_SCRIPT), "--project-root", str(temporary),
                 "--main-config", str(main_config), "--worker-config", str(worker_config)],
                env=os.environ.copy(),
            )
            decision = collaboration["user_decision"]
            run(cli("decision", "resolve", str(decision["decision_id"]), "--choice", "approved",
                    "--expected-revision", str(decision["revision"]), "--digest", str(decision["proposal_digest"])),
                env=base_env)
            completion = collaboration["completion"]
            failed_completion = json_output(
                cli("project", "complete", str(completion["proposal_id"]),
                    "--expected-project-revision", str(completion["revision"]),
                    "--digest", str(completion["proposal_digest"])),
                env=base_env,
            )
            if failed_completion.get("checkpoint_status") != "failed" or not failed_completion.get("operation_id"):
                raise RuntimeError(f"checkpoint_failure_not_observed:{failed_completion}")
            current_endpoint = json.loads((state_dir / "endpoint.json").read_text(encoding="utf-8"))
            failed_operation = http_json(
                f"{current_endpoint['url']}/api/v1/operations/{failed_completion['operation_id']}"
            )
            if failed_operation.get("status") != "failed":
                raise RuntimeError(f"checkpoint_failure_not_queryable:{failed_operation}")
            confirmed = json_output(cli("checkpoint", "retry"), env=base_env)
            if not confirmed.get("checkpoint_digest"):
                raise RuntimeError(f"checkpoint_retry_failed:{confirmed}")
            run(cli("daemon", "stop", "--coordination-root", str(temporary)), env=base_env)
            run(cli("daemon", "start", "--coordination-root", str(temporary), "--port", "0"), env=base_env)
            recovery = json_output(cli("recover"), env=base_env)
            checkpoints = json_output(cli("checkpoint", "list"), env=base_env)
            endpoint = json.loads((state_dir / "endpoint.json").read_text(encoding="utf-8"))
            task_query = http_json(f"{endpoint['url']}/api/v1/projects/{project['project_id']}/tasks")
            if not any(item.get("task_id") == collaboration.get("task_id") and item.get("status") == "completed"
                       for item in task_query.get("items", [])):
                raise RuntimeError("completed_task_not_queryable_after_restart")
            attempts_query = http_json(f"{endpoint['url']}/api/v1/projects/{project['project_id']}/attempts")
            if not any(item.get("attempt_id") == collaboration.get("attempt_id")
                       for item in attempts_query.get("items", [])):
                raise RuntimeError("attempt_not_queryable_after_restart")
            results_query = http_json(f"{endpoint['url']}/api/v1/projects/{project['project_id']}/results")
            if not any(item.get("result_id") == collaboration.get("result_id")
                       and item.get("digest") for item in results_query.get("items", [])):
                raise RuntimeError("result_not_queryable_after_restart")
            jobs_query = http_json(f"{endpoint['url']}/api/v1/projects/{project['project_id']}/jobs")
            if "items" not in jobs_query:
                raise RuntimeError("jobs_not_queryable_after_restart")
            agents_query = http_json(f"{endpoint['url']}/api/v1/projects/{project['project_id']}/agents")
            if agents_query.get("main_agent_id") != main_agent_id:
                raise RuntimeError("main_agent_not_queryable_after_restart")
            cognition_query = http_json(f"{endpoint['url']}/api/v1/projects/{project['project_id']}/cognition")
            if not cognition_query.get("reports") or not cognition_query.get("discrepancies"):
                raise RuntimeError("cognition_facts_not_queryable_after_restart")
            if not any(item.get("proposal_id") == collaboration["contract_id"]
                       for item in cognition_query.get("contracts", [])):
                raise RuntimeError("contract_not_queryable_after_restart")
            message_query = http_json(f"{endpoint['url']}/api/v1/projects/{project['project_id']}/messages")
            message_ids = {item.get("message_id") for item in message_query.get("items", [])}
            if collaboration.get("message_id") not in message_ids or collaboration.get("response_message_id") not in message_ids:
                raise RuntimeError("message_facts_not_queryable_after_restart")
            workspace_query = http_json(f"{endpoint['url']}/api/v1/projects/{project['project_id']}/workspaces")
            workspace_results = [item.get("result") for item in workspace_query.get("items", [])]
            if not any(result and result.get("baseline_conflict") is True for result in workspace_results):
                raise RuntimeError("workspace_result_not_queryable_after_restart")
            decision_query = http_json(f"{endpoint['url']}/api/v1/decisions")
            if not any(item.get("decision_id") == decision["decision_id"] and item.get("status") == "resolved"
                       for item in decision_query.get("items", [])):
                raise RuntimeError("decision_not_queryable_after_restart")
            audit_query = http_json(f"{endpoint['url']}/api/v1/projects/{project['project_id']}/audit")
            if not audit_query.get("items"):
                raise RuntimeError("audit_not_queryable_after_restart")
            if recovery.get("status") != "ready":
                raise RuntimeError(f"recovery_not_ready:{recovery}")
            if checkpoints.get("current", {}).get("digest") != confirmed.get("checkpoint_digest"):
                raise RuntimeError("checkpoint_pointer_mismatch")
            resumed_context = json_output(
                ["node", str(BRIDGE_SCRIPT), "--project-root", str(temporary),
                 "--main-config", str(main_config), "--worker-config", str(worker_config), "--context-only"],
                env=os.environ.copy(),
            )
            if resumed_context["main"].get("agent_id") != main_agent_id:
                raise RuntimeError("main_identity_not_recovered")
            print(json.dumps({
                "status": "passed",
                "project_id": project.get("project_id"),
                "task_id": collaboration.get("task_id"),
                "review_status": collaboration.get("review_status"),
                "stale_execution": stale.get("stale_execution"),
                "worker_user_only_commands": "rejected",
                "checkpoint_digest": confirmed.get("checkpoint_digest"),
                "checkpoint_failure_retry": "passed",
                "recovery_status": recovery.get("status"),
                "bridge_sessions": 2,
                "restart_queries": {
                    "tasks": True,
                    "attempts": True,
                    "results": True,
                    "jobs": True,
                    "agents": True,
                    "cognition": True,
                    "contracts": True,
                    "messages": True,
                    "workspaces": True,
                    "decisions": True,
                    "audit": True,
                },
            }, sort_keys=True))
        finally:
            manifest = state_dir / "endpoint.json"
            if manifest.is_file():
                run(cli("daemon", "stop", "--coordination-root", str(temporary)), env=base_env)
    finally:
        if args.keep:
            print(json.dumps({"kept_project": str(temporary)}))
        else:
            shutil.rmtree(temporary, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"standalone_smoke_failed:{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
