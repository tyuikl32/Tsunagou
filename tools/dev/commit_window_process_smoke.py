"""Exercise commit-window recovery with real daemon process exits.

The harness uses only the CLI to start/stop the daemon and loopback HTTP for
one deliberately interrupted command. The exit switches are test-only and are
never set by normal CLI or bridge execution.
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
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def run(command: list[str], *, env: dict[str, str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command, cwd=str(cwd or ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command_failed:{' '.join(command)}\n"
            f"stdout={completed.stdout[-3000:]}\n"
            f"stderr={completed.stderr[-3000:]}"
        )
    return completed.stdout.strip()


def cli(*args: str) -> list[str]:
    return [PYTHON, "-m", "tsunagou", *args]


def json_cli(command: list[str], *, env: dict[str, str]) -> dict[str, Any]:
    value = json.loads(run(command, env=env))
    if not isinstance(value, dict):
        raise RuntimeError("json_object_required")
    return value


def dispatch(url: str, token: str, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    registry = json.loads(
        (ROOT / "src" / "tsunagou" / "protocol_data" / "registry" / "commands.json").read_text(
            encoding="utf-8"
        )
    )
    body = json.dumps({
        "command_id": command_id,
        "protocol_version": registry["protocol_version"],
        "schema_bundle_digest": registry["schema_bundle_digest"],
        "payload": payload,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{url}/api/v1/commands/agent.ticket.create.user", data=body,
        method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("command_response_object_required")
    return value


def interrupted_dispatch(url: str, token: str, command_id: str, payload: dict[str, Any]) -> None:
    try:
        dispatch(url, token, command_id, payload)
    except (urllib.error.URLError, ConnectionResetError, TimeoutError, OSError):
        return
    raise RuntimeError("fault_command_returned_before_process_exit")


def run_window(mode: str, *, keep: bool) -> dict[str, Any]:
    temporary = Path(tempfile.mkdtemp(prefix=f"tsunagou-{mode}-window-"))
    base_env = os.environ.copy()
    base_env.update({"PYTHONPATH": str(ROOT / "src"), "TSUNAGOU_PROJECT_ROOT": str(temporary)})
    try:
        run(["git", "init", "--quiet", str(temporary)], env=base_env)
        project = json_cli(
            cli("project", "init", "--coordination-root", str(temporary), "--name", mode,
                "--objective", "commit window"), env=base_env,
        )
        command_id = uuid.uuid4().hex
        payload = {
            "kind": "worker", "installation_id": f"{mode}-install",
            "conversation_evidence": {"conversation_id": f"{mode}-conversation"},
        }
        fault_name = (
            "TSUNAGOU_TEST_EXIT_BEFORE_COMMIT_COMMAND_ID"
            if mode == "pre_commit" else "TSUNAGOU_TEST_EXIT_AFTER_COMMIT_COMMAND_ID"
        )
        fault_env = dict(base_env)
        fault_env[fault_name] = command_id
        fault_env["TSUNAGOU_STATE_DIR"] = str(temporary / ".tsunagou" / "local")
        run(cli("daemon", "start", "--coordination-root", str(temporary), "--port", "0"), env=fault_env)
        state_dir = temporary / ".tsunagou" / "local"
        manifest = json.loads((state_dir / "endpoint.json").read_text(encoding="utf-8"))
        token = (state_dir / "control.token").read_text(encoding="utf-8").strip()
        interrupted_dispatch(str(manifest["url"]), token, command_id, payload)

        # Remove the one-shot exit switch before starting the replacement daemon.
        restart_env = dict(base_env)
        restart_env["TSUNAGOU_STATE_DIR"] = str(state_dir)
        run(cli("daemon", "start", "--coordination-root", str(temporary), "--port", "0"), env=restart_env)
        replacement = json.loads((state_dir / "endpoint.json").read_text(encoding="utf-8"))
        replay = dispatch(str(replacement["url"]), token, command_id, payload)
        result = replay.get("result")
        if not isinstance(result, dict) or not result.get("secret"):
            raise RuntimeError(f"replay_result_missing:{replay}")
        run(cli("daemon", "stop", "--coordination-root", str(temporary)), env=restart_env)
        return {
            "mode": mode, "status": "passed", "command_id": command_id,
            "replayed": True, "project_id": project.get("project_id"),
        }
    finally:
        if keep:
            print(json.dumps({"kept_project": str(temporary)}))
        else:
            shutil.rmtree(temporary, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real daemon commit-window crash smoke.")
    parser.add_argument("--keep", action="store_true", help="keep temporary projects")
    args = parser.parse_args()
    results = [run_window(mode, keep=args.keep) for mode in ("pre_commit", "post_commit")]
    print(json.dumps({"status": "passed", "windows": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"commit_window_process_smoke_failed:{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
