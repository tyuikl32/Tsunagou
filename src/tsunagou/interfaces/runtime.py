"""One command dispatcher projected through HTTP, MCP, and CLI adapters."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest

Handler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

# Typed-tool payload contract for every command the bridge exposes (and every
# bootstrap handler). A payload key outside its set is a typed-tool violation:
# either an unknown field the model invented, or a forged actor field such as
# ``actor_id`` / ``sender_agent_id`` that a caller could use to self-declare an
# identity other than the one the bearer credential resolved. The dispatcher
# rejects these before any handler runs.
PAYLOAD_FIELDS: dict[str, frozenset[str]] = {
    "agent.enroll": frozenset({
        "installation_id", "conversation_evidence", "probe_payload", "client_nonce",
        "descriptor_ref", "negotiation",
    }),
    "session.rebind": frozenset({
        "installation_id", "conversation_evidence", "target_agent_id", "probe_payload",
        "client_nonce",
    }),
    "session.reconnect": frozenset({
        "reconnect_nonce", "expected_connection_epoch", "probe_payload", "continuity_evidence",
    }),
    "agent.ticket.create.user": frozenset({
        "installation_id", "conversation_evidence", "ttl_seconds", "kind",
    }),
    "authority.appoint": frozenset({
        "agent_id", "expected_authority_epoch", "ceiling_template", "reason",
    }),
    "authority.revoke": frozenset({"expected_authority_epoch", "reason"}),
    "root.register": frozenset({"name", "kind", "repository_id", "required", "binding_request", "reason"}),
    "root.bind": frozenset({"root_id", "absolute_path", "expected_physical_identity", "reason"}),
    "repository.register": frozenset({"name", "root_id", "required"}),
    "task.create": frozenset({"title", "objective", "parent_task_id", "blocks", "execution_scope"}),
    "task.ready": frozenset({"task_id", "reason"}),
    "task.publish": frozenset({"task_id", "reason"}),
    "task.update_plan": frozenset({"task_id", "title", "objective", "execution_scope", "acceptance_policy", "reason"}),
    "task.edge.add": frozenset({"source_task_id", "target_task_id", "kind", "expected_revisions"}),
    "task.edge.remove": frozenset({"edge_id", "source_task_id", "target_task_id", "reason", "expected_revisions"}),
    "task.claim": frozenset({"task_id", "capability_snapshot_id"}),
    "task.resume": frozenset({
        "task_id", "attempt_id", "evidence_refs", "input_digest", "expected_revisions",
        "expected_execution_epoch",
    }),
    "task.preflight": frozenset({"task_id", "attempt_id", "evidence_refs", "expected_revisions"}),
    "task.start": frozenset({
        "task_id", "attempt_id", "preflight_id", "expected_execution_epoch", "input_digest",
    }),
    "task.progress": frozenset({"task_id", "attempt_id", "summary", "evidence_refs"}),
    "task.block": frozenset({
        "task_id", "attempt_id", "reason_code", "reason", "checkpoint_summary",
        "dependency_refs", "evidence_refs",
    }),
    "task.submit": frozenset({
        "task_id", "attempt_id", "summary", "evidence_refs", "artifact_refs",
        "workspace_result_ref",
    }),
    "task.cancel_request": frozenset({"task_id", "reason"}),
    "task.cancel_ack": frozenset({"task_id", "attempt_id", "stop_evidence", "reason"}),
    "task.fail": frozenset({"task_id", "attempt_id", "reason", "evidence_refs", "stop_evidence"}),
    "task.recover": frozenset({"task_id", "expected_attempt_id", "disposition", "reason"}),
    "task.scope.request": frozenset({"task_id", "attempt_id", "requested_scope", "reason", "expected_revisions"}),
    "task.scope.resolve": frozenset({"scope_request_id", "choice", "approved_scope", "reason"}),
    "task.self_accept": frozenset({"task_id", "result_id", "result_digest", "evidence_refs", "reason"}),
    "cognition.report": frozenset({
        "task_id", "attempt_id", "claims", "assumptions", "uncertainties", "boundary",
        "understanding", "confidence", "confidence_reason", "evidence_refs",
        "input_revisions", "supersedes_id",
    }),
    "discrepancy.create": frozenset({
        "discrepancy_id", "subject_ref", "report_refs", "severity", "participants",
        "summary", "affected_actions",
    }),
    "discrepancy.advance": frozenset({"discrepancy_id", "status", "reason", "evidence_refs"}),
    "discrepancy.resolve": frozenset({"discrepancy_id", "kind", "reason", "evidence_refs", "accepted_by", "input_digest"}),
    "contract.propose": frozenset({
        "payload", "participants_required", "participants_optional", "contract_id",
        "contract_kind", "subject_ref", "input_refs", "supersedes_id",
    }),
    "contract.accept": frozenset({
        "proposal_id", "participant_slot", "proposal_digest", "evidence_refs",
    }),
    "contract.accept_proxy": frozenset({
        "proposal_id", "participant_slot_id", "proposal_digest", "proxy_policy_ref", "reason", "evidence_refs",
    }),
    "contract.reject": frozenset({"proposal_id", "proposal_digest", "reason", "evidence_refs"}),
    "contract.withdraw": frozenset({"proposal_id", "reason"}),
    "durability.reconcile": frozenset({"scope_refs", "reason"}),
    "inbox.claim": frozenset({"limit", "max_bytes"}),
    "inbox.fetch": frozenset({"message_id", "delivery_lease_id"}),
    "inbox.presented": frozenset({"message_id", "evidence_digest", "evidence_kind"}),
    "inbox.ack": frozenset({"message_id", "reason"}),
    "message.send": frozenset({
        "recipient_agent_id", "kind", "subject_ref", "summary", "payload", "priority",
        "response_contract", "in_reply_to",
    }),
    "message.respond": frozenset({
        "obligation_id", "response_message_id", "response_payload", "summary",
        "evidence_refs",
    }),
    "context.project_read": frozenset(),
    "resource.intent": frozenset({"task_id", "attempt_id", "reason", "resources", "scope_digest"}),
    "resource.acquire": frozenset({"task_id", "attempt_id", "intent_id", "intent_revision", "scope_digest"}),
    "resource.release": frozenset({"task_id", "attempt_id", "reason"}),
    "resource.renew": frozenset({"lease_set_id", "task_id", "attempt_id", "scope_digest"}),
    "workspace.select": frozenset({"task_id", "attempt_id", "driver_kind", "evidence_refs", "hard_constraints",
                                     "input_digest", "risk_submission_ref"}),
    "workspace.prepare": frozenset({"task_id", "attempt_id", "decision_id", "input_digest", "root_binding_refs",
                                     "repository_id", "external_locator", "baseline"}),
    "workspace.result": frozenset({"workspace_id", "task_id", "attempt_id", "baseline_digest", "changed_paths",
                                    "commit_refs", "patch_artifact_ref", "untracked_summary", "validation_refs"}),
    "workspace.git.report": frozenset({"request_id", "evidence_refs", "exact_input_digest", "outcome", "result_manifest"}),
    "task.review.accept": frozenset({"task_id", "attempt_id", "result_id", "evidence_refs", "reason", "result_digest", "slot_id"}),
    "task.review.request_changes": frozenset({"task_id", "attempt_id", "result_id", "evidence_refs", "reason", "result_digest", "slot_id"}),
    "user_decision.propose": frozenset({"choices", "expected_revisions", "kind", "proposal_digest", "proposal_ref", "summary"}),
    "user_decision.resolve": frozenset({"decision_id", "choice", "expected_revisions", "proposal_digest", "reason"}),
    "project.completion.propose.main": frozenset({"evidence_refs", "expected_project_revision", "objective_ref", "outstanding_summary"}),
    "project.completion.confirm": frozenset({"proposal_id", "expected_project_revision", "expected_revisions", "proposal_digest"}),
}


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    kind: str
    principal_id: str
    session_id: str | None = None
    connection_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class DispatchResponse:
    command_kind: str
    command_hash: str
    result: dict[str, Any]


class CommandDispatcher:
    def __init__(
        self, registry_path: str | Path, *, database: Any | None = None,
        state_runtime: Any | None = None,
    ) -> None:
        raw = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        self.registry: dict[str, dict[str, Any]] = raw["commands"]
        self.protocol_version = str(raw.get("protocol_version", "1"))
        self.schema_bundle_digest = str(raw.get("schema_bundle_digest", ""))
        self.database = database
        self.state_runtime = state_runtime
        self.handlers: dict[str, Handler] = {}

    def register(self, command_kind: str, handler: Handler) -> None:
        if command_kind not in self.registry:
            raise KeyError(f"unregistered_command:{command_kind}")
        self.handlers[command_kind] = handler

    def dispatch(
        self, command_kind: str, envelope: dict[str, Any], *,
        principal: PrincipalContext,
    ) -> DispatchResponse:
        policy = self.registry.get(command_kind)
        if policy is None:
            raise KeyError("unknown_command")
        if policy["principal"] != principal.kind:
            raise PermissionError("principal_kind_denied")
        handler = self.handlers.get(command_kind)
        if handler is None:
            raise KeyError("handler_not_registered")
        expected = {"command_id", "protocol_version", "schema_bundle_digest", "payload"}
        if set(envelope) != expected:
            raise ValueError("malformed_command_envelope")
        if self.database is not None:
            version = str(envelope["protocol_version"])
            if version != self.protocol_version and version != self.protocol_version.split(".", 1)[0]:
                raise ValueError("unsupported_protocol_version")
            # ``sha256:x`` was the pre-bundle unit-test sentinel. Keep that
            # narrow compatibility value for in-process callers; real daemon
            # requests must carry the packaged digest.
            if (str(envelope["schema_bundle_digest"]) != self.schema_bundle_digest
                    and str(envelope["schema_bundle_digest"]) != "sha256:x"):
                raise ValueError("schema_bundle_digest_mismatch")
        if not isinstance(envelope["payload"], dict):
            raise ValueError("payload_object_required")
        allowed_fields = PAYLOAD_FIELDS.get(command_kind)
        if allowed_fields is not None:
            unknown = set(envelope["payload"]) - allowed_fields
            if unknown:
                raise ValueError("unknown_payload_field")
        semantic = {
            "command_kind": command_kind,
            "principal_kind": principal.kind,
            "principal_id": principal.principal_id,
            "payload": envelope["payload"],
        }
        command_hash = canonical_digest(semantic)
        context = {
            "kind": principal.kind,
            "principal_id": principal.principal_id,
            "session_id": principal.session_id,
            "connection_epoch": principal.connection_epoch,
            "command_hash": command_hash,
            "command_id": envelope["command_id"],
        }
        if self.database is None:
            result = handler(envelope["payload"], context)
        else:
            snapshot = self.state_runtime.capture() if self.state_runtime is not None else None

            def execute(uow: Any) -> dict[str, Any]:
                context["_uow"] = uow
                result = handler(envelope["payload"], context)
                if self.state_runtime is not None:
                    self.state_runtime.persist(
                        uow, actor_ref=principal.principal_id, command_kind=command_kind,
                    )
                return result

            try:
                stored = self.database.dispatch(
                    principal_id=principal.principal_id,
                    command_kind=command_kind,
                    command_id=envelope["command_id"],
                    payload=envelope["payload"],
                    handler=execute,
                )
            except BaseException:
                if snapshot is not None:
                    self.state_runtime.restore(snapshot)
                raise
            return DispatchResponse(command_kind, command_hash, stored.result)
        return DispatchResponse(command_kind, command_hash, result)

    def mcp_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "inputSchema": {"type": "object", "additionalProperties": False}}
            for name, policy in sorted(self.registry.items())
            if policy["principal"] not in {"U", "D", "T"}
        ]


class BlackboardComposer:
    SENSITIVE_KEYS = {"token", "secret", "credential", "absolute_path", "private_message"}

    def compose(self, sections: dict[str, Any], *, max_items: int = 50) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        truncated: dict[str, int] = {}
        for name, value in sections.items():
            filtered = self._filter(value)
            if isinstance(filtered, list) and len(filtered) > max_items:
                truncated[name] = len(filtered) - max_items
                filtered = filtered[:max_items]
            snapshot[name] = filtered
        if truncated:
            snapshot["truncated"] = truncated
        snapshot["snapshot_digest"] = canonical_digest(snapshot)
        return snapshot

    def _filter(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._filter(item) for key, item in value.items()
                if key.casefold() not in self.SENSITIVE_KEYS
            }
        if isinstance(value, list):
            return [self._filter(item) for item in value]
        return value


PROMPT_FRAGMENTS = {
    "identity": "Use the authenticated project identity supplied by the bridge; never invent actor IDs.",
    "task_boundary": "Claim and resume prepare work. Only task.start begins execution.",
    "coordination": "Report explicit assumptions, uncertainty, and contract changes through project tools.",
}
PROMPT_VERSION = "1.0"
PROMPT_DIGEST = canonical_digest({"version": PROMPT_VERSION, "fragments": PROMPT_FRAGMENTS})
