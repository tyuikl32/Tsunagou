"""Application assembly; domain services are added by their owning tasks."""

from __future__ import annotations

import base64
import json
import os
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from tsunagou.api.app import create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import build_handlers
from tsunagou.application.workflows.lifecycle import LifecycleService
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.evaluation import AuditProjector
from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.modules.workspaces import WorkspaceService
from tsunagou.platform.checkpoints import CheckpointStore
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.platform.maintenance import RuntimeMaintenance
from tsunagou.platform.state import ServiceStateRuntime

_REGISTRY_RESOURCE = files("tsunagou.protocol_data").joinpath("registry", "commands.json")


def _registry_path() -> Path:
    """Return a package resource path without depending on the checkout cwd."""
    return Path(str(_REGISTRY_RESOURCE))


def build_application() -> FastAPI:
    """Assemble the real application with authority, handlers and control credentials.

    Credentials come only from the environment, never from request headers or hardcoded
    defaults. When unset, the application stays fail-closed for every business command:

    - ``TSUNAGOU_CONTROL_TOKEN`` is the private user-control bearer credential.
    - ``TSUNAGOU_STATE_DIR`` points at the durable authority state directory; without it,
      authority state is in-memory only and does not survive a restart.
    """
    state_dir = os.environ.get("TSUNAGOU_STATE_DIR")
    state_path = Path(state_dir) if state_dir else None
    authority = AuthorityService(None)
    tasks = TaskService()
    cognition = CognitionService()
    messages = MessageStore(None)
    resources = ResourceService()
    workspaces = WorkspaceService()
    project_id = _project_id()
    project_registry = None
    project_root = os.environ.get("TSUNAGOU_PROJECT_ROOT")
    if project_root:
        project_registry = ProjectRegistry(project_root)
    lifecycle = (
        LifecycleService(registry=project_registry, authority=authority)
        if project_registry is not None and project_registry.project is not None else None
    )
    database = None
    state_runtime = None
    checkpoint_store = None
    maintenance = None
    schema_bundle_digest = ""
    try:
        schema_bundle_digest = json.loads(_REGISTRY_RESOURCE.read_text(encoding="utf-8"))["schema_bundle_digest"]
    except (OSError, json.JSONDecodeError, KeyError):
        schema_bundle_digest = ""
    if state_path is not None:
        database = ProjectDatabase(state_path / "state.sqlite3", project_id=project_id or "local-project")
        checkpoint_store = CheckpointStore(state_path.parent / "checkpoints")
        database.acquire_process_lock()
        database.rotate_runtime_epoch()
        state_runtime = ServiceStateRuntime(
            authority=authority, tasks=tasks, cognition=cognition, messages=messages,
            database=database, resources=resources, workspaces=workspaces, lifecycle=lifecycle,
        )
        state_runtime.invalidate_execution_state()
        with database.transaction("runtime-recovery") as uow:
            state_runtime.persist(uow, actor_ref="runtime", command_kind="runtime.recovery")
        maintenance = RuntimeMaintenance(
            database=database, state_runtime=state_runtime, resources=resources,
            tasks=tasks, authority=authority,
            interval_seconds=float(os.environ.get("TSUNAGOU_MAINTENANCE_INTERVAL", "1")),
        )
    dispatcher = CommandDispatcher(
        _registry_path(), database=database, state_runtime=state_runtime,
    )
    for command_kind, handler in build_handlers(
        authority=authority, tasks=tasks, cognition=cognition, messages=messages,
        resources=resources, workspaces=workspaces, lifecycle=lifecycle,
        project_id=project_id, strict_runtime=database is not None,
        database=database, state_runtime=state_runtime,
        checkpoint_store=checkpoint_store, schema_bundle_digest=schema_bundle_digest,
        project_root=project_root, artifact_root=str(state_path.parent / "artifacts") if state_path else None,
        project_registry=project_registry,
    ).items():
        dispatcher.register(command_kind, handler)
    authenticator = LocalCommandAuthenticator(
        authority=authority, control_token=os.environ.get("TSUNAGOU_CONTROL_TOKEN")
    )
    application = create_app(
        dispatcher, authenticator=authenticator,
        query_provider=_query_provider(
            project_id=project_id, registry=state_runtime, database=database,
            authority=authority, tasks=tasks, cognition=cognition, messages=messages,
            resources=resources, workspaces=workspaces, lifecycle=lifecycle,
            project_registry=project_registry,
            checkpoint_store=checkpoint_store,
        ),
    )
    application.state.project_database = database
    application.state.state_runtime = state_runtime
    application.state.checkpoint_store = checkpoint_store
    application.state.maintenance = maintenance
    if maintenance is not None:
        @application.on_event("startup")
        def start_runtime_maintenance() -> None:
            maintenance.start()

        @application.on_event("shutdown")
        def stop_runtime_maintenance() -> None:
            maintenance.stop()
    return application


