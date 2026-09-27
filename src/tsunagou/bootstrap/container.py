"""Application assembly; domain services are added by their owning tasks."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import sqlite3
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from tsunagou.api.app import create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import build_handlers
from tsunagou.application.workflows.lifecycle import LifecycleService
from tsunagou.hostwake import (
    DesktopAttachProvider,
    HostWakeProviderRegistry,
    ManagedCodexProvider,
    PrivateBindingStore,
    WakeDispatcher,
)
from tsunagou.interfaces.runtime import CommandDispatcher, PrincipalContext
from tsunagou.modules.artifacts import ArtifactService
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.coordination import CoordinationService
from tsunagou.modules.evaluation import AuditProjector
from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.modules.workspaces import WorkspaceService
from tsunagou.platform.audit_cursor import AuditCursorCodec
from tsunagou.platform.checkpoint_worker import CheckpointWorker
from tsunagou.platform.checkpoints import CheckpointStore
from tsunagou.platform.db.sqlite import ProjectDatabase, ProjectLock
from tsunagou.platform.maintenance import RuntimeMaintenance
from tsunagou.platform.state import ServiceStateRuntime
from tsunagou.shared_kernel.time import format_timestamp, parse_timestamp

_REGISTRY_RESOURCE = files("tsunagou.protocol_data").joinpath("registry", "commands.json")


def _registry_path() -> Path:
    """Return a package resource path without depending on the checkout cwd."""
    return Path(str(_REGISTRY_RESOURCE))


def build_application() -> FastAPI:
    state_dir = os.environ.get("TSUNAGOU_STATE_DIR")
    project_root = os.environ.get("TSUNAGOU_PROJECT_ROOT")
    if state_dir and project_root:
        shared = Path(project_root) / ".tsunagou"
        with ProjectLock(shared / "bootstrap.lock"):
            if not (Path(state_dir) / "state.sqlite3").exists() and (shared / "checkpoints" / "current.json").is_file():
                raise RuntimeError("checkpoint_restore_required")
            return _build_application()
    return _build_application()


def _build_application() -> FastAPI:
    """Assemble the real application with authority, handlers and control credentials.

    Credentials come only from the environment, never from request headers or hardcoded
    defaults. When unset, the application stays fail-closed for every business command:

    - ``TSUNAGOU_CONTROL_TOKEN`` is the private user-control bearer credential.
    - ``TSUNAGOU_STATE_DIR`` points at the durable authority state directory; without it,
      authority state is in-memory only and does not survive a restart.
    """
    state_dir = os.environ.get("TSUNAGOU_STATE_DIR")
    state_path = Path(state_dir) if state_dir else None
    if state_path is not None:
        from tsunagou.platform.credential_migration import assert_credential_migration_ready

        assert_credential_migration_ready(state_path)
    authority = AuthorityService(None)
    tasks = TaskService()
    cognition = CognitionService()
    coordination = CoordinationService()
    messages = MessageStore(None)
    resources = ResourceService()
    workspaces = WorkspaceService()
    artifacts = ArtifactService(state_path / "artifacts") if state_path else None
    project_id = _project_id()
    project_registry = None
    project_root = os.environ.get("TSUNAGOU_PROJECT_ROOT")
    if project_root:
        durable = _durable_project_snapshot(state_path)
        project_registry = ProjectRegistry(project_root, load_files=durable is None)
        if durable is not None:
            project_registry.restore_local_state(durable["project"], durable.get("bindings", {}))
    lifecycle = (
        LifecycleService(registry=project_registry, authority=authority)
        if project_registry is not None and project_registry.project is not None else None
    )
    database = None
    state_runtime = None
    checkpoint_store = None
    checkpoint_worker = None
    maintenance = None
    wake_dispatcher = None
    hostwake_provider = None
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
            coordination=coordination,
            project_registry=project_registry,
            artifacts=artifacts,
        )
        if project_registry is not None:
            project_registry.managed_by_database = True
        recovery_before = state_runtime.capture()
        state_runtime.invalidate_execution_state()
        with database.transaction("runtime-recovery") as uow:
            state_runtime.persist(uow, actor_ref="runtime", command_kind="runtime.recovery", before=recovery_before)
        checkpoint_worker = CheckpointWorker(database, checkpoint_store, state_runtime, schema_bundle_digest)
        if project_registry is not None and project_registry.project is not None:
            checkpoint_worker.request_genesis()
        checkpoint_worker.run_once()
        try:
            checkpoint_worker.reconcile_project_projection()
        except OSError:
            pass
        maintenance = RuntimeMaintenance(
            database=database, state_runtime=state_runtime, resources=resources,
            tasks=tasks, authority=authority, coordination=coordination,
            interval_seconds=float(os.environ.get("TSUNAGOU_MAINTENANCE_INTERVAL", "1")),
            checkpoint_worker=checkpoint_worker,
        )
        if os.environ.get("TSUNAGOU_HOST_WAKE", "").casefold() == "managed":
            binding_store = PrivateBindingStore(state_path / "host-bindings.json")
            hostwake_provider = HostWakeProviderRegistry(
                ManagedCodexProvider(binding_store),
                DesktopAttachProvider(binding_store),
            )
            wake_dispatcher = WakeDispatcher(
                hostwake_provider,
                attempts_path=state_path / "host-wake-attempts.json",
            )
    dispatcher = CommandDispatcher(
        _registry_path(), database=database, state_runtime=state_runtime,
        checkpoint_worker=checkpoint_worker,
    )
    for command_kind, handler in build_handlers(
        authority=authority, tasks=tasks, cognition=cognition, messages=messages,
        resources=resources, workspaces=workspaces, lifecycle=lifecycle,
        coordination=coordination,
        project_id=project_id, strict_runtime=database is not None,
        database=database, state_runtime=state_runtime,
        checkpoint_store=checkpoint_store, schema_bundle_digest=schema_bundle_digest,
        checkpoint_worker=checkpoint_worker,
        project_root=project_root, artifact_root=str(state_path.parent / "artifacts") if state_path else None,
        project_registry=project_registry,
        artifacts=artifacts,
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
            coordination=coordination,
            project_registry=project_registry,
            checkpoint_store=checkpoint_store,
            artifacts=artifacts,
        ),
        wake_dispatcher=wake_dispatcher,
        hostwake_provider=hostwake_provider,
    )
    application.state.project_database = database
    application.state.state_runtime = state_runtime
    application.state.checkpoint_store = checkpoint_store
    application.state.checkpoint_worker = checkpoint_worker
    application.state.maintenance = maintenance
    application.state.hostwake_provider = hostwake_provider
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
    coordination: CoordinationService,
    artifacts: ArtifactService | None = None,
) -> Any:
    cursor_codec = AuditCursorCodec()

    def can_read_event(event: dict[str, Any], viewer: PrincipalContext) -> bool:
        payload = event.get("payload") or {}
        refs = [event.get("subject_ref") or event.get("aggregate_ref", "")]
        refs.extend(change.get("subject_ref", "") for change in payload.get("changes", []))
        # Migrated rows can retain references in the old payload location.
        # Authorize the exact fallback that the public projection will emit.
        evidence = event.get("evidence_refs") or payload.get("evidence_refs", [])
        refs.extend(ref for ref in evidence if isinstance(ref, str))
        private_refs = []
        for ref in refs:
            if ref in messages.messages:
                private_refs.append(f"message/{ref}")
            elif ref in messages.obligations:
                private_refs.append(f"obligation/{ref}")
            elif ref.startswith(("message/", "delivery/", "obligation/")):
                private_refs.append(ref)
            elif ref.startswith(("message:", "delivery:", "obligation:")):
                private_refs.append(ref.replace(":", "/", 1))
        # Old message events used only a project aggregate, so their audience
        # cannot be proved. Fail closed rather than infer a recipient from text.
        action = str(event["event_type"]).removeprefix("command.")
        if not private_refs and action.startswith(("message.", "inbox.")):
            return False
        for ref in private_refs:
            kind, identity = ref.split("/", 1)
            if kind == "obligation":
                obligation = messages.obligations.get(identity)
                if obligation is None:
                    return False
                identity = obligation.message_id
            message = messages.messages.get(identity)
            if message is None or viewer.principal_id not in {message.sender_agent_id, message.recipient_agent_id}:
                return False
        return True

    def query(
        kind: str,
        requested_project_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        from_timestamp: str | None = None,
        to_timestamp: str | None = None,
        actor_ref: str | None = None,
        subject_ref: str | None = None,
        viewer: PrincipalContext | None = None,
    ) -> dict[str, Any]:
        if kind == "artifact":
            if artifacts is None or viewer is None:
                raise PermissionError("artifact_authentication_required")
            artifact_ref = requested_project_id
            reference = artifacts.refs.get(artifact_ref)
            if reference is None or reference.project_id != project_id or (
                registry and reference.lineage_id != registry.lineage_id
            ):
                raise KeyError("artifact_not_found")
            matching = [
                result for result in workspaces.results.values()
                if result.patch_artifact_ref == artifact_ref
            ]
            if not matching:
                # A content hash is not an authorization reference.  Only a
                # workspace result that names this artifact can expose it.
                raise KeyError("artifact_not_found")
            authorised = False
            selected = None
            for result in matching:
                attempt = tasks.attempts.get(result.attempt_id)
                owners = {result.submitted_by}
                if attempt is not None:
                    owners.add(attempt.owner_agent_id)
                if viewer.kind == "U" or viewer.principal_id == authority.main_agent_id or viewer.principal_id in owners:
                    authorised = True
                    selected = result
                    break
            if not authorised or selected is None:
                raise PermissionError("artifact_access_denied")
            if (reference.domain_ref != f"workspace/{selected.workspace_id}"
                    or reference.scope_digest != selected.scope_digest
                    or reference.owner_actor != selected.submitted_by):
                raise PermissionError("artifact_access_denied")
            content = artifacts.read(artifact_ref, actor=viewer.principal_id, domain_authorized=lambda *_: True)
            return {
                "artifact_ref": artifact_ref, "digest": "sha256:" + reference.digest,
                "content_base64": base64.b64encode(content).decode("ascii"),
                "workspace_result_ref": selected.manifest_id,
                "scope_digest": selected.scope_digest,
                "domain_ref": selected.patch_artifact_domain,
                "owner_actor": selected.patch_artifact_owner,
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
        if kind in {"coordination", "assignments", "wake_attempts", "events"}:
            plans = [
                {
                    "plan_id": plan.plan_id, "objective": plan.objective,
                    "main_agent_id": plan.main_agent_id, "status": plan.status,
                    "assignment_ids": list(plan.assignment_ids),
                }
                for plan in coordination.plans.values()
            ]
            assignments = [
                {
                    "assignment_id": item.assignment_id, "plan_id": item.plan_id,
                    "task_id": item.task_id, "assigned_worker_id": item.assigned_worker_id,
                    "status": item.status, "wake_attempt_id": item.wake_attempt_id,
                    "claimed_attempt_id": item.claimed_attempt_id,
                    "takeover_agent_id": item.takeover_agent_id,
                    "takeover_reason": item.takeover_reason,
                }
                for item in coordination.assignments.values()
            ]
            wakes = [
                {
                    "wake_attempt_id": item.wake_attempt_id, "assignment_id": item.assignment_id,
                    "task_id": item.task_id, "worker_id": item.worker_id,
                    "wake_id": item.wake_id, "retry_count": item.retry_count,
                    "status": item.status, "host_accepted": item.host_accepted,
                    "host_turn_id": item.host_turn_id,
                    "worker_ready": item.worker_ready, "deadline": item.deadline,
                    "failure_reason": item.failure_reason,
                }
                for item in coordination.wake_attempts.values()
            ]
            events = [
                {
                    "event_id": item.event_id, "kind": item.kind,
                    "actor_id": item.actor_id, "assignment_id": item.assignment_id,
                    "task_id": item.task_id, "summary": item.summary,
                    "important": item.important, "created_at": item.created_at,
                }
                for item in coordination.events
            ]
            if kind == "assignments":
                return {"project_id": requested_project_id, "items": assignments,
                        "coverage": coordination.coverage(),
                        "auto_wake_multi_agent": bool(
                            project_registry is not None and project_registry.project is not None
                            and project_registry.project.settings.get("auto_wake_multi_agent", False)
                        )}
            if kind == "wake_attempts":
                return {"project_id": requested_project_id, "items": wakes}
            if kind == "events":
                return {"project_id": requested_project_id, "items": events}
            return {"project_id": requested_project_id, "plans": plans,
                    "assignments": assignments, "wake_attempts": wakes,
                    "events": events,
                    "coverage": coordination.coverage(),
                    "auto_wake_multi_agent": bool(
                        project_registry is not None and project_registry.project is not None
                        and project_registry.project.settings.get("auto_wake_multi_agent", False)
                    )}
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
                        "evidence_level": result.payload.get("evidence_level"),
                        "observed_at": result.payload.get("observed_at"),
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
                    {"agent_id": item.agent_id, "status": item.status, "role": item.role,
                     "conversation_digest": item.conversation_digest}
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
                         "scope_digest": workspaces.results[workspace.result_manifest_id].scope_digest,
                         "submitted_by": workspaces.results[workspace.result_manifest_id].submitted_by,
                         "observed_at": format_timestamp(workspaces.results[workspace.result_manifest_id].observed_at),
                         "observed_by": "daemon" if workspaces.results[workspace.result_manifest_id].root_observations else None,
                         "evidence_subject": (
                             "workspace_filesystem_observation"
                             if workspaces.results[workspace.result_manifest_id].root_observations else "agent_assertion"
                         ),
                         "evidence_level": workspaces.results[workspace.result_manifest_id].evidence_level,
                         "validation_metadata": list(workspaces.results[workspace.result_manifest_id].validation_metadata),
                         "root_observations": list(workspaces.results[workspace.result_manifest_id].root_observations),
                         "patch_artifact_domain": workspaces.results[workspace.result_manifest_id].patch_artifact_domain,
                         "patch_artifact_owner": workspaces.results[workspace.result_manifest_id].patch_artifact_owner,
                     }} if workspace.result_manifest_id in workspaces.results else {})}
                    for workspace in workspaces.workspaces.values()
                ],
            }
        if kind == "audit":
            if viewer is None:
                raise PermissionError("authentication_failed")
            if database is None:
                return {"project_id": requested_project_id, "items": [], "next_cursor": None, "projection_version": "v1",
                        "as_of_event_seq": 0, "snapshot_event_seq": 0}
            projector = AuditProjector()
            audit_items: list[dict[str, Any]] = []
            if not 1 <= limit <= 200:
                raise ValueError("invalid_audit_limit")
            bounded = limit
            from_ms, to_ms = parse_timestamp(from_timestamp), parse_timestamp(to_timestamp)
            if from_ms is not None and to_ms is not None and from_ms > to_ms:
                raise ValueError("invalid_time_range")
            cursor_context = {
                "project_id": database.project_id, "lineage_id": registry.lineage_id if registry else database.lineage_id,
                "viewer": {"kind": viewer.kind, "id": viewer.principal_id,
                           "session_id": viewer.session_id, "connection_epoch": viewer.connection_epoch},
                "from_ms": from_ms, "to_ms": to_ms, "actor_ref": actor_ref, "subject_ref": subject_ref,
                "limit": limit, "sort": "event_seq_asc",
            }
            after, watermark = cursor_codec.decode(cursor, context=cursor_context) if cursor else (0, database.last_event_seq())
            audit_events: list[dict[str, Any]] = []
            scanned = after
            # Apply visibility before pagination and continue over hidden rows;
            # otherwise a private message page can hide the next public event.
            while len(audit_events) <= bounded:
                batch = database.list_events(
                    limit=201, cursor=scanned, from_ms=from_ms, to_ms=to_ms,
                    actor_ref=actor_ref, subject_ref=subject_ref, through_event_seq=watermark,
                )
                if not batch:
                    break
                for event in batch:
                    scanned = event["event_seq"]
                    if can_read_event(event, viewer):
                        audit_events.append(event)
                    if len(audit_events) > bounded:
                        break
                if len(batch) < 201:
                    break
            has_next = len(audit_events) > bounded
            audit_events = audit_events[:bounded]
            for event in audit_events:
                raw_payload = event.get("payload")
                audit_payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
                view = projector.project({
                    "event_id": event["event_id"], "event_seq": event["event_seq"],
                    "actor_ref": event["actor_ref"], "action": event["event_type"].removeprefix("command."),
                    "subject_ref": event.get("subject_ref") or event["aggregate_ref"],
                    "outcome": event.get("outcome") or audit_payload.get("outcome", "committed"),
                    "reason_code": event.get("reason_code") or audit_payload.get("reason_code"),
                    "evidence_refs": event.get("evidence_refs") or audit_payload.get("evidence_refs", []),
                    "occurred_at": event.get("occurred_at"),
                    "recorded_at": event.get("recorded_at"),
                    "caused_by_command_id": event.get("caused_by_command_id"),
                    "revision_before": event.get("revision_before"),
                    "revision_after": event.get("revision_after"),
                    "projection_version": event.get("projection_version", "v1"),
                    "evidence_level": audit_payload.get("evidence_level"),
                }, can_read_subject=True)
                audit_items.append({
                    "event_id": view.source_event_id, "event_seq": view.source_event_seq,
                    "project_id": event["project_id"], "lineage_id": event["lineage_id"],
                    "schema_version": event["schema_version"],
                    "source_event_id": view.source_event_id,
                    "source_event_seq": view.source_event_seq,
                    "actor_ref": view.actor_ref, "action": view.action,
                    "subject_ref": view.subject_ref, "outcome": view.outcome,
                    "reason_code": view.reason_code,
                    "evidence_refs": list(view.evidence_refs),
                    "occurred_at": format_timestamp(view.occurred_at),
                    "recorded_at": format_timestamp(view.recorded_at),
                    "caused_by_command_id": view.caused_by_command_id,
                    "revision_before": view.revision_before,
                    "revision_after": view.revision_after,
                    "evidence_level": view.evidence_level,
                    "projection_version": view.projection_version,
                    "actor_session_id": audit_payload.get("session_id"),
                    "changes": [
                        {**change, "created_at": format_timestamp(change.get("created_at")),
                         "updated_at": format_timestamp(change.get("updated_at"))}
                        for change in audit_payload.get("changes", [])
                    ],
                })
            return {
                "project_id": requested_project_id,
                "items": audit_items,
                "next_cursor": cursor_codec.encode(
                    context=cursor_context, after_seq=audit_items[-1]["event_seq"], as_of_event_seq=watermark,
                ) if has_next and audit_items else None,
                "projection_version": "v1",
                "as_of_event_seq": watermark, "snapshot_event_seq": watermark,
            }
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
    def query_with_entity_times(kind: str, requested_project_id: str, **kwargs: Any) -> dict[str, Any]:
        result = query(kind, requested_project_id, **kwargs)
        if database is None or kind in {"audit", "artifact"}:
            return result
        metadata = database.entity_metadata(registry.lineage_id if registry else database.lineage_id)
        # Each query owns its DTO shape. Never guess identity from foreign keys
        # (a Result also has task_id and attempt_id; a Report has actor_agent_id).
        identities = {
            "tasks": ("task", "task_id"), "attempts": ("attempt", "attempt_id"),
            "results": ("result", "result_id"), "reports": ("report", "report_id"),
            "contracts": ("contract", "proposal_id"), "discrepancies": ("discrepancy", "discrepancy_id"),
            "decisions": ("decision", "decision_id"), "agents": ("agent", "agent_id"),
            "workspaces": ("workspace", "workspace_id"), "resources": ("lease", "lease_set_id"),
            "plans": ("plan", "plan_id"), "assignments": ("assignment", "assignment_id"),
            "wake_attempts": ("wake_attempt", "wake_attempt_id"), "events": ("coordination_event", "event_id"),
            "messages": ("message", "message_id"), "roots": ("root", "root_id"),
            "repositories": ("repository", "repository_id"),
        }
        for section, values in list(result.items()):
            identity = identities.get(kind if section == "items" else section)
            if identity is None or not isinstance(values, list):
                continue
            entity_kind, identity_field = identity
            rows = []
            for item in values:
                times = metadata.get(f"{entity_kind}/{item.get(identity_field)}", {})
                rows.append({**item, "created_at": format_timestamp(times.get("created_at")),
                             "updated_at": format_timestamp(times.get("updated_at"))})
            result[section] = rows
        return result

    return query_with_entity_times


def _project_id() -> str | None:
    """Resolve a project id from the environment or the coordination repo."""
    configured = os.environ.get("TSUNAGOU_PROJECT_ID")
    state_dir = os.environ.get("TSUNAGOU_STATE_DIR")
    durable = _durable_project_snapshot(Path(state_dir) if state_dir else None)
    if durable is not None:
        durable_id = str(durable["project"]["project_id"])
        if configured and configured != durable_id:
            raise ValueError("configured_project_identity_mismatch")
        return durable_id
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


def _durable_project_snapshot(state_path: Path | None) -> dict[str, Any] | None:
    if state_path is None or not (state_path / "state.sqlite3").is_file():
        return None
    path = (state_path / "state.sqlite3").resolve()
    with contextlib.closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as conn:
        rows = conn.execute("SELECT payload_json FROM module_state WHERE module='projects'").fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("project_database_identity_ambiguous")
    return json.loads(rows[0][0])  # type: ignore[no-any-return]
