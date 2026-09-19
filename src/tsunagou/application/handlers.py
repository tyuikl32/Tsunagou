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
from typing import Any

from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import Claim, CognitionService
from tsunagou.modules.messaging import Message, MessageStore
from tsunagou.modules.tasks import TaskService

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


def _message_view(message: Message) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "sender_agent_id": message.sender_agent_id,
        "recipient_agent_id": message.recipient_agent_id,
        "kind": message.kind,
        "subject_ref": message.subject_ref,
        "summary": message.summary,
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


def build_handlers(
    *, authority: AuthorityService, tasks: TaskService | None = None,
    cognition: CognitionService | None = None, messages: MessageStore | None = None,
) -> dict[str, Handler]:
    tasks = tasks if tasks is not None else TaskService()
    cognition = cognition if cognition is not None else CognitionService()
    messages = messages if messages is not None else MessageStore()

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
        }

    def issue_user_ticket(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        installation_id = payload.get("installation_id")
        if not isinstance(installation_id, str) or not installation_id:
            raise ValueError("installation_id_required")
        conversation_id = _conversation_id(payload.get("conversation_evidence"))
        ttl_seconds = payload.get("ttl_seconds", 600)
        secret = authority.issue_ticket(installation_id, conversation_id, ttl_seconds=int(ttl_seconds))
        return {"installation_id": installation_id, "conversation_id": conversation_id, "secret": secret}

    def appoint_main(payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        agent_id = payload.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("agent_id_required")
        grant = authority.appoint_main(actor_kind="user_control", agent_id=agent_id)
        return {"main_agent_id": agent_id, "grant_id": grant.grant_id, "authority_epoch": authority.authority_epoch}

    def revoke_main(_payload: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
        authority.revoke_main(actor_kind="user_control")
        return {"main_agent_id": None, "authority_epoch": authority.authority_epoch}

    def task_create(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.manage")
        title = _required_str(payload, "title")
        objective = _required_str(payload, "objective")
        parent_task_id = payload.get("parent_task_id")
        blocks = set(payload.get("blocks") or [])
        task = tasks.create_task(title, objective, parent_task_id=parent_task_id, blocks=blocks)
        tasks.ready(task.task_id)
        tasks.publish(task.task_id)
        return {"task_id": task.task_id, "title": title, "objective": objective, "status": task.status}

    def task_claim(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.claim")
        task_id = _required_str(payload, "task_id")
        attempt = tasks.claim(task_id, context["principal_id"])
        return {"task_id": task_id, "attempt_id": attempt.attempt_id, "status": attempt.status}

    def task_resume(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        attempt = tasks.resume(task_id, context["principal_id"])
        return {"task_id": task_id, "attempt_id": attempt.attempt_id, "status": attempt.status}

    def task_preflight(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        attempt_id = payload.get("attempt_id")
        evidence_refs = tuple(payload.get("evidence_refs") or ())
        preflight = tasks.preflight(
            task_id, context["principal_id"], attempt_id=attempt_id, evidence_refs=evidence_refs,
        )
        return {
            "task_id": task_id, "attempt_id": preflight.attempt_id,
            "preflight_id": preflight.preflight_id, "status": preflight.status,
        }

    def task_start(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        attempt_id = payload.get("attempt_id")
        preflight_id = payload.get("preflight_id")
        attempt = tasks.start(task_id, context["principal_id"], preflight_id=preflight_id)
        if attempt_id is not None and attempt_id != attempt.attempt_id:
            raise ValueError("attempt_id_mismatch")
        grant = authority.issue_execution_grant(
            agent_id=context["principal_id"], session_id=context["session_id"],
            task_id=task_id, attempt_id=attempt.attempt_id, execution_epoch=attempt.execution_epoch,
        )
        return {
            "task_id": task_id, "attempt_id": attempt.attempt_id, "status": attempt.status,
            "execution_grant_id": grant.grant_id,
        }

    def task_progress(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        _authorize(context, "task.execute", task_id=task_id, attempt_id=attempt_id)
        progress = tasks.progress(
            task_id, context["principal_id"], attempt_id=attempt_id,
            summary=payload.get("summary") or "",
            evidence_refs=tuple(payload.get("evidence_refs") or ()),
        )
        return {
            "task_id": task_id, "attempt_id": attempt_id,
            "progress_id": progress.progress_id, "summary": progress.summary,
        }

    def task_block(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "task.coordinate_self")
        task_id = _required_str(payload, "task_id")
        reason = payload.get("reason_code") or payload.get("reason") or "blocked"
        task = tasks.block(task_id, str(reason))
        return {"task_id": task_id, "status": task.status}

    def task_submit(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        _authorize(context, "task.execute", task_id=task_id, attempt_id=attempt_id)
        work = {key: value for key, value in payload.items() if key not in {"task_id", "attempt_id"}}
        result = tasks.submit(task_id, context["principal_id"], work)
        return {"result_id": result.result_id, "task_id": task_id, "attempt_id": attempt_id, "digest": result.digest}

    def cognition_report(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "cognition.report")
        task_id = _required_str(payload, "task_id")
        attempt_id = _required_str(payload, "attempt_id")
        claims = [_claim(item) for item in (payload.get("claims") or [])]
        report = cognition.submit_report(
            task_id=task_id, attempt_id=attempt_id, actor_agent_id=context["principal_id"],
            claims=claims,
            uncertainties=payload.get("uncertainties"),
            assumptions=payload.get("assumptions"),
        )
        return {"report_id": report.report_id, "task_id": task_id, "attempt_id": attempt_id, "digest": report.digest}

    def contract_propose(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "contract.propose")
        participants = [
            _slot(item, True) for item in (payload.get("participants_required") or [])
        ] + [
            _slot(item, False) for item in (payload.get("participants_optional") or [])
        ]
        proposal = cognition.propose_contract(payload.get("payload") or {}, participants)
        return {"proposal_id": proposal.proposal_id, "digest": proposal.digest, "status": proposal.status}

    def contract_accept(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "contract.accept")
        proposal_id = _required_str(payload, "proposal_id")
        participant_slot = _required_str(payload, "participant_slot")
        proposal_digest = _required_str(payload, "proposal_digest")
        cognition.accept_contract(
            proposal_id, participant_slot=participant_slot,
            proposal_digest=proposal_digest, actor_id=context["principal_id"],
        )
        return {"proposal_id": proposal_id, "participant_slot": participant_slot, "status": "accepted"}

    def inbox_claim(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "inbox.consume")
        limit = int(payload.get("limit", 50))
        claimed = messages.fetch(context["principal_id"], limit=limit)
        return {"messages": [_message_view(message) for message in claimed], "count": len(claimed)}

    def inbox_fetch(payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _authorize(context, "inbox.consume")
        message_id = payload.get("delivery_lease_id") or _required_str(payload, "message_id")
        message = messages.messages.get(message_id)
        if message is None or message.recipient_agent_id != context["principal_id"]:
            raise PermissionError("inbox_access_denied")
        return _message_view(message)

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
        return {
            "agent_id": agent_id,
            "role": agent.role if agent is not None else "worker",
            "main_agent_id": authority.main_agent_id,
            "scope": {"capabilities": capabilities},
            "tasks": owned_tasks,
        }

    return {
        "agent.enroll": enroll,
        "session.rebind": session_rebind,
        "session.reconnect": session_reconnect,
        "agent.ticket.create.user": issue_user_ticket,
        "authority.appoint": appoint_main,
        "authority.revoke": revoke_main,
        "task.create": task_create,
        "task.claim": task_claim,
        "task.resume": task_resume,
        "task.preflight": task_preflight,
        "task.start": task_start,
        "task.progress": task_progress,
        "task.block": task_block,
        "task.submit": task_submit,
        "cognition.report": cognition_report,
        "contract.propose": contract_propose,
        "contract.accept": contract_accept,
        "inbox.claim": inbox_claim,
        "inbox.fetch": inbox_fetch,
        "inbox.presented": inbox_presented,
        "inbox.ack": inbox_ack,
        "message.send": message_send,
        "message.respond": message_respond,
        "context.project_read": context_project_read,
    }
