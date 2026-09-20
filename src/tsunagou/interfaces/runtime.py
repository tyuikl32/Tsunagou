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
    "task.create": frozenset({"title", "objective", "parent_task_id", "blocks"}),
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
    "cognition.report": frozenset({
        "task_id", "attempt_id", "claims", "assumptions", "uncertainties", "boundary",
        "understanding", "confidence", "confidence_reason", "evidence_refs",
        "input_revisions", "supersedes_id",
    }),
    "contract.propose": frozenset({
        "payload", "participants_required", "participants_optional", "contract_id",
        "contract_kind", "subject_ref", "input_refs", "supersedes_id",
    }),
    "contract.accept": frozenset({
        "proposal_id", "participant_slot", "proposal_digest", "evidence_refs",
    }),
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
    def __init__(self, registry_path: str | Path) -> None:
        raw = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        self.registry: dict[str, dict[str, Any]] = raw["commands"]
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
        result = handler(envelope["payload"], {
            "principal_id": principal.principal_id,
            "session_id": principal.session_id,
            "connection_epoch": principal.connection_epoch,
            "command_hash": command_hash,
            "command_id": envelope["command_id"],
        })
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
