from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from tsunagou.application.onboarding import conversation_key
from tsunagou.modules.projects import PENDING_OBJECTIVE
from tsunagou.platform import host_registration
from tsunagou.platform.bridge_files import write_bridge_config, write_ticket_file
from tsunagou.platform.runtime_context import RuntimeContext, resolve_runtime, running_source_root
from tsunagou.shared_kernel.time import format_timestamp, now_ms

if TYPE_CHECKING:
    from tsunagou.application.agent_connection import ConnectionOperations

_selected_project_root: ContextVar[Path | None] = ContextVar("cli_project_root", default=None)


# The one-time ticket writer lives in ``tsunagou.platform.bridge_files`` so that the
# middle layer and the CLI share one implementation and one process-owned lock; the CLI
# tests import it under this older name.
_write_ticket_private = write_ticket_file


def _advertised_url(declared: str, bind_host: str) -> str:
    """核对"别人该怎么连我"这句话，返回规范化后的地址（空串 = 没声明）。

    监听地址回答"我在哪些网卡上听"，对外地址回答"远端该拨哪个号"——同一台机器上常常
    不是同一个值（绑 ``0.0.0.0`` 时尤其明显：那不是一个远方能拨的地址）。所以两件事分开：
    监听仍由 ``--host/--port`` 决定，这里只管写给别人看的那一个。
    """

    text = str(declared or "").strip().rstrip("/")
    if not text:
        return ""
    # 手写 "192.168.1.10:2810" 是常态：补上默认协议再解析，别让人为了一个冒号重敲一遍。
    candidate = text if "://" in text else f"http://{text}"
    parsed = urllib.parse.urlsplit(candidate)
    hostname = parsed.hostname or ""
    if hostname in {"0.0.0.0", "::"}:
        # 绑 0.0.0.0 是"在所有网卡上听"，不是"我在这里"：写成对外地址，远端永远连不上。
        raise RuntimeError("advertised_url_must_not_be_a_wildcard")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("advertised_url_must_be_an_origin") from exc
    if (parsed.scheme not in {"http", "https"} or not hostname
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
        raise RuntimeError("advertised_url_must_be_an_origin")
    loopback_bind = bind_host in {"127.0.0.1", "localhost", "::1"}
    loopback_advertised = hostname in {"127.0.0.1", "localhost", "::1"}
    if loopback_advertised and not loopback_bind:
        print(json.dumps({
            "status": "warning", "error": "advertised_url_is_loopback",
            "advertised_url": text,
            "note": "对外地址写的是回环：只有这台机器自己能连，远端拿到这张邀请也连不上。",
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    if loopback_bind and not loopback_advertised:
        print(json.dumps({
            "status": "warning", "error": "daemon_bind_is_loopback",
            "advertised_url": text, "host": bind_host,
            "note": f"对外地址是 {text}，但监听只在 {bind_host}：远端连不上。"
                    f"要跨机器就同时给 --host 0.0.0.0（或那张网卡的地址）。",
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
    port = parsed.port
    return f"{parsed.scheme}://{hostname}" + (f":{port}" if port else "")


def _runtime_context() -> RuntimeContext:
    return resolve_runtime(_selected_project_root.get())


#: The coordination centre's fixed port. Reachable remotes need a port that survives a
#: restart — that is the whole point of fixing it — but a port somebody else already holds
#: must never stop the daemon: it falls back to a free one and says so (``--port 0`` still
#: means "any free port", and says nothing because that is what was asked for).
DEFAULT_DAEMON_PORT = 2810


def _daemon_port_is_free(host: str, port: int) -> bool:
    """Can this address be bound right now?

    No ``SO_REUSEADDR`` on purpose: on Windows that option lets a second process bind a
    port that is already in use, which would turn this check into a yes-man.
    """

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return True
    except OSError:
        return False


def _pick_daemon_port(host: str, requested: int) -> tuple[int, bool]:
    """Return ``(port, fell_back)``: the fixed port, or a free one when it is taken."""

    if requested == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, 0))
            return int(sock.getsockname()[1]), False
    if _daemon_port_is_free(host, requested):
        return requested, False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1]), True


def _pending_record(adapter: str) -> dict[str, Any] | None:
    """The one pending handoff the console wrote for this host, if there is one."""

    if not adapter:
        return None
    try:
        from tsunagou.platform.enrollment_store import EnrollmentStore

        return EnrollmentStore().active_for(adapter)
    except RuntimeError:
        return None


def _role_for_connect(adapter: str, explicit: str | None) -> str | None:
    """Which role does this join take? The record decides while it is pending.

    The console wrote down what the person chose (main or worker) together with the
    project. That decision is the answer to "what am I joining as", so it outranks a
    role the chat happens to ask for: a request for the other role is refused
    (``enrollment_role_conflict``) instead of quietly obeyed. Without a pending record
    this is the explicit manual path: ``--role`` wins, and ``None`` means "keep whatever
    this conversation already is, else the host default".

    The daemon cannot be talked into a role by the enrolling side at all — ``agent.enroll``
    carries no role field, and the seat takes the role written in the ticket.
    """

    pending = _pending_record(adapter)
    wanted = str((pending or {}).get("requested_role") or "").strip()
    if wanted and explicit and explicit != wanted:
        raise RuntimeError("enrollment_role_conflict")
    return wanted or explicit or None


def _runtime_for_connect(adapter: str) -> RuntimeContext:
    """接入时项目从哪来：显式指定/环境 → 那条唯一待接入记录 → 聊天的工作目录。

    宿主聊天里说"请接入 Tsunagou"的那一刻，它手上只有自己的会话 id 和工作目录；而工作
    目录经常不是协调仓库 —— 一个项目可以协调好几个文件夹，控制台也把项目建在自己的根下。
    机器上唯一说得清"接哪个项目、什么角色"的，就是用户在控制台点接入时留下的那条记录
    （``platform/enrollment_store.py``）。只在 cwd 推不出项目时才用它：显式路径和环境变量
    永远优先，工作目录里真有项目时也不必绕这一圈。
    """

    runtime = _runtime_context()
    if runtime.project_id or not adapter:
        return runtime
    pending = _pending_record(adapter)
    if pending is None:
        return runtime
    root = Path(str(pending["project_root"])).expanduser().resolve()
    if not (root / ".tsunagou" / "project.json").is_file():
        return runtime
    _selected_project_root.set(root)
    return _runtime_context()


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
        objective: str = typer.Option(PENDING_OBJECTIVE, "--objective"),
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
        port: int = typer.Option(DEFAULT_DAEMON_PORT, "--port", min=0, max=65535),
        name: str = typer.Option("Tsunagou project", "--name"),
        objective: str = typer.Option(PENDING_OBJECTIVE, "--objective"),
        host_wake: str = typer.Option("auto", "--host-wake"),
        advertised_url: str = typer.Option("", "--advertised-url"),
        reuse: Path | None = typer.Option(None, "--reuse"),  # noqa: B008
    ) -> None:
        from tsunagou.modules.projects import ProjectRegistry

        if host_wake not in {"disabled", "managed", "desktop", "auto"}:
            raise typer.BadParameter("host-wake must be disabled, managed, desktop or auto")
        advertised = _advertised_url(advertised_url, host)
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
        # 上一次写在清单里的对外地址要沿用：重启时没人会再敲一遍那个参数，
        # 而远端手里那张邀请依赖它不变。
        previous_manifest: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded_manifest, dict):
                    previous_manifest = loaded_manifest
            except (OSError, json.JSONDecodeError):
                previous_manifest = {}
        advertised = advertised or str(previous_manifest.get("advertised_url") or "")
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
                    print(json.dumps({"status": "already_running", **existing,
                                      **({"note": "对外地址改过了：重启 daemon（daemon stop 再 start）才会生效。"}
                                         if advertised and advertised != existing.get("advertised_url") else {})},
                                     ensure_ascii=False, sort_keys=True))
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
        selected_port, port_fallback = _pick_daemon_port(host, port)
        if port_fallback:
            # 人得看得见：地址变了，邀请里用的也是这个新端口。
            print(json.dumps({
                "status": "warning", "error": "daemon_port_in_use", "requested_port": port,
                "port": selected_port,
                "note": f"{port} 已被占用，这次改用空闲端口 {selected_port}；给远端的邀请里会带上真正使用的端口。",
            }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
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
            **({"TSUNAGOU_DAEMON_ADVERTISED_URL": advertised} if advertised else {}),
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
        print(json.dumps({
            "status": "started", **manifest,
            **({"port_fallback": {"requested": port, "used": selected_port}} if port_fallback else {}),
        }, sort_keys=True))

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

    def _register_host_mcp(*, adapter: str, profile: str, bridge_config_path: Path) -> str:
        """Put the bridge into the host's own configuration, through the shared table.

        The CLI and the console take this same path, so neither can write a registration
        the other would not recognise. The host table is the single place that knows how
        each dialect works: DeepSeek writes its own conversation-scoped overlay, OpenCode
        runs its own `mcp add` inside the project. DeepSeek Desktop uses its
        credential-free provider and private route instead of an overlay.
        """

        if adapter == "deepseek" and profile == "desktop":
            _prepare_deepseek_desktop()
            return "configured:desktop"
        config = json.loads(bridge_config_path.read_text(encoding="utf-8"))
        project_root = Path(str((config.get("env") or {}).get("TSUNAGOU_PROJECT_ROOT") or _project_root()))
        result = host_registration.register(
            adapter, profile=profile, project_root=project_root, bridge=config,
        )
        if result.status == host_registration.REGISTERED:
            return f"registered:{result.name}"
        if adapter == "deepseek":
            raise RuntimeError(f"deepseek_host_registration_{result.status}")
        return f"{adapter}_{result.status}"

    def _deepseek_desktop_config() -> dict[str, Any]:
        """Installed runtime paths only; no project or conversation credentials."""
        from tsunagou.application.onboarding import deepseek_routing_directory
        from tsunagou.platform.runtime_context import installation_path, read_object

        source = running_source_root()
        if source is None:
            raise RuntimeError("installation_source_unavailable")
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("bridge_node_unavailable")
        bridge_entry = source / "packages/bridge-server/dist/server.js"
        if not bridge_entry.is_file():
            raise RuntimeError("bridge_build_missing")
        installation = read_object(installation_path())
        python = Path(sys.executable).absolute()
        if installation.get("python") and Path(str(installation.get("source_root", ""))).resolve() == source:
            installed_python = Path(installation["python"]).expanduser().resolve()
            if installed_python.is_file():
                python = installed_python
        packages = [source / ".venv/Lib/site-packages", *sorted((source / ".venv/lib").glob("python*/site-packages"))]
        pythonpath = os.pathsep.join(str(path) for path in [source / "src", *packages] if path.is_dir())
        return {
            "command": str(Path(node).resolve()), "args": [str(bridge_entry)],
            "env": {"TSUNAGOU_ROUTING_DIR": str(deepseek_routing_directory()),
                    "TSUNAGOU_HOST_META_KEY": host_registration.DEEPSEEK_HOST_META_KEY},
            "connect": {"command": str(python), "args": ["-m", "tsunagou"],
                        "env": {"PYTHONPATH": pythonpath, "PYTHONNOUSERSITE": "1",
                                "PATH": str(Path(node).resolve().parent) + os.pathsep + os.environ.get("PATH", "")}},
        }

    def _prepare_deepseek_desktop() -> host_registration.ConfigChange:
        result = host_registration.register_deepseek_desktop(_deepseek_desktop_config())
        if result.status != host_registration.REGISTERED:
            raise RuntimeError(result.note)
        return result

    def _deepseek_launch_command(*, profile: str, bridge_config_path: Path) -> str:
        """The one command that boots this conversation with its own overlay.

        It is emitted rather than executed: Harness only learns which conversation it
        is when that conversation starts, so the binding has to travel on the launch.
        """

        from tsunagou.application.onboarding import powershell_quote
        from tsunagou.platform.host_registration import deepseek_overlay_path

        config = json.loads(bridge_config_path.read_text(encoding="utf-8"))
        overlay = deepseek_overlay_path(config)
        host = host_registration.host_for("deepseek")
        executable = host_registration.find_executable(host) if host is not None else None
        return (f"& {powershell_quote(executable or 'dsh')} "
                f"--profile {powershell_quote(host_registration.dsh_app_profile(profile))} "
                f"--patch {powershell_quote(str(overlay))} "
                f"--session-id <this conversation's Harness session id>")

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

    def _host_conversation_id(adapter: str) -> str:
        if adapter == "deepseek":
            conversation_id = os.environ.get("DSH_SESSION_ID")
        else:
            conversation_id = os.environ.get("TSUNAGOU_HOST_CONVERSATION_ID")
            if not conversation_id and adapter == "codex":
                conversation_id = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
        if not conversation_id or not conversation_id.strip():
            raise RuntimeError("host_conversation_required:run_agent_prepare_inside_the_host")
        return conversation_id

    def _profile_identity(output_dir: Path, adapter: str, profile: str) -> tuple[str, str]:
        """Use a host-provided identity; a display profile is never a Worker."""
        from tsunagou.platform.private_files import write_private_bytes
        from tsunagou.platform.runtime_context import read_object

        conversation_id = _host_conversation_id(adapter)
        identity_path = output_dir / "host-identity.json"
        prior = read_object(identity_path)
        if prior and (prior.get("conversation_id") != conversation_id or prior.get("adapter") != adapter):
            raise RuntimeError("profile_conversation_conflict")
        installation_id = os.environ.get("TSUNAGOU_INSTALLATION_ID") or prior.get("installation_id") or f"{adapter}:local"
        if prior.get("installation_id") not in {None, installation_id}:
            raise RuntimeError("profile_installation_conflict")
        value = {"adapter": adapter, "profile": profile, "installation_id": installation_id, "conversation_id": conversation_id}
        if value != prior:
            write_private_bytes(identity_path, (json.dumps(value, sort_keys=True) + "\n").encode())
        return installation_id, conversation_id

    @agent_app.command("prepare")
    def agent_prepare(
        adapter: str = typer.Option(..., "--adapter"),
        role: str = typer.Option("worker", "--role"),
        profile: str = typer.Option("desktop", "--profile"),
    ) -> None:
        """Privately observe the current host; return one fully filled user command."""
        from tsunagou.application.onboarding import powershell_quote, prepare_codex_request
        from tsunagou.hostwake.port import HostWakeError

        if adapter not in {"codex", "deepseek"} or role not in {"worker", "main"}:
            raise typer.BadParameter("prepare supports codex/deepseek and role worker/main")
        try:
            if adapter == "deepseek":
                if profile != "desktop":
                    raise RuntimeError("deepseek_prepare_requires_desktop_profile")
                result = _prepare_deepseek_desktop()
                print(json.dumps({"status": "prepared", "adapter": adapter, "profile": profile,
                                  "host_registration": "configured", "host_ready": False, "creates_agent": False,
                                  "files": [str(path) for path in result.files],
                                  "next": "call_tsunagou_connect_in_original_conversation"}, ensure_ascii=False))
                return
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
            try:
                failure = json.loads(result.stdout)
            except ValueError:
                failure = {}
            code = failure.get("error", "") if isinstance(failure, dict) else ""
            if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,100}", code):
                detail = failure.get("os_error")
                raise RuntimeError(code + (f":os_error_{detail}" if isinstance(detail, int) else ""))
            raise RuntimeError("daemon_start_failed")
        context = _runtime_context()
        _verify_daemon_identity(_daemon_request("GET", "/api/v1/health"), context.endpoint, context.project_id)

    def _bridge_bootstrap(config: Path, request: Path | None) -> dict[str, Any]:
        source = running_source_root()
        if source is None:
            raise RuntimeError("installation_source_unavailable")
        launch = json.loads(config.read_text(encoding="utf-8"))
        command = [str(launch["command"]), str(source / "packages/bridge-server/scripts/connect-context.mjs"), str(config)]
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

    def _connection_operations(adapter: str = "") -> ConnectionOperations:
        from tsunagou.application.agent_connection import ConnectionOperations
        return ConnectionOperations(
            runtime=lambda: _runtime_for_connect(adapter), ensure_daemon=_ensure_project_daemon,
            control_token=_control_token,
            host_conversation_id=_host_conversation_id, profile_identity=_profile_identity,
            write_bridge=lambda adapter, mode, installation, destination, ticket: _write_bridge_config(
                adapter=adapter, mode=mode, installation_id=installation, output_dir=destination, ticket_path=ticket,
            ),
            invoke=lambda kind, payload, token: _invoke_command(kind, payload, authorization=f"Bearer {token}"),
            ack_delivery=_ack_private_delivery, bootstrap=_bridge_bootstrap,
            register_codex=lambda profile, config, root: _register_codex_mcp(
                profile=profile, bridge_config_path=config, legacy_project_root=root,
            ),
            register_host=lambda adapter, profile, config: _register_host_mcp(
                adapter=adapter, profile=profile, bridge_config_path=config,
            ),
            launch_command=lambda profile, config: _deepseek_launch_command(profile=profile, bridge_config_path=config),
            daemon_version=lambda: str(_daemon_request("GET", "/api/v1/health")["version"]),
        )

    @agent_app.command("invite")
    def agent_invite(
        adapter: str = typer.Option(..., "--adapter"),
        profile: str = typer.Option("", "--profile"),
        role: str = typer.Option("worker", "--role"),
        nickname: str = typer.Option("", "--nickname"),
        conversation_id: str = typer.Option("", "--conversation-id"),
        ttl_seconds: int = typer.Option(600, "--ttl"),
    ) -> None:
        """打一张给远端机器的邀请（主机这边执行）：一段可以复制的内容。

        里面写着"接哪个项目、用什么身份、当什么角色、什么时候失效"，以及那张一次性票。
        远端只需要把这段内容粘进 `agent import` 一条命令里。

        身份这件事分两种宿主：**会话名可以由主机起的**（OpenCode）这边直接起一个；
        **只有它自己知道会话名的**（Codex、DeepSeek Harness）要先让它报号（`agent whoami`），
        再用 `--conversation-id` 传进来。主 Agent 必须和协调中心在同一台机器上，所以这里
        只发子 Agent 的邀请。
        """

        import tsunagou.platform.remote_invite as remote_invite
        from tsunagou.platform.host_registration import host_for

        try:
            host = host_for(adapter)
            if host is None:
                raise RuntimeError("unknown_host_adapter")
            if role != "worker":
                # 主 Agent 要和协调中心同机：跨机器那一个只能是子 Agent。
                raise RuntimeError("main_agent_must_be_local")
            runtime = _runtime_context()
            if not runtime.project_id:
                raise RuntimeError("project_not_initialized")
            url = str(runtime.endpoint.get("advertised_url") or runtime.endpoint.get("url") or "")
            if not url:
                raise RuntimeError("daemon_endpoint_not_configured")
            if urllib.parse.urlsplit(url).hostname in {"127.0.0.1", "localhost", "::1"}:
                print(json.dumps({
                    "status": "warning", "error": "invite_address_is_loopback",
                    "note": "现在这个地址只有这台机器能连：远端拿到邀请也连不上。"
                            "跨机器请让协调中心带上 --advertised-url（并 --host 0.0.0.0 或网卡地址）。",
                }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
            chosen_profile = profile.strip() or nickname.strip() or "remote"
            conversation = conversation_id.strip()
            if not conversation:
                if host.adapter != "opencode":
                    raise RuntimeError("conversation_id_required_for_this_host")
                # 这个名字是我们起的：票绑它，人用同一个名字开会话，两边身份就对上了。
                conversation = f"ses_{chosen_profile}"
            installation_id = f"{host.adapter}:{chosen_profile}"
            token = _control_token()
            if not token:
                raise RuntimeError("control_credential_missing")
            issued = _invoke_command("agent.ticket.create.user", {
                "installation_id": installation_id, "kind": "worker", "role": "worker",
                "ttl_seconds": _invite_ttl(ttl_seconds),
                "conversation_evidence": {"conversation_id": conversation},
            }, authorization=f"Bearer {token}")
            if not isinstance(issued, dict) or not isinstance(issued.get("secret"), str):
                raise RuntimeError("ticket_response_invalid")
            expires_at = format_timestamp(now_ms() + _invite_ttl(ttl_seconds) * 1000)
            invite = remote_invite.encode({
                "project_id": runtime.project_id, "url": url, "adapter": host.adapter,
                "profile": chosen_profile, "installation_id": installation_id,
                "conversation_id": conversation, "role": "worker",
                "nickname": nickname.strip(), "secret": issued["secret"], "expires_at": expires_at,
            })
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
            raise typer.Exit(4) from exc
        print(json.dumps({
            "status": "invited", "invite": invite, "project_id": runtime.project_id,
            "adapter": host.adapter, "profile": chosen_profile, "role": "worker",
            "conversation_id": conversation, "url": url, "expires_at": expires_at,
            "expires_in_seconds": max(0, int(ttl_seconds)),
            # 这条命令**不写**机器级那条待接入记录（那是页面/中间层那条路的东西，用来回答
            # "聊天里被要求接入时该接哪个项目"）。远端不需要它：邀请内容里已经写全了项目、
            # 身份和角色 —— 但要说清楚，免得有人拿 `agent pending` 去找一张命令行发的邀请。
            "enrollment_record": "not_written",
            "next": (
                # 会话名是我们起的（只有 OpenCode 这一家）：不说清楚，那边起一个别的会话，
                # 身份对不上，第一次调用就只会得到 not_enrolled。
                f"让那边用这个名字开会话：opencode --session {conversation}（在代码副本目录里起），"
                "然后把 invite 里的整段内容发给远端，在那台机器上跑：tsunagou agent import <邀请>"
                if host.adapter == "opencode" else
                "把 invite 里的整段内容发给远端，在那台机器上跑：tsunagou agent import <邀请>；"
                "重启/重载那个宿主窗口后，在**这个会话**里说一句：接入 Tsunagou"
            ),
        }, ensure_ascii=False, sort_keys=True))

    @agent_app.command("import")
    def agent_import(
        invite: str = typer.Argument(...),
        workdir: Path | None = typer.Option(None, "--workdir"),  # noqa: B008
        daemon_url: str = typer.Option("", "--daemon-url"),
        machine: str = typer.Option("", "--machine"),
        copy: str = typer.Option("", "--copy"),
        baseline: str = typer.Option("", "--baseline"),
        state_dir: Path | None = typer.Option(None, "--state-dir"),  # noqa: B008
    ) -> None:
        """在这台机器上导入一张邀请：一条命令，然后在窗口里说一句话。

        只写**这台机器自己的**东西：身份、票、桥的启动配置（都放在本机私有目录里，
        不放进代码副本）；再把桥接进本机的宿主。项目本身仍在主机上 —— 这里不会、也不该
        长出第二份协作数据。

        ``--copy``：这台机器上的代码副本在哪（配合 ``--baseline`` 说清是哪条基线）。报了它，
        这台机器才能接**要动文件**的任务 —— 主机不会去读那个路径（读不到），只把位置记成账，
        工作区按"外部准备"指向它，证据记成自报。不报也能接入，但只能做不需要文件的活。

        这一步能自检的是"网络通不通、项目和票对不对"；"工具在不在、身份对不对"要等本机
        宿主真的加载一次 MCP，那一下由窗口里的 `context__project_read` 完成（失败码在接入
        Skill 里有人话对照）。
        """

        import tsunagou.platform.remote_invite as remote_invite
        from tsunagou.platform import host_registration
        from tsunagou.platform.bridge_files import (
            read_bridge_config,
            write_bridge_config,
            write_shared_bridge_config,
            write_ticket_file,
        )
        from tsunagou.platform.private_files import write_private_bytes

        try:
            data = remote_invite.decode(invite)
            remote_invite.check(data)
            host = host_registration.host_for(data["adapter"])
            if host is None:
                raise RuntimeError("unknown_host_adapter")
            copy_path = _reported_copy(copy)
            copy_baseline = _bounded_baseline(baseline)
            url = daemon_url.strip() or data["url"]
            if urllib.parse.urlsplit(url).hostname in {"127.0.0.1", "localhost", "::1"} and not daemon_url:
                raise RuntimeError("invite_address_is_loopback:用 --daemon-url 给出这台机器能连到主机的地址")
            workspace = (workdir or Path.cwd()).expanduser().resolve()
            destination = (state_dir or (Path.home() / ".tsunagou" / "remote"
                                         / f"{data['adapter']}-{conversation_key(data['conversation_id'])[:16]}")).resolve()
            health = _read_daemon_health(url)
            served = (health.get("runtime") or {}).get("project_ids") or []
            if health.get("status") != "ok" or data["project_id"] not in served:
                raise RuntimeError("invite_project_not_served_by_that_daemon")
            destination.mkdir(parents=True, exist_ok=True)
            write_private_bytes(destination / "host-identity.json", (json.dumps({
                "adapter": data["adapter"], "profile": data["profile"],
                "installation_id": data["installation_id"], "conversation_id": data["conversation_id"],
                # 远端自己报的机器名（不是主机猜的 IP）：宿主把桥接进本机之后，就靠它
                # 在名单里显示成"远端 · 机器名"。
                "machine": _machine_name(machine),
                # 这台机器上的代码副本（有才写）：主机据此把工作区以"外部准备"的形态指向它，
                # 于是远端也能接要动文件的任务（D192）。主机不读这个路径，只记账。
                **({"copy_path": copy_path} if copy_path else {}),
                **({"copy_baseline": copy_baseline} if copy_baseline else {}),
            }, sort_keys=True, indent=2) + "\n").encode("utf-8"))
            # 桥从哪儿找主机：路由式的宿主（Codex、深寻）**只看**这个状态目录里的 endpoint.json，
            # 它不读 `TSUNAGOU_HTTP_URL`；本机接入时这份文件是那台机器的 daemon 写的，远端当然没有，
            # 所以要在这里补一份 —— 内容就是邀请里那个地址（隧道场景下 `--daemon-url` 覆盖过的那个）。
            write_private_bytes(destination / "endpoint.json",
                                (json.dumps({"url": url, "advertised_url": url}, sort_keys=True) + "\n").encode("utf-8"))
            ticket_path = write_ticket_file(
                data["installation_id"], data["conversation_id"], data["secret"],
                destination / "ticket.json", data["role"],
            )
            extra_env = _write_remote_route(data, workspace=workspace, destination=destination, url=url)
            # 路由式的宿主（Codex、深寻）注册的是一份**共享**条目：会话级的事实（票、会话文件、状态
            # 目录、主机地址）全在路由文件里，由每次调用带的会话身份去取 —— 与本地 `agent connect`
            # 的形状一致，所以同一台机器上第二个远端会话不会把第一个覆盖掉。
            # OpenCode 没有路由，靠"每条会话一份配置"（它自己那份 entry 里带着票与会话文件）；
            # 它的项目号得**显式声明**，因为这台机器上没有项目的 `.tsunagou/project.json`。
            if data["adapter"] in {"codex", "deepseek"}:
                bridge_config = write_shared_bridge_config(
                    adapter=data["adapter"], installation_id=data["installation_id"],
                    output_dir=destination, routing_dir=extra_env.get("TSUNAGOU_ROUTING_DIR", ""),
                )
            else:
                bridge_config = write_bridge_config(
                    adapter=data["adapter"], mode="attach", installation_id=data["installation_id"],
                    output_dir=destination, ticket_path=ticket_path, daemon_url=url,
                    # 让桥只认主机这个地址：如果指到代码副本里的 .tsunagou/local，
                    # 副本里万一有一份旧的 endpoint.json，桥就会去连本机那个 daemon。
                    daemon_state_dir=str(destination), project_root=workspace,
                    extra_env={"TSUNAGOU_PROJECT_ID": data["project_id"]},
                )
            registration = _remote_registration(
                data["adapter"], profile=data["profile"], workspace=workspace,
                config=read_bridge_config(bridge_config),
            )
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
            raise typer.Exit(4) from exc
        print(json.dumps({
            "status": "imported", "project_id": data["project_id"], "adapter": data["adapter"],
            "role": data["role"], "conversation_id": data["conversation_id"],
            "url": url, "machine": _machine_name(machine),
            **({"copy_path": copy_path} if copy_path else {}),
            **({"copy_baseline": copy_baseline} if copy_baseline else {}),
            "workspace": str(workspace), "state_dir": str(destination),
            "host_registration": {"status": registration.status, "label": registration.label,
                                 **({"note": registration.note} if registration.note else {})},
            "next": "重启或重载这个宿主窗口，然后在里面说一句：接入 Tsunagou",
        }, ensure_ascii=False, sort_keys=True))

    def _invite_ttl(declared: int) -> int:
        """邀请能活多久：至少一分钟，最多一小时。

        上限不是技术限制，是那条红线：邀请是一次性的、短时效的机密。一张活一整天的邀请，
        等于把"票绑身份 + 用完即废"这套保护交回去。下限只是别让人发一张当场就过期的。
        """

        return max(60, min(int(declared), 3600))

    def _machine_name(declared: str) -> str:
        """这台机器叫什么：人给的，或它自己的名字。不猜 IP —— 走隧道时 IP 只会骗人。"""

        import socket as socket_module

        text = "".join(ch for ch in str(declared or "") if ch.isprintable() and ch not in "\r\n\t").strip()
        if not text:
            try:
                text = socket_module.gethostname().strip()
            except OSError:  # pragma: no cover - 拿不到主机名时如实说"未命名"
                text = ""
        return text[:64] or "未命名"

    def _reported_copy(declared: str) -> str:
        """这台机器上的代码副本在哪（`--copy`）：**必须真的在这台机器上存在**。

        这是"远端能不能干文件活"的唯一凭据，报一个不存在的路径只会让主机把工作区指向一个
        没有东西的地方 —— 所以这里先在本机确认它是目录，确认不了就拒绝。
        """

        text = str(declared or "").strip()
        if not text:
            return ""
        path = Path(text).expanduser()
        if not path.is_dir():
            raise RuntimeError("copy_path_not_found:--copy 要给这台机器上真实存在的目录")
        return str(path.resolve())

    def _bounded_baseline(declared: str) -> str:
        """这条副本对应哪条基线（分支或提交号）：只作显示与记账，去不了换行之类的东西。"""

        text = "".join(ch for ch in str(declared or "") if ch.isprintable() and ch not in "\r\n\t").strip()
        return text[:128]

    def _remote_registration(
        adapter: str, *, profile: str, workspace: Path, config: dict[str, Any],
    ) -> host_registration.Registration:
        """把这台机器的宿主配置好，好让桥被它加载起来。

        OpenCode / Codex 是"每个会话一份"：把它们自己的入口写进宿主配置。
        DeepSeek Harness 只有**整机一份**插件（每个会话靠路由目录找自己），所以这里做的是
        "确保那颗插件装着"，而不是灌进我们这份每会话配置 —— 那份配置交进去也只会被拒绝。
        """

        if adapter != "deepseek":
            return host_registration.register(
                adapter, profile=profile, project_root=workspace, bridge=config,
            )
        try:
            change = _prepare_deepseek_desktop()
        except RuntimeError as exc:
            change = host_registration.ConfigChange(host_registration.FAILED, note=str(exc))
        return host_registration.Registration(
            adapter="deepseek", label="DeepSeek Harness", status=change.status,
            name="tsunagou", files=tuple(str(path) for path in change.files),
            note=change.note or "插件是整机一份：装好之后，这个会话靠路由文件找到自己。",
        )

    def _write_remote_route(
        data: dict[str, Any], *, workspace: Path, destination: Path, url: str,
    ) -> dict[str, str]:
        """给"靠路由目录找自己"的宿主写一份远端路由（Codex、DeepSeek Harness）。

        这两个宿主的 tools/call 各自带一个会话身份，桥按键去路由目录里找自己那一条 ——
        所以远端导入时也得在这里写一条：项目在主机上，票和会话文件在本机私有目录里。

        写不出的宿主（OpenCode 靠 `_meta` 直接找，不用路由）返回空字典。
        """

        from tsunagou.application.onboarding import (
            codex_routing_directory,
            deepseek_routing_directory,
            write_codex_route,
            write_deepseek_route,
        )
        from tsunagou.platform.runtime_context import RuntimeContext

        adapter = str(data["adapter"])
        if adapter not in {"codex", "deepseek"}:
            return {}
        # 远端没有本机 daemon，"daemon 状态目录"就指自己的私有目录（里面没有 endpoint.json，
        # 于是桥只会用主机那个地址）；project_root 是代码副本 —— 项目本身仍在主机上。
        runtime = RuntimeContext(
            project_root=workspace, state_dir=destination, project_id=str(data["project_id"]),
            endpoint={"url": url, "project_id": str(data["project_id"])}, daemon_url=url, source_root=None,
        )
        if adapter == "codex":
            # 远端不参与"唤醒桌面 App"：那需要主机那台机器的管道，跨机器不成立（也不在本次范围内）。
            write_codex_route({
                "conversation_id": str(data["conversation_id"]),
                "installation_id": str(data["installation_id"]),
                "endpoint": "", "source_root": "", "host_generation": "",
            }, runtime, destination)
            return {"TSUNAGOU_ROUTING_DIR": str(codex_routing_directory())}
        write_deepseek_route(str(data["conversation_id"]), runtime, destination)
        return {"TSUNAGOU_ROUTING_DIR": str(deepseek_routing_directory())}

    @agent_app.command("whoami")
    def agent_whoami(
        adapter: str = typer.Option(..., "--adapter"),
    ) -> None:
        """报号：把"我这条会话在宿主眼里的编号"打出来，好让主机给我发邀请。

        Codex / DeepSeek Harness 的会话名只有宿主自己知道，主机签票前必须先拿到它。
        编号不是凭据（凭据是那张一次性票），但它是主机签票时要绑的另一半身份 —— 所以这个
        命令**必须在 Agent 自己的会话里跑**（编号来自宿主给的上下文）。

        OpenCode 不用报号：它的会话名由主机起（`ses_<名字>`）。
        """

        try:
            conversation_id = _host_conversation_id(adapter)
        except RuntimeError as exc:
            print(json.dumps({
                "status": "error", "error": str(exc),
                "note": "这个命令要在 Agent 自己的会话里跑：编号来自宿主给的上下文，在别处跑不出来。",
            }, ensure_ascii=False, sort_keys=True))
            raise typer.Exit(4) from exc
        print(json.dumps({
            "status": "ok", "adapter": adapter, "conversation_id": conversation_id,
            "next": "把这串编号发给主机上的人；他在「添加子 Agent → 位置＝网络」里填进去，"
                    "再把生成的邀请发回来，你在这台机器上 import 一次就完成接入。",
        }, ensure_ascii=False, sort_keys=True))

    @agent_app.command("pending")
    def agent_pending(
        adapter: str | None = typer.Option(None, "--adapter"),
    ) -> None:
        """谁在等我接入？—— 只读地看一眼机器上那条唯一的待接入记录。

        给"在宿主聊天里被要求接入 Tsunagou"的 Agent 用：它手上只有自己的会话 id 和工作
        目录，而工作目录经常不是协调仓库（项目可以协调好几个文件夹）。机器上唯一说得清
        "接哪个项目、什么角色"的就是这条记录 —— 它是用户在控制台点接入时写下的。

        没有记录时如实说没有，不要让 Agent 去猜、也不要让它自己建项目：接入是用户的决定。
        读这个命令不改任何状态；票和凭据都不在这里（控制台那条路没有票，另一条由聊天自己签）。
        """

        from tsunagou.platform.enrollment_store import EnrollmentStore

        try:
            store = EnrollmentStore()
            record = store.active_for(adapter) if adapter else store.active()
        except RuntimeError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}))
            raise typer.Exit(4) from exc
        if record is None:
            print(json.dumps({
                "status": "none",
                "note": "现在没有待接入的申请。请让用户在控制台为这个项目点一次接入"
                        "（或在控制台登记这个项目），不要在这里自己创建项目。",
            }, ensure_ascii=False, sort_keys=True))
            return
        print(json.dumps({
            "status": "pending",
            # 记录自己的状态：claimed/enrolled 表示已经有别的聊天认领或已经接入 —— 那是别人的，
            # 不要试图接手（Codex 的 agent join 会以 enrollment_claimed_by_another_chat 拒绝）。
            "state": record.get("status"),
            "adapter": record.get("adapter"),
            "role": record.get("requested_role"),
            "nickname": record.get("nickname"),
            "project_id": record.get("project_id"),
            "project_root": record.get("project_root"),
            "expires_in_seconds": max(0, int(float(record.get("expires_at") or 0) - time.time())),
        }, ensure_ascii=False, sort_keys=True))

    @agent_app.command("connect")
    def agent_connect(
        adapter: str = typer.Option(..., "--adapter"),
        role: str | None = typer.Option(None, "--role"),
        profile: str = typer.Option("current", "--profile"),
        mode: str = typer.Option("attach", "--mode"),
        output_dir: Path | None = typer.Option(None, "--output-dir"),  # noqa: B008
        request_file: Path | None = typer.Option(None, "--request-file"),  # noqa: B008
        register_host: bool = typer.Option(True, "--register-host/--no-register-host"),
    ) -> None:
        """Enroll the actual conversation and register its route in one user action."""
        from tsunagou.application.agent_connection import ConnectionFailure, connect_agent
        from tsunagou.hostwake.port import HostWakeError
        try:
            if mode not in {"attach", "launch"} or role not in {None, "worker", "main"}:
                raise typer.BadParameter("mode must be attach/launch; role must be worker/main")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", adapter) or not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
                raise typer.BadParameter("adapter/profile must contain only letters, digits, '_' or '-'")
            # 角色先定下来：有记录就以记录为准（用户的决定），与显式 --role 冲突直接拒绝。
            # 放在 connect_agent 之前，失败时不留下任何桥材料。
            effective_role = _role_for_connect(adapter, role)
            connected = connect_agent(
                _connection_operations(adapter), adapter=adapter, role=effective_role, profile=profile, mode=mode,
                output_dir=output_dir, request_file=request_file, register_host=register_host,
            )
            print(json.dumps(connected, sort_keys=True))
        except typer.BadParameter as exc:
            print(json.dumps({"status": "error", "error": str(exc)}))
            raise typer.Exit(2) from exc
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired, HostWakeError) as exc:
            code = exc.code if isinstance(exc, HostWakeError) else str(exc) if isinstance(exc, RuntimeError) else "onboarding_failed"
            print(json.dumps({"status": "error", "error": code,
                              **(exc.observations if isinstance(exc, ConnectionFailure) else {})}))
            raise typer.Exit(4) from exc

    @agent_app.command("join")
    def agent_join() -> None:
        """Join the console's pending Agent as this real Codex Desktop conversation."""
        from tsunagou.application.agent_connection import connect_agent
        from tsunagou.application.onboarding import (
            bind_console_enrollment,
            prepare_codex_request,
            read_codex_request,
            validate_codex_route,
        )
        from tsunagou.hostwake.port import HostWakeError
        from tsunagou.platform.enrollment_store import EnrollmentStore
        from tsunagou.platform.runtime_context import read_object

        store = EnrollmentStore()
        claimed: dict[str, Any] | None = None
        selection = None
        thread_id = os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID")
        try:
            if not thread_id:
                raise RuntimeError("desktop_context_missing:run_agent_join_inside_the_codex_conversation")
            intent = store.current(thread_id)
            root = Path(intent["project_root"]).resolve()
            previous_root = _selected_project_root.get()
            if previous_root is not None and previous_root.resolve() != root:
                raise RuntimeError("onboarding_project_mismatch")
            selection = _selected_project_root.set(root)
            runtime = _runtime_context()
            manifest = read_object(root / ".tsunagou/project.json")
            if runtime.project_id != intent["project_id"] or manifest.get("project_id") != intent["project_id"]:
                raise RuntimeError("onboarding_project_mismatch")
            request_file = prepare_codex_request(runtime)
            request = read_codex_request(request_file, runtime)
            if request["conversation_id"] != thread_id:
                raise RuntimeError("desktop_conversation_mismatch")
            validate_codex_route(request, runtime)
            claimed = store.claim(intent["enrollment_id"], thread_id, expected_revision=int(intent["revision"]))
            connected = connect_agent(
                _connection_operations(), adapter="codex", role=claimed["requested_role"],
                profile="current", request_file=request_file,
            )
            if (connected.get("project_id") != intent["project_id"]
                    or connected.get("role") != intent["requested_role"]):
                raise RuntimeError("onboarding_result_mismatch")
            registration = str(connected.get("host_registration") or "")
            if not registration.startswith(("registered:", "unchanged:")):
                raise RuntimeError("codex_mcp_registration_incomplete")
            bind_console_enrollment(request, claimed)
            store.mark_enrolled(claimed["enrollment_id"], thread_id, agent_id=connected["agent_id"])
            print(json.dumps({**connected, "enrollment_id": claimed["enrollment_id"],
                              "project_root": str(root)}, ensure_ascii=False, sort_keys=True))
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired, HostWakeError) as exc:
            code = exc.code if isinstance(exc, HostWakeError) else str(exc) if isinstance(exc, RuntimeError) else "onboarding_failed"
            if claimed is not None and thread_id:
                try:
                    store.fail(claimed["enrollment_id"], thread_id, code)
                except (RuntimeError, OSError, ValueError):
                    pass  # Preserve the actual enrollment error.
            print(json.dumps({"status": "error", "error": code}, ensure_ascii=False))
            raise typer.Exit(4) from exc
        finally:
            if selection is not None:
                _selected_project_root.reset(selection)

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
            # 人明确写下的端口被占用时不回退（隧道/防火墙是对着它配的）。
            settings.port_explicit = True
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
                if record.get("port_fallback"):
                    print(
                        f"默认端口 {record.get('port_requested')} 被占用，改用 {record.get('port')}"
                        "；要收藏的是上面这个地址。"
                    )

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
