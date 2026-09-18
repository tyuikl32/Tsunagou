from __future__ import annotations

import json
from pathlib import Path

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

    @agent_app.command("enroll")
    def agent_enroll(
        adapter: str = typer.Option(..., "--adapter"),
        mode: str = typer.Option("attach", "--mode"),
    ) -> None:
        if mode not in {"attach", "launch"}:
            raise typer.BadParameter("mode must be attach or launch")
        print(json.dumps({"adapter": adapter, "mode": mode, "status": "ticket_required"}, sort_keys=True))

    @agent_app.command("appoint")
    def agent_appoint(agent_id: str = typer.Argument(...)) -> None:
        print(json.dumps({"agent_id": agent_id, "status": "user_decision_required"}, sort_keys=True))

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
