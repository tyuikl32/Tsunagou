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

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tsunagou.application.workflows.execution_commands import ExecutionCommands
from tsunagou.application.workflows.lifecycle import LifecycleService
from tsunagou.application.workspace_evidence import WorkspaceEvidence
from tsunagou.modules.artifacts import ArtifactService
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import Claim, CognitionService
from tsunagou.modules.coordination import CoordinationService
from tsunagou.modules.messaging import Message, MessageStore
from tsunagou.modules.projects import ProjectRegistry, physical_identity
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.modules.workspaces import WorkspaceService
from tsunagou.platform.checkpoint_worker import CheckpointWorker
from tsunagou.platform.checkpoints import CheckpointStore
from tsunagou.shared_kernel.baseline import missing_admission_capabilities
from tsunagou.shared_kernel.digests import canonical_digest

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


def _required_contracts(payload: dict[str, Any]) -> tuple[str, ...]:
    values = payload.get("required_contract_ids", [])
    if (not isinstance(values, list) or any(not isinstance(item, str) or not item.strip() for item in values)
            or len(set(values)) != len(values)):
        raise ValueError("invalid_required_contract_ids")
    return tuple(values)


def _message_view(message: Message, messages: MessageStore | None = None, *, include_payload: bool = False) -> dict[str, Any]:
    view: dict[str, Any] = {
        "message_id": message.message_id,
        "sender_agent_id": message.sender_agent_id,
        "recipient_agent_id": message.recipient_agent_id,
        "kind": message.kind,
        "subject_ref": message.subject_ref,
        "summary": message.summary,
        "in_reply_to": message.in_reply_to,
        "payload_digest": message.payload_digest,
    }
    if include_payload:
        view["payload"] = message.payload
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
    if not isinstance(item, dict) or set(item) != {"slot", "agent_id"}:
        raise ValueError("invalid_contract_participant")
    for field in ("slot", "agent_id"):
        if not isinstance(item[field], str) or not item[field].strip():
            raise ValueError(f"participant_{field}_required")
    return {**item, "required": required}


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
    preparers: dict[str, Handler] | None = None,
) -> dict[str, Handler]:
    tasks = tasks if tasks is not None else TaskService()
    cognition = cognition if cognition is not None else CognitionService()
    messages = messages if messages is not None else MessageStore()
    resources = resources if resources is not None else ResourceService()
    workspaces = workspaces if workspaces is not None else WorkspaceService()
    coordination = coordination if coordination is not None else CoordinationService()
    execution = ExecutionCommands(
        authority=authority, tasks=tasks, cognition=cognition, resources=resources, workspaces=workspaces,
        coordination=coordination, evidence=WorkspaceEvidence(workspaces, project_registry, project_root) if project_root else None,
        artifacts=artifacts, lifecycle=lifecycle, project_id=project_id or "local-project", state_runtime=state_runtime,
        messages=messages,
    )
    if preparers is not None:
        preparers.update({"task.begin": execution.prepare_begin, "task.submit": execution.prepare_submit})

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
        host_binding = payload.get("host_binding")
        if host_binding is not None:
            if (not isinstance(host_binding, dict)
                    or set(host_binding) != {"provider", "endpoint", "thread_id", "host_generation"}
                    or host_binding.get("provider") != "codex_desktop_app"
                    or host_binding.get("thread_id") != conversation_id
                    or any(not isinstance(value, str) or not value for value in host_binding.values())):
                raise ValueError("enrollment_host_binding_invalid")
            if project_registry is None or project_registry.project is None:
                raise ValueError("project_not_initialized")
            host_binding = {
                **host_binding, "adapter_profile": "codex", "cwd": str(project_registry.repository),
                "scope_digest": canonical_digest({"project_id": project_id, "roots": list(project_registry.project.roots)}),
                "policy_digest": canonical_digest({"requested_role": role, "host_policy": "inherit"}),
                "attach_confirmed": True,
            }
        secret = authority.issue_ticket(
            installation_id, conversation_id, ttl_seconds=int(ttl_seconds), requested_role=role,
            host_binding=host_binding,
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
            execution_scope=execution_scope, required_contract_ids=_required_contracts(payload),
        )
        return {"task_id": task.task_id, "title": title, "objective": objective, "status": task.status, "revision": task.revision}

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
        return {"task_id": task_id, "status": task.status, "revision": task.revision}

    def task_publish(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        task_id = _required_str(payload, "task_id")
        task = tasks.publish(task_id)
        return {"task_id": task_id, "status": task.status, "revision": task.revision}

    def task_update_plan(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        task = tasks.update_plan(
            _required_str(payload, "task_id"),
            title=payload.get("title"), objective=payload.get("objective"),
            required_contract_ids=_required_contracts(payload) if "required_contract_ids" in payload else None,
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





    def task_progress(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task_id, attempt_id = _required_str(payload, "task_id"), _required_str(payload, "attempt_id")
        _authorize(context, "task.execute", task_id=task_id, attempt_id=attempt_id)
        record = tasks.progress(task_id, context["principal_id"], attempt_id=attempt_id,
                                summary=str(payload.get("summary") or ""), evidence_refs=tuple(payload.get("evidence_refs") or ()))
        return {"task_id": task_id, "attempt_id": attempt_id, "progress_id": record.progress_id, "summary": record.summary}

    def task_block(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id, attempt_id = _required_str(payload, "task_id"), _required_str(payload, "attempt_id")
        task = tasks.tasks[task_id]
        attempt = tasks.attempts.get(task.current_attempt_id or "")
        if attempt is None or attempt.attempt_id != attempt_id or attempt.owner_agent_id != context["principal_id"]:
            raise PermissionError("attempt_owner_required")
        if task.status == "cancel_requested":
            tasks.acknowledge_cancel(task_id, context["principal_id"], attempt_id=attempt_id)
        elif task.status in {"claimed", "running"}:
            tasks.block(task_id, str(payload.get("reason_code") or payload.get("reason") or "blocked"),
                        checkpoint_summary=payload.get("checkpoint_summary") or {},
                        dependency_refs=tuple(payload.get("dependency_refs") or ()),
                        evidence_refs=tuple(payload.get("evidence_refs") or ()))
        else:
            raise ValueError("attempt_not_running")
        execution.release(attempt_id, "task_blocked")
        return {"task_id": task_id, "attempt_id": attempt_id, "status": task.status, "revision": task.revision}

    def task_cancel_request(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        task = tasks.request_cancel(_required_str(payload, "task_id"), _required_str(payload, "reason"))
        if task.status == "cancelled" and task.current_attempt_id is not None:
            execution.release(task.current_attempt_id, "task_cancelled")
        return {"task_id": task.task_id, "status": task.status, "revision": task.revision}

    def task_cancel_ack(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task = tasks.acknowledge_cancel(
            _required_str(payload, "task_id"), context["principal_id"],
            attempt_id=_required_str(payload, "attempt_id"),
        )
        execution.release(payload["attempt_id"], "task_cancelled")
        return {"task_id": task.task_id, "status": task.status, "revision": task.revision}

    def task_fail(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task = tasks.fail(
            _required_str(payload, "task_id"), context["principal_id"],
            attempt_id=_required_str(payload, "attempt_id"), reason=_required_str(payload, "reason"),
        )
        execution.release(payload["attempt_id"], "task_failed")
        return {"task_id": task.task_id, "status": task.status, "revision": task.revision}

    def task_recover(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        task_id = _required_str(payload, "task_id")
        task = tasks.recover(
            task_id, expected_attempt_id=_required_str(payload, "expected_attempt_id"),
            disposition=_required_str(payload, "disposition"),
        )
        execution.release(payload["expected_attempt_id"], "task_recovered")
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
        task_id, result_id = _required_str(payload, "task_id"), _required_str(payload, "result_id")
        _authorize(context, "task.review", task_id=task_id)
        result = tasks.results.get(result_id)
        if result is None or result.task_id != task_id:
            raise ValueError("result_task_mismatch")
        if payload.get("result_digest") != result.digest:
            raise ValueError("result_digest_mismatch")
        review = tasks.review(task_id, context["principal_id"], result_id, decision=decision, reason=payload.get("reason"))
        execution.release(result.attempt_id, "review_" + decision)
        if result.submitted_by != context["principal_id"]:
            messages.send(command_id=context["command_id"] + ":review", sender_agent_id=context["principal_id"],
                          recipient_agent_id=result.submitted_by, kind="task.reviewed", subject_ref="task/" + task_id,
                          summary=decision, payload={"task_id": task_id, "result_id": result_id, "decision": decision})
        return {"task_id": task_id, "result_id": result_id, "decision": review.decision, "status": tasks.tasks[task_id].status}

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
        if related_task is not None:
            attempt = tasks.attempts.get(related_task.current_attempt_id or "")
            if attempt is not None and attempt.status in {"claimed", "running"}:
                # A decision request cannot assert that a running host stopped.
                # The owner releases resources with task.block; main may recover explicitly.
                messages.send(command_id=context["command_id"] + ":decision", sender_agent_id=context["principal_id"],
                              recipient_agent_id=attempt.owner_agent_id, kind="user_decision.pending",
                              subject_ref="task/" + related_task.task_id, summary="Pause work affected by the pending decision",
                              payload={"task_id": related_task.task_id, "decision_id": decision.decision_id})
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
        if authority.main_agent_id is not None:
            messages.send(
                command_id=context["command_id"] + ":decision-resolved",
                sender_agent_id=context["principal_id"], recipient_agent_id=authority.main_agent_id,
                kind="user_decision.resolved", subject_ref="decision/" + resolved.decision_id,
                summary="User decision resolved: " + str(resolved.decision),
                payload={
                    "decision_id": resolved.decision_id, "kind": resolved.kind,
                    "subject_ref": resolved.subject_ref, "revision": resolved.expected_revision,
                    "proposal_digest": resolved.input_digest, "status": resolved.status,
                    "decision": resolved.decision, "reason": resolved.reason,
                    "related_task_id": resolved.subject_ref if resolved.subject_ref in tasks.tasks else None,
                },
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
        required = payload.get("participants_required")
        optional = payload.get("participants_optional", [])
        if not isinstance(required, list) or not isinstance(optional, list):
            raise ValueError("contract_participant_arrays_required")
        participants = [
            _slot(item, True) for item in required
        ] + [
            _slot(item, False) for item in optional
        ]
        for participant in participants:
            if participant["agent_id"] not in authority.agents:
                raise ValueError("contract_participant_not_member")
        body = payload.get("payload")
        if not isinstance(body, dict):
            raise ValueError("contract_payload_object_required")
        if revised is not None:
            old = cognition.proposals[_required_str(payload, "supersedes_id")]
            if old.proposed_by != context["principal_id"]:
                raise PermissionError("proposal_owner_required")
            proposal = cognition.supersede_contract(old.proposal_id, body, participants)
        else:
            proposal = cognition.propose_contract(body, participants, proposed_by=context["principal_id"])
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
        return {"proposal_id": proposal_id, "participant_slot": participant_slot, "status": "accepted",
                "proposal_status": cognition.proposals[proposal_id].status}

    def contract_accept_proxy(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "contract.accept_proxy")
        slot = _required_str(payload, "participant_slot_id")
        proposal = cognition.proposals[_required_str(payload, "proposal_id")]
        was_accepted = proposal.status == "accepted"
        participant = next((item for item in proposal.participants if item["slot"] == slot), None)
        if participant is None:
            raise PermissionError("participant_slot_denied")
        acceptance = cognition.accept_proxy(
            proposal.proposal_id, participant_slot=slot,
            proposal_digest=_required_str(payload, "proposal_digest"),
            real_actor_id=context["principal_id"], represented_participant=participant["agent_id"],
            main_allowed=True,
        )
        if proposal is not None and not was_accepted and proposal.status == "accepted":
            _announce_contract_revision(proposal, context)
        return {"proposal_id": acceptance.proposal_id, "participant_slot": acceptance.participant_slot,
                "status": "accepted", "proposal_status": proposal.status, "via_proxy": True,
                "real_actor_id": acceptance.real_actor_id, "represented_participant": acceptance.represented_participant}

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
        message_id = _required_str(payload, "message_id")
        message = messages.messages.get(message_id)
        if message is None or message.recipient_agent_id != context["principal_id"]:
            raise PermissionError("inbox_access_denied")
        return _message_view(message, messages, include_payload=True)

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
        _authorize(context, "coordination.write")
        rows = payload.get("assignments")
        if not isinstance(rows, list) or not rows:
            raise ValueError("assignments_required")
        normalized = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("invalid_assignment")
            worker_id = _required_str(row, "assigned_worker_id")
            worker = authority.agents.get(worker_id)
            if worker is None or worker.status != "active" or worker_id == authority.main_agent_id:
                raise ValueError("worker_not_member")
            for dependency in row.get("dependencies") or ():
                if dependency not in tasks.tasks:
                    raise ValueError("dependency_task_not_found")
            normalized.append(row)
        auto_wake = payload.get("auto_wake", True)
        if not isinstance(auto_wake, bool):
            raise ValueError("auto_wake_boolean_required")
        specs = []
        for row in normalized:
            task = tasks.create_task(_required_str(row, "title"), _required_str(row, "task_objective"),
                                     parent_task_id=row.get("parent_task_id"), blocks=set(row.get("dependencies") or ()),
                                     execution_scope=row.get("execution_scope") or {},
                                     required_contract_ids=_required_contracts(row))
            if row.get("workspace"):
                execution.select_workspace({**row["workspace"], "task_id": task.task_id}, context)
            tasks.ready(task.task_id)
            tasks.publish(task.task_id)
            specs.append({**row, "task_id": task.task_id})
        plan = coordination.create_plan(main_agent_id=context["principal_id"], objective=_required_str(payload, "objective"),
                                        assignments=specs, auto_wake=auto_wake)
        result = []
        for assignment_id in plan.assignment_ids:
            item = coordination.assignments[assignment_id]
            if auto_wake:
                message = messages.send(command_id=context["command_id"] + ":" + item.assignment_id,
                                        sender_agent_id=context["principal_id"], recipient_agent_id=item.assigned_worker_id,
                                        kind="task.assigned", subject_ref="task/" + item.task_id, summary="Task available",
                                        payload={"task_id": item.task_id, "assignment_id": item.assignment_id})
                item.message_id = message.message_id
            result.append({"assignment_id": item.assignment_id, "task_id": item.task_id,
                           "assigned_worker_id": item.assigned_worker_id, "status": tasks.tasks[item.task_id].status,
                           "message_id": item.message_id})
        return {"plan_id": plan.plan_id, "objective": plan.objective, "assignments": result,
                "coverage": coordination.coverage({key: item.status for key, item in tasks.tasks.items()}, plan.plan_id)}


    def coordination_takeover(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "coordination.write")
        if context["principal_id"] != authority.main_agent_id:
            raise PermissionError("main_authority_required")
        assignment = coordination.assignment(_required_str(payload, "assignment_id"))
        task = tasks.tasks[assignment.task_id]
        if task.status in {"completed", "submitted", "cancelled", "failed"}:
            raise ValueError("task_not_recoverable")
        if task.current_attempt_id is not None:
            previous_id = task.current_attempt_id
            tasks.recover(task.task_id, expected_attempt_id=previous_id, disposition="reopen")
            execution.release(previous_id, "coordination_takeover")
        assignment = coordination.takeover(assignment.assignment_id, main_agent_id=context["principal_id"],
                                           reason=_required_str(payload, "takeover_reason"))
        return {"assignment_id": assignment.assignment_id, "task_id": task.task_id, "status": task.status,
                "takeover_reason": assignment.takeover_reason, "revision": task.revision}


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
            tasks.describe_task(task.task_id)
            for task in tasks.tasks.values()
            if (attempt := tasks.attempts.get(task.current_attempt_id or "")) is not None
            and attempt.owner_agent_id == agent_id
        ]
        open_tasks = [
            tasks.describe_task(task.task_id)
            for task in tasks.tasks.values()
            if task.status in {"open", "blocked"}
            and (
                (assignment := coordination.assignment_for_task(task.task_id)) is None
                or agent_id == (assignment.takeover_agent_id or assignment.assigned_worker_id)
            )
        ]
        visible_assignments = [
            {
                "assignment_id": assignment.assignment_id,
                "plan_id": assignment.plan_id,
                "task_id": assignment.task_id,
                "assigned_worker_id": assignment.assigned_worker_id,
                "status": tasks.tasks[assignment.task_id].status,
                "message_id": assignment.message_id,
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
            "session": {"session_id": context["session_id"],
                        "connection_epoch": authority.sessions[context["session_id"]].connection_epoch,
                        "status": authority.sessions[context["session_id"]].status},
            "scope": {"capabilities": capabilities},
            "tasks": owned_tasks,
            "open_tasks": open_tasks,
            "contracts": {"tasks": contracts_by_task, "participating": participating_contracts},
            "coordination": {
                "coverage": coordination.coverage({key: item.status for key, item in tasks.tasks.items()}),
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
        "task.progress": task_progress,
        "task.block": task_block,
        "task.begin": execution.begin,
        "task.submit": execution.submit,
        "task.cancel_request": task_cancel_request,
        "task.cancel_ack": task_cancel_ack,
        "task.fail": task_fail,
        "task.recover": task_recover,
        "task.scope.request": task_scope_request,
        "task.scope.resolve": task_scope_resolve,
        "task.self_accept": task_self_accept,
        "workspace.select": execution.select_workspace,
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
        "coordination.takeover": coordination_takeover,
        "context.project_read": context_project_read,
        "user_decision.propose": user_decision_propose,
        "user_decision.resolve": user_decision_resolve,
        "project.completion.propose.main": completion_propose,
        "project.completion.confirm": completion_confirm,
        "checkpoint.create.user": checkpoint_create_user,
        "checkpoint.create": checkpoint_create_main,
        "durability.reconcile": durability_reconcile,
    }
