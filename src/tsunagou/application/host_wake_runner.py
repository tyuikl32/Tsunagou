"""Internal host runner; callers authorize message scope before invocation.

OpenCode's active map proves a session is running, not that this message owns
that turn. ``request_associated`` records our queued/delivered input only;
``turn_started`` remains false without associated execution evidence. A false
value means unproven here, not proof that the recipient never ran.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.time import format_timestamp, now_ms


def run_host_operation(
    action: str, *, adapter: str, conversation_id: str, project_root: str | Path, message_id: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "host": adapter, "version": None, "state": "unknown", "can_queue": "unknown",
        "result": "unsupported", "error_code": None, "evidence": [],
        "observed_at": format_timestamp(now_ms()), "turn_started": False, "request_associated": False,
    }
    if action not in {"status", "wake"}:
        return {**result, "error_code": "host_action_invalid"}
    if adapter != "opencode":
        return {**result, "error_code": "deepseek_form_unverified" if adapter == "deepseek" else "host_runner_unsupported"}
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        return {**result, "error_code": "powershell_unavailable"}
    # stdin is internal input, not a model-facing shell command or credential file.
    payload = {"action": action, "conversation_id": conversation_id, "message_id": message_id}
    try:
        completed = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
             str(Path(__file__).with_name("host_wake_runner.ps1"))],
            input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
            cwd=project_root, timeout=25, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        parsed = json.loads(completed.stdout)
        if completed.returncode != 0 or not isinstance(parsed, dict):
            raise ValueError("invalid_runner_response")
        # Never expose raw CLI output, host conversations, endpoints or stdin.
        for key in result:
            if key in parsed:
                result[key] = parsed[key]
        return result
    except subprocess.TimeoutExpired:
        return {**result, "result": "unknown", "error_code": "host_operation_timeout"}
    except (OSError, ValueError):
        return {**result, "result": "unknown", "error_code": "host_runner_failed"}
