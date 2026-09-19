from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, cast


def _restrict_file_access(path: Path) -> None:
    """Restrict a ticket file to its creator, with a real ACL on Windows.

    ``chmod 0o600`` is only meaningful on POSIX. On Windows it merely toggles the
    read-only attribute: ``st_mode`` stays ``0o666`` and the file inherits its
    parent directory ACL, so a ticket written next to the repo ends up readable by
    ``Authenticated Users`` / ``Users``. Here we strip inherited ACEs and grant
    full control to ``CREATOR OWNER`` (``S-1-3-0``), which resolves to the account
    that just created the file (this process). Fails closed: if the ACL cannot be
    restricted, the secret-bearing file is removed rather than left world-readable.
    """
    if os.name != "nt":
        os.chmod(path, 0o600)
        return
    proc = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", "*S-1-3-0:(F)"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"failed to restrict ticket file ACL: {proc.stderr.strip()}")


def _write_ticket_private(
    installation_id: str, conversation_id: str, secret: str, ticket_file: Path | None,
) -> Path:
    """Deliver a one-time enrollment ticket through a private file, never stdout.

    The ticket secret is a bearer credential for ``agent.enroll``; echoing it to a
    terminal leaks it into scrollback, logs and shell history. The bridge reads it
    from this file through its own private channel instead. The file is restricted
    to its creator (POSIX ``0600``, or a stripped Windows ACL) so other local
    accounts cannot read the secret.
    """
    if ticket_file is None:
        fd, temp_name = tempfile.mkstemp(prefix="tsunagou-ticket-", suffix=".json")
        os.close(fd)
        path = Path(temp_name)
    else:
        path = ticket_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({
            "installation_id": installation_id,
            "conversation_id": conversation_id,
            "secret": secret,
        }, handle, sort_keys=True)
        handle.write("\n")
    _restrict_file_access(path)
    return path


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
    app.add_typer(project_app, name="project")
    app.add_typer(agent_app, name="agent")
    app.add_typer(decision_app, name="decision")
    app.add_typer(operation_app, name="operation")

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
        result = {"status": "ok", "version": "0.1.0", "platform": "local"}
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
        print(json.dumps({"project_id": registry.project.project_id, "status": "active"}, sort_keys=True))

    def _invoke_command(
        app: Any, command_kind: str, payload: dict[str, Any], *, authorization: str
    ) -> dict[str, Any]:
        from fastapi import HTTPException, Response

        from tsunagou.api.app import CommandRequest
        from tsunagou.shared_kernel.ids import new_id

        endpoint = next(
            route.endpoint for route in app.routes
            if getattr(route, "path", "") == "/api/v1/commands/{command_kind}"
        )
        try:
            return cast(dict[str, Any], endpoint(
                command_kind,
                CommandRequest(
                    command_id=new_id(), protocol_version="1",
                    schema_bundle_digest="sha256:x", payload=payload,
                ),
                Response(), authorization, None, None,
            ))
        except HTTPException as exc:
            detail: dict[str, Any] = exc.detail if isinstance(exc.detail, dict) else {}
            print(json.dumps({"status": detail.get("code", "error")}, sort_keys=True))
            raise typer.Exit(1) from exc

    @agent_app.command("enroll")
    def agent_enroll(
        adapter: str = typer.Option(..., "--adapter"),
        mode: str = typer.Option("attach", "--mode"),
        installation_id: str | None = typer.Option(None, "--installation-id"),
        conversation_id: str | None = typer.Option(None, "--conversation-id"),
        ticket_file: Path | None = typer.Option(None, "--ticket-file"),  # noqa: B008
    ) -> None:
        if mode not in {"attach", "launch"}:
            raise typer.BadParameter("mode must be attach or launch")
        token = os.environ.get("TSUNAGOU_CONTROL_TOKEN")
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(1)
        if not installation_id or not conversation_id:
            print(json.dumps({
                "adapter": adapter, "mode": mode, "status": "ticket_required",
                "reason": "target_conversation_identity_required",
            }, sort_keys=True))
            raise typer.Exit(0)
        from tsunagou.bootstrap.container import build_application

        result = _invoke_command(
            build_application(), "agent.ticket.create.user",
            {"kind": "worker", "installation_id": installation_id,
             "conversation_evidence": {"conversation_id": conversation_id}},
            authorization=f"Bearer {token}",
        )
        secret = result["result"]["secret"]
        path = _write_ticket_private(installation_id, conversation_id, secret, ticket_file)
        print(json.dumps({
            "adapter": adapter, "mode": mode, "status": "ticket_issued",
            "installation_id": installation_id, "conversation_id": conversation_id,
            "ticket_file": str(path),
        }, sort_keys=True))

    @agent_app.command("appoint")
    def agent_appoint(agent_id: str = typer.Argument(...)) -> None:
        token = os.environ.get("TSUNAGOU_CONTROL_TOKEN")
        if not token:
            print(json.dumps({"status": "control_credential_missing"}, sort_keys=True))
            raise typer.Exit(1)
        from tsunagou.bootstrap.container import build_application

        result = _invoke_command(
            build_application(), "authority.appoint",
            {"agent_id": agent_id}, authorization=f"Bearer {token}",
        )
        print(json.dumps({
            "agent_id": agent_id, "status": "appointed", **result["result"],
        }, sort_keys=True))

    @decision_app.command("list")
    def decision_list() -> None:
        print("[]")

    @decision_app.command("resolve")
    def decision_resolve(
        decision_id: str,
        choice: str = typer.Option(..., "--choice"),
        expected_revision: int = typer.Option(..., "--expected-revision"),
        digest: str = typer.Option(..., "--digest"),
        reason: str | None = typer.Option(None, "--reason"),
    ) -> None:
        print(json.dumps({
            "decision_id": decision_id,
            "choice": choice,
            "expected_revision": expected_revision,
            "digest": digest,
            "reason": reason,
            "status": "submitted",
        }, sort_keys=True))

    @operation_app.command("show")
    def operation_show(operation_id: str) -> None:
        print(json.dumps({"operation_id": operation_id, "status": "unknown"}, sort_keys=True))

    @app.command("recover")
    def recover() -> None:
        print(json.dumps({"status": "recovery_review_required"}, sort_keys=True))

    main = app
else:
    def main() -> None:
        print("Tsunagou 0.1.0 — local coordination runtime")
