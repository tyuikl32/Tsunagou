from __future__ import annotations

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
from pathlib import Path
from typing import Any, cast

from tsunagou.platform import host_registration
from tsunagou.platform.bridge_files import (
    profile_identity,
    read_bridge_config,
    write_bridge_config,
    write_ticket_file,
)

# 这两个名字以前住在本文件里，CLI 自己的测试按老名字导入它们；实现现在只有一份，
# 在 `tsunagou.platform.bridge_files`（中间层也用它）。
_write_ticket_private = write_ticket_file
_profile_identity = profile_identity

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
    ) -> None:
        ctx.ensure_object(dict)
        ctx.obj["json"] = json_output
        if version:
            print("0.1.0")
            raise typer.Exit()
        if ctx.invoked_subcommand is None:
            print("Tsunagou 0.1.0 — local coordination runtime")

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

    @project_app.command("diagnostics")
    def project_diagnostics(
        ctx: typer.Context,
        project_id: str = typer.Argument(...),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Read host-wake/A2A transport evidence without changing domain history."""
        from tsunagou.shared_kernel.query_models import DiagnosticPageModel

        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(3)
        try:
            path = f"/api/v1/projects/{urllib.parse.quote(project_id, safe='')}/diagnostics"
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
            print(f"{item.observed_at}\t{item.kind}\t{item.agent_id}\t{item.message_id}\t"
                  f"{item.wake_attempt_id or '-'}\t{item.evidence_digest or '-'}")

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
        configured = os.environ.get("TSUNAGOU_PROJECT_ROOT")
        if configured:
            return Path(configured).expanduser().resolve()
        return Path.cwd().resolve()

    def _cli_project_id(explicit: str | None = None) -> str:
        if explicit:
            return explicit
        configured = os.environ.get("TSUNAGOU_PROJECT_ID")
        if configured:
            return configured
        root = _project_root()
        project_file = root / ".tsunagou" / "project.json"
        try:
            value = json.loads(project_file.read_text(encoding="utf-8")).get("project_id")
        except (OSError, json.JSONDecodeError):
            value = None
        if isinstance(value, str) and value:
            return value
        raise RuntimeError("project_id_required")

    def _state_dir_from_environment() -> Path | None:
        value = os.environ.get("TSUNAGOU_STATE_DIR")
        if value:
            return Path(value)
        root = os.environ.get("TSUNAGOU_PROJECT_ROOT")
        if root:
            return _coordination_state_dir(Path(root))
        candidate = _coordination_state_dir(Path.cwd())
        if candidate.is_dir():
            return candidate
        return None

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
        return _coordination_state_dir(coordination_root) / "endpoint.json"

    def _choose_port(host: str) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            return int(sock.getsockname()[1])

    def _wait_for_daemon(url: str, process: subprocess.Popen[bytes], timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        request = urllib.request.Request(url.rstrip("/") + "/api/v1/health", method="GET")
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("daemon_exited_during_start")
            try:
                with urllib.request.urlopen(request, timeout=0.5) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.1)
        raise RuntimeError("daemon_start_timeout")

    @daemon_app.command("start")
    def daemon_start(
        coordination_root: Path = typer.Option(Path("."), "--coordination-root"),  # noqa: B008
        host: str = typer.Option("127.0.0.1", "--host"),
        port: int = typer.Option(0, "--port", min=0, max=65535),
        name: str = typer.Option("Tsunagou project", "--name"),
        objective: str = typer.Option("Coordinate local agents", "--objective"),
        host_wake: str = typer.Option("disabled", "--host-wake"),
    ) -> None:
        from tsunagou.modules.projects import ProjectRegistry

        if host_wake not in {"disabled", "managed"}:
            raise typer.BadParameter("host-wake must be disabled or managed")
        root = coordination_root.expanduser().resolve()
        try:
            registry = ProjectRegistry.initialize(root, name=name, objective=objective)
        except (OSError, RuntimeError, ValueError) as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True))
            raise typer.Exit(1) from exc
        assert registry.project is not None
        _remember_project(registry.project, root)
        state_dir = _coordination_state_dir(root)
        if not (state_dir / "state.sqlite3").exists() and (root / ".tsunagou/checkpoints/current.json").is_file():
            print(json.dumps({"status": "error", "error": "checkpoint_restore_required",
                              "next": "project restore --coordination-root <clone> --checkpoint-digest <digest>"}))
            raise typer.Exit(4)
        state_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = state_dir / "endpoint.json"
        if manifest_path.is_file():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                existing_url = existing.get("url")
                if isinstance(existing_url, str):
                    with urllib.request.urlopen(existing_url.rstrip("/") + "/api/v1/health", timeout=1):
                        print(json.dumps({"status": "already_running", **existing}, sort_keys=True))
                        return
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
            "PYTHONPATH": os.pathsep.join(
                [str(Path(__file__).resolve().parents[2]), child_env.get("PYTHONPATH", "")]
            ).rstrip(os.pathsep),
        })
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with open(log_path, "ab") as log_handle:
            process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "tsunagou.bootstrap.container:build_application",
                 "--factory", "--host", host, "--port", str(selected_port)],
                cwd=str(root), env=child_env, stdout=log_handle, stderr=log_handle,
                creationflags=flags,
            )
        try:
            _wait_for_daemon(url, process)
        except RuntimeError as exc:
            if process.poll() is None:
                process.terminate()
            print(json.dumps({"status": "error", "error": str(exc), "log": str(log_path)}, sort_keys=True))
            raise typer.Exit(1) from exc
        manifest = {
            "url": url, "pid": process.pid, "project_id": registry.project.project_id,
            "state_dir": str(state_dir), "host_wake": host_wake, "started_at": int(time.time()),
        }
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({"status": "started", **manifest}, sort_keys=True))

    @daemon_app.command("status")
    def daemon_status(
        coordination_root: Path = typer.Option(Path("."), "--coordination-root"),  # noqa: B008
    ) -> None:
        path = _endpoint_manifest(coordination_root)
        if not path.is_file():
            print(json.dumps({"status": "stopped", "manifest": str(path)}, sort_keys=True))
            raise typer.Exit(3)
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            with urllib.request.urlopen(manifest["url"].rstrip("/") + "/api/v1/health", timeout=2) as response:
                running = response.status == 200
        except (OSError, urllib.error.URLError, KeyError, json.JSONDecodeError):
            running = False
        print(json.dumps({**manifest, "status": "running" if running else "stopped"}, sort_keys=True))
        if not running:
            raise typer.Exit(3)

    @daemon_app.command("stop")
    def daemon_stop(
        coordination_root: Path = typer.Option(Path("."), "--coordination-root"),  # noqa: B008
    ) -> None:
        path = _endpoint_manifest(coordination_root)
        if not path.is_file():
            print(json.dumps({"status": "already_stopped"}, sort_keys=True))
            return
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            pid = int(manifest["pid"])
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(json.dumps({"status": "error", "error": "invalid_endpoint_manifest"}, sort_keys=True))
            raise typer.Exit(1) from exc
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
            else:
                os.kill(pid, 15)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        print(json.dumps({"status": "stopped", "pid": pid}, sort_keys=True))

    def _daemon_url() -> str:
        value = os.environ.get("TSUNAGOU_DAEMON_URL")
        if value:
            return value.rstrip("/")
        state_dir = os.environ.get("TSUNAGOU_STATE_DIR")
        if not state_dir:
            project_root = os.environ.get("TSUNAGOU_PROJECT_ROOT")
            if project_root:
                state_dir = str(_coordination_state_dir(Path(project_root)))
        if state_dir:
            manifest = Path(state_dir) / "endpoint.json"
            if manifest.is_file():
                try:
                    value = json.loads(manifest.read_text(encoding="utf-8")).get("url")
                    if isinstance(value, str) and value:
                        return value.rstrip("/")
                except (OSError, json.JSONDecodeError):
                    pass
        raise RuntimeError("daemon_endpoint_not_configured")

    def _daemon_request(
        method: str, path: str, body: dict[str, Any] | None = None,
        *, authorization: str | None = None, session_id: str | None = None,
        connection_epoch: int | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
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

    def _register_codex_mcp(*, profile: str, bridge_config_path: Path) -> str:
        """Register the bridge with Codex, in Codex's own dialect (see the host table)."""

        config = read_bridge_config(bridge_config_path)
        result = host_registration.register(
            "codex", profile=profile,
            project_root=Path(str(config.get("env", {}).get("TSUNAGOU_PROJECT_ROOT", ""))),
            bridge=config,
        )
        if result.status == host_registration.REGISTERED:
            return f"registered:{result.name}"
        if result.status == host_registration.EXECUTABLE_MISSING:
            return "codex_not_found"
        if result.status == host_registration.UNSUPPORTED:
            return "codex_not_supported"
        return "codex_registration_failed"

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

    @agent_app.command("connect")
    def agent_connect(
        adapter: str = typer.Option(..., "--adapter"),
        role: str = typer.Option("worker", "--role"),
        profile: str = typer.Option("current", "--profile"),
        mode: str = typer.Option("attach", "--mode"),
        output_dir: Path | None = typer.Option(None, "--output-dir"),  # noqa: B008
        register_host: bool = typer.Option(True, "--register-host/--no-register-host"),
    ) -> None:
        """Prepare one host conversation in one user-control action.

        The daemon still creates the Agent/session/token. ``--role main`` is
        an explicit user request carried by the one-time ticket; an Agent
        cannot invoke this command through its bridge.
        """
        if mode not in {"attach", "launch"}:
            raise typer.BadParameter("mode must be attach or launch")
        if role not in {"worker", "main"}:
            raise typer.BadParameter("role must be worker or main")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", adapter):
            raise typer.BadParameter("adapter must contain only letters, digits, '_' or '-'")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
            raise typer.BadParameter("profile must contain only letters, digits, '_' or '-'")
        token = _control_token()
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(1)
        root = _project_root()
        destination = (output_dir or (root / ".tsunagou" / "bridges" / f"{adapter}-{profile}")).expanduser().resolve()
        installation_id, conversation_id = _profile_identity(destination, adapter, profile)
        ticket_file = destination / "ticket.json"
        result = _invoke_command(
            "agent.ticket.create.user",
            {
                "kind": role, "role": role,
                "installation_id": installation_id,
                "conversation_evidence": {"conversation_id": conversation_id},
            },
            authorization=f"Bearer {token}",
        )
        ticket_path = _write_ticket_private(
            installation_id, conversation_id, result["secret"], ticket_file, role,
        )
        _ack_private_delivery(result, token)
        bridge_config_path = _write_bridge_config(
            adapter=adapter, mode=mode, installation_id=installation_id,
            output_dir=destination, ticket_path=ticket_path,
        )
        registration = "not_requested"
        if register_host and adapter == "codex":
            registration = _register_codex_mcp(profile=profile, bridge_config_path=bridge_config_path)
        print(json.dumps({
            "adapter": adapter,
            "mode": mode,
            "status": "ticket_issued",
            "requested_role": role,
            "profile": profile,
            "installation_id": installation_id,
            "bridge_config": str(bridge_config_path),
            "host_registration": registration,
            "next": "restart_or_reload_host_then_call_context__project_read",
        }, sort_keys=True))

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
            result = _daemon_request("GET", "/api/v1/decisions")
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