def _query_provider(
    *, project_id: str | None, registry: ServiceStateRuntime | None,
    database: ProjectDatabase | None, authority: AuthorityService, tasks: TaskService,
    cognition: CognitionService, messages: MessageStore, resources: ResourceService,
    workspaces: WorkspaceService, lifecycle: LifecycleService | None,
    project_registry: ProjectRegistry | None,
    checkpoint_store: CheckpointStore | None,
) -> Any:
    def query(kind: str, requested_project_id: str) -> dict[str, Any]:
        if kind == "artifact":
            if checkpoint_store is None:
                raise KeyError("artifact_not_found")
            artifact_ref = requested_project_id
            if not artifact_ref.startswith("sha256:"):
                raise KeyError("artifact_not_found")
            artifact_path = checkpoint_store.root.parent / "artifacts" / (
                artifact_ref.replace(":", "_") + ".patch"
            )
            if not artifact_path.is_file():
                raise KeyError("artifact_not_found")
            return {
                "digest": artifact_ref,
                "content_base64": base64.b64encode(artifact_path.read_bytes()).decode("ascii"),
            }
        if project_id is not None and requested_project_id and requested_project_id != project_id:
            raise KeyError("project_not_found")
        if kind == "roots":
            if project_registry is None or project_registry.project is None:
                raise KeyError("project_not_found")
            return {
                "project_id": requested_project_id or project_registry.project.project_id,
                "items": [
                    {
                        **descriptor,
                        "binding": {
                            key: value for key, value in project_registry.local_bindings.get(root_id, {}).items()
                            if key != "absolute_path"
                        },
                    }
                    for root_id, descriptor in project_registry.project.roots.items()
                ],
            }
        if kind == "repositories":
            if project_registry is None or project_registry.project is None:
                raise KeyError("project_not_found")
            return {
                "project_id": requested_project_id or project_registry.project.project_id,
                "items": list(project_registry.project.repositories.values()),
            }
        if kind == "tasks":
            return {
                "project_id": requested_project_id,
                "items": [
                    {
                        "task_id": task.task_id, "title": task.title,
                        "objective": task.objective, "status": task.status,
                        "revision": task.revision, "current_attempt_id": task.current_attempt_id,
                    }
                    for task in tasks.tasks.values()
                ],
            }
        if kind == "attempts":
            return {
                "project_id": requested_project_id,
                "items": [
                    {
                        "attempt_id": attempt.attempt_id, "task_id": attempt.task_id,
                        "owner_agent_id": attempt.owner_agent_id, "status": attempt.status,
                        "execution_epoch": attempt.execution_epoch, "revision": attempt.revision,
                    }
                    for attempt in tasks.attempts.values()
                ],
            }
        if kind == "results":
            return {
                "project_id": requested_project_id,
                "items": [
                    {
                        "result_id": result.result_id, "task_id": result.task_id,
                        "attempt_id": result.attempt_id, "digest": result.digest,
                        "submitted_by": result.submitted_by,
                        "workspace_result_ref": result.payload.get("workspace_result_ref"),
                    }
                    for result in tasks.results.values()
                ],
            }
        if kind == "jobs" and database is not None:
            with database._connect() as conn:
                rows = conn.execute(
                    """SELECT id,operation_id,handler_kind,status,attempt_count,
                              max_attempts,lease_owner,lease_epoch,lease_until,
                              available_at,updated_at
                       FROM jobs WHERE project_id=? ORDER BY created_at,id""",
                    (database.project_id,),
                ).fetchall()
            return {
                "project_id": requested_project_id,
                "items": [dict(row) for row in rows],
            }
        if kind == "contracts":
            return {
                "items": [
                    {"proposal_id": item.proposal_id, "digest": item.digest, "status": item.status}
                    for item in cognition.proposals.values()
                ],
            }
        if kind == "cognition":
            return {
                "reports": [
                    {"report_id": report.report_id, "task_id": report.task_id,
                     "attempt_id": report.attempt_id, "actor_agent_id": report.actor_agent_id,
                     "digest": report.digest, "claims": [
                         {"subject_key": claim.subject_key, "claim_type": claim.claim_type,
                          "equality_key": claim.equality_key, "value": claim.value}
                         for claim in report.claims
                     ]}
                    for report in cognition.reports.values()
                ],
                "discrepancies": [
                    {"discrepancy_id": item.discrepancy_id, "subject_key": item.subject_key,
                     "severity": item.severity, "status": item.status,
                     "claim_ids": list(item.claim_ids), "input_digest": item.input_digest}
                    for item in cognition.discrepancies.values()
                ],
                "contracts": [
                    {"proposal_id": proposal.proposal_id, "digest": proposal.digest,
                     "status": proposal.status, "participants": list(proposal.participants),
                     "required_slots": list(proposal.required_slots)}
                    for proposal in cognition.proposals.values()
                ],
            }
        if kind == "agents":
            return {
                "items": [
                    {"agent_id": item.agent_id, "status": item.status, "role": item.role}
                    for item in authority.agents.values()
                ],
                "main_agent_id": authority.main_agent_id,
            }
        if kind == "messages":
            return {
                "items": [
                    {
                        "message_id": item.message_id, "sender_agent_id": item.sender_agent_id,
                        "recipient_agent_id": item.recipient_agent_id, "kind": item.kind,
                        "subject_ref": item.subject_ref, "summary": item.summary,
                    }
                    for item in messages.messages.values()
                ],
            }
        if kind == "resources":
            return {
                "items": [
                    {"lease_set_id": lease.lease_set_id, "attempt_id": lease.attempt_id,
                     "status": lease.status, "expires_at": lease.expires_at,
                     "resources": [request.key.canonical for request in lease.resources]}
                    for lease in resources.lease_sets.values()
                ],
            }
        if kind == "workspaces":
            return {
                "items": [
                    {"workspace_id": workspace.workspace_id, "attempt_id": workspace.attempt_id,
                     "driver_kind": workspace.driver_kind, "status": workspace.status,
                     "baseline_manifest_id": workspace.baseline_manifest_id,
                     "result_manifest_id": workspace.result_manifest_id,
                     **({"result": {
                         "changed_paths": list(workspaces.results[workspace.result_manifest_id].changed_paths),
                         "patch_artifact_ref": workspaces.results[workspace.result_manifest_id].patch_artifact_ref,
                         "baseline_conflict": workspaces.results[workspace.result_manifest_id].baseline_conflict,
                     }} if workspace.result_manifest_id in workspaces.results else {})}
                    for workspace in workspaces.workspaces.values()
                ],
            }
        if kind == "audit":
            if database is None:
                return {"items": [], "next_cursor": None}
            projector = AuditProjector()
            items = []
            for event in reversed(database.list_events(limit=200)):
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                view = projector.project({
                    "event_id": event["event_id"], "event_seq": event["event_seq"],
                    "actor_ref": event["actor_ref"], "action": event["event_type"],
                    "subject_ref": event["aggregate_ref"],
                    "outcome": payload.get("outcome", "committed"),
                    "reason_code": payload.get("reason_code"),
                    "evidence_refs": payload.get("evidence_refs", []),
                }, can_read_subject=True)
                items.append({
                    "source_event_id": view.source_event_id,
                    "source_event_seq": view.source_event_seq,
                    "actor_ref": view.actor_ref, "action": view.action,
                    "subject_ref": view.subject_ref, "outcome": view.outcome,
                    "reason_code": view.reason_code,
                    "evidence_refs": list(view.evidence_refs),
                    "projection_version": view.projection_version,
                })
            return {"project_id": requested_project_id, "items": items, "next_cursor": None}
        if kind == "decisions" and lifecycle is not None:
            return {
                "items": [
                    {"decision_id": decision.decision_id, "kind": decision.kind,
                     "subject_ref": decision.subject_ref, "expected_revision": decision.expected_revision,
                     "input_digest": decision.input_digest, "status": decision.status,
                     "decision": decision.decision, "reason": decision.reason}
                    for decision in lifecycle.decisions.values()
                ],
            }
        if kind == "operations" and database is not None:
            with database._connect() as conn:
                rows = conn.execute(
                    "SELECT id,kind,status,error_code,revision,created_at,updated_at FROM operations "
                    "WHERE project_id=? ORDER BY created_at", (database.project_id,),
                ).fetchall()
            return {"items": [dict(row) for row in rows]}
        if kind == "checkpoints" and checkpoint_store is not None:
            pointer = checkpoint_store.pointer
            current = json.loads(pointer.read_text(encoding="utf-8")) if pointer.is_file() else None
            return {"current": current, "items": [current] if current else []}
        if kind == "decisions":
            # Decision persistence is introduced with the lifecycle task. Keep
            # this endpoint explicit so a CLI query never fabricates success.
            return {"items": []}
        if kind == "recovery":
            return {
                "project_id": project_id,
                "status": "ready",
                "runtime_epoch": database.runtime_epoch if database is not None else None,
            }
        return {"items": []}
    return query


def _project_id() -> str | None:
    """Resolve a project id from the environment or the coordination repo."""
    configured = os.environ.get("TSUNAGOU_PROJECT_ID")
    if configured:
        return configured
    project_root = os.environ.get("TSUNAGOU_PROJECT_ROOT")
    if not project_root:
        return None
    project_file = Path(project_root) / ".tsunagou" / "project.json"
    if not project_file.is_file():
        return None
    try:
        raw = json.loads(project_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = raw.get("project_id")
    return value if isinstance(value, str) and value else None
