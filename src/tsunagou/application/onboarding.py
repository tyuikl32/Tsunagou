"""Private host-context requests prepared inside the actual Agent conversation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tsunagou.hostwake.codex_desktop import NativeAppToolsClient
from tsunagou.platform.private_file_lock import private_file_lock
from tsunagou.platform.private_files import write_private_bytes
from tsunagou.platform.runtime_context import RuntimeContext, is_source_root, read_object, running_source_root
from tsunagou.shared_kernel.time import format_timestamp, now_ms


def conversation_key(thread_id: str) -> str:
    return hashlib.sha256(thread_id.encode()).hexdigest()


def prepare_codex_request(runtime: RuntimeContext, *, environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    thread_id = env.get("CODEX_THREAD_ID") or env.get("CODEX_SESSION_ID")
    endpoint = env.get("CODEX_APP_TOOLS_PIPE_PATH")
    if not thread_id or not endpoint:
        raise RuntimeError("desktop_context_missing:run_agent_prepare_inside_the_codex_conversation")
    if not runtime.project_id:
        raise RuntimeError("project_not_initialized")
    client = NativeAppToolsClient(endpoint, thread_id)
    try:
        view = client.call_tool("read_thread", {"threadId": thread_id, "turnLimit": 1, "includeOutputs": False})
    finally:
        client.close()
    if view.get("thread", {}).get("id") != thread_id:
        raise RuntimeError("desktop_conversation_mismatch")
    source = running_source_root()
    if source is None or not is_source_root(source):
        raise RuntimeError("installation_source_unavailable")
    key = conversation_key(thread_id)
    path = runtime.state_dir / "onboarding" / key / "request.json"
    existing = read_object(path)
    request: dict[str, Any] = {
        "format_version": 1, "adapter": "codex", "project_id": runtime.project_id,
        "project_root": str(runtime.project_root), "source_root": str(source),
        "installation_id": "codex:desktop", "conversation_id": thread_id,
        "endpoint": endpoint, "host_generation": conversation_key(endpoint),
        "created_at": existing.get("created_at") or format_timestamp(now_ms()),
    }
    if request != existing:
        write_private_bytes(path, (json.dumps(request, sort_keys=True) + "\n").encode())
    return path


def read_codex_request(path: Path, runtime: RuntimeContext) -> dict[str, Any]:
    request = read_object(path)
    if (request.get("format_version") != 1 or request.get("adapter") != "codex"
            or request.get("project_id") != runtime.project_id
            or Path(str(request.get("project_root", ""))).resolve() != runtime.project_root):
        raise RuntimeError("onboarding_request_project_mismatch")
    for key in ("conversation_id", "installation_id", "endpoint", "source_root", "host_generation"):
        if not isinstance(request.get(key), str) or not request[key]:
            raise RuntimeError("onboarding_request_invalid")
    return request


def codex_routing_directory() -> Path:
    configured = os.environ.get("TSUNAGOU_ROUTING_DIR")
    return Path(configured).expanduser().resolve() if configured else Path.home() / ".tsunagou/hosts/codex"


def validate_codex_route(request: dict[str, Any], runtime: RuntimeContext) -> None:
    """Reject a chat already routed elsewhere before it consumes a console claim."""
    route = codex_routing_directory() / (conversation_key(request["conversation_id"]) + ".json")
    with private_file_lock(route):
        previous = read_object(route)
        if previous and (previous.get("project_id") != runtime.project_id
                         or Path(str(previous.get("project_root", ""))).resolve() != runtime.project_root):
            raise RuntimeError("host_route_project_conflict")


def write_codex_route(request: dict[str, Any], runtime: RuntimeContext, destination: Path) -> Path:
    route = codex_routing_directory() / (conversation_key(request["conversation_id"]) + ".json")
    with private_file_lock(route):
        previous = read_object(route)
        if previous and previous.get("project_id") != runtime.project_id:
            raise RuntimeError("host_route_project_conflict")
        value = {
            "format_version": 1, "conversation_id": request["conversation_id"], "project_id": runtime.project_id,
            "project_root": str(runtime.project_root), "daemon_state_dir": str(runtime.state_dir),
            "state_dir": str(destination), "ticket_file": str(destination / "ticket.json"),
            "session_file": str(destination / "bridge-session.json"), "endpoint": request["endpoint"],
        }
        if "console_enrollment" in previous:
            value["console_enrollment"] = previous["console_enrollment"]
        if value != previous:
            write_private_bytes(route, (json.dumps(value, sort_keys=True) + "\n").encode())
    return route


def bind_console_enrollment(request: dict[str, Any], intent: dict[str, Any]) -> None:
    """Attach only this claim's receipt destination to its existing private route."""
    route = codex_routing_directory() / (conversation_key(request["conversation_id"]) + ".json")
    with private_file_lock(route):
        value = read_object(route)
        if (value.get("conversation_id") != request["conversation_id"]
                or value.get("project_id") != intent["project_id"]
                or Path(str(value.get("project_root", ""))).resolve() != Path(intent["project_root"]).resolve()):
            raise RuntimeError("onboarding_route_mismatch")
        value["console_enrollment"] = {
            "enrollment_id": intent["enrollment_id"],
            "requested_role": intent["requested_role"],
            "receipt_file": intent["receipt_file"],
        }
        write_private_bytes(route, (json.dumps(value, sort_keys=True) + "\n").encode())


def powershell_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def configure_codex_host_environment() -> bool:
    """Forward the current Desktop endpoint, never freeze it in config.env."""
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    path = home / "config.toml"
    content = path.read_text(encoding="utf-8")
    config = tomllib.loads(content)
    server = config.get("mcp_servers", {}).get("tsunagou", {})
    if "TSUNAGOU_ROUTING_DIR" not in server.get("env", {}):
        raise RuntimeError("codex_shared_server_not_registered")
    variables = list(server.get("env_vars") or [])
    if "CODEX_APP_TOOLS_PIPE_PATH" in variables:
        return False
    variables.append("CODEX_APP_TOOLS_PIPE_PATH")
    section = re.search(r"(?m)^\[mcp_servers\.tsunagou\][ \t]*(?:#[^\n]*)?$", content)
    if section is None:
        raise RuntimeError("codex_shared_server_config_unrecognized")
    following = re.search(r"(?m)^\[", content[section.end():])
    end = section.end() + following.start() if following else len(content)
    body = content[section.end():end]
    # Codex CLI writes this owned server as ordinary TOML; parse any existing
    # multi-line array before replacing its assignment, preserving other keys.
    assignment = re.search(r"(?ms)^[ \t]*env_vars\s*=\s*\[.*?\][ \t]*(?:#[^\n]*)?(?:\n|$)", body)
    line = "env_vars = " + json.dumps(variables) + "\n"
    body = body[:assignment.start()] + line + body[assignment.end():] if assignment else "\n" + line + body
    updated = content[:section.end()] + body + content[end:]
    tomllib.loads(updated)
    write_private_bytes(path, updated.encode())
    return True
