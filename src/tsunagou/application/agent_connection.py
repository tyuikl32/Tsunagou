"""Shared connection service for explicit CLI and console-intent enrollment."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.application.onboarding import (
    codex_routing_directory,
    conversation_key,
    prepare_codex_request,
    read_codex_request,
    write_codex_route,
)
from tsunagou.hostwake.port import HostWakeError
from tsunagou.platform.bridge_files import HOST_META_KEYS, write_ticket_file
from tsunagou.platform.db.sqlite import ProjectLock
from tsunagou.platform.private_files import write_private_bytes
from tsunagou.platform.runtime_context import RuntimeContext, read_object, running_source_root
from tsunagou.shared_kernel import time as wall_time


class ConnectionFailure(RuntimeError):
    """Keep observed attempt timing when enrollment fails partway through."""

    def __init__(self, code: str, observations: dict[str, Any]) -> None:
        super().__init__(code)
        self.observations = observations


@dataclass(frozen=True)
class ConnectionOperations:
    """Local transport ports; no process-global environment changes."""

    runtime: Callable[[], RuntimeContext]
    ensure_daemon: Callable[[], None]
    control_token: Callable[[], str | None]
    profile_identity: Callable[[Path, str, str], tuple[str, str]]
    write_bridge: Callable[[str, str, str, Path, Path], Path]
    invoke: Callable[[str, dict[str, Any], str], dict[str, Any]]
    ack_delivery: Callable[[dict[str, Any], str], None]
    bootstrap: Callable[[Path, Path | None], dict[str, Any]]
    register_codex: Callable[[str, Path, Path], str]
    register_host: Callable[[str, str, Path], str]
    launch_command: Callable[[str, Path], str]
    daemon_version: Callable[[], str]


def connect_agent(
    operations: ConnectionOperations,
    *,
    adapter: str,
    role: str,
    profile: str = "current",
    mode: str = "attach",
    output_dir: Path | None = None,
    request_file: Path | None = None,
    register_host: bool = True,
) -> dict[str, Any]:
    """Enroll once; original-host readiness is verified separately."""
    started_ns = time.monotonic_ns()
    connect_started_at = wall_time.format_timestamp(wall_time.now_ms())
    enrolled_at = None

    def timing() -> dict[str, Any]:
        return {
            "connect_started_at": connect_started_at,
            "connect_finished_at": wall_time.format_timestamp(wall_time.now_ms()),
            "enrolled_at": enrolled_at,
            "duration_ms": (time.monotonic_ns() - started_ns) // 1_000_000,
        }

    try:
        runtime = operations.runtime()
        request = None
        if request_file is not None or (adapter == "codex" and register_host):
            if adapter != "codex":
                raise RuntimeError("onboarding_request_adapter_mismatch")
            request_file = request_file or prepare_codex_request(runtime)
            request = read_codex_request(request_file, runtime)
            installation_id, conversation_id = request["installation_id"], request["conversation_id"]
            destination = request_file.parent.resolve()
            if output_dir and output_dir.resolve() != destination:
                raise RuntimeError("onboarding_request_output_conflict")
        else:
            identity = (
                os.environ.get("TSUNAGOU_HOST_CONVERSATION_ID") or os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
            )
            if not identity:
                raise RuntimeError("host_conversation_required:run_agent_prepare_inside_the_host")
            destination = (
                output_dir or runtime.project_root / ".tsunagou/bridges" / f"{adapter}-{conversation_key(identity)[:16]}"
            ).resolve()
            installation_id, conversation_id = operations.profile_identity(destination, adapter, profile)
        operations.ensure_daemon()
        token = operations.control_token()
        if not token:
            raise RuntimeError("control_credential_missing")
        source = running_source_root()
        if source is None:
            raise RuntimeError("installation_source_unavailable")
        if request is not None and Path(request["source_root"]).resolve() != source:
            raise RuntimeError("onboarding_source_mismatch")
        destination.mkdir(parents=True, exist_ok=True)
        ticket_file, session_file = destination / "ticket.json", destination / "bridge-session.json"
        bootstrap_request = request_file or (destination / "host-identity.json" if adapter in HOST_META_KEYS else None)
        # Connect serializes only its own conversation. CredentialHandoff
        # continues to own session rotation and ticket cleanup separately.
        with ProjectLock(destination / "connect.lock"):
            if request is not None:
                write_codex_route(request, runtime, destination)
                bridge_config_path = destination / "bridge-config.json"
                config = {
                    "command": "node",
                    "args": [str(source / "packages/bridge-server/dist/server.js")],
                    "env": {"TSUNAGOU_ROUTING_DIR": str(codex_routing_directory())},
                    "secret_fields": [],
                }
                write_private_bytes(bridge_config_path, (json.dumps(config, indent=2) + "\n").encode())
            else:
                bridge_config_path = operations.write_bridge(adapter, mode, installation_id, destination, ticket_file)
            if not ticket_file.exists() and not session_file.exists():
                payload: dict[str, Any] = {
                    "kind": role,
                    "role": role,
                    "installation_id": installation_id,
                    "conversation_evidence": {"conversation_id": conversation_id},
                }
                if request:
                    payload["host_binding"] = {
                        "provider": "codex_desktop_app",
                        "endpoint": request["endpoint"],
                        "thread_id": conversation_id,
                        "host_generation": request["host_generation"],
                    }
                result = operations.invoke("agent.ticket.create.user", payload, token)
                write_ticket_file(
                    installation_id, conversation_id, result["secret"], ticket_file, role, request["host_generation"] if request else None
                )
                operations.ack_delivery(result, token)
            context = operations.bootstrap(bridge_config_path, bootstrap_request)
            if context["project_id"] != runtime.project_id:
                raise RuntimeError("onboarding_project_mismatch")
            if role == "main" and context["role"] != "main":
                operations.invoke("authority.appoint", {"agent_id": context["agent_id"]}, token)
                context = operations.bootstrap(bridge_config_path, bootstrap_request)
            if role == "worker" and context["role"] != "worker":
                raise RuntimeError("current_agent_is_main:explicit_revoke_required")
            # This verifies enrollment through a helper bridge. Original-host
            # MCP readiness remains a separate observation after connect.
            enrolled_at = wall_time.format_timestamp(wall_time.now_ms())
            launch_command = ""
            if register_host and adapter == "codex":
                registration = operations.register_codex(profile, bridge_config_path, runtime.project_root)
            elif register_host and adapter in {"deepseek", "opencode"}:
                # DeepSeek also needs its launch command (the overlay only works when
                # the conversation is booted with it); OpenCode reads its project
                # config on reload, so it needs no command of our own.
                registration = operations.register_host(adapter, profile, bridge_config_path)
                if adapter == "deepseek":
                    launch_command = operations.launch_command(profile, bridge_config_path)
            else:
                registration = "not_requested"

            public_context = {key: context[key] for key in ("project_id", "agent_id", "role")}
            for name, fields in (
                ("session", ("status", "connection_epoch", "baseline_status")),
                ("host_binding", ("provider", "status", "binding_revision", "connection_epoch")),
            ):
                value = context.get(name)
                public_context[name] = {key: value[key] for key in fields if key in value} if isinstance(value, dict) else None
            connected = {
                "status": "enrolled",
                **public_context,
                "adapter": adapter,
                "mode": mode,
                "requested_role": role,
                "profile": profile,
                "installation_id": installation_id,
                "bridge_config": str(bridge_config_path),
                "host_registration": registration,
                "source_root": str(source),
                "version": operations.daemon_version(),
                "next": "call_context__project_read_in_original_conversation",
            }
            if adapter == "deepseek" and launch_command:
                # The private overlay avoids adding tools to the shared profile.
                # Reusing it in another conversation can still reuse this identity.
                connected["launch_command"] = launch_command
            connection_file = destination / "connection.json"
            previous = read_object(connection_file)
            connected["connected_at"] = previous.get("connected_at") if connection_file.exists() else enrolled_at
            connected.update(timing())
            write_private_bytes(connection_file, (json.dumps(connected, sort_keys=True) + "\n").encode())
            return connected
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired, HostWakeError) as exc:
        code = exc.code if isinstance(exc, HostWakeError) else str(exc) if isinstance(exc, RuntimeError) else "onboarding_failed"
        raise ConnectionFailure(code, timing()) from exc
