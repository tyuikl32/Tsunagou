"""Internal host runner; callers authorize message scope before invocation.

OpenCode's active map proves a session is running, not that this message owns
that turn. ``request_associated`` records our queued/delivered input only;
``turn_started`` remains false without associated execution evidence. A false
value means unproven here, not proof that the recipient never ran.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.time import format_timestamp, now_ms

_STAGES = {
    "input", "launcher", "version", "service", "service_version", "session", "location",
    "state", "inbox", "message", "admission", "complete",
}


def sanitize_diagnostics(value: Any) -> dict[str, Any] | None:
    """Allow only fixed vocabulary and numbers across the presentation boundary."""
    if not isinstance(value, dict):
        return None
    version = value.get("interpreter_version")
    exit_code = value.get("exit_code")
    stage = value.get("stage")
    interpreter = value.get("interpreter")
    error_class = value.get("error_class")
    return {
        "stage": stage if isinstance(stage, str) and stage in _STAGES | {"spawn", "process", "response", "host_operation"} else "unknown",
        "interpreter": interpreter if isinstance(interpreter, str) and interpreter in {"pwsh", "powershell"} else None,
        "interpreter_version": version if isinstance(version, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version) else None,
        "exit_code": exit_code if type(exit_code) is int and -(2**31) <= exit_code < 2**32 else None,
        "error_class": error_class if isinstance(error_class, str) and error_class in {
            "spawn_failed", "process_nonzero", "powershell_parse_error", "invalid_json", "invalid_response", "timeout",
            "host_operation_error",
        } else None,
    }


def _interpreter_version(executable: str) -> str | None:
    """Probe the selected executable, not an assumed daemon PATH version."""
    try:
        probe = subprocess.run(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        version = probe.stdout.strip()
        return version if probe.returncode == 0 and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version) else None
    except (OSError, subprocess.TimeoutExpired):
        return None


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
    diagnostics: dict[str, Any] = {
        "stage": "spawn", "interpreter": "pwsh" if Path(powershell).stem.lower() == "pwsh" else "powershell",
        "interpreter_version": _interpreter_version(powershell), "exit_code": None, "error_class": None,
    }
    result["diagnostics"] = diagnostics
    # stdin is internal input, not a model-facing shell command or credential file.
    payload = {"action": action, "conversation_id": conversation_id, "message_id": message_id}
    try:
        completed = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
             str(Path(__file__).with_name("host_wake_runner.ps1"))],
            input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=project_root, timeout=25, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        diagnostics["exit_code"] = completed.returncode
        diagnostics["stage"] = "process"
        if completed.returncode != 0:
            # Inspect only a fixed parser marker. Never return raw/localized stderr.
            parser_error = "ParserError" in completed.stderr
            diagnostics["error_class"] = "powershell_parse_error" if parser_error else "process_nonzero"
            return {**result, "result": "unknown", "error_code": "host_runner_failed"}
        diagnostics["stage"] = "response"
        try:
            parsed = json.loads(completed.stdout)
        except ValueError:
            diagnostics["error_class"] = "invalid_json"
            return {**result, "result": "unknown", "error_code": "host_runner_failed"}
        if not isinstance(parsed, dict) or not isinstance(parsed.get("result"), str) or parsed.get("result") not in {
            "observed", "queued", "request_already_delivered", "unsupported", "unknown",
        }:
            diagnostics["error_class"] = "invalid_response"
            return {**result, "result": "unknown", "error_code": "host_runner_failed"}
        # Never expose raw CLI output, host conversations, endpoints or stdin.
        for key in result:
            if key in parsed and key != "diagnostics":
                result[key] = parsed[key]
        script_stage = parsed.get("diagnostics", {}).get("stage") if isinstance(parsed.get("diagnostics"), dict) else None
        diagnostics["stage"] = script_stage if isinstance(script_stage, str) and script_stage in _STAGES else "host_operation"
        diagnostics["error_class"] = "host_operation_error" if result["error_code"] else None
        return result
    except subprocess.TimeoutExpired:
        diagnostics.update(stage="process", error_class="timeout")
        return {**result, "result": "unknown", "error_code": "host_operation_timeout"}
    except OSError:
        diagnostics["error_class"] = "spawn_failed"
        return {**result, "result": "unknown", "error_code": "host_runner_failed"}
