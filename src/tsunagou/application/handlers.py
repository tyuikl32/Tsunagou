"""Command handlers bound to domain services, preserving fail-closed semantics.

Each handler trusts only the principal/context resolved by the authenticator and
the grants checked inside ``AuthorityService.authorize``. None of these read
caller-supplied identity headers; the ticket secret and session credential stay in
memory and are returned only to the authenticated caller (the private delivery
channel).

Business object ids (``task_id``, ``proposal_id``, ``message_id``, ``obligation_id``,
``attempt_id``) arrive in the payload. The canonical registry expresses them as URI
path parameters (``/tasks/{id}:claim``) on project-scoped routes that the flat
``/api/v1/commands/{command_kind}`` entrypoint does not yet route; until that REST
surface lands, the bridge sends them in the payload and each handler fails with a
``*_required`` ``ValueError`` when one is missing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tsunagou import __version__
from tsunagou.application.workflows.lifecycle import LifecycleService
from tsunagou.application.workflows.task_execution import TaskExecutionWorkflow
from tsunagou.application.workspace_evidence import WorkspaceEvidence
from tsunagou.modules.artifacts import ArtifactService
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import Claim, CognitionService
from tsunagou.modules.coordination import CoordinationService
from tsunagou.modules.messaging import Message, MessageStore
from tsunagou.modules.projects import ProjectRegistry, physical_identity
from tsunagou.modules.resources import ResourceKey, ResourceRequest, ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.modules.workspaces import WorkspaceService
from tsunagou.platform.checkpoint_worker import CheckpointWorker
from tsunagou.platform.checkpoints import CheckpointStore
from tsunagou.shared_kernel.baseline import missing_admission_capabilities
from tsunagou.shared_kernel.time import format_timestamp, now_ms

Handler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _conversation_id(evidence: Any) -> str:
    """Extract the conversation identity string from enrollment evidence.

    The authority binds a ticket to a single ``conversation_id``; the enrollment
    schema carries it inside the opaque ``conversation_evidence`` object.
    """
    if isinstance(evidence, str) and evidence:
        return evidence
    if isinstance(evidence, dict):
        value = evidence.get("conversation_id") or evidence.get("id")
        if isinstance(value, str) and value:
            return value
    raise ValueError("conversation_id_required")


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key}_required")
    return value


def _admission_report(baseline: Any) -> dict[str, Any]:
    """Which of the four admission rows this report did *not* prove.

    The same shared rule the admission gate uses, so the receipt, the agents exit
    and the audit line can never disagree about why a session is degraded. The
    report's own contents are never echoed back — only the names of the rows it
    failed to prove.
    """

    report = baseline if isinstance(baseline, dict) else {}
    return {"missing_admission": sorted(missing_admission_capabilities(report))}


def _message_view(message: Message, messages: MessageStore | None = None) -> dict[str, Any]:
    view: dict[str, Any] = {
        "message_id": message.message_id,
        "sender_agent_id": message.sender_agent_id,
        "recipient_agent_id": message.recipient_agent_id,
        "kind": message.kind,
        "subject_ref": message.subject_ref,
        "summary": message.summary,
    }
    if messages is not None:
        obligations = [
            {
                "obligation_id": obligation.obligation_id,
                "status": obligation.status,
                "contract": obligation.contract,
            }
            for obligation in messages.obligations.values()
            if obligation.message_id == message.message_id
        ]
        if obligations:
            view["response_obligations"] = obligations
    return view


def _contract_view(proposal: Any) -> dict[str, Any]:
    """A contract as a reader needs it: identity, version, chain link, and its body.

    The body matters: agreeing to a digest without being able to read what it commits
    to is signing blind.
    """
    return {
        "proposal_id": proposal.proposal_id,
        "digest": proposal.digest,
        "status": proposal.status,
        "supersedes_id": proposal.supersedes_id,
        "resolution_reason": proposal.resolution_reason,
        "payload": proposal.payload,
    }


def _slot(item: Any, required: bool) -> dict[str, Any]:
    if isinstance(item, str):
        return {"slot": item, "required": required}
    if isinstance(item, dict):
        slot = item.get("slot") or item.get("agent_id") or item.get("id")
        if not isinstance(slot, str) or not slot:
            raise ValueError("participant_slot_required")
        entry: dict[str, Any] = {"slot": slot, "required": required}
        if "agent_id" in item:
            entry["agent_id"] = item["agent_id"]
        return entry
    raise ValueError("invalid_participant")


def _claim(item: Any) -> Claim:
    if not isinstance(item, dict):
        raise ValueError("invalid_claim")
    subject = item.get("subject_key") or item.get("subject")
    if not isinstance(subject, str) or not subject:
        raise ValueError("claim_subject_required")
    return Claim(
        subject_key=subject,
        claim_type=str(item.get("claim_type", "literal")),
        equality_key=str(item.get("equality_key", subject)),
        value=item.get("value"),
        evidence_refs=tuple(item.get("evidence_refs") or ()),
    )


def _resource_requests(items: Any) -> list[ResourceRequest]:
    if not isinstance(items, list) or not items:
        raise ValueError("resource_intent_empty")
    result: list[ResourceRequest] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("mode"), str):
            raise ValueError("invalid_resource_request")
        kind = item.get("kind", "path")
        if kind == "path":
            root_id = item.get("root_id")
            segments = item.get("segments") or ()
            if not isinstance(root_id, str) or not isinstance(segments, list | tuple):
                raise ValueError("invalid_path_resource")
            key = ResourceKey.path(root_id, *(str(segment) for segment in segments))
        elif kind == "named":
            namespace, name = item.get("namespace"), item.get("name")
            if not isinstance(namespace, str) or not isinstance(name, str):
                raise ValueError("invalid_named_resource")
            key = ResourceKey.named(namespace, name)
        else:
            raise ValueError("invalid_resource_kind")
        result.append(ResourceRequest(key, item["mode"]))
    return result


def _scope_allows_requests(scope: dict[str, Any], requests: list[ResourceRequest], supplied_digest: Any) -> None:
    """Enforce the explicit task resource prefix without interpreting intent."""
    if not scope:
        return
    expected_digest = scope.get("digest")
    if expected_digest is not None and str(supplied_digest or "") != str(expected_digest):
        raise ValueError("resource_scope_conflict")
    entries = scope.get("resources")
    roots = scope.get("roots")
    if entries is None and isinstance(roots, list):
        allowed_roots = {str(root) for root in roots}
        if not allowed_roots:
            raise PermissionError("task_scope_denied")
        for request in requests:
            if request.key.kind != "path" or str(request.key.root_id) not in allowed_roots:
                raise PermissionError("task_scope_denied")
        return
    if not isinstance(entries, list):
        raise ValueError("invalid_task_execution_scope")
    if not entries:
        raise PermissionError("task_scope_denied")
    allowed = _resource_requests(entries)
    for request in requests:
        permitted = False
        for candidate in allowed:
            if candidate.mode != request.mode:
                continue
            if request.key.kind == "named":
                permitted = candidate.key == request.key
            elif candidate.key.kind == "path" and request.key.kind == "path":
                permitted = (
                    candidate.key.root_id == request.key.root_id
                    and request.key.segments[:len(candidate.key.segments)] == candidate.key.segments
                )
            if permitted:
                break
        if not permitted:
            raise PermissionError("task_scope_denied")


class IllegalChangeRejected(ValueError):
    """A submitted workspace result contradicts what the daemon observed.

    Carries structured detail so the caller (bridge/agent) learns *what* is wrong,
    not just that something is. The message stays a bare machine code, so the API
    layer keeps its existing `detail["code"]` contract.
    """

    def __init__(
        self, code: str, *, violations: list[str], allowed: list[str], next_steps: list[str]
    ) -> None:
        super().__init__(code)
        self.detail: dict[str, Any] = {
            "violations": violations,
            "allowed": allowed,
            "next_steps": next_steps,
        }


def build_handlers(
    *, authority: AuthorityService, tasks: TaskService | None = None,
    cognition: CognitionService | None = None, messages: MessageStore | None = None,
    resources: ResourceService | None = None, workspaces: WorkspaceService | None = None,
    lifecycle: LifecycleService | None = None,
    project_id: str | None = None, strict_runtime: bool = False,
    database: Any | None = None, state_runtime: Any | None = None,
    checkpoint_store: CheckpointStore | None = None,
    checkpoint_worker: CheckpointWorker | None = None,
    schema_bundle_digest: str = "",
    project_root: str | None = None, artifact_root: str | None = None,
    project_registry: ProjectRegistry | None = None,
    coordination: CoordinationService | None = None,
    artifacts: ArtifactService | None = None,
) -> dict[str, Handler]:
    tasks = tasks if tasks is not None else TaskService()
    cognition = cognition if cognition is not None else CognitionService()
    messages = messages if messages is not None else MessageStore()
    resources = resources if resources is not None else ResourceService()
    workspaces = workspaces if workspaces is not None else WorkspaceService()
    coordination = coordination if coordination is not None else CoordinationService()
    execution_workflow = TaskExecutionWorkflow(
        tasks=tasks, cognition=cognition, resources=resources, workspaces=workspaces,
        strict_runtime=strict_runtime,
    )

    def _authorize(
        context: dict[str, Any], capability: str, *,
        task_id: str | None = None, attempt_id: str | None = None,
    ) -> None:
        agent_id = context["principal_id"]
        session_id = context["session_id"]
        grant = authority.find_grant(
            agent_id=agent_id, session_id=session_id, capability=capability,
            task_id=task_id, attempt_id=attempt_id,
        )
        if grant is None:
            raise PermissionError("capability_denied")
        authority.authorize(
            agent_id=agent_id, session_id=session_id, grant_id=grant.grant_id,
            capability=capability, task_id=task_id, attempt_id=attempt_id,
        )

    def _reconcile_expired_leases() -> None:
        """Revoke execution state when a lease expires before the next request."""
        # ``expire_due`` returns only rows whose status changed in this call.
        # Include already-expired rows too: a prior maintenance pass may have
        # persisted the Lease fence but crashed before reconciling the owning
        # Attempt.  The attempt/status guards below make this replay-safe.
        expired_ids = set(resources.expire_due())
        expired_ids.update(
            lease.lease_set_id for lease in resources.lease_sets.values()
            if lease.status == "expired"
        )
        for lease_id in expired_ids:
            lease = resources.lease_sets.get(lease_id)
            if lease is None:
                continue
            attempt = tasks.attempts.get(lease.attempt_id)
            if attempt is None:
                continue
            assignment = coordination.assignment_for_task(attempt.task_id)
            if attempt.status in {"claimed", "running"}:
                attempt.status = "orphaned"
                attempt.revision += 1
                task = tasks.tasks.get(attempt.task_id)
                if task is not None and task.current_attempt_id == attempt.attempt_id:
                    # Expiry fences only the old execution Attempt. The Task is
                    # returned to the public queue so a later Agent can claim it;
                    # the old Agent is not a prerequisite for recovery.
                    task.current_attempt_id = None
                    task.status = "open"
                    task.orphan_reason = "resource_lease_expired"
                    task.revision += 1
                for key, grant in list(authority.grants.items()):
                    if grant.attempt_id == attempt.attempt_id and grant.status == "active":
                        authority.grants[key] = type(grant)(
                            **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"}
                        )
            if assignment is not None:
                coordination.mark_lease_expired(attempt.task_id, attempt.attempt_id)

    def _assignment_id_for_task(task_id: str) -> str | None:
        assignment = coordination.assignment_for_task(task_id)
        return assignment.assignment_id if assignment is not None else None

    def _lease_guidance(attempt_id: str | None = None) -> dict[str, Any]:
        """Expose worker-owned renewal facts without renewing on its behalf."""
        with resources._lock:  # noqa: SLF001 - snapshot lease guidance atomically
            leases = [
                lease for lease in resources.lease_sets.values()
                if attempt_id is not None
                and lease.attempt_id == attempt_id
                and lease.status == "active"
            ]
            leases.sort(key=lambda item: item.lease_set_id)
            return {
                "renewal_owner": "worker",
                "renew_with": ["task.progress", "resource.renew"],
                "daemon_heartbeat": False,
                "leases": [
                    {
                        "lease_set_id": lease.lease_set_id,
                        "attempt_id": lease.attempt_id,
                        "status": lease.status,
                        "expires_at": lease.expires_at,
                    }
                    for lease in leases
                ],
            }

    def enroll(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        installation_id = payload.get("installation_id")
        if not isinstance(installation_id, str) or not installation_id:
            raise ValueError("installation_id_required")
        conversation_id = _conversation_id(payload.get("conversation_evidence"))
        baseline = payload.get("probe_payload")
        if baseline is not None and not isinstance(baseline, dict):
            raise ValueError("invalid_probe_payload")
        # context["principal_id"] is the one-time ticket secret carried by the T
        # bearer; redeem_ticket hashes it and enforces single-use/expiry/identity.
        receipt = authority.redeem_ticket(
            context["principal_id"], installation_id, conversation_id, baseline=baseline
        )
        return {
            "agent_id": receipt.agent_id,
            "session_id": receipt.session_id,
            "connection_epoch": receipt.connection_epoch,
            "baseline_status": receipt.baseline_status,
            "secret_token": receipt.secret_token,
            "reconnect_nonce": receipt.reconnect_nonce,
            **_admission_report(baseline),
        }

    def session_rebind(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        installation_id = payload.get("installation_id")
        if not isinstance(installation_id, str) or not installation_id:
            raise ValueError("installation_id_required")
        conversation_id = _conversation_id(payload.get("conversation_evidence"))
        target_agent_id = payload.get("target_agent_id")
        if target_agent_id is not None and (not isinstance(target_agent_id, str) or not target_agent_id):
            target_agent_id = None
        baseline = payload.get("probe_payload")
        if baseline is not None and not isinstance(baseline, dict):
            raise ValueError("invalid_probe_payload")
        # Resume path: a *fresh* one-time ticket (T bearer) bound to the same
        # conversation, redeemed against the already-attached session. This is what
        # yields identity.continuity_evidence honestly — the same conversation
        # digest, never a second identity, and never caller self-asserted identity.
        receipt = authority.redeem_rebind_ticket(
            context["principal_id"], installation_id, conversation_id,
            target_agent_id=target_agent_id, baseline=baseline,
        )
        return {
            "agent_id": receipt.agent_id,
            "session_id": receipt.session_id,
            "connection_epoch": receipt.connection_epoch,
            "baseline_status": receipt.baseline_status,
            "secret_token": receipt.secret_token,
            "reconnect_nonce": receipt.reconnect_nonce,
            **_admission_report(baseline),
        }

    def session_reconnect(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        session_id = _required_str(context, "session_id")
        reconnect_nonce = _required_str(payload, "reconnect_nonce")
        expected_connection_epoch = payload.get("expected_connection_epoch")
        if expected_connection_epoch is not None and not isinstance(expected_connection_epoch, int):
            raise ValueError("invalid_expected_connection_epoch")
        baseline = payload.get("probe_payload")
        if baseline is not None and not isinstance(baseline, dict):
            raise ValueError("invalid_probe_payload")
        # AuthorityService.rebind is the reconnect_nonce + connection_epoch
        # compare-and-swap: a stale nonce or epoch fails closed instead of
        # double-rotating the credential, which is what makes a reconnect
        # idempotent under retry (recovery.idempotent_reconnect).
        receipt = authority.rebind(
            session_id, expected_nonce=reconnect_nonce,
            expected_connection_epoch=expected_connection_epoch, baseline=baseline,
        )
        return {
            "agent_id": receipt.agent_id,
            "session_id": receipt.session_id,
            "connection_epoch": receipt.connection_epoch,
            "baseline_status": receipt.baseline_status,
            "secret_token": receipt.secret_token,
            "reconnect_nonce": receipt.reconnect_nonce,
            **_admission_report(baseline),
        }

    def issue_user_ticket(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        installation_id = payload.get("installation_id")
        if not isinstance(installation_id, str) or not installation_id:
            raise ValueError("installation_id_required")
        conversation_id = _conversation_id(payload.get("conversation_evidence"))
        ttl_seconds = payload.get("ttl_seconds", 600)
        role = payload.get("role", "worker")
        if role not in {"worker", "main"}:
            raise ValueError("invalid_requested_role")
        secret = authority.issue_ticket(
            installation_id, conversation_id, ttl_seconds=int(ttl_seconds), requested_role=role,
        )
        return {
            "installation_id": installation_id,
            "conversation_id": conversation_id,
            "requested_role": role,
            "secret": secret,
        }

    def appoint_main(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        agent_id = payload.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("agent_id_required")
        grant = authority.appoint_main(actor_kind="user_control", agent_id=agent_id)
        return {"main_agent_id": agent_id, "grant_id": grant.grant_id, "authority_epoch": authority.authority_epoch}

    def root_register(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "root.manage")
        if project_registry is None:
            raise RuntimeError("project_not_initialized")
        name = _required_str(payload, "name")
        root_kind = str(payload.get("kind", "directory"))
        binding_request = payload.get("binding_request")
        if not isinstance(binding_request, dict):
            raise ValueError("binding_request_required")
        absolute_path = binding_request.get("absolute_path") or binding_request.get("path")
        if not isinstance(absolute_path, str) or not absolute_path:
            raise ValueError("absolute_path_required")
        root_id = project_registry.register_root(
            name, absolute_path, root_kind=root_kind,
            required=bool(payload.get("required", False)),
        )
        binding = project_registry.local_bindings[root_id]
        return {
            "root_id": root_id,
            "name": name,
            "kind": root_kind,
            "status": binding["status"],
            "physical_identity": binding["physical_identity"],
        }

    def root_bind(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "root.manage")
        if project_registry is None:
            raise RuntimeError("project_not_initialized")
        root_id = _required_str(payload, "root_id")
        absolute_path = _required_str(payload, "absolute_path")
        expected_identity = payload.get("expected_physical_identity")
        actual_identity = physical_identity(Path(absolute_path))
        if expected_identity is not None and str(expected_identity) != actual_identity:
            raise ValueError("physical_identity_conflict")
        project_registry.bind_root(root_id, absolute_path)
        binding = project_registry.local_bindings[root_id]
        return {
            "root_id": root_id,
            "status": binding["status"],
            "binding_revision": binding["binding_revision"],
            "physical_identity": binding["physical_identity"],
        }

    def repository_register(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "root.manage")
        if project_registry is None:
            raise RuntimeError("project_not_initialized")
        name = _required_str(payload, "name")
        root_id = _required_str(payload, "root_id")
        binding = project_registry.local_bindings.get(root_id)
        if not binding or binding.get("status") != "bound":
            raise ValueError("root_binding_required")
        repository_id = project_registry.register_repository(
            name, root_id, physical_identity(Path(binding["absolute_path"])),
        )
        return {"repository_id": repository_id, "root_id": root_id, "name": name}

    def revoke_main(_payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        authority.revoke_main(actor_kind="user_control")
        return {"main_agent_id": None, "authority_epoch": authority.authority_epoch}

    def project_configure(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        try:
            _authorize(context, "project.configure")
        except PermissionError:
            # Main grants issued before this capability was introduced only
            # carry coordination.write; keep their upgrade path fail-closed
            # to current Main authority without broadening worker access.
            _authorize(context, "coordination.write")
        if context["principal_id"] != authority.main_agent_id:
            raise PermissionError("main_authority_required")
        if project_registry is None:
            raise RuntimeError("project_not_initialized")
        policy_patch = payload.get("policy_patch")
        if not isinstance(policy_patch, dict):
            raise ValueError("policy_patch_required")
        project = project_registry.configure(
            policy_patch=policy_patch,
            reason=_required_str(payload, "reason"),
        )
        return {
            "project_id": project.project_id,
            "policy_revision": project.policy_revision,
            "settings": dict(project.settings),
            "config_revision": project.config.revision if project.config else None,
        }

    def task_create(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        title = _required_str(payload, "title")
        objective = _required_str(payload, "objective")
        parent_task_id = payload.get("parent_task_id")
        blocks = set(payload.get("blocks") or [])
        execution_scope = payload.get("execution_scope")
        if execution_scope is not None and not isinstance(execution_scope, dict):
            raise ValueError("invalid_task_execution_scope")
        task = tasks.create_task(
            title, objective, parent_task_id=parent_task_id, blocks=blocks,
            execution_scope=execution_scope,
        )
        return {"task_id": task.task_id, "title": title, "objective": objective, "status": task.status}

    def _check_task_revisions(task: Any, payload: dict[str, Any]) -> None:
        expected = payload.get("expected_revisions")
        if expected is None:
            return
        if not isinstance(expected, dict):
            # Legacy in-process callers used a single opaque revision token;
            # only the typed object form carries per-domain expectations.
            return
        for key, actual in (("task", task.revision), ("scope", task.scope_revision)):
            value = expected.get(key)
            if value is not None and int(value) != actual:
                raise ValueError(f"{key}_revision_conflict")
        declared = expected.get("contract")
        if declared is None:
            return
        # Starting work is the one moment where "which contract version governs" has to
        # be settled, so the caller declares the versions it read. A declaration that is
        # not the version in force means it has not caught up with a revision yet.
        if not isinstance(declared, (list, tuple)) or sorted(
            str(item) for item in declared
        ) != list(cognition.current_contract_versions(task.task_id)):
            raise ValueError("contract_revision_conflict")

    def task_ready(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        task_id = _required_str(payload, "task_id")
        task = tasks.ready(task_id)
        return {"task_id": task_id, "status": task.status}

    def task_publish(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        task_id = _required_str(payload, "task_id")
        task = tasks.publish(task_id)
        return {"task_id": task_id, "status": task.status}

    def task_update_plan(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        task = tasks.update_plan(
            _required_str(payload, "task_id"),
            title=payload.get("title"), objective=payload.get("objective"),
        )
        return {"task_id": task.task_id, "status": task.status, "revision": task.revision}

    def task_edge_add(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        source = _required_str(payload, "source_task_id")
        target = _required_str(payload, "target_task_id")
        if payload.get("kind", "blocks") != "blocks":
            raise ValueError("unsupported_task_edge_kind")
        tasks.add_block(source, target)
        return {"source_task_id": source, "target_task_id": target, "kind": "blocks"}

    def task_edge_remove(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        source = _required_str(payload, "source_task_id")
        target = _required_str(payload, "target_task_id")
        tasks.remove_block(source, target)
        return {"source_task_id": source, "target_task_id": target, "removed": True}

    def task_claim(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.claim")
        task_id = _required_str(payload, "task_id")
        coordination.require_worker_ready(task_id, context["principal_id"])
        attempt = tasks.claim(task_id, context["principal_id"])
        coordination.mark_claimed(task_id, context["principal_id"], attempt.attempt_id)
        return {
            "task_id": task_id, "attempt_id": attempt.attempt_id, "status": attempt.status,
            "lease_guidance": _lease_guidance(attempt.attempt_id),
        }

    def task_resume(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        task = tasks.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        _check_task_revisions(task, payload)
        attempt = tasks.resume(task_id, context["principal_id"])
        expected_epoch = payload.get("expected_execution_epoch")
        if expected_epoch is not None and int(expected_epoch) != attempt.execution_epoch:
            raise ValueError("execution_epoch_conflict")
        return {"task_id": task_id, "attempt_id": attempt.attempt_id, "status": attempt.status}

    def task_preflight(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        attempt_id = payload.get("attempt_id")
        task = tasks.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        _check_task_revisions(task, payload)
        evidence_refs = tuple(payload.get("evidence_refs") or ())
        preflight = execution_workflow.preflight(
            task_id, context["principal_id"], attempt_id=attempt_id, evidence_refs=evidence_refs,
        )
        return {
            "task_id": task_id, "attempt_id": preflight.attempt_id,
            "preflight_id": preflight.preflight_id, "status": preflight.status,
            "input_digest": preflight.input_digest, "blockers": list(preflight.blockers),
        }

    def task_start(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        attempt_id = payload.get("attempt_id")
        preflight_id = payload.get("preflight_id")
        # ResourceService's lock is the execution fence shared with the
        # runtime maintenance loop. Holding it across expiry reconciliation,
        # TaskService.start, and execution-grant issuance prevents a lease
        # from expiring in the gap after validation but before the running
        # state/grant become visible together.
        with resources._lock:  # noqa: SLF001 - shared in-process state fence
            _reconcile_expired_leases()
            current_task = tasks.tasks.get(task_id)
            current_attempt = tasks.attempts.get(current_task.current_attempt_id or "") if current_task else None
            if current_task is None or current_attempt is None:
                if current_task is not None and current_task.orphan_reason == "resource_lease_expired":
                    raise ValueError("resource_lease_expired")
                raise KeyError(task_id)
            if attempt_id is not None and attempt_id != current_attempt.attempt_id:
                raise ValueError("attempt_id_mismatch")
            expected_epoch = payload.get("expected_execution_epoch")
            if expected_epoch is not None and int(expected_epoch) != current_attempt.execution_epoch:
                raise ValueError("execution_epoch_conflict")
            if preflight_id is None:
                raise ValueError("preflight_required")
            if preflight_id not in tasks.preflights:
                raise ValueError("preflight_id_mismatch")
            preflight = tasks.preflights[preflight_id]
            if preflight.task_id != task_id or preflight.attempt_id != current_attempt.attempt_id:
                raise ValueError("preflight_id_mismatch")
            if strict_runtime and payload.get("input_digest") and payload["input_digest"] != preflight.input_digest:
                raise ValueError("preflight_digest_mismatch")
            try:
                execution_workflow.start(preflight, agent_id=context["principal_id"])
            except ValueError as exc:
                # A failed start may have discovered a missing runtime
                # condition after a preflight lease was reserved. Keep blocked
                # work free of execution resources so another Agent can claim
                # it later.
                if str(exc) == "resource_lease_expired":
                    # The lease may have crossed its deadline after the first
                    # reconciliation pass but before the final start check.
                    # Run the same orphan/open + grant-revocation path again
                    # before releasing any remaining active rows.
                    _reconcile_expired_leases()
                resources.release_for_attempt(current_attempt.attempt_id, reason="task_start_blocked")
                for grant_id, grant in list(authority.grants.items()):
                    if grant.attempt_id == current_attempt.attempt_id and grant.status == "active":
                        authority.grants[grant_id] = type(grant)(
                            **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"}
                        )
                raise ValueError(str(exc)) from exc
            attempt = tasks.attempts[preflight.attempt_id]
            if attempt_id is not None and attempt_id != attempt.attempt_id:
                raise ValueError("attempt_id_mismatch")
            coordination.mark_started(task_id, context["principal_id"], attempt.attempt_id)
            grant = authority.issue_execution_grant(
                agent_id=context["principal_id"], session_id=context["session_id"],
                task_id=task_id, attempt_id=attempt.attempt_id, execution_epoch=attempt.execution_epoch,
            )
            return {
                "task_id": task_id, "attempt_id": attempt.attempt_id, "status": attempt.status,
                "execution_grant_id": grant.grant_id,
                "lease_guidance": _lease_guidance(attempt.attempt_id),
            }

    def task_progress(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _reconcile_expired_leases()
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        _authorize(context, "task.execute", task_id=task_id, attempt_id=attempt_id)
        progress = tasks.progress(
            task_id, context["principal_id"], attempt_id=attempt_id,
            summary=payload.get("summary") or "",
            evidence_refs=tuple(payload.get("evidence_refs") or ()),
        )
        renewed: list[dict[str, Any]] = []
        # A progress report also renews the active Lease. The lease scope is
        # read from the durable intent rather than caller input, so a worker
        # cannot renew a different scope while reporting progress.
        for lease in resources.lease_sets.values():
            if lease.attempt_id != attempt_id or lease.status != "active":
                continue
            renewed_lease = resources.renew(
                lease.lease_set_id, attempt_id=attempt_id,
                execution_epoch=tasks.attempts[attempt_id].execution_epoch,
                scope_digest=lease.scope_digest,
            )
            renewed.append({
                "lease_set_id": renewed_lease.lease_set_id,
                "expires_at": renewed_lease.expires_at,
            })
        coordination.record_event(
            "task.progress", actor_id=context["principal_id"], task_id=task_id,
            assignment_id=_assignment_id_for_task(task_id),
            summary=str(payload.get("summary") or ""), important=False,
        )
        return {
            "task_id": task_id, "attempt_id": attempt_id,
            "progress_id": progress.progress_id, "summary": progress.summary,
            "renewed_leases": renewed,
        }

    def task_block(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        current = tasks.tasks.get(task_id)
        if current is None:
            raise KeyError(task_id)
        attempt = tasks.attempts.get(current.current_attempt_id or "")
        if attempt is not None and attempt.owner_agent_id != context["principal_id"]:
            raise PermissionError("attempt_owner_required")
        previous_attempt_id = attempt.attempt_id if attempt is not None else None
        reason = payload.get("reason_code") or payload.get("reason") or "blocked"
        task = tasks.block(
            task_id, str(reason), checkpoint_summary=payload.get("checkpoint_summary") or {},
            dependency_refs=tuple(payload.get("dependency_refs") or ()),
            evidence_refs=tuple(payload.get("evidence_refs") or ()),
        )
        coordination.record_event(
            "task.blocked", actor_id=context["principal_id"], task_id=task_id,
            assignment_id=_assignment_id_for_task(task_id),
            summary=str(reason), important=True,
        )
        coordination.mark_blocked(task_id, context["principal_id"])
        if previous_attempt_id is not None:
            resources.release_for_attempt(previous_attempt_id, reason="task_blocked")
            for grant_id, grant in list(authority.grants.items()):
                if grant.attempt_id == previous_attempt_id and grant.status == "active":
                    authority.grants[grant_id] = type(grant)(
                        **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"}
                    )
        return {"task_id": task_id, "status": task.status}

    def task_submit(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        _authorize(context, "task.execute", task_id=task_id, attempt_id=attempt_id)
        # Capture the caller's attempt before reconciliation.  If a Lease is
        # already due, reconciliation intentionally orphans that Attempt and
        # revokes its execution grant; surface the deterministic Lease fence
        # to this command instead of allowing a stale submit to succeed.
        now = time.time()
        attempt_leases = [
            lease for lease in resources.lease_sets.values()
            if lease.attempt_id == attempt_id
        ]
        lease_expired = any(
            lease.status == "expired"
            or (lease.status == "active" and lease.expires_at <= now)
            for lease in attempt_leases
        )
        _reconcile_expired_leases()
        if lease_expired:
            raise ValueError("resource_lease_expired")
        if strict_runtime and cognition.unaligned_contracts_for_task(task_id):
            # A result must not be published while an agreement this task depends on
            # is unsettled, or has been revised past the one it worked under. This is
            # the "everyone is still working from the old agreement" failure.
            raise ValueError("contract_not_accepted")
        task = tasks.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        # Delivery is the second place where "which contract version governs" has to be
        # settled, and the same declaration the start boundary uses answers it here: a
        # result must not be published on top of a superseded agreement. The refusal
        # closes nothing — the attempt keeps running, its Lease stays held and its files
        # stay in place — so the caller can read the current version, bring the work up
        # to date and submit again, instead of starting over.
        _check_task_revisions(task, payload)
        work = {key: value for key, value in payload.items() if key not in {"task_id", "attempt_id"}}
        try:
            result = execution_workflow.submit(
                task_id, context["principal_id"], work, attempt_id=attempt_id,
            )
        except ValueError as exc:
            # A deadline may pass after the initial reconciliation but before
            # the workflow's atomic check.  Re-run the normal orphan/revoke
            # path before returning the failure to the caller.
            if str(exc) == "resource_lease_expired":
                _reconcile_expired_leases()
            raise
        coordination.mark_submitted(task_id, context["principal_id"], attempt_id)
        coordination.record_event(
            "task.submitted", actor_id=context["principal_id"], task_id=task_id,
            assignment_id=_assignment_id_for_task(task_id),
            summary=result.digest, important=True,
        )
        if strict_runtime and authority.main_agent_id and authority.main_agent_id != context["principal_id"]:
            reviewer_session = next(
                (session for session in authority.sessions.values()
                 if session.agent_id == authority.main_agent_id and session.active and session.status == "ready"),
                None,
            )
            if reviewer_session is not None:
                authority.issue_grant(
                    issuer_agent_id=authority.main_agent_id, kind="task_review",
                    principal_id=authority.main_agent_id, session_id=reviewer_session.session_id,
                    task_id=task_id, capabilities={"task.review"}, scope={"task_id": task_id},
                )
        return {"result_id": result.result_id, "task_id": task_id, "attempt_id": attempt_id, "digest": result.digest}

    def task_cancel_request(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        task = tasks.request_cancel(_required_str(payload, "task_id"), _required_str(payload, "reason"))
        return {"task_id": task.task_id, "status": task.status, "revision": task.revision}

    def task_cancel_ack(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task = tasks.acknowledge_cancel(
            _required_str(payload, "task_id"), context["principal_id"],
            attempt_id=_required_str(payload, "attempt_id"),
        )
        resources.release_for_attempt(payload["attempt_id"], reason="task_cancelled")
        return {"task_id": task.task_id, "status": task.status, "revision": task.revision}

    def task_fail(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task = tasks.fail(
            _required_str(payload, "task_id"), context["principal_id"],
            attempt_id=_required_str(payload, "attempt_id"), reason=_required_str(payload, "reason"),
        )
        coordination.mark_failed(task.task_id, context["principal_id"])
        resources.release_for_attempt(payload["attempt_id"], reason="task_failed")
        return {"task_id": task.task_id, "status": task.status, "revision": task.revision}

    def task_recover(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        task_id = _required_str(payload, "task_id")
        task = tasks.recover(
            task_id, expected_attempt_id=_required_str(payload, "expected_attempt_id"),
            disposition=_required_str(payload, "disposition"),
        )
        resources.release_for_attempt(payload["expected_attempt_id"], reason="task_recovered")
        for grant_id, grant in list(authority.grants.items()):
            if grant.attempt_id == payload["expected_attempt_id"] and grant.status == "active":
                authority.grants[grant_id] = type(grant)(
                    **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"}
                )
        return {"task_id": task_id, "status": task.status, "revision": task.revision}

    def task_scope_request(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        expected_revisions = payload.get("expected_revisions")
        if expected_revisions is not None:
            if not isinstance(expected_revisions, dict):
                raise ValueError("expected_revisions_object_required")
            task = tasks.tasks.get(task_id)
            if task is None:
                raise KeyError(task_id)
            for key, actual in (("task", task.revision), ("scope", task.scope_revision)):
                expected = expected_revisions.get(key)
                if expected is not None and expected != actual:
                    raise ValueError(f"{key}_revision_conflict")
        attempt = tasks.attempts.get(attempt_id)
        if attempt is None or attempt.task_id != task_id or attempt.owner_agent_id != context["principal_id"]:
            raise PermissionError("attempt_owner_required")
        request_id = tasks.request_scope(task_id, payload.get("requested_scope") or {}, context["principal_id"])
        return {"scope_request_id": request_id, "task_id": task_id, "status": "pending"}

    def task_scope_resolve(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        request_id = _required_str(payload, "scope_request_id")
        choice = _required_str(payload, "choice")
        if choice == "approve":
            def revoke_task_grants(task_id: str) -> None:
                for grant_id, grant in list(authority.grants.items()):
                    if grant.task_id == task_id and grant.status == "active":
                        authority.grants[grant_id] = type(grant)(
                            **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"}
                        )

            task = tasks.approve_scope(
                request_id, approved_scope=payload.get("approved_scope") or {},
                approver=context["principal_id"],
                revoke_grants=revoke_task_grants,
            )
            return {"scope_request_id": request_id, "task_id": task.task_id, "status": "approved"}
        if choice == "reject":
            request = tasks.reject_scope(request_id, approver=context["principal_id"])
            return {"scope_request_id": request_id, "task_id": request["task_id"], "status": "rejected"}
        raise ValueError("invalid_scope_choice")

    def task_self_accept(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        result = tasks.results.get(_required_str(payload, "result_id"))
        if result is None or result.task_id != task_id or result.submitted_by != context["principal_id"]:
            raise PermissionError("result_owner_required")
        if result.digest != _required_str(payload, "result_digest"):
            raise ValueError("result_digest_mismatch")
        review = tasks.review(task_id, context["principal_id"], result.result_id, decision="accepted",
                              reason=payload.get("reason"))
        resources.release_for_attempt(result.attempt_id, reason="self_accepted")
        return {"task_id": task_id, "result_id": result.result_id, "status": tasks.tasks[task_id].status,
                "decision": review.decision}

    def resource_intent(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "resource.intent")
        if project_registry is not None:
            resources.set_root_aliases({
                root_id: str(binding.get("physical_identity") or root_id)
                for root_id, binding in project_registry.local_bindings.items()
            })
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        attempt = tasks.attempts.get(attempt_id)
        if attempt is None or attempt.task_id != task_id or attempt.owner_agent_id != context["principal_id"]:
            raise PermissionError("attempt_owner_required")
        task = tasks.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        requests = _resource_requests(payload.get("resources"))
        _scope_allows_requests(task.execution_scope, requests, payload.get("scope_digest"))
        intent = resources.declare_intent(
            task_id=task_id, attempt_id=attempt_id, owner_agent_id=context["principal_id"],
            scope_digest=str(payload.get("scope_digest") or ""),
            resources=requests, reason=str(payload.get("reason") or ""),
        )
        return {"intent_id": intent.intent_id, "revision": intent.revision,
                "task_id": task_id, "attempt_id": attempt_id}

    def resource_acquire(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _reconcile_expired_leases()
        _authorize(context, "resource.acquire")
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        intent_id = _required_str(payload, "intent_id")
        intent = resources.intents.get(intent_id)
        attempt = tasks.attempts.get(attempt_id)
        if intent is None or attempt is None or intent.task_id != task_id or intent.attempt_id != attempt_id:
            raise ValueError("resource_intent_attempt_mismatch")
        if attempt.owner_agent_id != context["principal_id"]:
            raise PermissionError("attempt_owner_required")
        coordination.require_worker_ready(task_id, context["principal_id"])
        expected_revision = payload.get("intent_revision")
        if expected_revision is not None and int(expected_revision) != intent.revision:
            raise ValueError("resource_intent_revision_conflict")
        scope_digest = payload.get("scope_digest")
        if scope_digest is not None and str(scope_digest) != intent.scope_digest:
            raise ValueError("resource_scope_conflict")
        lease = resources.reserve_set(intent_id, execution_epoch=attempt.execution_epoch, attempt_status=attempt.status)
        return {
            "lease_set_id": lease.lease_set_id, "attempt_id": attempt_id,
            "expires_at": lease.expires_at, "status": lease.status,
            "lease_guidance": _lease_guidance(attempt_id),
        }

    def resource_release(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "resource.release")
        attempt_id = _required_str(payload, "attempt_id")
        attempt = tasks.attempts.get(attempt_id)
        if attempt is None or attempt.owner_agent_id != context["principal_id"]:
            raise PermissionError("attempt_owner_required")
        return {"attempt_id": attempt_id, "released": resources.release_for_attempt(
            attempt_id, reason=str(payload.get("reason") or "released"))}

    def resource_renew(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _reconcile_expired_leases()
        lease_id = _required_str(payload, "lease_set_id")
        attempt_id = _required_str(payload, "attempt_id")
        _authorize(context, "task.execute", attempt_id=attempt_id)
        attempt = tasks.attempts.get(attempt_id)
        lease = resources.lease_sets.get(lease_id)
        if attempt is None or lease is None:
            raise KeyError(lease_id)
        renewed = resources.renew(
            lease_id, attempt_id=attempt_id, execution_epoch=attempt.execution_epoch,
            scope_digest=str(payload.get("scope_digest") or ""),
        )
        return {"lease_set_id": renewed.lease_set_id, "expires_at": renewed.expires_at, "status": renewed.status}

    def workspace_select(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "workspace.select")
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        attempt = tasks.attempts.get(attempt_id)
        if attempt is None or attempt.task_id != task_id:
            raise ValueError("task_attempt_relationship_required")
        decision = workspaces.record_isolation_decision(
            task_id=task_id, attempt_id=attempt_id, driver_kind=_required_str(payload, "driver_kind"),
            input_snapshot={"input_digest": payload.get("input_digest"), "task_id": task_id,
                            "attempt_id": attempt_id},
            hard_constraints=set(payload.get("hard_constraints") or ()),
            evidence_refs=list(payload.get("evidence_refs") or ()), decided_by=context["principal_id"],
        )
        return {"decision_id": decision.decision_id, "decision_digest": decision.decision_digest,
                "driver_kind": decision.driver_kind, "status": "selected"}

    def workspace_prepare(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "workspace.prepare")
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        decision_id = _required_str(payload, "decision_id")
        attempt = tasks.attempts.get(attempt_id)
        decision = workspaces.decisions.get(decision_id)
        if attempt is None or decision is None or attempt.task_id != task_id or decision.attempt_id != attempt_id:
            raise ValueError("workspace_decision_attempt_mismatch")
        if attempt.owner_agent_id != context["principal_id"]:
            raise PermissionError("attempt_owner_required")
        evidence = WorkspaceEvidence(workspaces, project_registry, project_root) if project_root else None
        scope_roots = evidence.resolve_scope(tasks.tasks[task_id], list(payload.get("root_binding_refs") or ())) if evidence else []
        scope_paths = evidence.virtual_paths(scope_roots) if evidence else None
        workspace = workspaces.request_workspace(
            decision_id, root_binding_refs=[root["root_id"] for root in scope_roots] or list(payload.get("root_binding_refs") or ()),
            repository_id=payload.get("repository_id"), external_locator=payload.get("external_locator"),
            current_main_id=authority.main_agent_id,
            scope_paths=scope_paths, scope_roots=scope_roots,
        )
        baseline = payload.get("baseline") or {}
        if not isinstance(baseline, dict):
            raise ValueError("invalid_baseline")
        if strict_runtime and evidence and decision.driver_kind == "shared":
            observed = evidence.scan(workspace, tasks.tasks[task_id])
            baseline = {**baseline, **observed}
        manifest = workspaces.record_baseline(
            workspace.workspace_id, head_commit=baseline.get("head_commit"), branch=baseline.get("branch"),
            index_digest=str(baseline.get("index_digest") or ""),
            tracked_state_digest=str(baseline.get("tracked_state_digest") or ""),
            untracked_summary=list(baseline.get("untracked_summary") or ()),
            root_identities=list(baseline.get("root_identities") or ()), dirty=bool(baseline.get("dirty", False)),
            root_observations=list(baseline.get("root_observations") or ()),
        )
        return {"workspace_id": workspace.workspace_id, "status": workspace.status,
                "baseline_manifest_id": manifest.manifest_id, "baseline_digest": manifest.digest,
                "scope_digest": workspace.scope_digest, "scope_roots": list(workspace.scope_roots),
                "observed_state_digest": manifest.tracked_state_digest}

    def _reject_unreported_changes(
        *, payload: dict[str, Any], observed: dict[str, Any], attempt_id: str
    ) -> None:
        """Reject a workspace result that leaves out a change made inside its own lease.

        Runs *before* anything is written, so raising here rolls the whole command
        back and leaves no state behind. That is what makes self-repair possible: the
        agent declares or rolls the path back and simply re-submits (idempotent).

        Scope compliance is deliberately *not* re-checked here. The recorded paths must
        already be a subset of what the daemon observed, and every recorded path must
        fall inside the workspace's prepared scope, so the forward direction already
        has an owner. This gate owns only the reverse direction: a change the daemon
        saw inside the Attempt's own leased area that the Attempt never declared.
        """
        reported = {str(path) for path in (payload.get("changed_paths") or ()) if str(path)}
        # Newly created files land in untracked_summary, modified ones in
        # changed_paths; both are candidate evidence of this Attempt's edits.
        seen = {str(path) for path in (observed.get("changed_paths") or ()) if str(path)}
        seen |= {str(path) for path in (observed.get("untracked_summary") or ()) if str(path)}
        # `.tsunagou` / `.git` never reach either set: path normalisation refuses them
        # and the scanner drops them, so no private-path filtering is needed here.
        #
        # A single-root workspace reports plain relative paths, while a multi-root one
        # prefixes every path with `<root_id>/`. A lease key carries the root id plus
        # case-folded segments, so it is matched in both shapes, with both sides
        # case-folded to agree with the lease vocabulary itself.
        prefixes: list[tuple[str, ...]] = []
        allowed_labels: list[str] = []
        for lease in resources.lease_sets.values():
            if lease.attempt_id != attempt_id or lease.status != "active":
                continue
            for request in lease.resources:
                if request.key.kind != "path":
                    continue
                if request.mode not in {"exclusive_write", "exclusive_use"}:
                    continue
                segments = tuple(part.casefold() for part in request.key.segments)
                if not segments:
                    continue
                prefixes.append(segments)
                root_id = str(request.key.root_id or "").casefold()
                if root_id:
                    prefixes.append((root_id, *segments))
                allowed_labels.append("/".join(request.key.segments) or request.key.canonical)

        def _covered(path: str) -> bool:
            parts = tuple(part.casefold() for part in path.replace("\\", "/").split("/") if part)
            return bool(parts) and any(parts[: len(prefix)] == prefix for prefix in prefixes)

        # A change observed *inside* this Attempt's own leased area but never declared
        # is the Attempt's doing. Outside that area ownership cannot be attributed
        # (user edits, other attempts, the daemon's own writes), so those paths stay
        # part of the recorded result instead of blocking the Attempt.
        unreported = sorted(path for path in (seen - reported) if _covered(path))
        if not unreported:
            return
        raise IllegalChangeRejected(
            "unreported_changes",
            violations=unreported,
            allowed=sorted(set(allowed_labels)),
            next_steps=[
                "declare the paths listed above in changed_paths, or roll them back if they "
                "were not intended; never restore the whole workspace (that would wipe the "
                "user's uncommitted edits)",
                "if these changes are genuinely required but outside this task's purpose, "
                "request a wider execution scope or escalate a user decision",
                "re-submit the same result after the fix; repeated submission is safe",
            ],
        )

    def workspace_result(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        workspace_id = _required_str(payload, "workspace_id")
        _authorize(context, "task.execute", task_id=task_id, attempt_id=attempt_id)
        workspace = workspaces.workspaces.get(workspace_id)
        if workspace is None or workspace.attempt_id != attempt_id:
            raise ValueError("workspace_attempt_mismatch")
        attempt = tasks.attempts.get(attempt_id)
        if attempt is None or attempt.status != "running":
            # Recording a result is part of the execution, not a postscript: a
            # submitted or fenced Attempt has already released its Lease, so the
            # adjudication below could no longer attribute anything to it. Pinning
            # the order (result first, submit second) is what keeps it sound.
            raise ValueError("attempt_not_running")
        observed: dict[str, Any] = {}
        started_at = now_ms()
        if strict_runtime and project_root and workspace.driver_kind == "shared":
            observed = WorkspaceEvidence(workspaces, project_registry, project_root).scan(
                workspace, tasks.tasks[task_id], include_patch=True,
            )
        # Caller supplied paths are evidence claims, never an authorization
        # expansion.  record_result re-checks every path against the persisted
        # scope; observed paths are the daemon's independent facts.
        changed_paths = list(observed["changed_paths"] if observed else payload.get("changed_paths") or ())
        untracked_summary = list(observed["untracked_summary"] if observed else payload.get("untracked_summary") or ())
        if observed and not set(payload.get("changed_paths") or ()).issubset(changed_paths):
            raise ValueError("workspace_changed_paths_mismatch")
        supplied_patch_ref = payload.get("patch_artifact_ref")
        patch_artifact_ref = supplied_patch_ref
        if supplied_patch_ref is not None:
            if artifacts is None or state_runtime is None:
                raise PermissionError("artifact_service_required")
            supplied_bytes = artifacts.validate_workspace_ref(
                supplied_patch_ref, workspace_id=workspace_id, actor=context["principal_id"],
                project_id=project_id or "local-project", lineage_id=state_runtime.lineage_id,
                scope_digest=workspace.scope_digest or "",
            )
            if observed and supplied_bytes != observed["patch_bytes"]:
                raise ValueError("workspace_patch_artifact_mismatch")
        if observed.get("patch_bytes") and supplied_patch_ref is None:
            if artifacts is None or state_runtime is None:
                raise RuntimeError("artifact_service_required")
            reference = artifacts.record_workspace_patch(
                observed["patch_bytes"], workspace_id=workspace_id, actor=context["principal_id"],
                project_id=project_id or "local-project", lineage_id=state_runtime.lineage_id,
                scope_digest=workspace.scope_digest or "",
            )
            patch_artifact_ref = reference.artifact_ref
        if strict_runtime:
            # Submit-time adjudication. Reject before writing anything so the
            # transaction rolls back cleanly and a retry can succeed after repair.
            _reject_unreported_changes(payload=payload, observed=observed, attempt_id=attempt_id)
        baseline = workspaces.baselines.get(workspace.baseline_manifest_id or "")
        observed_state_digest = observed.get("tracked_state_digest")
        baseline_conflict = bool(observed_state_digest and baseline and observed_state_digest != baseline.tracked_state_digest)
        result = workspaces.record_result(
            workspace_id, attempt_id=attempt_id, baseline_digest=_required_str(payload, "baseline_digest"),
            commit_refs=list(payload.get("commit_refs") or ()), patch_artifact_ref=patch_artifact_ref,
            changed_paths=changed_paths,
            untracked_summary=untracked_summary,
            validation_refs=list(payload.get("validation_refs") or ()),
            observed_state_digest=observed_state_digest,
            baseline_conflict=baseline_conflict,
            submitted_by=context["principal_id"],
            root_observations=list(observed.get("root_observations") or ()),
            evidence_level="system_verified" if observed else "agent_asserted",
            validation_metadata=list(payload.get("validation_metadata") or ()),
            observed_validation_metadata=([
                {
                    "started_at": format_timestamp(started_at),
                    "finished_at": format_timestamp(now_ms()),
                    "command": "workspace.scan",
                    "exit_code": 0,
                    "tool": "tsunagou",
                    "tool_version": __version__,
                    "workspace_digest": observed.get("tracked_state_digest") or "unknown",
                    "evidence_level": "system_verified",
                }
            ] if observed else None),
        )
        return {"result_manifest_id": result.manifest_id, "digest": result.digest,
                "workspace_id": workspace_id, "status": workspace.status,
                "baseline_conflict": result.baseline_conflict,
                "observed_state_digest": result.observed_state_digest,
                "scope_digest": result.scope_digest,
                "submitted_by": result.submitted_by, "observed_at": format_timestamp(result.observed_at),
                "evidence_level": result.evidence_level,
                "observed_by": "daemon" if observed else None,
                "evidence_subject": "workspace_filesystem_observation" if observed else "agent_assertion",
                "validation_metadata": list(result.validation_metadata),
                **({"patch_artifact_ref": result.patch_artifact_ref} if result.patch_artifact_ref else {})}

    def workspace_integrate(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Create a Main-only, no-push integration request from a worker result."""
        _authorize(context, "workspace.select")
        if context["principal_id"] != authority.main_agent_id:
            raise PermissionError("main_authority_required")
        request = workspaces.request_integration(
            source_result_ref=_required_str(payload, "source_result_ref"),
            target_repository_id=_required_str(payload, "target_repository_id"),
            target_baseline_digest=_required_str(payload, "target_baseline_digest"),
            plan_digest=_required_str(payload, "plan_digest"),
            reason=_required_str(payload, "reason"),
            actor_main_id=context["principal_id"],
        )
        return {
            "request_id": request.request_id,
            "workspace_id": request.workspace_id,
            "action": request.action,
            "status": request.status,
            "exact_input_digest": request.exact_input_digest,
            "push_allowed": False,
        }

    def task_review(payload: dict[str, Any], context: dict[str, Any], *, decision: str) -> dict[str, Any]:
        task_id = _required_str(payload, "task_id")
        result_id = _required_str(payload, "result_id")
        _authorize(context, "task.review", task_id=task_id)
        result = tasks.results.get(result_id)
        if result is None or result.task_id != task_id:
            raise ValueError("result_task_mismatch")
        if payload.get("result_digest") != result.digest:
            raise ValueError("result_digest_mismatch")
        review = tasks.review(
            task_id, context["principal_id"], result_id, decision=decision,
            reason=payload.get("reason"),
        )
        if decision == "accepted":
            resources.release_for_attempt(result.attempt_id, reason="review_accepted")
            coordination.mark_completed(task_id, result.submitted_by, result.attempt_id)
        elif decision == "changes_requested":
            # A review that sends work back closes the current execution just as
            # a recovery does.  The next attempt must receive a fresh claim,
            # preflight, lease set and execution grant.
            resources.release_for_attempt(result.attempt_id, reason="review_changes_requested")
            for grant_id, grant in list(authority.grants.items()):
                if grant.attempt_id == result.attempt_id and grant.status == "active":
                    authority.grants[grant_id] = type(grant)(
                        **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"}
                    )
            assignment = coordination.assignment_for_task(task_id)
            wake = coordination.rework(
                assignment.assignment_id, reason=str(payload.get("reason") or "review_changes_requested"),
            ) if assignment is not None else None
            return {"task_id": task_id, "result_id": result_id, "decision": review.decision,
                    "status": tasks.tasks[task_id].status,
                    "wake_attempt_id": wake.wake_attempt_id if wake is not None else None}
        return {"task_id": task_id, "result_id": result_id, "decision": review.decision,
                "status": tasks.tasks[task_id].status}

    def user_decision_propose(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "user.decision.propose")
        if lifecycle is None:
            raise RuntimeError("lifecycle_not_available")
        revisions = payload.get("expected_revisions")
        expected_revision = revisions.get("decision", 1) if isinstance(revisions, dict) else int(revisions or 1)
        decision = lifecycle.request_decision(
            kind=_required_str(payload, "kind"), subject_ref=_required_str(payload, "proposal_ref"),
            payload={"choices": payload.get("choices"), "summary": payload.get("summary")},
            expected_revision=expected_revision,
        )
        supplied = payload.get("proposal_digest")
        if supplied and supplied != decision.input_digest:
            raise ValueError("proposal_digest_mismatch")
        related_task = tasks.tasks.get(decision.subject_ref)
        if related_task is not None and related_task.status not in {"completed", "cancelled"}:
            previous_attempt_id = related_task.current_attempt_id
            tasks.block(related_task.task_id, f"user_decision_pending:{decision.decision_id}")
            if previous_attempt_id is not None:
                resources.release_for_attempt(previous_attempt_id, reason="user_decision_pending")
                for grant_id, grant in list(authority.grants.items()):
                    if grant.attempt_id == previous_attempt_id and grant.status == "active":
                        authority.grants[grant_id] = type(grant)(
                            **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"}
                        )
        return {"decision_id": decision.decision_id, "proposal_digest": decision.input_digest,
                "revision": decision.expected_revision, "status": decision.status,
                "related_task_id": related_task.task_id if related_task is not None else None}

    def user_decision_resolve(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if context["kind"] != "U" or lifecycle is None:
            raise PermissionError("user_only")
        decision_id = _required_str(payload, "decision_id")
        item = lifecycle.decisions.get(decision_id)
        if item is None:
            raise KeyError(decision_id)
        revisions = payload.get("expected_revisions")
        expected = revisions.get("decision") if isinstance(revisions, dict) else revisions
        if expected is not None and int(expected) != item.expected_revision:
            raise ValueError("decision_revision_or_digest_conflict")
        resolved = lifecycle.resolve_decision(
            decision_id, actor_kind="user_control", decision=_required_str(payload, "choice"),
            input_digest=_required_str(payload, "proposal_digest"), reason=payload.get("reason"),
        )
        return {"decision_id": resolved.decision_id, "status": resolved.status, "decision": resolved.decision,
                "related_task_id": resolved.subject_ref if resolved.subject_ref in tasks.tasks else None}

    def completion_propose(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "user.decision.propose")
        if lifecycle is None or lifecycle.registry.project is None:
            raise RuntimeError("lifecycle_not_available")
        project = lifecycle.registry.project
        decision = lifecycle.request_decision(
            kind="project.complete", subject_ref=_required_str(payload, "objective_ref"),
            payload={"outstanding_summary": payload.get("outstanding_summary"),
                     "evidence_refs": payload.get("evidence_refs")},
            expected_revision=int(payload.get("expected_project_revision", project.policy_revision)),
        )
        return {"proposal_id": decision.decision_id, "proposal_digest": decision.input_digest,
                "revision": decision.expected_revision, "status": decision.status}

    def completion_confirm(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if context["kind"] != "U" or lifecycle is None or lifecycle.registry.project is None:
            raise PermissionError("user_only")
        proposal_id = _required_str(payload, "proposal_id")
        item = lifecycle.decisions.get(proposal_id)
        project = lifecycle.registry.project
        if item is None or item.kind != "project.complete":
            raise KeyError(proposal_id)
        if int(payload.get("expected_project_revision", project.policy_revision)) != project.policy_revision:
            raise ValueError("project_revision_conflict")
        lifecycle.resolve_decision(
            proposal_id, actor_kind="user_control", decision="approved",
            input_digest=_required_str(payload, "proposal_digest"), reason="project_completion_confirmed",
        )
        project.lifecycle = "completed"
        project.policy_revision += 1
        result = {"proposal_id": proposal_id, "project_id": project.project_id,
                  "status": project.lifecycle, "revision": project.policy_revision}
        if checkpoint_worker is not None:
            result.update(request_checkpoint(context, "project_completion"))
        elif strict_runtime:
            raise RuntimeError("checkpoint_not_available")
        return result

    def request_checkpoint(context: dict[str, Any], reason: str, minimum_event_seq: Any = None) -> dict[str, Any]:
        uow = context.get("_uow")
        if checkpoint_worker is None or uow is None:
            raise RuntimeError("checkpoint_not_available")
        if minimum_event_seq is not None:
            if not isinstance(minimum_event_seq, int) or isinstance(minimum_event_seq, bool) or minimum_event_seq < 0:
                raise ValueError("checkpoint_minimum_event_seq_invalid")
            latest = uow.conn.execute("SELECT COALESCE(MAX(event_seq),0) FROM events WHERE project_id=?",
                                      (uow.project_id,)).fetchone()[0]
            if minimum_event_seq > latest:
                raise ValueError("checkpoint_minimum_event_seq_not_reached")
        operation_id = uow.create_operation(
            kind="checkpoint.create", requested_by=context["principal_id"], payload={"reason": reason},
        )
        context["_checkpoint_request"] = {"operation_id": operation_id,
                                          "created_by": context["principal_id"], "reason": reason}
        return {"operation_id": operation_id, "checkpoint_status": "pending"}

    def checkpoint_create_user(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if context["kind"] != "U":
            raise PermissionError("user_only")
        if lifecycle is None or lifecycle.registry.project is None:
            raise RuntimeError("project_not_initialized")
        if payload.get("retry_operation_id"):
            if checkpoint_worker is None:
                raise RuntimeError("checkpoint_not_available")
            operation_id = checkpoint_worker.retry(
                context["_uow"], actor=context["principal_id"], operation_id=payload["retry_operation_id"],
            )
            return {"operation_id": operation_id, "checkpoint_status": "pending"}
        return request_checkpoint(context, str(payload.get("reason", "user_requested")), payload.get("minimum_event_seq"))

    def checkpoint_create_main(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "durability.checkpoint")
        return request_checkpoint(context, str(payload.get("reason", "main_milestone")), payload.get("minimum_event_seq"))

    def durability_reconcile(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "durability.checkpoint")
        if checkpoint_worker is None or context.get("_uow") is None:
            raise RuntimeError("checkpoint_not_available")
        refs = payload.get("scope_refs") or []
        if not isinstance(refs, list) or len(refs) > 1 or any(not isinstance(ref, str) for ref in refs):
            raise ValueError("checkpoint_single_operation_required")
        operation_id = checkpoint_worker.retry(context["_uow"], actor=context["principal_id"],
                                               operation_id=refs[0] if refs else None)
        return {"operation_id": operation_id, "checkpoint_status": "pending"}

    def cognition_report(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "cognition.report")
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        task = tasks.tasks.get(task_id)
        attempt = tasks.attempts.get(attempt_id)
        if strict_runtime:
            if task is None or attempt is None or attempt.task_id != task_id:
                raise ValueError("task_attempt_relationship_required")
            if (attempt.owner_agent_id != context["principal_id"]
                    and authority.main_agent_id != context["principal_id"]):
                raise PermissionError("attempt_owner_required")
        claims = [_claim(item) for item in (payload.get("claims") or [])]
        # What the reporter says it was working from. A declared premise is the only way
        # "these two reports were written under different agreements" can be pointed at
        # later, so the field is read here instead of being silently dropped.
        declared_revisions = payload.get("input_revisions")
        if declared_revisions is not None and not isinstance(declared_revisions, dict):
            raise ValueError("input_revisions_object_required")
        report = cognition.submit_report(
            task_id=task_id, attempt_id=attempt_id, actor_agent_id=context["principal_id"],
            claims=claims,
            uncertainties=payload.get("uncertainties"),
            assumptions=payload.get("assumptions"),
            input_revisions=declared_revisions,
        )
        return {"report_id": report.report_id, "task_id": task_id, "attempt_id": attempt_id, "digest": report.digest}

    def discrepancy_create(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "cognition.discuss")
        discrepancy = cognition.create_discrepancy(
            subject_ref=_required_str(payload, "subject_ref"),
            report_refs=[str(item) for item in (payload.get("report_refs") or [])],
            severity=str(payload.get("severity") or "hard"),
            summary=str(payload.get("summary") or ""),
            participants=payload.get("participants") or [],
            affected_actions=payload.get("affected_actions") or [],
        )
        return {"discrepancy_id": discrepancy.discrepancy_id, "status": discrepancy.status,
                "subject_ref": discrepancy.subject_key, "input_digest": discrepancy.input_digest}

    def discrepancy_advance(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "cognition.discuss")
        discrepancy = cognition.advance_discrepancy(
            _required_str(payload, "discrepancy_id"), _required_str(payload, "status"),
        )
        return {"discrepancy_id": discrepancy.discrepancy_id, "status": discrepancy.status}

    def discrepancy_resolve(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "cognition.resolve")
        discrepancy = cognition.resolve_discrepancy(
            _required_str(payload, "discrepancy_id"), _required_str(payload, "kind"),
        )
        return {"discrepancy_id": discrepancy.discrepancy_id, "status": discrepancy.status}

    def _announce_contract_revision(proposal: Any, context: dict[str, Any]) -> None:
        """Tell the mechanically derivable dependants that a revision landed.

        Recipients are the contract's participants plus whoever currently holds the
        task it is linked to — both are derivable, so nobody has to guess a mailing
        list. The notice carries no response obligation and no contract content: it
        informs, while the start/submit boundaries are what actually hold anyone to
        the new version. Skipped for proposals that replace nothing.
        """
        if proposal.supersedes_id is None:
            return
        recipients = {
            str(item["agent_id"]) for item in proposal.participants if item.get("agent_id")
        }
        task_id = proposal.payload.get("task_id") if isinstance(proposal.payload, dict) else None
        if isinstance(task_id, str):
            task = tasks.tasks.get(task_id)
            attempt = tasks.attempts.get(task.current_attempt_id or "") if task is not None else None
            if attempt is not None:
                recipients.add(attempt.owner_agent_id)
        recipients.discard(str(proposal.proposed_by or ""))
        for recipient in sorted(recipients):
            messages.send(
                command_id=f"{context['command_id']}:contract-revised:{recipient}",
                sender_agent_id=str(proposal.proposed_by or context["principal_id"]),
                recipient_agent_id=recipient,
                kind="contract.revised",
                subject_ref=proposal.proposal_id,
                # The new digest travels in the summary: message views do not expose the
                # payload, and a notice that cannot say which version is now in force is
                # useless to the agent that has to switch to it.
                summary=f"contract revised: {proposal.supersedes_id} -> {proposal.proposal_id} @ {proposal.digest}",
                payload={
                    "proposal_id": proposal.proposal_id,
                    "supersedes_id": proposal.supersedes_id,
                    "digest": proposal.digest,
                },
            )

    def _announce_contract_proposal(proposal: Any, context: dict[str, Any]) -> None:
        """Ask every required slot to answer the proposal.

        A proposal is an invitation to agree, and nothing else in the system says so:
        acceptances only ever happen if a participant learns that a slot is waiting for
        it. The recipients are mechanically derivable — the slots that must accept — so
        no mailing list has to be guessed. Slots declared without an agent_id have no
        one to notify (they can only be answered by proxy).

        The notice carries a response obligation whose answer must quote the digest it
        is answering, which turns "I read it" into a checkable fact. Answering is still
        not agreeing: the decision recorded here is a stated intent, and the contract
        itself only moves through `contract.accept` / `contract.reject`.
        """
        required = set(proposal.required_slots)
        recipients = {
            str(item["agent_id"])
            for item in proposal.participants
            if item.get("agent_id") and str(item["slot"]) in required
        }
        recipients.discard(str(proposal.proposed_by or ""))
        for recipient in sorted(recipients):
            messages.send(
                command_id=f"{context['command_id']}:contract-proposed:{recipient}",
                sender_agent_id=str(proposal.proposed_by or context["principal_id"]),
                recipient_agent_id=recipient,
                kind="contract.proposed",
                subject_ref=proposal.proposal_id,
                summary=(
                    f"contract proposal {proposal.proposal_id}: answer with the digest you "
                    "read, then accept or reject it"
                ),
                payload={
                    "proposal_id": proposal.proposal_id,
                    "supersedes_id": proposal.supersedes_id,
                    "digest": proposal.digest,
                },
                response_contract={
                    "required": True,
                    "schema": {
                        "type": "object",
                        "required": ["proposal_id", "proposal_digest", "decision"],
                        "properties": {
                            "proposal_id": {"const": proposal.proposal_id},
                            "proposal_digest": {"const": proposal.digest},
                            "decision": {"enum": ["accept", "reject"]},
                        },
                    },
                },
            )

    def contract_propose(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "contract.propose")
        # On the wire, an empty string is the convention for "replaces nothing".
        revised = payload.get("supersedes_id") or None
        if revised is not None and not isinstance(revised, str):
            raise ValueError("invalid_supersedes_id")
        participants = [
            _slot(item, True) for item in (payload.get("participants_required") or [])
        ] + [
            _slot(item, False) for item in (payload.get("participants_optional") or [])
        ]
        if not participants and revised:
            # A revision defaults to the participants of the contract it replaces, so
            # it cannot quietly narrow who has to agree.
            previous = cognition.proposals.get(revised)
            if previous is not None:
                participants = list(previous.participants)
        proposal = cognition.propose_contract(
            payload.get("payload") or {}, participants,
            proposed_by=context["principal_id"], supersedes_id=revised,
        )
        _announce_contract_proposal(proposal, context)
        return {
            "proposal_id": proposal.proposal_id, "digest": proposal.digest,
            "status": proposal.status, "supersedes_id": proposal.supersedes_id,
        }

    def contract_accept(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "contract.accept")
        proposal_id = _required_str(payload, "proposal_id")
        participant_slot = _required_str(payload, "participant_slot")
        proposal_digest = _required_str(payload, "proposal_digest")
        proposal = cognition.proposals.get(proposal_id)
        was_accepted = proposal is not None and proposal.status == "accepted"
        cognition.accept_contract(
            proposal_id, participant_slot=participant_slot,
            proposal_digest=proposal_digest, actor_id=context["principal_id"],
        )
        if proposal is not None and not was_accepted and proposal.status == "accepted":
            # This acceptance completed the proposal: its predecessor has just been
            # retired, and the dependants need to hear about it.
            _announce_contract_revision(proposal, context)
        return {"proposal_id": proposal_id, "participant_slot": participant_slot, "status": "accepted"}

    def contract_accept_proxy(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "contract.accept_proxy")
        slot = _required_str(payload, "participant_slot_id")
        proposal = cognition.proposals.get(_required_str(payload, "proposal_id"))
        was_accepted = proposal is not None and proposal.status == "accepted"
        acceptance = cognition.accept_proxy(
            _required_str(payload, "proposal_id"), participant_slot=slot,
            proposal_digest=_required_str(payload, "proposal_digest"),
            real_actor_id=context["principal_id"], represented_participant=slot,
            main_allowed=True,
        )
        if proposal is not None and not was_accepted and proposal.status == "accepted":
            _announce_contract_revision(proposal, context)
        return {"proposal_id": acceptance.proposal_id, "participant_slot": acceptance.participant_slot,
                "status": "accepted", "via_proxy": True}

    def contract_reject(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "contract.accept")
        proposal = cognition.reject_contract(
            _required_str(payload, "proposal_id"),
            proposal_digest=_required_str(payload, "proposal_digest"),
            actor_id=context["principal_id"], reason=str(payload.get("reason") or ""),
        )
        return {"proposal_id": proposal.proposal_id, "status": proposal.status}

    def contract_withdraw(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "contract.propose")
        proposal = cognition.withdraw_contract(
            _required_str(payload, "proposal_id"), actor_id=context["principal_id"],
            reason=str(payload.get("reason") or ""),
        )
        return {"proposal_id": proposal.proposal_id, "status": proposal.status}

    def inbox_claim(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "inbox.consume")
        limit = int(payload.get("limit", 50))
        claimed = messages.fetch(context["principal_id"], limit=limit)
        return {"messages": [_message_view(message, messages) for message in claimed], "count": len(claimed)}

    def inbox_fetch(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "inbox.consume")
        message_id = payload.get("delivery_lease_id") or _required_str(payload, "message_id")
        message = messages.messages.get(message_id)
        if message is None or message.recipient_agent_id != context["principal_id"]:
            raise PermissionError("inbox_access_denied")
        return _message_view(message, messages)

    def inbox_presented(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "inbox.consume")
        message_id = _required_str(payload, "message_id")
        messages.present(context["principal_id"], message_id, {
            "digest": payload.get("evidence_digest"), "kind": payload.get("evidence_kind"),
        })
        return {"message_id": message_id, "presented": True}

    def inbox_ack(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "inbox.consume")
        message_id = _required_str(payload, "message_id")
        messages.ack(context["principal_id"], message_id)
        return {"message_id": message_id, "acked": True}

    def message_send(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "message.send")
        recipient_agent_id = _required_str(payload, "recipient_agent_id")
        message = messages.send(
            command_id=context["command_id"],
            sender_agent_id=context["principal_id"],
            recipient_agent_id=recipient_agent_id,
            kind=str(payload.get("kind", "message")),
            subject_ref=payload.get("subject_ref") or "",
            summary=payload.get("summary") or "",
            payload=payload.get("payload"),
            priority=int(payload.get("priority", 0)),
            response_contract=payload.get("response_contract"),
            in_reply_to=payload.get("in_reply_to"),
        )
        return {"message_id": message.message_id, "recipient_agent_id": recipient_agent_id}

    def message_respond(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "message.respond")
        obligation_id = _required_str(payload, "obligation_id")
        response_message_id = _required_str(payload, "response_message_id")
        messages.respond(context["principal_id"], obligation_id, response_message_id)
        return {"obligation_id": obligation_id, "response_message_id": response_message_id, "status": "responded"}

    def coordination_plan(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Create an atomic Main-owned assignment plan and wake records.

        Host wake itself is an adapter concern.  This handler only creates the
        durable assignment/wake facts that the adapter consumes.
        """
        _authorize(context, "coordination.write")
        if context["principal_id"] != authority.main_agent_id:
            raise PermissionError("main_authority_required")
        objective = _required_str(payload, "objective")
        raw_assignments = payload.get("assignments")
        if not isinstance(raw_assignments, list) or not raw_assignments:
            raise ValueError("assignments_required")
        # Auto-wake is an explicit opt-in for this new coordination plan;
        # legacy tasks and plans without the flag retain pull-first behavior.
        requested_auto_wake = payload.get("auto_wake")
        if requested_auto_wake is not None and not isinstance(requested_auto_wake, bool):
            raise ValueError("auto_wake_boolean_required")
        configured_auto_wake = bool(
            project_registry is not None and project_registry.project is not None
            and project_registry.project.settings.get("auto_wake_multi_agent", False)
        )
        if requested_auto_wake is True and project_registry is not None and not configured_auto_wake:
            raise ValueError("auto_wake_project_opt_in_required")
        if requested_auto_wake is True and strict_runtime and project_registry is None:
            raise ValueError("project_opt_in_required")
        auto_wake = configured_auto_wake if requested_auto_wake is None else bool(requested_auto_wake)
        deadline = float(payload.get("wake_deadline_seconds", 60))
        if deadline <= 0:
            raise ValueError("invalid_wake_deadline")
        # Validate all worker identities before creating any task so a bad
        # assignment cannot leave a partially published plan.
        ready_workers = {
            agent_id for agent_id, agent in authority.agents.items()
            if agent_id != authority.main_agent_id and agent.status == "active"
            and any(session.agent_id == agent_id and session.active and session.status == "ready"
                    for session in authority.sessions.values())
        }
        normalized: list[dict[str, Any]] = []
        assigned_workers: set[str] = set()
        for item in raw_assignments:
            if not isinstance(item, dict):
                raise ValueError("invalid_assignment")
            worker_id = _required_str(item, "assigned_worker_id")
            if worker_id not in ready_workers:
                raise ValueError("worker_not_ready")
            if worker_id in assigned_workers:
                raise ValueError("duplicate_assignment_worker")
            assigned_workers.add(worker_id)
            title = _required_str(item, "title")
            task_objective = _required_str(item, "task_objective")
            normalized.append({**item, "assigned_worker_id": worker_id, "title": title, "task_objective": task_objective})
        # When three workers are available, a healthy auto-wake plan must cover
        # all three.  With fewer ready workers the plan scales to what exists.
        if auto_wake and len(normalized) < min(3, len(ready_workers)):
            raise ValueError("worker_coverage_required")
        created_tasks: list[Any] = []
        try:
            for item in normalized:
                task = tasks.create_task(
                    item["title"], item["task_objective"],
                    parent_task_id=item.get("parent_task_id"),
                    # Assignment dependencies are recorded by coordination;
                    # task graph edges require IDs that already exist and are
                    # added by a later Main command.
                    blocks=set(),
                    execution_scope=item.get("execution_scope") or {},
                )
                tasks.ready(task.task_id)
                tasks.publish(task.task_id)
                created_tasks.append(task)
            assignment_specs = []
            for task, item in zip(created_tasks, normalized, strict=True):
                assignment_specs.append({
                    "task_id": task.task_id,
                    "assigned_worker_id": item["assigned_worker_id"],
                    "dependencies": item.get("dependencies") or (),
                    "acceptance_conditions": item.get("acceptance_conditions") or {},
                    "workspace": item.get("workspace") or {},
                    "resource_intent": item.get("resource_intent") or {},
                    "auto_wake": auto_wake,
                })
            plan = coordination.create_plan(
                main_agent_id=context["principal_id"], objective=objective,
                assignments=assignment_specs, auto_wake=auto_wake,
                wake_deadline_seconds=deadline,
            )
        except Exception:
            # In-memory callers do not have dispatcher snapshot rollback. Remove
            # only tasks created by this command if coordination registration
            # fails before the command can be persisted.
            for task in created_tasks:
                tasks.tasks.pop(task.task_id, None)
            raise
        return {
            "plan_id": plan.plan_id,
            "objective": plan.objective,
            "status": plan.status,
            "assignments": [
                {
                    "assignment_id": item.assignment_id,
                    "task_id": item.task_id,
                    "assigned_worker_id": item.assigned_worker_id,
                    "status": item.status,
                    "wake_attempt_id": item.wake_attempt_id,
                }
                for item in (coordination.assignments[item_id] for item_id in plan.assignment_ids)
            ],
            "coverage": coordination.coverage(plan.plan_id),
        }

    def worker_ready(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "coordination.report")
        assignment_id = _required_str(payload, "assignment_id")
        wake = coordination.record_worker_ready(
            assignment_id, worker_id=context["principal_id"],
            wake_attempt_id=_required_str(payload, "wake_attempt_id"),
        )
        assignment = coordination.assignment(assignment_id)
        coordination.record_event(
            "worker.ready", actor_id=context["principal_id"],
            assignment_id=assignment_id, task_id=assignment.task_id,
            summary="worker bridge round confirmed", important=True,
        )
        return {
            "assignment_id": assignment_id, "task_id": assignment.task_id,
            "wake_attempt_id": wake.wake_attempt_id, "status": "ready",
            "lease_guidance": _lease_guidance(assignment.claimed_attempt_id),
        }

    def coordination_takeover(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "coordination.write")
        if context["principal_id"] != authority.main_agent_id:
            raise PermissionError("main_authority_required")
        assignment_id = _required_str(payload, "assignment_id")
        assignment = coordination.assignment(assignment_id)
        previous_attempt_id = assignment.claimed_attempt_id
        if previous_attempt_id is not None:
            previous = tasks.attempts.get(previous_attempt_id)
            if previous is not None and previous.status not in {"completed", "submitted", "failed", "cancelled", "orphaned"}:
                tasks.orphan(assignment.task_id, reason="coordination_takeover")
                resources.release_for_attempt(previous_attempt_id, reason="coordination_takeover")
                for grant_id, grant in list(authority.grants.items()):
                    if grant.attempt_id == previous_attempt_id and grant.status == "active":
                        authority.grants[grant_id] = type(grant)(
                            **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"}
                        )
        assignment = coordination.takeover(
            assignment_id, main_agent_id=context["principal_id"],
            reason=_required_str(payload, "takeover_reason"),
        )
        coordination.record_event(
            "coordination.takeover", actor_id=context["principal_id"],
            assignment_id=assignment_id, task_id=assignment.task_id,
            summary=assignment.takeover_reason or "", important=True,
        )
        attempt = tasks.claim(assignment.task_id, context["principal_id"])
        assignment.claimed_attempt_id = attempt.attempt_id
        return {
            "assignment_id": assignment_id, "task_id": assignment.task_id,
            "attempt_id": attempt.attempt_id, "status": assignment.status,
            "takeover_reason": assignment.takeover_reason,
        }

    def coordination_host_accepted(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Internal adapter hook; host wake adapters call the service directly.

        The D-principal registry entry is an internal daemon callback rather
        than a worker-facing tool. Keeping the transition here gives adapters
        and tests one idempotent state change.
        """
        if context.get("kind") != "D":
            raise PermissionError("daemon_principal_required")
        wake = coordination.record_host_accepted(
            _required_str(payload, "assignment_id"),
            host_turn_id=payload.get("host_turn_id"),
            wake_attempt_id=_required_str(payload, "wake_attempt_id"),
        )
        assignment = coordination.assignment(_required_str(payload, "assignment_id"))
        coordination.record_event(
            "worker.host_accepted", assignment_id=assignment.assignment_id,
            task_id=assignment.task_id, summary=wake.host_turn_id or "",
            important=True,
        )
        return {"wake_attempt_id": wake.wake_attempt_id, "status": wake.status}

    def context_project_read(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        # A read-only, self-scoped project context snapshot. The actor is the
        # authenticated principal (never a payload field), capabilities come from
        # active grants, and owned tasks are scoped to this agent. No token,
        # credential or absolute path enters the snapshot.
        _authorize(context, "coordination.read")
        agent_id = context["principal_id"]
        agent = authority.agents.get(agent_id)
        capabilities = sorted({
            cap for grant in authority.grants.values()
            if grant.principal_id == agent_id and grant.status == "active"
            for cap in grant.capabilities
        })
        owned_tasks = [
            {
                "task_id": task.task_id, "title": task.title,
                "objective": task.objective, "status": task.status,
            }
            for task in tasks.tasks.values()
            if (attempt := tasks.attempts.get(task.current_attempt_id or "")) is not None
            and attempt.owner_agent_id == agent_id
        ]
        visible_assignments = [
            {
                "assignment_id": assignment.assignment_id,
                "plan_id": assignment.plan_id,
                "task_id": assignment.task_id,
                "assigned_worker_id": assignment.assigned_worker_id,
                "status": assignment.status,
                "wake_attempt_id": assignment.wake_attempt_id,
                "takeover_agent_id": assignment.takeover_agent_id,
                "takeover_reason": assignment.takeover_reason,
            }
            for assignment in coordination.assignments.values()
            if agent_id == authority.main_agent_id or assignment.assigned_worker_id == agent_id
        ]
        visible_assignment_ids = {item["assignment_id"] for item in visible_assignments}
        visible_events = [
            {
                "event_id": event.event_id, "kind": event.kind,
                "assignment_id": event.assignment_id, "task_id": event.task_id,
                "summary": event.summary, "important": event.important,
                "created_at": event.created_at,
            }
            for event in coordination.events
            if agent_id == authority.main_agent_id or event.assignment_id in visible_assignment_ids
        ]
        contracts_by_task = [
            {
                "task_id": item["task_id"],
                # The exact strings the start boundary compares against. Read them here,
                # hand them back through expected_revisions, and "I read the current
                # version" stops being a claim.
                "in_force": list(cognition.current_contract_versions(item["task_id"])),
                "proposals": [
                    _contract_view(proposal)
                    for proposal in sorted(
                        cognition.linked_contracts(item["task_id"]).values(),
                        key=lambda proposal: proposal.proposal_id,
                    )
                ],
            }
            for item in owned_tasks
        ]
        participating_contracts = [
            _contract_view(proposal)
            for proposal in sorted(cognition.proposals.values(), key=lambda item: item.proposal_id)
            if any(
                str(participant.get("agent_id") or "") == agent_id
                for participant in proposal.participants
            )
        ]
        return {
            **({"project_id": project_id} if project_id else {}),
            "agent_id": agent_id,
            "role": agent.role if agent is not None else "worker",
            "main_agent_id": authority.main_agent_id,
            "scope": {"capabilities": capabilities},
            "tasks": owned_tasks,
            "contracts": {"tasks": contracts_by_task, "participating": participating_contracts},
            "coordination": {
                "coverage": coordination.coverage(),
                "assignments": visible_assignments,
                "events": visible_events,
                "auto_wake_multi_agent": bool(
                    project_registry is not None and project_registry.project is not None
                    and project_registry.project.settings.get("auto_wake_multi_agent", False)
                ),
            },
        }

    return {
        "agent.enroll": enroll,
        "session.rebind": session_rebind,
        "session.reconnect": session_reconnect,
        "agent.ticket.create.user": issue_user_ticket,
        "authority.appoint": appoint_main,
        "authority.revoke": revoke_main,
        "project.configure": project_configure,
        "root.register": root_register,
        "root.bind": root_bind,
        "repository.register": repository_register,
        "task.create": task_create,
        "task.ready": task_ready,
        "task.publish": task_publish,
        "task.update_plan": task_update_plan,
        "task.edge.add": task_edge_add,
        "task.edge.remove": task_edge_remove,
        "task.claim": task_claim,
        "task.resume": task_resume,
        "task.preflight": task_preflight,
        "task.start": task_start,
        "task.progress": task_progress,
        "task.block": task_block,
        "task.submit": task_submit,
        "task.cancel_request": task_cancel_request,
        "task.cancel_ack": task_cancel_ack,
        "task.fail": task_fail,
        "task.recover": task_recover,
        "task.scope.request": task_scope_request,
        "task.scope.resolve": task_scope_resolve,
        "task.self_accept": task_self_accept,
        "resource.intent": resource_intent,
        "resource.acquire": resource_acquire,
        "resource.release": resource_release,
        "resource.renew": resource_renew,
        "workspace.select": workspace_select,
        "workspace.prepare": workspace_prepare,
        "workspace.result": workspace_result,
        "workspace.integrate": workspace_integrate,
        "task.review.accept": lambda payload, context: task_review(payload, context, decision="accepted"),
        "task.review.request_changes": lambda payload, context: task_review(payload, context, decision="changes_requested"),
        "cognition.report": cognition_report,
        "discrepancy.create": discrepancy_create,
        "discrepancy.advance": discrepancy_advance,
        "discrepancy.resolve": discrepancy_resolve,
        "contract.propose": contract_propose,
        "contract.accept": contract_accept,
        "contract.accept_proxy": contract_accept_proxy,
        "contract.reject": contract_reject,
        "contract.withdraw": contract_withdraw,
        "inbox.claim": inbox_claim,
        "inbox.fetch": inbox_fetch,
        "inbox.presented": inbox_presented,
        "inbox.ack": inbox_ack,
        "message.send": message_send,
        "message.respond": message_respond,
        "coordination.plan": coordination_plan,
        "worker.ready": worker_ready,
        "coordination.takeover": coordination_takeover,
        "coordination.wake.accepted": coordination_host_accepted,
        "context.project_read": context_project_read,
        "user_decision.propose": user_decision_propose,
        "user_decision.resolve": user_decision_resolve,
        "project.completion.propose.main": completion_propose,
        "project.completion.confirm": completion_confirm,
        "checkpoint.create.user": checkpoint_create_user,
        "checkpoint.create": checkpoint_create_main,
        "durability.reconcile": durability_reconcile,
    }
