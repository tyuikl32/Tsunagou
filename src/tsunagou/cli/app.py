from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextvars import ContextVar
from pathlib import Path
from typing import Any, cast

from tsunagou.platform import host_registration
from tsunagou.platform.bridge_files import HOST_META_KEYS, write_bridge_config, write_ticket_file
from tsunagou.platform.runtime_context import RuntimeContext, resolve_runtime, running_source_root

_selected_project_root: ContextVar[Path | None] = ContextVar("cli_project_root", default=None)


# The one-time ticket writer lives in ``tsunagou.platform.bridge_files`` so that the
# middle layer and the CLI share one implementation and one process-owned lock; the CLI
# tests import it under this older name.
_write_ticket_private = write_ticket_file


def _runtime_context() -> RuntimeContext:
    return resolve_runtime(_selected_project_root.get())


try:
    import typer
except ImportError:  # pragma: no cover
    typer = None  # type: ignore[assignment]


if typer is not None:
    app = typer.Typer(add_completion=False, invoke_without_command=True)
    project_app = typer.Typer(help="Project control commands.")
    agent_app = typer.Typer(help="Agent enrollment and appointment.")
    decision_app = typer.Typer(help="User decision commands.")
    operation_app = typer.Typer(help="Durable operation queries.")
    checkpoint_app = typer.Typer(help="Checkpoint creation and queries.")
    task_app = typer.Typer(help="Task history queries.")
    audit_app = typer.Typer(help="Audit event queries.")
    daemon_app = typer.Typer(help="Local daemon lifecycle commands.")
    host_app = typer.Typer(help="Host wake binding and capability commands.")
    web_app = typer.Typer(help="Local console commands.")
    app.add_typer(project_app, name="project")
    app.add_typer(agent_app, name="agent")
    app.add_typer(decision_app, name="decision")
    app.add_typer(operation_app, name="operation")
    app.add_typer(checkpoint_app, name="checkpoint")
    app.add_typer(task_app, name="task")
    app.add_typer(audit_app, name="audit")
    app.add_typer(daemon_app, name="daemon")
    app.add_typer(host_app, name="host")
    app.add_typer(web_app, name="web")

    @app.callback()
    def callback(
        ctx: typer.Context,
        version: bool = typer.Option(False, "--version", is_eager=True),
        json_output: bool = typer.Option(False, "--json"),
        project_root: Path | None = typer.Option(None, "--project-root"),  # noqa: B008
    ) -> None:
        ctx.ensure_object(dict)
        ctx.obj["json"] = json_output
        selection = _selected_project_root.set(project_root)
        ctx.call_on_close(lambda: _selected_project_root.reset(selection))
        if project_root is not None:
            try:
                _runtime_context()
            except RuntimeError as exc:
                print(json.dumps({"status": "error", "error": str(exc)}))
                raise typer.Exit(4) from exc
        if version:
            print("0.1.0")
            raise typer.Exit()
        if ctx.invoked_subcommand is None:
            print("Tsunagou 0.1.0 — local coordination runtime")

    @app.command("installation-info")
    def installation_info(
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Read installed source/version/timing metadata without opening project credentials."""
        from tsunagou.platform.runtime_context import read_object

        path = Path.home() / ".tsunagou/installation.json"
        try:
            record = read_object(path)
        except (RuntimeError, OSError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": "installation_registration_invalid"}))
            raise typer.Exit(4) from exc
        fields = ("source_root", "python", "launcher", "bridge_entry", "commit", "source_dirty", "python_version",
                  "bridge_version", "installed_at", "install_started_at", "install_finished_at", "duration_ms")
        print(json.dumps({"status": "installed" if record else "not_installed",
                          **{key: record.get(key) for key in fields}}, sort_keys=True))

    @app.command("doctor")
    def doctor(ctx: typer.Context) -> None:
        try:
            result = _daemon_request("GET", "/api/v1/health")
            result["daemon"] = "reachable"
            card = _daemon_request("GET", "/.well-known/agent-card.json")
            capabilities = card.get("capabilities", {})
            result["a2a"] = {
                "status": "reachable",
                "protocol_version": card.get("protocolVersion"),
                "streaming": capabilities.get("streaming"),
                "push_notifications": capabilities.get("pushNotifications"),
                "wake": card.get("x-tsunagou", {}).get("wake"),
            }
        except RuntimeError as exc:
            print(json.dumps({"status": "unavailable", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(5) from exc
        print(json.dumps(result, sort_keys=True) if ctx.obj.get("json") else "Tsunagou doctor: ok")

    @project_app.command("init")
    def project_init(
        coordination_root: Path = typer.Option(..., "--coordination-root"),  # noqa: B008
        name: str = typer.Option("Tsunagou project", "--name"),
        objective: str = typer.Option("Coordinate local agents", "--objective"),
    ) -> None:
        from tsunagou.modules.projects import ProjectRegistry

        registry = ProjectRegistry.initialize(coordination_root, name=name, objective=objective)
        assert registry.project is not None
        _remember_project(registry.project, coordination_root.expanduser().resolve())
        print(json.dumps({"project_id": registry.project.project_id, "status": "active"}, sort_keys=True))

    @daemon_app.command("migrate-credentials")
    def migrate_credentials(
        coordination_root: Path = typer.Option(..., "--coordination-root"),  # noqa: B008
        confirm_plan_digest: str | None = typer.Option(None, "--confirm-plan-digest"),
        dry_run: bool = typer.Option(False, "--dry-run"),
    ) -> None:
        """Preview by default; explicit digest confirms an offline credential revocation."""
        import sqlite3

        from tsunagou.platform.credential_migration import CredentialMigration
        from tsunagou.shared_kernel.errors import TsunagouError

        if dry_run and confirm_plan_digest:
            raise typer.BadParameter("--dry-run cannot be combined with --confirm-plan-digest")
        try:
            migration = CredentialMigration(coordination_root)
            result = migration.apply(confirm_plan_digest) if confirm_plan_digest else migration.preview()
        except (ValueError, RuntimeError, OSError, sqlite3.Error, TsunagouError) as exc:
            # Error classes/codes only: never echo SQLite rows or old credentials.
            code = (exc.code if isinstance(exc, TsunagouError) else str(exc) if isinstance(exc, (ValueError, RuntimeError))
                    else "migration_storage_error")
            print(json.dumps({"status": "error", "code": code}, ensure_ascii=False))
            raise typer.Exit(4) from exc
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))

    @project_app.command("bootstrap")
    def project_bootstrap(
        ctx: typer.Context,
        coordination_root: Path = typer.Option(..., "--coordination-root"),  # noqa: B008
        source_root: Path | None = typer.Option(None, "--source-root"),  # noqa: B008
        source_ref: str | None = typer.Option(None, "--source-ref"),
        hosts: list[str] = typer.Option([], "--host"),  # noqa: B008
        refresh: bool = typer.Option(False, "--refresh"),
        force_managed: bool = typer.Option(False, "--force-managed"),
    ) -> None:
        """Materialize non-secret Tsunagou rules in a coordination project."""
        from tsunagou.application.project_integration import ProjectIntegration, ProjectIntegrationError

        try:
            result = ProjectIntegration(coordination_root).bootstrap(
                source_root=source_root,
                source_ref=source_ref,
                hosts=hosts or ["generic"],
                refresh=refresh,
                force_managed=force_managed,
            )
        except (ProjectIntegrationError, OSError, ValueError) as exc:
            payload = {"status": "error", "error": str(exc)}
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            raise typer.Exit(1) from exc
        if ctx.obj.get("json"):
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return
        print(f"Tsunagou project bootstrap: {result['project_id']}")
        for item in result["files"]:
            print(f"{item['status']}: {item['path']}")
        print("No credentials or runtime secrets were written.")

    @project_app.command("restore")
    def project_restore(
        coordination_root: Path = typer.Option(..., "--coordination-root"),  # noqa: B008
        checkpoint_digest: str = typer.Option(..., "--checkpoint-digest"),
        confirm_plan_digest: str | None = typer.Option(None, "--confirm-plan-digest"),
    ) -> None:
        """Preview clean-clone recovery; confirm the exact preview as local user control."""
        import sqlite3

        from tsunagou.platform.clone_recovery import CloneRecovery
        from tsunagou.shared_kernel.errors import TsunagouError

        try:
            recovery = CloneRecovery(coordination_root)
            result = (recovery.confirm(checkpoint_digest, confirm_plan_digest) if confirm_plan_digest
                      else recovery.preview(checkpoint_digest))
        except (OSError, ValueError, RuntimeError, sqlite3.Error, TsunagouError) as exc:
            code = (exc.code if isinstance(exc, TsunagouError) else str(exc)
                    if isinstance(exc, (ValueError, RuntimeError)) else "restore_storage_error")
            print(json.dumps({"status": "error", "code": code}, ensure_ascii=False))
            raise typer.Exit(4) from exc
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))

    @project_app.command("complete")
    def project_complete(
        proposal_id: str = typer.Argument(...),
        expected_project_revision: int = typer.Option(..., "--expected-project-revision"),
        digest: str = typer.Option(..., "--digest"),
    ) -> None:
        """Confirm a main Agent's project-completion proposal as the user."""
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            result = _invoke_command(
                "project.completion.confirm",
                {
                    "proposal_id": proposal_id,
                    "expected_project_revision": expected_project_revision,
                    "expected_revisions": {"decision": expected_project_revision},
                    "proposal_digest": digest,
                },
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    @project_app.command("history")
    def project_history(
        ctx: typer.Context,
        project_id: str = typer.Argument(...),
        from_timestamp: str | None = typer.Option(None, "--from"),
        to_timestamp: str | None = typer.Option(None, "--to"),
        actor: str | None = typer.Option(None, "--actor"),
        subject: str | None = typer.Option(None, "--subject"),
        limit: int = typer.Option(50, "--limit", min=1, max=200),
        cursor: str | None = typer.Option(None, "--cursor"),
        json_output: bool = typer.Option(False, "--json"),
        export_output: bool = typer.Option(False, "--export"),
    ) -> None:
        """Read one authenticated audit page without modifying project state."""
        from tsunagou.generated.protocol.audit import AuditPageModel
        from tsunagou.shared_kernel.query_models import AuditExportModel

        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}))
            raise typer.Exit(3)
        filters = {"limit": str(limit), **{
            key: value for key, value in {
                "from": from_timestamp, "to": to_timestamp, "actor_ref": actor,
                "subject_ref": subject, "cursor": cursor,
            }.items() if value is not None
        }}
        route = "history/export" if export_output else "history"
        path = f"/api/v1/projects/{urllib.parse.quote(project_id, safe='')}/{route}?{urllib.parse.urlencode(filters)}"
        try:
            raw_page = _daemon_request("GET", path, authorization=f"Bearer {token}")
            if export_output:
                print(AuditExportModel.model_validate(raw_page).model_dump_json(by_alias=True))
                return
            page = AuditPageModel.model_validate(raw_page)
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
            cause = exc.__cause__
            status = cause.code if isinstance(cause, urllib.error.HTTPError) else None
            raise typer.Exit(3 if status in {401, 403} else 2 if status in {400, 422} else 5) from exc
        except ValueError as exc:
            # Never echo unvalidated server data (or a Pydantic input dump).
            print(json.dumps({"status": "error", "error": "invalid_audit_response"}))
            raise typer.Exit(5) from exc
        if json_output or ctx.obj.get("json"):
            print(page.model_dump_json())
            return
        print(f"Project {page.project_id} — as_of_event_seq={page.as_of_event_seq}")
        for item in page.items:
            when = item.occurred_at or "unknown_time"
            level = item.evidence_level or "unknown"
            print(f"{item.event_seq}\t{when}\t{item.actor_ref}\t{item.action}\t{item.subject_ref}\t{item.outcome}\t{level}")
        if not page.items:
            print("No visible events match this query.")
        if page.next_cursor:
            print(f"next_cursor: {page.next_cursor}")

    @project_app.command("timings")
    def project_timings(
        ctx: typer.Context,
        project_id: str = typer.Argument(...),
        task_id: str | None = typer.Option(None, "--task-id"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Read per-Attempt elapsed times with their public timestamp sources."""
        from tsunagou.application.workflows.project_timings import read_project_timings

        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}))
            raise typer.Exit(3)
        try:
            page = read_project_timings(
                project_id, lambda path: _daemon_request("GET", path, authorization=f"Bearer {token}"), task_id=task_id,
            )
        except RuntimeError as exc:
            cause = exc.__cause__
            status = cause.code if isinstance(cause, urllib.error.HTTPError) else None
            # Daemon error details are not an authorized timing projection.
            error = f"http_{status}" if status is not None else (
                str(exc) if str(exc) in {"daemon_unreachable", "daemon_endpoint_not_configured"} else "timing_query_failed"
            )
            print(json.dumps({"status": "error", "error": error}))
            raise typer.Exit(3 if status in {401, 403} else 2 if status in {400, 422} else 5) from exc
        except ValueError as exc:
            print(json.dumps({"status": "error", "error": "invalid_timing_response"}))
            raise typer.Exit(5) from exc
        if json_output or ctx.obj.get("json"):
            print(page.model_dump_json())
            return
        print(f"Project {page.project_id} — Attempt elapsed times (not pure work time)")
        for item in page.items:
            print(f"{item.attempt_id}\t{item.task_id}\t{item.owner_agent_id}\t{item.state}")
            for label in ("started", "submitted", "reviewed"):
                print(f"  {label}: {getattr(item, label + '_at') or 'unknown_time'} "
                      f"({getattr(item, label + '_source') or 'unknown'})")
            print(f"  visible events: begin={item.begin_events}, submit={item.submit_events}")
            for label, elapsed in (("work_elapsed", item.work_elapsed), ("review_wait_elapsed", item.review_wait_elapsed)):
                print(f"  {label}: {elapsed.elapsed_ms if elapsed.elapsed_ms is not None else 'unknown'} ms ({elapsed.clock_status})")
        if not page.items:
            print("No visible Attempts match this query.")

    @project_app.command("diagnostics")
    def project_diagnostics(
        ctx: typer.Context,
        project_id: str = typer.Argument(...),
        json_output: bool = typer.Option(False, "--json"),
        message_id: str | None = typer.Option(None, "--message-id"),
        task_id: str | None = typer.Option(None, "--task-id"),
        since: str | None = typer.Option(None, "--from"),
        until: str | None = typer.Option(None, "--to"),
    ) -> None:
        """Read host-wake/A2A transport evidence without changing domain history."""
        from tsunagou.shared_kernel.query_models import DiagnosticPageModel

        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(3)
        try:
            path = f"/api/v1/projects/{urllib.parse.quote(project_id, safe='')}/diagnostics"
            filters = {key: value for key, value in {"message_id": message_id, "task_id": task_id,
                                                    "from": since, "to": until}.items() if value is not None}
            if filters:
                path += "?" + urllib.parse.urlencode(filters)
            page = DiagnosticPageModel.model_validate(
                _daemon_request("GET", path, authorization=f"Bearer {token}")
            )
        except (RuntimeError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc) if isinstance(exc, RuntimeError)
                              else "invalid_diagnostic_response"}, sort_keys=True))
            raise typer.Exit(2) from exc
        if json_output or ctx.obj.get("json"):
            print(page.model_dump_json())
            return
        print(f"Project {page.project_id} — diagnostic_events={len(page.items)}")
        for item in page.items:
            print(f"{item.occurred_at or '-'}\t{item.kind}\t{item.agent_id}\t{item.message_id or '-'}\t"
                  f"{item.trigger_source}\t{item.error_code or '-'}\t{item.wake_attempt_id or '-'}")

    @task_app.command("history")
    def task_history(
        ctx: typer.Context,
        task_id: str = typer.Argument(...),
        project_id: str | None = typer.Option(None, "--project-id"),
        from_timestamp: str | None = typer.Option(None, "--from"),
        to_timestamp: str | None = typer.Option(None, "--to"),
        actor: str | None = typer.Option(None, "--actor"),
        limit: int = typer.Option(50, "--limit", min=1, max=200),
        cursor: str | None = typer.Option(None, "--cursor"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Read the responsibility timeline for one task."""
        from tsunagou.generated.protocol.audit import AuditPageModel

        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(3)
        try:
            resolved_project = _cli_project_id(project_id)
            filters = {"limit": str(limit), **{
                key: value for key, value in {
                    "from": from_timestamp, "to": to_timestamp, "actor_ref": actor, "cursor": cursor,
                }.items() if value is not None
            }}
            path = (
                f"/api/v1/projects/{urllib.parse.quote(resolved_project, safe='')}/tasks/"
                f"{urllib.parse.quote(task_id, safe='')}/history?{urllib.parse.urlencode(filters)}"
            )
            page = AuditPageModel.model_validate(_daemon_request("GET", path, authorization=f"Bearer {token}"))
        except (RuntimeError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc) if isinstance(exc, RuntimeError)
                              else "invalid_audit_response"}, ensure_ascii=False, sort_keys=True))
            raise typer.Exit(2) from exc
        if json_output or ctx.obj.get("json"):
            print(page.model_dump_json())
            return
        print(f"Task {task_id} — as_of_event_seq={page.as_of_event_seq}")
        for item in page.items:
            print(f"{item.event_seq}\t{item.occurred_at or 'unknown_time'}\t{item.actor_ref}\t"
                  f"{item.action}\t{item.subject_ref}\t{item.outcome}\t{item.evidence_level or 'unknown'}")
        if page.next_cursor:
            print(f"next_cursor: {page.next_cursor}")

    @audit_app.command("event")
    def audit_event(
        ctx: typer.Context,
        event_id: str = typer.Argument(...),
        project_id: str | None = typer.Option(None, "--project-id"),
        include_evidence: bool = typer.Option(True, "--include-evidence/--no-include-evidence"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Read one event and its causal/evidence references."""
        from tsunagou.generated.protocol.audit import AuditEventModel

        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(3)
        try:
            resolved_project = _cli_project_id(project_id)
            path = f"/api/v1/audit/events/{urllib.parse.quote(event_id, safe='')}?" + urllib.parse.urlencode({
                "project_id": resolved_project, "include_evidence": str(include_evidence).lower(),
            })
            event = AuditEventModel.model_validate(_daemon_request("GET", path, authorization=f"Bearer {token}"))
        except (RuntimeError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc) if isinstance(exc, RuntimeError)
                              else "invalid_audit_response"}, ensure_ascii=False, sort_keys=True))
            raise typer.Exit(2) from exc
        if json_output or ctx.obj.get("json"):
            print(event.model_dump_json())
        else:
            print(f"{event.event_id}\t{event.event_seq}\t{event.occurred_at or 'unknown_time'}\t"
                  f"{event.actor_ref}\t{event.action}\t{event.subject_ref}\t{event.outcome}")
            if event.caused_by_command_id:
                print(f"caused_by_command_id: {event.caused_by_command_id}")
            if event.evidence_refs:
                print("evidence_refs: " + ",".join(event.evidence_refs))

    def _coordination_state_dir(coordination_root: Path) -> Path:
        return coordination_root.expanduser().resolve() / ".tsunagou" / "local"

    def _remember_project(project: Any, coordination_root: Path) -> None:
        """Register the project in the machine-level index.

        The index exists for readers outside a project (the console, a person), so
        it must never be able to fail the command that created or started the
        project: an unwritable home directory costs a listing entry, nothing more.
        """
        from tsunagou.platform.project_index import record_project

        try:
            record_project(
                project_id=project.project_id, path=coordination_root,
                name=project.name, objective=project.objective, source="cli",
            )
        except OSError:
            pass

    def _project_root() -> Path:
        return _runtime_context().project_root

    def _cli_project_id(explicit: str | None = None) -> str:
        if explicit:
            return explicit
        project_id = _runtime_context().project_id
        if project_id:
            return project_id
        raise RuntimeError("project_id_required")

    def _state_dir_from_environment() -> Path | None:
        return _runtime_context().state_dir

    def _control_token() -> str | None:
        value = os.environ.get("TSUNAGOU_CONTROL_TOKEN")
        if value:
            return value
        state_dir = _state_dir_from_environment()
        if state_dir is None:
            return None
        try:
            value = (state_dir / "control.token").read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None

    def _endpoint_manifest(coordination_root: Path) -> Path:
        selected = _selected_project_root.get()
        if selected is not None and coordination_root.resolve() != selected.resolve():
            raise RuntimeError("project_context_conflict")
        return resolve_runtime(coordination_root).state_dir / "endpoint.json"

    def _choose_port(host: str) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])

    def _read_daemon_health(url: str) -> dict[str, Any]:
        with urllib.request.urlopen(url.rstrip("/") + "/api/v1/health", timeout=2) as response:
            return cast(dict[str, Any], json.load(response))

    def _verify_daemon_identity(health: dict[str, Any], manifest: dict[str, Any], project_id: str | None) -> None:
        runtime = health.get("runtime") or {}
        if health.get("status") != "ok" or (project_id and project_id not in runtime.get("project_ids", [])):
            raise RuntimeError("daemon_project_mismatch")
        for key in ("pid", "runtime_id", "source_root"):
            if manifest.get(key) is not None and runtime.get(key) != manifest[key]:
                raise RuntimeError("daemon_runtime_mismatch")

    def _wait_for_daemon(url: str, process: subprocess.Popen[bytes], timeout: float = 10.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("daemon_exited_during_start")
            try:
                health = _read_daemon_health(url)
                if health.get("status") == "ok":
                    return health
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.1)
        raise RuntimeError("daemon_start_timeout")

    def _daemon_process_running(pid: int) -> bool:
        """Check OS liveness; an unavailable HTTP endpoint does not prove exit."""
        if pid <= 0:
            raise ValueError("invalid_daemon_pid")
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
            if not handle:
                if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists
                    return False
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                result = kernel.WaitForSingleObject(handle, 0)
                if result == 0:  # WAIT_OBJECT_0: process exited (possibly still held by another handle)
                    return False
                if result == 258:  # WAIT_TIMEOUT
                    return True
                raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        if sys.platform == "linux":
            # A container's PID 1 may leave an exited orphan as a zombie.
            try:
                return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0] != "Z"
            except FileNotFoundError:
                return False
        return True

    @daemon_app.command("start")
    def daemon_start(
        coordination_root: Path | None = typer.Option(None, "--coordination-root"),  # noqa: B008
        host: str = typer.Option("127.0.0.1", "--host"),
        port: int = typer.Option(0, "--port", min=0, max=65535),
        name: str = typer.Option("Tsunagou project", "--name"),
        objective: str = typer.Option("Coordinate local agents", "--objective"),
        host_wake: str = typer.Option("auto", "--host-wake"),
        reuse: Path | None = typer.Option(None, "--reuse"),  # noqa: B008
    ) -> None:
        from tsunagou.modules.projects import ProjectRegistry

        if host_wake not in {"disabled", "managed", "desktop", "auto"}:
            raise typer.BadParameter("host-wake must be disabled, managed, desktop or auto")
        root = (coordination_root or _project_root()).expanduser().resolve()
        manifest_path = _endpoint_manifest(root)
        try:
            registry = ProjectRegistry.initialize(root, name=name, objective=objective)
        except (OSError, RuntimeError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        assert registry.project is not None
        _remember_project(registry.project, root)
        state_dir = manifest_path.parent
        if not (state_dir / "state.sqlite3").exists() and (root / ".tsunagou/checkpoints/current.json").is_file():
            print(json.dumps({"status": "error", "error": "checkpoint_restore_required",
                              "next": "project restore --coordination-root <clone> --checkpoint-digest <digest>"}))
            raise typer.Exit(4)
        state_dir.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if reuse is not None:
            try:
                target = resolve_runtime(reuse, environ={})
                if target.daemon_url is None:
                    raise RuntimeError("daemon_endpoint_not_configured")
                health = _read_daemon_health(target.daemon_url)
                _verify_daemon_identity(health, target.endpoint, target.project_id)
                if health["runtime"].get("source_root") != str(running_source_root()):
                    raise RuntimeError("daemon_source_mismatch")
                if manifest_path.exists():
                    current = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if current.get("url") != target.daemon_url:
                        try:
                            _read_daemon_health(current["url"])
                        except (OSError, KeyError, urllib.error.URLError):
                            pass
                        else:
                            raise RuntimeError("project_daemon_already_running")
                owner_state = Path(target.endpoint.get("daemon_owner_state_dir", str(target.state_dir)))
                owner_token = (owner_state / "control.token").read_text(encoding="utf-8").strip()
                request = urllib.request.Request(
                    target.daemon_url + "/api/v1/daemon/projects",
                    data=json.dumps({"project_root": str(root), "state_dir": str(state_dir)}).encode(),
                    headers={"Authorization": f"Bearer {owner_token}", "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    attached = json.load(response)
                print(json.dumps({"status": "attached", **attached}, sort_keys=True))
                return
            except (OSError, RuntimeError, ValueError, urllib.error.URLError) as exc:
                code = str(exc) if isinstance(exc, RuntimeError) else "daemon_attach_failed"
                print(json.dumps({"status": "error", "error": code}))
                raise typer.Exit(4) from exc
        if manifest_path.is_file():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                existing_url = existing.get("url")
                if isinstance(existing_url, str):
                    health = _read_daemon_health(existing_url)
                    _verify_daemon_identity(health, existing, registry.project.project_id)
                    current_source = str(running_source_root())
                    if health["runtime"].get("source_root") != current_source:
                        raise RuntimeError("daemon_source_mismatch")
                    print(json.dumps({"status": "already_running", **existing}, sort_keys=True))
                    return
            except RuntimeError as exc:
                print(json.dumps({"status": "error", "error": str(exc)}))
                raise typer.Exit(4) from exc
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
        token_path = state_dir / "control.token"
        from tsunagou.platform.private_files import restrict_access, write_private_bytes

        if token_path.is_file():
            restrict_access(token_path)
            token = token_path.read_text(encoding="utf-8").strip()
        else:
            token = secrets.token_urlsafe(32)
            write_private_bytes(token_path, (token + "\n").encode("utf-8"))
        selected_port = port or _choose_port(host)
        url = f"http://{host}:{selected_port}"
        log_path = state_dir / "daemon.log"
        child_env = os.environ.copy()
        child_env.update({
            "TSUNAGOU_PROJECT_ROOT": str(root),
            "TSUNAGOU_PROJECT_ID": registry.project.project_id,
            "TSUNAGOU_STATE_DIR": str(state_dir),
            "TSUNAGOU_CONTROL_TOKEN": token,
            "TSUNAGOU_HOST_WAKE": host_wake,
            "TSUNAGOU_DAEMON_URL": url,
            "TSUNAGOU_DAEMON_REGISTRY": existing.get("daemon_registry", str(state_dir / "daemon-projects.json")),
            "PYTHONPATH": os.pathsep.join(
                [str(Path(__file__).resolve().parents[2]), child_env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep),
        })
        # Console isolation alone still inherits a host's kill-on-close Job.
        # Windows permits breakaway only when that Job allows it; never retry
        # without this flag and silently launch a daemon tied to the host.
        flags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                 | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
        try:
            with open(log_path, "ab") as log_handle:
                process = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "tsunagou.bootstrap.daemon:build_daemon",
                     "--factory", "--host", host, "--port", str(selected_port)],
                    cwd=str(root), env=child_env, stdout=log_handle, stderr=log_handle,
                    stdin=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != "nt",
                )
        except OSError as exc:
            print(json.dumps({"status": "error", "error": "daemon_launch_failed", "log": str(log_path),
                              "os_error": getattr(exc, "winerror", None) or exc.errno,
                              "next": "Run daemon start from a standalone terminal allowed to launch independent processes."},
                             sort_keys=True))
            raise typer.Exit(1) from exc
        try:
            health = _wait_for_daemon(url, process)
            _verify_daemon_identity(health, {"source_root": str(running_source_root())}, registry.project.project_id)
        except (OSError, RuntimeError) as exc:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
                else:
                    process.terminate()
            print(json.dumps({"status": "error", "error": str(exc) if isinstance(exc, RuntimeError) else "daemon_identity_unverified",
                              "log": str(log_path)}, sort_keys=True))
            raise typer.Exit(1) from exc
        # The daemon writes all member endpoints after registering their containers.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(json.dumps({"status": "started", **manifest}, sort_keys=True))

    @daemon_app.command("status")
    def daemon_status(
        coordination_root: Path | None = typer.Option(None, "--coordination-root"),  # noqa: B008
    ) -> None:
        path = _endpoint_manifest(coordination_root or _project_root())
        if not path.is_file():
            print(json.dumps({"status": "stopped", "manifest": str(path)}, sort_keys=True))
            raise typer.Exit(3)
        manifest: dict[str, Any] = {}
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            health = _read_daemon_health(manifest["url"])
            _verify_daemon_identity(health, manifest, manifest.get("project_id"))
            status = "running"
        except (OSError, urllib.error.URLError, KeyError, json.JSONDecodeError, RuntimeError):
            try:
                status = "unverified" if _daemon_process_running(int(manifest["pid"])) else "stopped"
            except (OSError, ValueError, TypeError, KeyError):
                status = "unverified"
        print(json.dumps({**manifest, "status": status,
                          "project_ids": health["runtime"]["project_ids"] if status == "running" else [],
                          **({"error": "daemon_identity_unverified"} if status == "unverified" else {})}, sort_keys=True))
        if status != "running":
            raise typer.Exit(3 if status == "stopped" else 4)

    @daemon_app.command("stop")
    def daemon_stop(
        coordination_root: Path | None = typer.Option(None, "--coordination-root"),  # noqa: B008
    ) -> None:
        path = _endpoint_manifest(coordination_root or _project_root())
        if not path.is_file():
            print(json.dumps({"status": "already_stopped"}, sort_keys=True))
            return
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            pid = int(manifest["pid"])
            if pid <= 0:
                raise ValueError("invalid_daemon_pid")
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "error", "error": "invalid_endpoint_manifest"}, sort_keys=True))
            raise typer.Exit(1) from exc
        try:
            health = _read_daemon_health(manifest["url"])
            _verify_daemon_identity(health, manifest, manifest.get("project_id"))
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            try:
                exited = not _daemon_process_running(pid)
            except OSError:
                exited = False
            if exited:
                print(json.dumps({"status": "already_stopped", "pid": pid}, sort_keys=True))
                return
            print(json.dumps({"status": "error", "error": "daemon_identity_unverified"}))
            raise typer.Exit(4) from exc
        try:
            if os.name == "nt":
                stopped = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                         capture_output=True, check=False, timeout=10)
                if stopped.returncode != 0 and _daemon_process_running(pid):
                    raise RuntimeError("daemon_stop_failed")
            else:
                os.kill(pid, 15)
            deadline = time.monotonic() + 5
            while _daemon_process_running(pid):
                if time.monotonic() >= deadline:
                    raise RuntimeError("daemon_stop_timeout")
                time.sleep(0.05)
        except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
            print(json.dumps({"status": "error", "error": str(exc) if isinstance(exc, RuntimeError) else "daemon_stop_failed",
                              "pid": pid}, sort_keys=True))
            raise typer.Exit(4) from exc
        # Retain the selected registry so restart from any member rejoins the same daemon.
        print(json.dumps({"status": "stopped", "pid": pid, "project_ids": health["runtime"]["project_ids"]}, sort_keys=True))

    def _daemon_url() -> str:
        value = _runtime_context().daemon_url
        if value:
            return value
        raise RuntimeError("daemon_endpoint_not_configured")

    def _daemon_request(
        method: str, path: str, body: dict[str, Any] | None = None,
        *, authorization: str | None = None, session_id: str | None = None,
        connection_epoch: int | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        project_id = _runtime_context().project_id
        if project_id:
            headers["Tsunagou-Project-Id"] = project_id
        if authorization:
            headers["Authorization"] = authorization
        if session_id:
            headers["Tsunagou-Session-Id"] = session_id
        if connection_epoch is not None:
            headers["Tsunagou-Connection-Epoch"] = str(connection_epoch)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(_daemon_url() + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = json.load(response)
                return cast(dict[str, Any], raw.get("result", raw))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("detail", {})
            except (OSError, json.JSONDecodeError):
                detail = {}
            code = detail.get("code", f"http_{exc.code}") if isinstance(detail, dict) else f"http_{exc.code}"
            raise RuntimeError(str(code)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("daemon_unreachable") from exc

    def _invoke_command(
        command_kind: str, payload: dict[str, Any], *, authorization: str,
    ) -> dict[str, Any]:
        from importlib.resources import files
        registry = json.loads(
            files("tsunagou.protocol_data").joinpath("registry", "commands.json").read_text(encoding="utf-8")
        )
        return _daemon_request(
            "POST", f"/api/v1/commands/{command_kind}",
            {
                "command_id": __import__("uuid").uuid4().hex,
                "protocol_version": registry["protocol_version"],
                "schema_bundle_digest": registry["schema_bundle_digest"],
                "payload": payload,
            },
            authorization=authorization,
        )

    def _ack_private_delivery(result: dict[str, Any], token: str) -> None:
        """The ticket is already durably saved; a lost ACK cannot invalidate it."""
        ref = result.get("delivery_ref")
        if not isinstance(ref, str):
            return  # Older daemon responses did not have delivery receipts.
        try:
            _daemon_request(
                "POST", f"/api/v1/credential-deliveries/{urllib.parse.quote(ref, safe='')}/ack",
                authorization=f"Bearer {token}",
            )
        except RuntimeError:
            # The encrypted daemon escrow expires independently. The usable
            # ticket is now in the private bridge input, not in CLI output.
            pass

    def _write_bridge_config(
        *, adapter: str, mode: str, installation_id: str, output_dir: Path,
        ticket_path: Path,
    ) -> Path:
        """Write this conversation's launch description next to its ticket."""

        return write_bridge_config(
            adapter=adapter, mode=mode, installation_id=installation_id, output_dir=output_dir,
            ticket_path=ticket_path, daemon_url=_daemon_url(),
            daemon_state_dir=str(_state_dir_from_environment() or _coordination_state_dir(_project_root())),
            project_root=_project_root(),
        )

    def _resolve_codex_executable() -> str | None:
        """Find the Codex CLI even when the host GUI did not export its PATH."""

        host = host_registration.host_for("codex")
        return host_registration.find_executable(host) if host is not None else None

    def _register_codex_mcp(
        *, profile: str, bridge_config_path: Path, legacy_project_root: Path | None = None,
    ) -> str:
        from tsunagou.platform.db.sqlite import ProjectLock

        # Different conversations have different connect locks but update the
        # same user config. Serialize the whole get/add/forward-env sequence.
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        with ProjectLock(home / "tsunagou-mcp-registration.lock", timeout=10):
            return _register_codex_mcp_locked(
                profile=profile,
                bridge_config_path=bridge_config_path,
                legacy_project_root=legacy_project_root,
            )

    def _legacy_codex_server_names(codex: str, *, project_root: Path, bridge: dict[str, Any]) -> list[str]:
        """Return only fixed-session MCP entries created by the pre-routing bridge."""
        listed = subprocess.run([codex, "mcp", "list", "--json"], capture_output=True, text=True, check=False)
        if listed.returncode != 0:
            return []
        try:
            servers = json.loads(listed.stdout)
        except ValueError:
            return []
        if not isinstance(servers, list):
            return []
        names: list[str] = []
        for server in servers:
            if not isinstance(server, dict):
                continue
            name, transport = server.get("name"), server.get("transport")
            if (not isinstance(name, str) or not re.fullmatch(r"tsunagou-[A-Za-z0-9_-]+-[0-9a-f]{8}", name)
                    or not isinstance(transport, dict)):
                continue
            environment = transport.get("env")
            if not isinstance(environment, dict) or "TSUNAGOU_ROUTING_DIR" in environment:
                continue
            root = environment.get("TSUNAGOU_PROJECT_ROOT")
            session = environment.get("TSUNAGOU_SESSION_FILE")
            if not isinstance(root, str) or not isinstance(session, str):
                continue
            try:
                same_root = Path(root).expanduser().resolve() == project_root.expanduser().resolve()
            except OSError:
                same_root = False
            if (same_root and transport.get("command") == bridge.get("command")
                    and transport.get("args") == bridge.get("args")):
                names.append(name)
        return names

    def _remove_legacy_codex_servers(codex: str, *, project_root: Path, bridge: dict[str, Any]) -> None:
        for name in _legacy_codex_server_names(codex, project_root=project_root, bridge=bridge):
            subprocess.run([codex, "mcp", "remove", name], capture_output=True, text=True, check=False)

    def _register_codex_mcp_locked(
        *, profile: str, bridge_config_path: Path, legacy_project_root: Path | None = None,
    ) -> str:
        codex = _resolve_codex_executable()
        if codex is None:
            return "codex_not_found"
        config = json.loads(bridge_config_path.read_text(encoding="utf-8"))
        safe_profile = re.sub(r"[^A-Za-z0-9_-]+", "-", profile).strip("-") or "session"
        project_root = str(config.get("env", {}).get("TSUNAGOU_PROJECT_ROOT", ""))
        project_tag = hashlib.sha256(project_root.encode("utf-8")).hexdigest()[:8]
        name = "tsunagou" if "TSUNAGOU_ROUTING_DIR" in config["env"] else f"tsunagou-{safe_profile}-{project_tag}"
        existing = subprocess.run([codex, "mcp", "get", name, "--json"], capture_output=True, text=True, check=False)
        if existing.returncode == 0:
            try:
                transport = json.loads(existing.stdout).get("transport", {})
                if (transport.get("command") == config["command"] and transport.get("args") == config["args"]
                        and transport.get("env") == config["env"]):
                    if name == "tsunagou":
                        from tsunagou.application.onboarding import configure_codex_host_environment
                        environment_updated = configure_codex_host_environment()
                        if legacy_project_root is not None:
                            _remove_legacy_codex_servers(codex, project_root=legacy_project_root, bridge=config)
                        return f"registered:{name}" if environment_updated else f"unchanged:{name}"
                    return f"unchanged:{name}"
            except (ValueError, TypeError):
                pass
        # This name is generated by Tsunagou, so replacing an earlier entry is
        # safe and makes re-enrollment/recovery idempotent.
        subprocess.run([codex, "mcp", "remove", name], capture_output=True, text=True, check=False)
        command = [codex, "mcp", "add", name]
        for key, value in sorted(config["env"].items()):
            if value:
                command.extend(["--env", f"{key}={value}"])
        command.extend(["--", config["command"], *config["args"]])
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return "codex_registration_failed"
        if name == "tsunagou":
            from tsunagou.application.onboarding import configure_codex_host_environment
            configure_codex_host_environment()
            if legacy_project_root is not None:
                _remove_legacy_codex_servers(codex, project_root=legacy_project_root, bridge=config)
        return f"registered:{name}"

    @host_app.command("bind")
    def host_bind(
        agent_id: str = typer.Option(..., "--agent-id"),
        provider: str = typer.Option("managed_app_server", "--provider"),
        adapter_profile: str = typer.Option("codex-current", "--profile"),
        cwd: Path | None = typer.Option(None, "--cwd"),  # noqa: B008
        scope_digest: str = typer.Option(..., "--scope-digest"),
        policy_digest: str = typer.Option(..., "--policy-digest"),
        executable: str | None = typer.Option(None, "--executable"),
        model: str | None = typer.Option(None, "--model"),
        approval_policy: str | None = typer.Option(None, "--approval-policy"),
        sandbox: str | None = typer.Option(None, "--sandbox"),
        bridge_config: Path | None = typer.Option(None, "--bridge-config"),  # noqa: B008
        endpoint: str | None = typer.Option(None, "--endpoint"),
        thread_id: str | None = typer.Option(None, "--thread-id"),
        attach_confirmed: bool = typer.Option(False, "--attach-confirmed/--no-attach-confirmed"),
    ) -> None:
        """Register a managed or explicitly confirmed Desktop host binding."""
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            result = _daemon_request(
                "POST", "/api/v1/host-wake/bindings",
                {
                    "agent_id": agent_id,
                    "provider": provider,
                    "adapter_profile": adapter_profile,
                    "cwd": str((cwd or _project_root()).expanduser().resolve()),
                    "scope_digest": scope_digest,
                    "policy_digest": policy_digest,
                    "executable": executable,
                    "model": model,
                    "approval_policy": approval_policy,
                    "sandbox": sandbox,
                    "bridge_config": str(bridge_config.expanduser().resolve()) if bridge_config else None,
                    "endpoint": endpoint,
                    "thread_id": thread_id,
                    "attach_confirmed": attach_confirmed,
                },
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))

    @host_app.command("attach")
    def host_attach(
        agent_id: str = typer.Option(..., "--agent-id"),
        adapter_profile: str = typer.Option("codex-desktop", "--profile"),
        cwd: Path | None = typer.Option(None, "--cwd"),  # noqa: B008
        scope_digest: str = typer.Option(..., "--scope-digest"),
        policy_digest: str = typer.Option(..., "--policy-digest"),
        endpoint: str = typer.Option(..., "--endpoint"),
        thread_id: str = typer.Option(..., "--thread-id"),
        executable: str | None = typer.Option(None, "--executable"),
        model: str | None = typer.Option(None, "--model"),
        approval_policy: str | None = typer.Option(None, "--approval-policy"),
        sandbox: str | None = typer.Option(None, "--sandbox"),
        bridge_config: Path | None = typer.Option(None, "--bridge-config"),  # noqa: B008
        attach_confirmed: bool = typer.Option(False, "--attach-confirmed/--no-attach-confirmed"),
    ) -> None:
        """Attach an existing Codex thread through an explicit local app-server socket."""
        host_bind(
            agent_id=agent_id,
            provider="desktop_attach",
            adapter_profile=adapter_profile,
            cwd=cwd,
            scope_digest=scope_digest,
            policy_digest=policy_digest,
            executable=executable,
            model=model,
            approval_policy=approval_policy,
            sandbox=sandbox,
            bridge_config=bridge_config,
            endpoint=endpoint,
            thread_id=thread_id,
            attach_confirmed=attach_confirmed,
        )

    @host_app.command("probe")
    def host_probe(agent_id: str = typer.Argument(...)) -> None:
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            result = _daemon_request(
                "POST", f"/api/v1/host-wake/bindings/{agent_id}:probe",
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))

    @host_app.command("binding-show")
    def host_binding_show(agent_id: str = typer.Argument(...)) -> None:
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            result = _daemon_request(
                "GET", f"/api/v1/host-wake/bindings/{agent_id}",
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))

    @host_app.command("wake-status")
    def host_wake_status(attempt_id: str = typer.Argument(...)) -> None:
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            result = _daemon_request(
                "GET", f"/api/v1/host-wake/attempts/{attempt_id}",
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))

    def _profile_identity(output_dir: Path, adapter: str, profile: str) -> tuple[str, str]:
        """Use a host-provided identity; a display profile is never a Worker."""
        from tsunagou.platform.private_files import write_private_bytes
        from tsunagou.platform.runtime_context import read_object

        conversation_id = os.environ.get("TSUNAGOU_HOST_CONVERSATION_ID")
        if not conversation_id and adapter == "codex":
            conversation_id = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
        if not conversation_id:
            raise RuntimeError("host_conversation_required:run_agent_prepare_inside_the_host")
        installation_id = os.environ.get("TSUNAGOU_INSTALLATION_ID") or f"{adapter}:local"
        identity_path = output_dir / "host-identity.json"
        prior = read_object(identity_path)
        if prior and prior.get("conversation_id") != conversation_id:
            raise RuntimeError("profile_conversation_conflict")
        value = {"adapter": adapter, "profile": profile, "installation_id": installation_id, "conversation_id": conversation_id}
        if value != prior:
            write_private_bytes(identity_path, (json.dumps(value, sort_keys=True) + "\n").encode())
        return installation_id, conversation_id

    @agent_app.command("prepare")
    def agent_prepare(
        adapter: str = typer.Option(..., "--adapter"),
        role: str = typer.Option("worker", "--role"),
    ) -> None:
        """Privately observe the current host; return one fully filled user command."""
        from tsunagou.application.onboarding import powershell_quote, prepare_codex_request
        from tsunagou.hostwake.port import HostWakeError

        if adapter != "codex" or role not in {"worker", "main"}:
            raise typer.BadParameter("prepare currently supports codex and role worker/main")
        try:
            runtime = _runtime_context()
            path = prepare_codex_request(runtime)
        except (RuntimeError, OSError, HostWakeError) as exc:
            code = exc.code if isinstance(exc, HostWakeError) else str(exc) if isinstance(exc, RuntimeError) else "onboarding_io_error"
            print(json.dumps({"status": "error", "error": code}))
            raise typer.Exit(4) from exc
        command = (f"& {powershell_quote(sys.executable)} -m tsunagou --project-root {powershell_quote(runtime.project_root)} "
                   f"agent connect --adapter codex --request-file {powershell_quote(path)} --role {role}")
        print(json.dumps({"status": "prepared", "project_id": runtime.project_id, "request_file": str(path),
                          "command": command, "creates_agent": False}, ensure_ascii=False))

    def _ensure_project_daemon() -> None:
        try:
            context = _runtime_context()
            health = _daemon_request("GET", "/api/v1/health")
            _verify_daemon_identity(health, context.endpoint, context.project_id)
            return
        except RuntimeError as exc:
            if str(exc) not in {"daemon_endpoint_not_configured", "daemon_unreachable"}:
                raise
        result = subprocess.run(
            [sys.executable, "-m", "tsunagou", "--project-root", str(_project_root()), "daemon", "start"],
            capture_output=True, text=True, check=False, timeout=30,
        )
        if result.returncode:
            raise RuntimeError("daemon_start_failed")
        context = _runtime_context()
        _verify_daemon_identity(_daemon_request("GET", "/api/v1/health"), context.endpoint, context.project_id)

    def _bridge_bootstrap(config: Path, request: Path | None) -> dict[str, Any]:
        source = running_source_root()
        if source is None:
            raise RuntimeError("installation_source_unavailable")
        command = ["node", str(source / "packages/bridge-server/scripts/connect-context.mjs"), str(config)]
        if request is not None:
            command.append(str(request))
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=40)
        try:
            value = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError("bridge_bootstrap_failed") from exc
        if result.returncode:
            code = value.get("error", "")
            raise RuntimeError(code if re.fullmatch(r"[a-z][a-z0-9_:]{0,180}", code) else "bridge_bootstrap_failed")
        if not value.get("agent_id") or not value.get("project_id"):
            raise RuntimeError("bridge_context_invalid")
        return cast(dict[str, Any], value)

    @agent_app.command("connect")
    def agent_connect(
        adapter: str = typer.Option(..., "--adapter"),
        role: str = typer.Option("worker", "--role"),
        profile: str = typer.Option("current", "--profile"),
        mode: str = typer.Option("attach", "--mode"),
        output_dir: Path | None = typer.Option(None, "--output-dir"),  # noqa: B008
        request_file: Path | None = typer.Option(None, "--request-file"),  # noqa: B008
        register_host: bool = typer.Option(True, "--register-host/--no-register-host"),
    ) -> None:
        """Enroll the actual conversation and register its route in one user action."""
        from tsunagou.application.onboarding import (
            codex_routing_directory,
            conversation_key,
            prepare_codex_request,
            read_codex_request,
            write_codex_route,
        )
        from tsunagou.hostwake.port import HostWakeError
        from tsunagou.platform.db.sqlite import ProjectLock
        from tsunagou.platform.private_files import write_private_bytes
        from tsunagou.platform.runtime_context import read_object
        from tsunagou.shared_kernel.time import format_timestamp, now_ms

        started_ns = time.monotonic_ns()
        connect_started_at = format_timestamp(now_ms())
        enrolled_at = None

        def timing() -> dict[str, Any]:
            return {"connect_started_at": connect_started_at, "connect_finished_at": format_timestamp(now_ms()),
                    "enrolled_at": enrolled_at, "duration_ms": (time.monotonic_ns() - started_ns) // 1_000_000}

        try:
            if mode not in {"attach", "launch"} or role not in {"worker", "main"}:
                raise typer.BadParameter("mode must be attach/launch; role must be worker/main")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", adapter) or not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
                raise typer.BadParameter("adapter/profile must contain only letters, digits, '_' or '-'")
            runtime = _runtime_context()
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
                identity = (os.environ.get("TSUNAGOU_HOST_CONVERSATION_ID") or os.environ.get("CODEX_THREAD_ID")
                            or os.environ.get("CODEX_SESSION_ID"))
                if not identity:
                    raise RuntimeError("host_conversation_required:run_agent_prepare_inside_the_host")
                destination = (
                    output_dir or runtime.project_root / ".tsunagou/bridges" / f"{adapter}-{conversation_key(identity)[:16]}"
                ).resolve()
                installation_id, conversation_id = _profile_identity(destination, adapter, profile)
            _ensure_project_daemon()
            token = _control_token()
            if not token:
                raise RuntimeError("control_credential_missing")
            source = running_source_root()
            if source is None:
                raise RuntimeError("installation_source_unavailable")
            if request is not None and Path(request["source_root"]).resolve() != source:
                raise RuntimeError("onboarding_source_mismatch")
            destination.mkdir(parents=True, exist_ok=True)
            ticket_file, session_file = destination / "ticket.json", destination / "bridge-session.json"
            bootstrap_request = request_file or (
                destination / "host-identity.json" if adapter in HOST_META_KEYS else None
            )
            # Connect serializes only its own conversation. CredentialHandoff
            # continues to own session rotation and ticket cleanup separately.
            with ProjectLock(destination / "connect.lock"):
                if request is not None:
                    write_codex_route(request, runtime, destination)
                    bridge_config_path = destination / "bridge-config.json"
                    config = {"command": "node", "args": [str(source / "packages/bridge-server/dist/server.js")],
                              "env": {"TSUNAGOU_ROUTING_DIR": str(codex_routing_directory())}, "secret_fields": []}
                    write_private_bytes(bridge_config_path, (json.dumps(config, indent=2) + "\n").encode())
                else:
                    bridge_config_path = _write_bridge_config(
                        adapter=adapter, mode=mode, installation_id=installation_id, output_dir=destination, ticket_path=ticket_file,
                    )
                if not ticket_file.exists() and not session_file.exists():
                    payload: dict[str, Any] = {
                        "kind": role, "role": role, "installation_id": installation_id,
                        "conversation_evidence": {"conversation_id": conversation_id},
                    }
                    if request:
                        payload["host_binding"] = {
                            "provider": "codex_desktop_app", "endpoint": request["endpoint"],
                            "thread_id": conversation_id, "host_generation": request["host_generation"],
                        }
                    result = _invoke_command("agent.ticket.create.user", payload, authorization=f"Bearer {token}")
                    _write_ticket_private(installation_id, conversation_id, result["secret"], ticket_file, role,
                                          request["host_generation"] if request else None)
                    _ack_private_delivery(result, token)
                context = _bridge_bootstrap(bridge_config_path, bootstrap_request)
                if context["project_id"] != runtime.project_id:
                    raise RuntimeError("onboarding_project_mismatch")
                if role == "main" and context["role"] != "main":
                    _invoke_command("authority.appoint", {"agent_id": context["agent_id"]}, authorization=f"Bearer {token}")
                    context = _bridge_bootstrap(bridge_config_path, bootstrap_request)
                if role == "worker" and context["role"] != "worker":
                    raise RuntimeError("current_agent_is_main:explicit_revoke_required")
                # This verifies enrollment through a helper bridge. Original-host
                # MCP readiness remains a separate observation after connect.
                enrolled_at = format_timestamp(now_ms())
                registration = (_register_codex_mcp(
                                    profile=profile,
                                    bridge_config_path=bridge_config_path,
                                    legacy_project_root=runtime.project_root,
                                )
                                if register_host and adapter == "codex" else "not_requested")

                public_context = {key: context[key] for key in ("project_id", "agent_id", "role")}
                for name, fields in (("session", ("status", "connection_epoch", "baseline_status")),
                                     ("host_binding", ("provider", "status", "binding_revision", "connection_epoch"))):
                    value = context.get(name)
                    public_context[name] = {key: value[key] for key in fields if key in value} if isinstance(value, dict) else None
                connected = {"status": "enrolled", **public_context, "adapter": adapter, "mode": mode,
                             "requested_role": role, "profile": profile, "installation_id": installation_id,
                             "bridge_config": str(bridge_config_path), "host_registration": registration,
                             "source_root": str(source),
                             "version": _daemon_request("GET", "/api/v1/health")["version"],
                             "next": "call_context__project_read_in_original_conversation"}
                connection_file = destination / "connection.json"
                previous = read_object(connection_file)
                connected["connected_at"] = previous.get("connected_at") if connection_file.exists() else enrolled_at
                connected.update(timing())
                write_private_bytes(connection_file, (json.dumps(connected, sort_keys=True) + "\n").encode())
                print(json.dumps(connected, sort_keys=True))
        except typer.BadParameter as exc:
            print(json.dumps({"status": "error", "error": str(exc), **timing()}))
            raise typer.Exit(2) from exc
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired, HostWakeError) as exc:
            code = exc.code if isinstance(exc, HostWakeError) else str(exc) if isinstance(exc, RuntimeError) else "onboarding_failed"
            print(json.dumps({"status": "error", "error": code, **timing()}))
            raise typer.Exit(4) from exc

    @agent_app.command("enroll")
    def agent_enroll(
        adapter: str = typer.Option(..., "--adapter"),
        mode: str = typer.Option("attach", "--mode"),
        installation_id: str | None = typer.Option(None, "--installation-id"),
        conversation_id: str | None = typer.Option(None, "--conversation-id"),
        ticket_file: Path | None = typer.Option(None, "--ticket-file"),  # noqa: B008
        output_dir: Path | None = typer.Option(None, "--output-dir"),  # noqa: B008
    ) -> None:
        if mode not in {"attach", "launch"}:
            raise typer.BadParameter("mode must be attach or launch")
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(1)
        if not installation_id or not conversation_id:
            print(json.dumps({
                "adapter": adapter, "mode": mode, "status": "ticket_required",
                "reason": "target_conversation_identity_required",
            }, sort_keys=True))
            raise typer.Exit(0)
        if output_dir is not None and ticket_file is None:
            output_dir = output_dir.expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            ticket_file = output_dir / "ticket.json"
        result = _invoke_command(
            "agent.ticket.create.user",
            {"kind": "worker", "installation_id": installation_id,
             "conversation_evidence": {"conversation_id": conversation_id}},
            authorization=f"Bearer {token}",
        )
        secret = result["secret"]
        path = _write_ticket_private(installation_id, conversation_id, secret, ticket_file)
        _ack_private_delivery(result, token)
        bridge_config_path = None
        if output_dir is not None:
            output_dir = output_dir.expanduser().resolve()
            bridge_config_path = _write_bridge_config(
                adapter=adapter, mode=mode, installation_id=installation_id,
                output_dir=output_dir, ticket_path=path,
            )
        print(json.dumps({
            "adapter": adapter, "mode": mode, "status": "ticket_issued",
            "installation_id": installation_id, "conversation_id": conversation_id,
            "ticket_file": str(path),
            **({"bridge_config": str(bridge_config_path)} if bridge_config_path else {}),
        }, sort_keys=True))

    @agent_app.command("list")
    def agent_list(ctx: typer.Context, json_output: bool = typer.Option(False, "--json")) -> None:
        try:
            result = _daemon_request("GET", f"/api/v1/projects/{_cli_project_id()}/agents")
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}))
            raise typer.Exit(4) from exc
        if json_output or ctx.obj.get("json"):
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            for item in result["items"]:
                print(f"{item['agent_id']} {item['role']} session={item['session_status']} "
                      f"tasks={','.join(item['current_task_ids']) or '-'} last_activity={item['last_activity_at'] or 'unknown'}")

    @agent_app.command("appoint")
    def agent_appoint(agent_id: str = typer.Argument(...)) -> None:
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(1)
        result = _invoke_command(
            "authority.appoint",
            {"agent_id": agent_id}, authorization=f"Bearer {token}",
        )
        print(json.dumps({
            "agent_id": agent_id, "status": "appointed", **result,
        }, sort_keys=True))

    @decision_app.command("list")
    def decision_list() -> None:
        try:
            token = _control_token()
            if not token:
                raise RuntimeError("control_credential_missing")
            result = _daemon_request("GET", "/api/v1/decisions", authorization=f"Bearer {token}")
        except RuntimeError as exc:
            print(json.dumps({"status": "unavailable", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(5) from exc
        print(json.dumps(result, sort_keys=True))

    @decision_app.command("resolve")
    def decision_resolve(
        decision_id: str,
        choice: str = typer.Option(..., "--choice"),
        expected_revision: int = typer.Option(..., "--expected-revision"),
        digest: str = typer.Option(..., "--digest"),
        reason: str | None = typer.Option(None, "--reason"),
    ) -> None:
        token = _control_token()
        if not token:
            raise typer.Exit(5)
        try:
            result = _invoke_command(
                "user_decision.resolve",
                {
                    "decision_id": decision_id, "choice": choice,
                    "expected_revisions": {"decision": expected_revision},
                    "proposal_digest": digest, "reason": reason or "",
                },
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    @operation_app.command("show")
    def operation_show(operation_id: str) -> None:
        try:
            result = _daemon_request("GET", f"/api/v1/operations/{operation_id}")
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    @checkpoint_app.command("create")
    def checkpoint_create() -> None:
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            result = _invoke_command("checkpoint.create.user", {}, authorization=f"Bearer {token}")
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    @checkpoint_app.command("retry")
    def checkpoint_retry(operation_id: str | None = typer.Argument(None)) -> None:
        """Retry checkpoint materialization after a recorded failed operation."""
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            if operation_id is None:
                operations = _daemon_request("GET", "/api/v1/operations")["items"]
                failed = [item for item in operations if item["kind"] == "checkpoint.create"
                          and item["status"] in {"failed", "retry_wait"}]
                if not failed:
                    raise RuntimeError("checkpoint_operation_not_found")
                operation_id = str(failed[-1]["id"])
            result = _invoke_command(
                "checkpoint.create.user", {"reason": "user_retry_after_failure", "retry_operation_id": operation_id},
                authorization=f"Bearer {token}",
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps(result, sort_keys=True))

    @checkpoint_app.command("list")
    def checkpoint_list(
        project_id: str = typer.Argument(...),
        verify: bool = typer.Option(False, "--verify"),
    ) -> None:
        """List public checkpoint metadata; optionally verify every file."""
        from tsunagou.shared_kernel.query_models import CheckpointPageModel

        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            path = f"/api/v1/projects/{urllib.parse.quote(project_id, safe='')}/checkpoints?verify={str(verify).lower()}"
            result = CheckpointPageModel.model_validate(
                _daemon_request("GET", path, authorization=f"Bearer {token}")
            ).model_dump(mode="json", by_alias=True)
        except (RuntimeError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc) if isinstance(exc, RuntimeError)
                              else "invalid_checkpoint_response"}, sort_keys=True))
            raise typer.Exit(2) from exc
        print(json.dumps(result, sort_keys=True))

    @checkpoint_app.command("verify")
    def checkpoint_verify(checkpoint_id: str = typer.Argument(...)) -> None:
        """Verify one checkpoint manifest, files and local Git anchor."""
        from tsunagou.shared_kernel.query_models import CheckpointVerificationModel

        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(5)
        try:
            path = f"/api/v1/checkpoints/{urllib.parse.quote(checkpoint_id, safe='')}/verify"
            result = CheckpointVerificationModel.model_validate(
                _daemon_request("GET", path, authorization=f"Bearer {token}")
            ).model_dump(mode="json", by_alias=True)
        except (RuntimeError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc) if isinstance(exc, RuntimeError)
                              else "invalid_checkpoint_response"}, sort_keys=True))
            raise typer.Exit(2) from exc
        print(json.dumps(result, sort_keys=True))

    @app.command("recover")
    def recover() -> None:
        try:
            result = _daemon_request("GET", "/api/v1/recovery")
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(5) from exc
        print(json.dumps(result, sort_keys=True))

    def _console_settings(
        ctx: typer.Context, config: Path | None, host: str | None, port: int | None,
    ) -> Any:
        """Load the console config, apply command-line overrides, or exit with a reason."""

        from tsunagou.console.config import ConsoleConfig

        try:
            settings = ConsoleConfig.load(config)
        except (FileNotFoundError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        if host:
            settings.host = host
        if port is not None:
            settings.port = port
        ctx.ensure_object(dict)
        return settings

    @web_app.command("start")
    def web_start(
        ctx: typer.Context,
        config: Path | None = typer.Option(None, "--config"),  # noqa: B008
        host: str | None = typer.Option(None, "--host"),
        port: int | None = typer.Option(None, "--port"),
    ) -> None:
        """Serve the console page and forward it to the projects' daemons."""
        from tsunagou.console.service import serve

        settings = _console_settings(ctx, config, host, port)

        def announce(record: dict[str, Any]) -> None:
            if ctx.obj.get("json"):
                print(json.dumps({"status": "serving", **record}, sort_keys=True))
            else:
                print(f"Tsunagou console: {record['url']}  (Ctrl+C to stop)")

        try:
            serve(settings, on_ready=announce)
        except (FileNotFoundError, RuntimeError) as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        print(json.dumps({"status": "stopped"}, sort_keys=True) if ctx.obj.get("json") else "Tsunagou console: stopped")

    @web_app.command("status")
    def web_status(
        ctx: typer.Context,
        config: Path | None = typer.Option(None, "--config"),  # noqa: B008
    ) -> None:
        """Report whether the console is running, and where."""
        from tsunagou.console.service import status as console_status

        settings = _console_settings(ctx, config, None, None)
        result = console_status(settings)
        if ctx.obj.get("json"):
            print(json.dumps(result, sort_keys=True))
        elif result["status"] == "running":
            print(f"Tsunagou console: running at {result['url']} (pid {result['pid']})")
        else:
            print(f"Tsunagou console: {result['status']}")
        if result["status"] != "running":
            raise typer.Exit(5)

    main = app
else:
    def main() -> None:
        print("Tsunagou 0.1.0 — local coordination runtime")
