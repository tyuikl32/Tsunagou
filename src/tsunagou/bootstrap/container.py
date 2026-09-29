"""Application assembly; domain services are added by their owning tasks."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import sqlite3
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from tsunagou.api.app import create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import Handler, build_handlers
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
from tsunagou.platform.checkpoints import CheckpointStore, GitAnchorScanner
from tsunagou.platform.db.sqlite import ProjectDatabase, ProjectLock
from tsunagou.platform.host_delivery import HostDeliveryWorker
from tsunagou.platform.maintenance import RuntimeMaintenance
from tsunagou.platform.runtime_context import running_source_root
from tsunagou.platform.state import ServiceStateRuntime
from tsunagou.platform.telemetry import Telemetry
from tsunagou.shared_kernel.baseline import (
    OPERATIONAL_CAPABILITIES,
    missing_admission_capabilities,
    missing_baseline_capabilities,
)
from tsunagou.shared_kernel.time import format_timestamp, now_ms, parse_timestamp

_REGISTRY_RESOURCE = files("tsunagou.protocol_data").joinpath("registry", "commands.json")


def _registry_path() -> Path:
    """Return a package resource path without depending on the checkout cwd."""
    return Path(str(_REGISTRY_RESOURCE))


def build_application(config: Mapping[str, str] | None = None) -> FastAPI:
    config = dict(os.environ if config is None else config)
    state_dir = config.get("TSUNAGOU_STATE_DIR")
    project_root = config.get("TSUNAGOU_PROJECT_ROOT")
    if state_dir and project_root:
        shared = Path(project_root) / ".tsunagou"
        with ProjectLock(shared / "bootstrap.lock"):
            if not (Path(state_dir) / "state.sqlite3").exists() and (shared / "checkpoints" / "current.json").is_file():
                raise RuntimeError("checkpoint_restore_required")
            return _build_application(config)
    return _build_application(config)


def _build_application(config: Mapping[str, str]) -> FastAPI:
    """Assemble the real application with authority, handlers and control credentials.

    Credentials come only from the environment, never from request headers or hardcoded
    defaults. When unset, the application stays fail-closed for every business command:

    - ``TSUNAGOU_CONTROL_TOKEN`` is the private user-control bearer credential.
    - ``TSUNAGOU_STATE_DIR`` points at the durable authority state directory; without it,
      authority state is in-memory only and does not survive a restart.
    """
    telemetry = Telemetry(config.get("TSUNAGOU_OTEL_ENDPOINT"))
    state_dir = config.get("TSUNAGOU_STATE_DIR")
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
    project_id = _project_id(config)
    project_registry = None
    project_root = config.get("TSUNAGOU_PROJECT_ROOT")
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
            database=database,
            interval_seconds=float(config.get("TSUNAGOU_MAINTENANCE_INTERVAL", "1")),
            checkpoint_worker=checkpoint_worker,
        )
        if config.get("TSUNAGOU_HOST_WAKE", "").casefold() in {"managed", "desktop", "auto"}:
            binding_store = PrivateBindingStore(state_path / "host-bindings.json")
            hostwake_provider = HostWakeProviderRegistry(
                ManagedCodexProvider(binding_store),
                DesktopAttachProvider(binding_store),
            )
            wake_dispatcher = WakeDispatcher(
                hostwake_provider,
                attempts_path=state_path / "host-wake-attempts.json",
                diagnostics_path=state_path / "diagnostic-events.json",
            )
    dispatcher = CommandDispatcher(
        _registry_path(), database=database, state_runtime=state_runtime,
        checkpoint_worker=checkpoint_worker,
    )
    if wake_dispatcher is not None:
        dispatcher.record_failure = wake_dispatcher.record_command_failure
    preparers: dict[str, Handler] = {}
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
        artifacts=artifacts, preparers=preparers,
    ).items():
        dispatcher.register(command_kind, handler)
    for command_kind, prepare in preparers.items():
        dispatcher.register_preparer(command_kind, prepare)
    authenticator = LocalCommandAuthenticator(
        authority=authority, control_token=config.get("TSUNAGOU_CONTROL_TOKEN")
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
            project_root=project_root,
            wake_dispatcher=wake_dispatcher,
        ),
        wake_dispatcher=wake_dispatcher,
        hostwake_provider=hostwake_provider,
        telemetry=telemetry,
    )
    application.state.project_database = database
    application.state.runtime_info = {
        "pid": os.getpid(), "runtime_id": database.runtime_epoch if database is not None else None,
        "project_ids": [project_id] if project_id else [],
        "source_root": str(running_source_root()), "schema_bundle_digest": schema_bundle_digest,
    }
    application.state.state_runtime = state_runtime
    application.state.checkpoint_store = checkpoint_store
    application.state.checkpoint_worker = checkpoint_worker
    application.state.maintenance = maintenance
    application.state.hostwake_provider = hostwake_provider
    if database is not None and wake_dispatcher is not None:
        host_delivery = HostDeliveryWorker(database, wake_dispatcher, telemetry)
        application.state.host_delivery = host_delivery

        @application.on_event("startup")
        def start_host_delivery() -> None:
            host_delivery.start()
    if maintenance is not None:
        @application.on_event("startup")
        def start_runtime_maintenance() -> None:
            maintenance.start()

        @application.on_event("shutdown")
        def stop_runtime_maintenance() -> None:
            maintenance.stop()
    return application


def message_status(obligations: list[dict[str, Any]]) -> str:
    """What became of one message, worked out from the obligations it created.

    A message has no status stored on it (see ``modules/messaging.py``): it owns a
    delivery row, and — only when the sender attached a response contract — one or more
    response obligations. So:

    * no obligation at all  → ``none`` (nobody owed an answer);
    * any obligation ``open`` → ``pending``;
    * everything else (``responded`` / ``waived`` / ``superseded``) → ``answered``.

    Kept as a function of the rows rather than of the store so the verdict can be
    asserted directly, without a message ever being sent.
    """

    if not obligations:
        return "none"
    return "pending" if any(row.get("status") == "open" for row in obligations) else "answered"


def _agent_features(authority: AuthorityService, agent_id: str) -> dict[str, Any]:
    """Which of the 11 baseline capabilities this Agent's session proved.

    The session keeps the host's own report (normalized, bounded); whether a row counts
    as proven is decided by the shared rule in ``shared_kernel.baseline``, so the console
    reads the same answer the admission gate did instead of a second opinion.
    """

    session = next(
        (item for item in authority.sessions.values() if item.agent_id == agent_id and item.active),
        None,
    )
    if session is None:
        return {"session_status": None, "connection_epoch": None,
                "missing_admission": None, "missing_operational": None}
    rows = session.baseline.get("capabilities") if isinstance(session.baseline, dict) else None
    evidence = {"baseline": rows if isinstance(rows, dict) else {}}
    missing_all = set(missing_baseline_capabilities(evidence))
    return {
        "session_status": session.status,
        "connection_epoch": session.connection_epoch,
        "missing_admission": sorted(missing_admission_capabilities(evidence)),
        "missing_operational": sorted(name for name in OPERATIONAL_CAPABILITIES if name in missing_all),
    }


def _query_provider(
    *, project_id: str | None, registry: ServiceStateRuntime | None,
    database: ProjectDatabase | None, authority: AuthorityService, tasks: TaskService,
    cognition: CognitionService, messages: MessageStore, resources: ResourceService,
    workspaces: WorkspaceService, lifecycle: LifecycleService | None,
    project_registry: ProjectRegistry | None,
    checkpoint_store: CheckpointStore | None,
    coordination: CoordinationService,
    artifacts: ArtifactService | None = None,
    project_root: str | None = None,
    wake_dispatcher: Any | None = None,
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

    def task_subject_refs(task_id: str) -> set[str]:
        """Build the persisted entity refs that form one task's timeline."""
        refs = {f"task/{task_id}"}
        attempt_ids = {
            attempt.attempt_id for attempt in tasks.attempts.values()
            if attempt.task_id == task_id
        }
        refs.update(f"attempt/{attempt_id}" for attempt_id in attempt_ids)
        refs.update(
            f"result/{result.result_id}" for result in tasks.results.values()
            if result.task_id == task_id
        )
        refs.update(
            f"preflight/{preflight.preflight_id}" for preflight in tasks.preflights.values()
            if preflight.task_id == task_id
        )
        refs.update(
            f"progress/{progress.progress_id}" for progress in tasks.progress_records.values()
            if progress.task_id == task_id
        )
        refs.update(
            f"report/{report.report_id}" for report in cognition.reports.values()
            if report.task_id == task_id
        )
        refs.update(
            f"workspace/{workspace.workspace_id}" for workspace in workspaces.workspaces.values()
            if workspace.attempt_id in attempt_ids
        )
        refs.update(
            f"isolation_decision/{decision.decision_id}"
            for decision in workspaces.decisions.values()
            if decision.task_id == task_id
        )
        refs.update(
            f"message/{message.message_id}" for message in messages.messages.values()
            if message.subject_ref in refs
        )
        refs.update(
            f"obligation/{obligation.obligation_id}"
            for obligation in messages.obligations.values()
            if obligation.message_id in {ref.removeprefix("message/") for ref in refs}
        )
        return refs

    def visible_event(event: dict[str, Any], viewer: PrincipalContext) -> dict[str, Any] | None:
        if can_read_event(event, viewer):
            return event
        subject = event.get("subject_ref") or event.get("aggregate_ref", "")
        action = str(event["event_type"]).removeprefix("command.")
        # A compound domain command may also emit a private notification. Its
        # shared fact remains visible; the notification and private references
        # do not. Unknown/legacy message audiences still fail closed.
        if action.startswith(("message.", "inbox.")) or not subject.startswith((
            "task/", "attempt/", "result/", "workspace/", "contract/", "decision/", "project/",
        )):
            return None
        payload = event.get("payload") or {}
        # Explicit evidence defines the claim itself, so it must be authorized
        # in full. Only ancillary entity changes may be omitted.
        if not can_read_event({**event, "payload": {**payload, "changes": []}}, viewer):
            return None
        def readable_ref(ref: str) -> bool:
            probe = {**event, "subject_ref": ref, "payload": {}, "evidence_refs": []}
            return can_read_event(probe, viewer)

        if not readable_ref(subject):
            return None
        return {**event, "payload": {
            **payload,
            "changes": [change for change in payload.get("changes", [])
                        if readable_ref(change.get("subject_ref", ""))],
        }}

    def event_matches_subject_refs(event: dict[str, Any], refs: set[str]) -> bool:
        if event.get("subject_ref") in refs or event.get("aggregate_ref") in refs:
            return True
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return False
        return any(
            isinstance(change, dict) and change.get("subject_ref") in refs
            for change in payload.get("changes", [])
        )

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
        task_id: str | None = None,
        message_id: str | None = None,
        project_filter: str | None = None,
        verify: bool = False,
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
        # Some read endpoints use a resource identity (event/checkpoint
        # digest) as requested_project_id.  They validate project ownership in
        # their own branch after loading the resource; comparing the resource
        # key to the configured project id here would reject valid reads.
        if (
            kind not in {"audit_event", "checkpoint_verify"}
            and project_id is not None
            and requested_project_id
            and requested_project_id != project_id
        ):
            raise KeyError("project_not_found")
        if kind == "overview":
            if project_registry is None or project_registry.project is None:
                raise KeyError("project_not_found")
            project = project_registry.project
            # A summary, never a copy: `/roots` and `/repositories` own the full
            # shapes, and a console header only needs to know what is there.
            return {
                "project_id": project.project_id,
                "name": project.name,
                "objective": project.objective,
                "lifecycle": project.lifecycle,
                "policy_revision": project.policy_revision,
                "roots": [
                    {key: descriptor.get(key) for key in ("root_id", "name", "root_kind", "required")}
                    for descriptor in project.roots.values()
                ],
                "repositories": [
                    {key: descriptor.get(key) for key in ("repository_id", "name", "root_id")}
                    for descriptor in project.repositories.values()
                ],
            }
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
                    tasks.describe_task(task.task_id)
                    for task in tasks.tasks.values()
                ],
            }
        if kind in {"coordination", "assignments", "wake_attempts", "events"}:
            plans = [
                {
                    "plan_id": plan.plan_id, "objective": plan.objective,
                    "main_agent_id": plan.main_agent_id,
                    "assignment_ids": list(plan.assignment_ids),
                }
                for plan in coordination.plans.values()
            ]
            assignments = [
                {
                    "assignment_id": item.assignment_id, "plan_id": item.plan_id,
                    "task_id": item.task_id, "assigned_worker_id": item.assigned_worker_id,
                    "status": tasks.tasks[item.task_id].status, "message_id": item.message_id,
                    "current_attempt_id": tasks.tasks[item.task_id].current_attempt_id,
                    "takeover_agent_id": item.takeover_agent_id,
                    "takeover_reason": item.takeover_reason,
                }
                for item in coordination.assignments.values()
            ]
            wakes = list(wake_dispatcher.attempts.values()) if wake_dispatcher is not None else []
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
                        "coverage": coordination.coverage({key: task.status for key, task in tasks.tasks.items()}),
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
                    "coverage": coordination.coverage({key: task.status for key, task in tasks.tasks.items()}),
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
                        "started_at": attempt.started_at, "ended_at": attempt.ended_at,
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
        if kind == "reviews":
            # A result says work was submitted; a review says whether it was good enough
            # and who said so. The console's task-acceptance column asks the second
            # question, so the rounds have to be readable — not merely stored in state.
            rounds: list[dict[str, Any]] = []
            for _, review in sorted(tasks.reviews.items()):
                submitted = tasks.results.get(review.result_id)
                rounds.append({
                    "task_id": submitted.task_id if submitted is not None else None,
                    "result_id": review.result_id, "round_no": review.round_no,
                    "reviewer_agent_id": review.reviewer_agent_id,
                    "decision": review.decision, "reason": review.reason,
                })
            return {"project_id": requested_project_id, "items": rounds}
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
                    {
                        "proposal_id": item.proposal_id, "digest": item.digest, "status": item.status,
                        # The body is what was agreed; a reader that only sees an id and a
                        # digest is being asked to trust an agreement it cannot read.
                        "payload": item.payload,
                        "supersedes_id": item.supersedes_id,
                        "resolution_reason": item.resolution_reason,
                        "required_slots": list(item.required_slots),
                        "participants": [dict(participant) for participant in item.participants],
                        # Who signed which slot: without it "has everyone agreed" is unanswerable.
                        "acceptances": [
                            {
                                "participant_slot": acceptance.participant_slot,
                                "proposal_digest": acceptance.proposal_digest,
                                "real_actor_id": acceptance.real_actor_id,
                                "represented_participant": acceptance.represented_participant,
                                "via_proxy": acceptance.via_proxy,
                            }
                            for key, acceptance in sorted(cognition.acceptances.items())
                            if key[0] == item.proposal_id
                        ],
                    }
                    for item in cognition.proposals.values()
                ],
            }
        if kind == "cognition":
            return {
                "reports": [
                    {"report_id": report.report_id, "task_id": report.task_id,
                     "attempt_id": report.attempt_id, "actor_agent_id": report.actor_agent_id,
                     "digest": report.digest, "input_revisions": report.input_revisions,
                     "claims": [
                         {"subject_key": claim.subject_key, "claim_type": claim.claim_type,
                          "equality_key": claim.equality_key, "value": claim.value}
                         for claim in report.claims
                     ]}
                    for report in cognition.reports.values()
                ],
                "discrepancies": [
                    {"discrepancy_id": item.discrepancy_id, "rule_id": item.rule_id,
                     "subject_key": item.subject_key,
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
            activity = {}
            if database is not None:
                with contextlib.closing(database._connect()) as conn:
                    activity = {
                        row["principal_id"]: format_timestamp(row["last_activity"])
                        for row in conn.execute(
                            "SELECT principal_id,MAX(created_at) AS last_activity FROM commands WHERE project_id=? GROUP BY principal_id",
                            (project_id,),
                        )
                    }
            return {
                "items": [
                    # ``_agent_features`` first: it also answers ``session_status`` (None when
                    # the Agent has no live session), and the explicit value below is the more
                    # accurate one — an Agent with no session is ``inactive``, not ``unknown``.
                    # Everything else it adds (``connection_epoch``, ``missing_admission``,
                    # ``missing_operational``) survives as the console's capability columns.
                    {**_agent_features(authority, item.agent_id),
                     "agent_id": item.agent_id, "status": item.status, "role": item.role,
                     "conversation_digest": item.conversation_digest,
                     "session_status": next((s.status for s in authority.sessions.values()
                                             if s.agent_id == item.agent_id and s.active), "inactive"),
                     "current_task_ids": [task.task_id for task in tasks.tasks.values()
                                          if task.status in {"claimed", "running", "cancel_requested"}
                                          and (attempt := tasks.attempts.get(task.current_attempt_id or "")) is not None
                                          and attempt.owner_agent_id == item.agent_id],
                     "last_activity_at": activity.get(item.agent_id)}
                    for item in authority.agents.values()
                ],
                "main_agent_id": authority.main_agent_id,
                # ``authority.appoint``/``revoke`` demand the epoch the caller saw, so it
                # has to be readable *before* the command rather than only in its reply.
                "authority_epoch": authority.authority_epoch,
            }
        if kind == "messages":
            # A message carries no verdict of its own: the durable facts are its delivery
            # row and the response obligations the sender asked for. The page's column is
            # "已答复 / 等待中 / 无需答复", so the verdict is worked out *here* instead of
            # being left for the reader to infer — an empty obligation list means nobody
            # owed an answer, which is not the same as "still waiting for one".
            obligations: dict[str, list[dict[str, Any]]] = {}
            for obligation in messages.obligations.values():
                obligations.setdefault(obligation.message_id, []).append({
                    "obligation_id": obligation.obligation_id,
                    "status": obligation.status,
                })
            return {
                "items": [
                    {
                        "message_id": item.message_id, "sender_agent_id": item.sender_agent_id,
                        "recipient_agent_id": item.recipient_agent_id, "kind": item.kind,
                        "subject_ref": item.subject_ref, "summary": item.summary,
                        "status": message_status(obligations.get(item.message_id, [])),
                        "obligations": obligations.get(item.message_id, []),
                    }
                    for item in messages.messages.values()
                ],
            }
        if kind == "resources":
            return {
                "items": [
                    {"reservation_id": item.reservation_id, "task_id": item.task_id, "attempt_id": item.attempt_id,
                     "owner_agent_id": item.owner_agent_id, "status": item.status,
                     "created_at": format_timestamp(item.created_at), "released_at": format_timestamp(item.released_at),
                     "release_reason": item.release_reason, "resources": [request.key.canonical for request in item.resources]}
                    for item in resources.reservations.values()
                ],
            }
        if kind == "intents":
            # The base model's resource *intents* (declare → wait → acquire, with a lease
            # that expired on its own) were replaced by explicit reservations in the FX
            # line — see docs/decisions/2026-09-28-explicit-resource-release.md: occupancy
            # is taken and released explicitly, and elapsed time never releases anything.
            # There is no intent object left to read, and reconstructing one here would be
            # a second resource model. The exit therefore answers honestly with nothing:
            # the console's audit screen keeps its 意图 column empty instead of showing
            # invented rows or a 500. How that screen should read the new model is a
            # front-end design decision, not a merge decision.
            return {"project_id": requested_project_id, "items": []}
        if kind == "conflicts":
            # A refusal is a shared fact, not an error string: the HTTP layer already
            # records every structured rejection as ``command.<kind>.denied``. This exit
            # reads those rows and asks the *current* state what became of them, so
            # "how often do agents collide, over what, and did they recover" is a
            # question about the run rather than about one caller's memory.
            # Capped at the first 200 refusals (oldest first in the ledger).
            if database is None:
                return {"project_id": requested_project_id, "items": []}
            refusals: list[dict[str, Any]] = []
            for refusal_event in database.list_events(limit=200, event_type_like="%.denied"):
                refusal = refusal_event.get("payload")
                if not isinstance(refusal, dict):
                    continue
                if not str(refusal.get("code", "")).startswith("resource_conflict:"):
                    continue
                requester_raw = refusal.get("requester")
                requester: dict[str, Any] = requester_raw if isinstance(requester_raw, dict) else {}
                entries = [
                    entry for entry in refusal.get("conflicts", []) if isinstance(entry, dict)
                ]
                holders: list[dict[str, Any]] = []
                for entry in entries:
                    # Two generations of refusal payloads live in the ledger: the older
                    # ``holder_*`` rows written when occupancy was a timed lease, and the
                    # reservation-era ``attempt_id``/``reservation_id``/``resource_key``
                    # rows. A ledger is a history, so both shapes are read rather than
                    # pretending old rows do not exist.
                    holder_attempt_id = entry.get("holder_attempt_id") or entry.get("attempt_id")
                    attempt = tasks.attempts.get(str(holder_attempt_id or ""))
                    holders.append({
                        "attempt_id": holder_attempt_id,
                        "agent_id": attempt.owner_agent_id if attempt is not None else entry.get("owner_agent_id"),
                        "task_id": attempt.task_id if attempt is not None else entry.get("task_id"),
                        "lease_set_id": entry.get("holder_lease_set_id") or entry.get("reservation_id"),
                        "held_key": entry.get("held_key") or entry.get("resource_key"),
                        "resource": entry.get("resource"),
                        "mode": entry.get("mode"),
                        "expires_at": entry.get("holder_expires_at"),
                    })
                requester_attempt_id = str(requester.get("attempt_id") or "")
                wanted = {str(item) for item in (requester.get("resource_keys") or [])}
                # Asking the current state is what keeps this honest: nobody reports an
                # outcome, so "what happened next" has to be read off the reservations and
                # attempts that exist now. Occupancy no longer expires by itself, so
                # "still active" is the only thing that makes a holder a holder.
                acquired_afterwards = any(
                    reservation.status == "active" and reservation.attempt_id == requester_attempt_id
                    and any(request.key.canonical in wanted for request in reservation.resources)
                    for reservation in resources.reservations.values()
                )
                requester_attempt = tasks.attempts.get(requester_attempt_id)
                holders_gone = bool(holders) and all(
                    (reservation := resources.reservations.get(
                        str(entry.get("holder_lease_set_id") or entry.get("reservation_id") or "")))
                    is None or reservation.status != "active"
                    for entry in entries
                )
                if acquired_afterwards:
                    resolution = "retried_and_won"
                elif requester_attempt is not None and requester_attempt.status in {
                    "orphaned", "failed", "cancelled",
                }:
                    resolution = "gave_up"
                elif holders_gone:
                    resolution = "holder_released"
                else:
                    resolution = "open"
                refusals.append({
                    "conflict_id": refusal_event["event_id"],
                    "at": refusal_event.get("occurred_at"),
                    "phase": refusal.get("command_kind"),
                    "requester": {
                        "attempt_id": requester.get("attempt_id"),
                        "agent_id": requester.get("owner_agent_id"),
                        "task_id": requester.get("task_id"),
                        "intent_id": requester.get("intent_id"),
                        "resource_keys": sorted(wanted),
                    },
                    "holders": holders,
                    "resolution": resolution,
                })
            refusals.reverse()
            return {"project_id": requested_project_id, "items": refusals}
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
        def project_audit_event(event: dict[str, Any]) -> dict[str, Any]:
            """Project one event through the same public fields as AuditPage."""
            raw_payload = event.get("payload")
            audit_payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
            view = AuditProjector().project({
                "event_id": event["event_id"], "event_seq": event["event_seq"],
                "actor_ref": event["actor_ref"], "action": event["event_type"].removeprefix("command."),
                "subject_ref": event.get("subject_ref") or event["aggregate_ref"],
                "outcome": event.get("outcome") or audit_payload.get("outcome", "committed"),
                "reason_code": event.get("reason_code") or audit_payload.get("reason_code"),
                "evidence_refs": event.get("evidence_refs") or audit_payload.get("evidence_refs", []),
                "occurred_at": event.get("occurred_at"), "recorded_at": event.get("recorded_at"),
                "caused_by_command_id": event.get("caused_by_command_id"),
                "revision_before": event.get("revision_before"), "revision_after": event.get("revision_after"),
                "projection_version": event.get("projection_version", "v1"),
                "evidence_level": audit_payload.get("evidence_level"),
            }, can_read_subject=True)
            return {
                "event_id": view.source_event_id, "event_seq": view.source_event_seq,
                "project_id": event["project_id"], "lineage_id": event["lineage_id"],
                "schema_version": event["schema_version"], "source_event_id": view.source_event_id,
                "source_event_seq": view.source_event_seq, "actor_ref": view.actor_ref,
                "action": view.action, "subject_ref": view.subject_ref, "outcome": view.outcome,
                "reason_code": view.reason_code, "evidence_refs": list(view.evidence_refs),
                "occurred_at": format_timestamp(view.occurred_at),
                "recorded_at": format_timestamp(view.recorded_at),
                "caused_by_command_id": view.caused_by_command_id,
                "revision_before": view.revision_before, "revision_after": view.revision_after,
                "evidence_level": view.evidence_level, "projection_version": view.projection_version,
                "actor_session_id": audit_payload.get("session_id"),
                "session_status": audit_payload.get("session_status"),
                "missing_admission": list(audit_payload.get("missing_admission") or []),
                "changes": [
                    {**change, "created_at": format_timestamp(change.get("created_at")),
                     "updated_at": format_timestamp(change.get("updated_at"))}
                    for change in audit_payload.get("changes", [])
                ],
            }

        if kind == "audit_event":
            if viewer is None or database is None:
                raise PermissionError("authentication_failed")
            if project_filter is not None and project_filter != database.project_id:
                raise KeyError("project_not_found")
            event = database.get_event(requested_project_id)
            if event is None:
                raise KeyError("audit_event_not_found")
            event = visible_event(event, viewer)
            if event is None:
                raise PermissionError("audit_event_access_denied")
            return project_audit_event(event)

        if kind == "audit_export":
            if viewer is None:
                raise PermissionError("authentication_failed")
            page = query(
                "audit", requested_project_id, cursor=cursor, limit=limit,
                from_timestamp=from_timestamp, to_timestamp=to_timestamp,
                actor_ref=actor_ref, subject_ref=subject_ref, viewer=viewer,
            )
            lineage = registry.lineage_id if registry is not None else (database.lineage_id if database else None)
            return {
                "schema": "tsunagou.audit-export.v1", "exported_at": format_timestamp(now_ms()),
                "source": {"project_id": requested_project_id, "lineage_id": lineage},
                "projection_version": page["projection_version"], "as_of_event_seq": page["as_of_event_seq"],
                "next_cursor": page["next_cursor"], "items": page["items"],
            }

        if kind == "task_history":
            if viewer is None:
                raise PermissionError("authentication_failed")
            if not task_id or tasks is None or task_id not in tasks.tasks:
                raise KeyError("task_not_found")
            return query(
                "audit", requested_project_id, cursor=cursor, limit=limit,
                from_timestamp=from_timestamp, to_timestamp=to_timestamp,
                actor_ref=actor_ref, task_id=task_id, viewer=viewer,
            )

        if kind == "diagnostics":
            if viewer is None:
                raise PermissionError("authentication_failed")
            if wake_dispatcher is None:
                return {"project_id": requested_project_id, "items": []}
            from_ms, to_ms = parse_timestamp(from_timestamp), parse_timestamp(to_timestamp)
            if from_ms is not None and to_ms is not None and from_ms > to_ms:
                raise ValueError("invalid_time_range")
            diagnostic_items = []
            for item in wake_dispatcher.diagnostics(project_id=requested_project_id):
                if message_id is not None and item.get("message_id") != message_id:
                    continue
                if task_id is not None and item.get("task_id") != task_id:
                    continue
                occurred = parse_timestamp(item.get("occurred_at"))
                if from_ms is not None and (occurred is None or occurred < from_ms):
                    continue
                if to_ms is not None and (occurred is None or occurred > to_ms):
                    continue
                # Diagnostics expose transport facts only. Private references
                # still follow the message audience; U/main can see shared task
                # delivery failures without gaining the private message ID.
                ref = item.get("message_id")
                message = messages.messages.get(ref) if ref else None
                audience = message is not None and viewer.principal_id in {
                    message.sender_agent_id, message.recipient_agent_id,
                }
                if not ref and viewer.kind != "U" and authority.main_agent_id != viewer.principal_id:
                    if item.get("agent_id") != viewer.principal_id:
                        continue
                if ref and not audience:
                    if message_id is not None:
                        continue
                    if viewer.kind != "U" and authority.main_agent_id != viewer.principal_id:
                        continue
                    item = {**item, "message_id": None}
                diagnostic_items.append(item)
            return {
                "project_id": requested_project_id,
                "items": diagnostic_items,
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
                "from_ms": from_ms, "to_ms": to_ms, "actor_ref": actor_ref,
                "subject_ref": subject_ref, "task_id": task_id,
                "limit": limit, "sort": "event_seq_asc",
            }
            after, watermark = cursor_codec.decode(cursor, context=cursor_context) if cursor else (0, database.last_event_seq())
            audit_events: list[dict[str, Any]] = []
            scanned = after
            related_refs = task_subject_refs(task_id) if task_id else None
            # Apply visibility before pagination and continue over hidden rows;
            # otherwise a private message page can hide the next public event.
            while len(audit_events) <= bounded:
                batch = database.list_events(
                    limit=201, cursor=scanned, from_ms=from_ms, to_ms=to_ms,
                    actor_ref=actor_ref,
                    subject_ref=subject_ref if related_refs is None else None,
                    through_event_seq=watermark,
                )
                if not batch:
                    break
                for event in batch:
                    scanned = event["event_seq"]
                    event = visible_event(event, viewer)
                    if event is not None and (
                        related_refs is None or event_matches_subject_refs(event, related_refs)
                    ):
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
                    "reason_code": event.get("reason_code") or audit_payload.get("reason_code")
                    # A refusal recorded by the HTTP layer keeps its reason in ``code``
                    # (``resource_conflict:file:…``); without this fallback the timeline
                    # could only say "this was denied" and never why.
                    or audit_payload.get("code"),
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
                    # Why a session was not ready at that moment: the verdict and the
                    # admission rows the report did not prove. Absent for every other
                    # kind of event (and for events recorded before this existed).
                    "session_status": audit_payload.get("session_status"),
                    "missing_admission": list(audit_payload.get("missing_admission") or []),
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
        if kind == "decisions":
            if viewer is None:
                raise PermissionError("authentication_failed")
            return {
                "project_id": project_id,
                "items": [
                    {"decision_id": decision.decision_id, "kind": decision.kind,
                     "subject_ref": decision.subject_ref,
                     # Two spellings for the same two values, on purpose: the console reads
                     # ``expected_revision``/``input_digest`` (the model's own attribute
                     # names), while the daemon's resolve command and the Codex-side tests
                     # read ``revision``/``proposal_digest``. Dropping either name would
                     # silently break a live consumer, so both are served until one
                     # canonical name is agreed.
                     "expected_revision": decision.expected_revision,
                     "revision": decision.expected_revision,
                     "input_digest": decision.input_digest,
                     "proposal_digest": decision.input_digest,
                     "status": decision.status, "choices": decision.choices,
                     "summary": decision.summary,
                     "decision": decision.decision, "reason": decision.reason,
                     # What is being decided, including the choices offered: a pending
                     # decision nobody can read is one nobody can answer.
                     "payload": decision.payload}
                    for decision in lifecycle.decisions.values()
                ] if lifecycle is not None else [],
            }
        if kind == "operations" and database is not None:
            with database._connect() as conn:
                rows = conn.execute(
                    "SELECT id,kind,status,error_code,revision,created_at,updated_at FROM operations "
                    "WHERE project_id=? ORDER BY created_at", (database.project_id,),
                ).fetchall()
            return {"items": [dict(row) for row in rows]}
        if kind == "checkpoint_failures" and database is not None:
            # A checkpoint that never materialized is the one case where the answer to
            # "is my work durable" is no — and that answer has to be readable *before*
            # anyone can retry it. The console lists these rows and hands their ids to
            # `checkpoint.create.user`, so this exit reads the same ledger that retry
            # path writes: the operations table (a failed column on the checkpoint page
            # would have to be invented; an operation that failed never produced one).
            with database._connect() as conn:
                rows = conn.execute(
                    """SELECT o.id,o.status,o.error_code,o.requested_by,o.revision,
                              o.created_at,o.updated_at,
                              j.payload_json,j.attempt_count,j.max_attempts
                       FROM operations o LEFT JOIN jobs j ON j.operation_id=o.id
                       WHERE o.project_id=? AND o.kind='checkpoint.create'
                         AND o.status IN ('failed','retry_wait')
                       ORDER BY o.created_at DESC,o.id DESC""",
                    (database.project_id,),
                ).fetchall()
            failures: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                # Why the checkpoint was being taken is carried by the job's payload
                # (`request_checkpoint` writes the reason there), not by the operation row.
                raw_payload = item.pop("payload_json", None)
                try:
                    payload = json.loads(raw_payload) if raw_payload else {}
                except (TypeError, ValueError):
                    payload = {}
                item["operation_id"] = item.pop("id")
                item["reason"] = payload.get("reason") if isinstance(payload, dict) else None
                failures.append(item)
            return {"project_id": requested_project_id, "items": failures}
        if kind in {"checkpoints", "checkpoint_verify"} and checkpoint_store is not None:
            if viewer is None:
                raise PermissionError("authentication_failed")
            if kind == "checkpoint_verify":
                digest = requested_project_id
                manifest = checkpoint_store.load(digest)
                if manifest.get("project_id") not in {None, project_id}:
                    raise KeyError("checkpoint_not_found")
                manifest_relative = (
                    checkpoint_store._directory(digest) / "manifest.json"
                ).relative_to(Path(project_root).resolve()).as_posix() if project_root else ""
                anchors = GitAnchorScanner().scan(
                    Path(project_root).resolve() if project_root else Path.cwd(),
                    {digest}, {digest: manifest_relative} if manifest_relative else {},
                )
                return {
                    "digest": digest, "status": "verified", "project_id": manifest.get("project_id"),
                    "lineage_id": manifest["lineage_id"], "through_event_seq": manifest["through_event_seq"],
                    "created_at": format_timestamp(manifest.get("created_at")),
                    "verified_at": format_timestamp(manifest.get("verified_at")),
                    "git_anchors": [
                        {"ref_name": anchor.ref_name, "commit_oid": anchor.commit_oid}
                        for anchor in anchors if anchor.checkpoint_digest == digest
                    ],
                }
            if requested_project_id and project_id is not None and requested_project_id != project_id:
                raise KeyError("project_not_found")
            pointer = checkpoint_store.pointer
            current = json.loads(pointer.read_text(encoding="utf-8")) if pointer.is_file() else None
            items: list[dict[str, Any]] = []
            for manifest_file in sorted(checkpoint_store.checkpoints.glob("sha256_*/manifest.json")):
                try:
                    raw = json.loads(manifest_file.read_text(encoding="utf-8"))
                    digest = raw.get("digest")
                    if not isinstance(digest, str) or raw.get("project_id") not in {None, project_id}:
                        continue
                    if verify:
                        checkpoint_store.verify(digest)
                    items.append({
                        "digest": digest, "parent_digest": raw.get("parent_digest"),
                        "project_id": raw.get("project_id"), "lineage_id": raw.get("lineage_id"),
                        "through_event_seq": raw.get("through_event_seq"),
                        "format_version": raw.get("format_version"),
                        "schema_bundle_digest": raw.get("schema_bundle_digest"),
                        "created_at": format_timestamp(raw.get("created_at")),
                        "created_by": raw.get("created_by"), "reason": raw.get("reason"),
                        "projection_version": raw.get("projection_version"),
                        "verified_at": format_timestamp(raw.get("verified_at")),
                        "status": "verified" if verify else raw.get("status", "sealed"),
                        "artifact_digests": list(raw.get("artifact_digests", [])),
                    })
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    if verify:
                        raise ValueError("checkpoint_verification_failed") from exc
            items.sort(key=lambda item: (int(item.get("through_event_seq") or 0), item["digest"]))
            return {
                "project_id": project_id, "current": current, "items": items,
                "projection_version": "v1", "as_of_event_seq": database.last_event_seq() if database else 0,
            }
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
            "workspaces": ("workspace", "workspace_id"), "resources": ("reservation", "reservation_id"),
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


def _project_id(config: Mapping[str, str]) -> str | None:
    """Resolve a project id from the environment or the coordination repo."""
    configured = config.get("TSUNAGOU_PROJECT_ID")
    state_dir = config.get("TSUNAGOU_STATE_DIR")
    durable = _durable_project_snapshot(Path(state_dir) if state_dir else None)
    if durable is not None:
        durable_id = str(durable["project"]["project_id"])
        if configured and configured != durable_id:
            raise ValueError("configured_project_identity_mismatch")
        return durable_id
    if configured:
        return configured
    project_root = config.get("TSUNAGOU_PROJECT_ROOT")
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
