"""User-controlled project completion, succession, and lineage reset flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id


@dataclass(slots=True)
class UserDecision:
    decision_id: str
    kind: str
    subject_ref: str
    expected_revision: int
    input_digest: str
    status: str = "pending"
    decision: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class OperationResolution:
    operation_id: str
    actor: str
    conclusion: str
    evidence_refs: tuple[dict[str, Any], ...]
    reason: str


class LifecycleService:
    def __init__(self, *, registry: ProjectRegistry, authority: AuthorityService) -> None:
        self.registry = registry
        self.authority = authority
        self.decisions: dict[str, UserDecision] = {}
        self.resolutions: list[OperationResolution] = []
        self.operations: dict[str, str] = {}
        self.succession: list[dict[str, Any]] = []

    def request_decision(
        self, *, kind: str, subject_ref: str, payload: dict[str, Any], expected_revision: int,
    ) -> UserDecision:
        decision = UserDecision(
            new_id(), kind, subject_ref, expected_revision,
            canonical_digest({"subject_ref": subject_ref, "payload": payload, "revision": expected_revision}),
        )
        self.decisions[decision.decision_id] = decision
        return decision

    def resolve_decision(
        self, decision_id: str, *, actor_kind: str, decision: str,
        input_digest: str, reason: str | None = None,
    ) -> UserDecision:
        if actor_kind != "user_control":
            raise PermissionError("user_only")
        item = self.decisions[decision_id]
        if item.status != "pending" or item.input_digest != input_digest:
            raise ValueError("decision_revision_or_digest_conflict")
        if decision not in {"approved", "rejected"}:
            raise ValueError("invalid_decision")
        item.status, item.decision, item.reason = "resolved", decision, reason
        return item

    def complete_project(
        self, *, expected_revision: int, evidence_refs: list[dict[str, Any]],
        request_checkpoint: Callable[[str], str],
    ) -> str:
        project = self.registry.project
        if project is None:
            raise RuntimeError("project_not_initialized")
        if project.policy_revision != expected_revision:
            raise ValueError("project_revision_conflict")
        project.lifecycle = "completed"
        project.policy_revision += 1
        operation_id = request_checkpoint(project.project_id)
        self.operations[operation_id] = "pending"
        return operation_id

    def checkpoint_result(self, operation_id: str, *, success: bool, reason: str | None = None) -> None:
        if operation_id not in self.operations:
            raise KeyError(operation_id)
        self.operations[operation_id] = "succeeded" if success else "failed"
        if not success:
            # Completion is already a user-confirmed fact; only archival is blocked.
            self.operations[f"repair:{operation_id}"] = "required"

    def archive_project(self, *, checkpoint_operation_id: str) -> None:
        project = self.registry.project
        if project is None or project.lifecycle != "completed":
            raise ValueError("project_not_completed")
        if self.operations.get(checkpoint_operation_id) != "succeeded":
            raise ValueError("checkpoint_barrier_not_met")
        project.lifecycle = "archived"

    def handoff(self, *, old_agent_id: str, new_agent_id: str, initiated_by: str) -> dict[str, Any]:
        if initiated_by not in {self.authority.main_agent_id, "user_control"}:
            raise PermissionError("handoff_authority_required")
        for session in self.authority.sessions.values():
            if session.agent_id == old_agent_id:
                session.active = False
                session.status = "ended"
        for key, grant in list(self.authority.grants.items()):
            if grant.principal_id == old_agent_id and grant.status == "active":
                self.authority.grants[key] = type(grant)(**{**asdict(grant), "capabilities": grant.capabilities, "status": "frozen"})
        record = {"old_agent_id": old_agent_id, "new_agent_id": new_agent_id, "status": "pending_stop_evidence"}
        self.succession.append(record)
        self.authority._save()
        return record

    def reset_lineage(self) -> dict[str, str]:
        project = self.registry.project
        if project is None:
            raise RuntimeError("project_not_initialized")
        old_lineage = project.current_lineage_id
        project.current_lineage_id = new_id()
        project.current_replica_id = new_id()
        project.runtime_epoch = new_id()
        self.authority.reset_runtime()
        return {"old_lineage_id": old_lineage, "new_lineage_id": project.current_lineage_id, "runtime_epoch": project.runtime_epoch}

    def resolve_unknown(
        self, *, operation_id: str, actor: str, conclusion: str,
        evidence_refs: list[dict[str, Any]], reason: str,
    ) -> OperationResolution:
        if conclusion not in {"verified_succeeded", "verified_failed", "risk_accepted", "retry_authorized"}:
            raise ValueError("invalid_resolution")
        resolution = OperationResolution(operation_id, actor, conclusion, tuple(evidence_refs), reason)
        self.resolutions.append(resolution)
        return resolution
