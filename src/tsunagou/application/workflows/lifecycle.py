"""User-controlled project completion, succession, and lineage reset flows."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
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
    # What the proposer actually asked, including the choices offered. It used to
    # only feed the digest, which left "what am I deciding" unanswerable for every
    # reader that was not the proposer.
    payload: dict[str, Any] = field(default_factory=dict)


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
            payload=dict(payload),
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
        answer = decision.strip() if isinstance(decision, str) else ""
        if not answer or answer not in self.answerable_values(item):
            raise ValueError("invalid_decision")
        item.status, item.decision, item.reason = "resolved", answer, reason
        return item

    @staticmethod
    def answerable_values(item: UserDecision) -> tuple[str, ...]:
        """Which answers this one decision accepts.

        The proposer owns the vocabulary: ``choices`` is what it offered, and the
        runbook answers with one of those real values
        (``docs/standalone/debugging-runbook.md``, B5: "阅读后按该决定 choices 中的真实值
        填写；以下选择 approved 只用于该选项确实存在时"). So the offered words are read
        here instead of assuming every answer is a yes/no.

        ``approved``/``rejected`` are the fallback **only** for a decision proposed
        without options (the completion proposal carries no ``choices``): they are
        not a second vocabulary. Answering ``approved`` to a decision whose options
        are, say, 「再补一轮回归 / 换方案」 is refused rather than recorded as an
        answer the proposer never offered.
        """

        offered: list[str] = []
        for choice in item.payload.get("choices") or ():
            if isinstance(choice, str):
                value = choice.strip()
            elif isinstance(choice, dict):
                # Choices may arrive as {value, label} rows; either field is the answer.
                value = str(choice.get("value") or choice.get("label") or "").strip()
            else:
                value = ""
            if value and value not in offered:
                offered.append(value)
        return tuple(offered) if offered else ("approved", "rejected")

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
