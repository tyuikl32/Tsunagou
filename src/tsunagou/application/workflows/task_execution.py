"""Preflight and task execution orchestration without a second domain store."""

from __future__ import annotations

import time
from typing import Any

from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import PreflightResult, TaskResult, TaskService, TaskStateError
from tsunagou.modules.workspaces import WorkspaceService
from tsunagou.shared_kernel.digests import canonical_digest


class TaskExecutionWorkflow:
    def __init__(
        self, *, tasks: TaskService, cognition: CognitionService,
        resources: ResourceService, workspaces: WorkspaceService,
        strict_runtime: bool = False,
    ) -> None:
        self.tasks = tasks
        self.cognition = cognition
        self.resources = resources
        self.workspaces = workspaces
        self.strict_runtime = strict_runtime

    def preflight(
        self, task_id: str, agent_id: str | None = None, *,
        attempt_id: str | None = None, evidence_refs: tuple[str, ...] = (),
    ) -> PreflightResult:
        task = self.tasks.tasks[task_id]
        attempt = self.tasks._current_attempt(task)
        owner = agent_id or attempt.owner_agent_id
        evidence: dict[str, Any] = {
            "task_revision": task.revision,
            "scope_revision": task.scope_revision,
            "attempt_revision": attempt.revision,
            "attempt_status": attempt.status,
            "reports": sorted(
                report.digest for report in self.cognition.reports.values()
                if report.task_id == task_id and report.attempt_id == attempt.attempt_id
            ),
            "contracts": sorted(
                f"{proposal.digest}:{proposal.status}"
                for proposal in self.cognition.proposals.values()
            ),
            "workspace_status": self._workspace_status(attempt.attempt_id),
        }
        evidence.update(self._lease_evidence(attempt.attempt_id))
        blockers: list[str] = []
        if attempt.owner_agent_id != owner:
            raise TaskStateError("attempt_owner_required")
        if task.status not in {"claimed", "running"}:
            blockers.append("task_not_claimed")
        if attempt.status not in {"claimed", "running"}:
            blockers.append("attempt_not_preparable")
        if evidence["workspace_status"] not in {None, "ready", "result_recorded"}:
            blockers.append("workspace_not_ready")
        if self.strict_runtime:
            if not evidence["lease_valid"]:
                blockers.append("resource_lease_required")
            if evidence["workspace_status"] != "ready":
                blockers.append("workspace_ready_required")
            linked_contracts = [
                proposal for proposal in self.cognition.proposals.values()
                if isinstance(proposal.payload, dict)
                and proposal.payload.get("task_id") == task_id
            ]
            if any(proposal.status != "accepted" for proposal in linked_contracts):
                blockers.append("contract_not_accepted")
        digest = canonical_digest(evidence)
        return self.tasks.preflight(
            task_id, owner, attempt_id=attempt_id or attempt.attempt_id,
            evidence_refs=evidence_refs, input_digest=digest,
            blockers=tuple(dict.fromkeys(blockers)), evidence=evidence,
        )

    def start(self, preflight: PreflightResult, *, agent_id: str) -> None:
        # Keep direct workflow callers under the same execution fence as the
        # command handler.  ResourceService uses an RLock, so the handler may
        # safely hold it across grant issuance as well.
        with self.resources._lock:  # noqa: SLF001 - shared in-process state fence
            current = self._current_evidence(preflight.task_id)
            # Lease expiry is an execution fence, independent of the
            # maintenance thread.  A stale active lease must never let
            # TaskService move the attempt to ``running``; a missing lease is
            # still permitted for the legacy non-strict workflow.
            if current["lease_ids"] and not current["lease_valid"]:
                raise TaskStateError("resource_lease_expired")
            if current["digest"] != preflight.input_digest or preflight.blockers:
                raise TaskStateError("stale_or_blocked_preflight")
            # Re-read the clock immediately before the state transition.  A
            # lease can cross its deadline while digest/revision checks are
            # running; the resource lock prevents maintenance from hiding that
            # fact until after ``TaskService.start``.
            lease_evidence = self._lease_evidence(preflight.attempt_id)
            if lease_evidence["lease_ids"] and not lease_evidence["lease_valid"]:
                raise TaskStateError("resource_lease_expired")
            attempt = self.tasks.start(
                preflight.task_id, agent_id, preflight_id=preflight.preflight_id,
                require_preflight=True,
            )
            if attempt.attempt_id != preflight.attempt_id:
                raise TaskStateError("attempt_id_mismatch")

    def block(self, task_id: str, reason: str) -> PreflightResult:
        self.tasks.block(task_id, reason)
        return self.preflight(task_id)

    def resume(self, task_id: str, agent_id: str) -> PreflightResult:
        self.tasks.resume(task_id, agent_id)
        return self.preflight(task_id)

    def submit(
        self, task_id: str, agent_id: str, payload: dict[str, Any], *,
        attempt_id: str | None = None,
    ) -> TaskResult:
        """Submit an attempt while fencing its execution Lease.

        Submission is the terminal operation for a running attempt.  Keep the
        resource lock held while checking the wall-clock deadline, moving the
        task to ``submitted`` and releasing its Lease rows so runtime
        maintenance cannot expire the same Lease between those operations.
        A worker must never be able to publish a result after its Lease has
        expired, even when the maintenance thread has not run yet.
        """
        with self.resources._lock:  # noqa: SLF001 - execution fence
            task = self.tasks.tasks[task_id]
            attempt = self.tasks._current_attempt(task)
            if attempt_id is not None and attempt.attempt_id != attempt_id:
                raise TaskStateError("attempt_id_mismatch")

            now = time.time()
            # Mark due rows before evaluating the current attempt.  This keeps
            # the status durable for callers that invoke the workflow directly
            # (without the command handler's reconciliation callback).
            self.resources.expire_due(now=now)
            attempt_leases = [
                lease for lease in self.resources.lease_sets.values()
                if lease.attempt_id == attempt.attempt_id
            ]
            if any(
                lease.status == "expired"
                or (lease.status == "active" and lease.expires_at <= now)
                for lease in attempt_leases
            ):
                raise TaskStateError("resource_lease_expired")

            result = self.tasks.submit(task_id, agent_id, payload)
            self.resources.release_for_attempt(attempt.attempt_id, reason="attempt_submitted")
            return result

    def _workspace_status(self, attempt_id: str) -> str | None:
        statuses = [workspace.status for workspace in self.workspaces.workspaces.values() if workspace.attempt_id == attempt_id]
        return statuses[-1] if statuses else None

    def _current_evidence(self, task_id: str) -> dict[str, Any]:
        task = self.tasks.tasks[task_id]
        attempt = self.tasks._current_attempt(task)
        evidence: dict[str, Any] = {
            "task_revision": task.revision,
            "scope_revision": task.scope_revision,
            "attempt_revision": attempt.revision,
            "attempt_status": attempt.status,
            "reports": sorted(
                report.digest for report in self.cognition.reports.values()
                if report.task_id == task_id and report.attempt_id == attempt.attempt_id
            ),
            "contracts": sorted(
                f"{proposal.digest}:{proposal.status}"
                for proposal in self.cognition.proposals.values()
            ),
            "workspace_status": self._workspace_status(attempt.attempt_id),
        }
        evidence.update(self._lease_evidence(attempt.attempt_id))
        return {"digest": canonical_digest(evidence), **evidence}

    def _lease_evidence(self, attempt_id: str) -> dict[str, Any]:
        """Return stable lease identity plus an explicit current validity bit.

        A preflight must become stale when a lease is renewed (its expiry
        changes) or when the expiry passes before ``task.start``.  Including
        the durable expiry timestamp in the digest handles renewal; checking
        the wall-clock validity in ``start`` handles an untouched lease whose
        status is still ``active`` because maintenance has not run yet.
        """
        with self.resources._lock:  # noqa: SLF001 - snapshot the lease set atomically
            now = time.time()
            leases = [
                lease for lease in self.resources.lease_sets.values()
                if lease.attempt_id == attempt_id and lease.status == "active"
            ]
            states = sorted(
                [
                    {
                        "lease_set_id": lease.lease_set_id,
                        "status": lease.status,
                        "expires_at": lease.expires_at,
                    }
                    for lease in leases
                ],
                key=lambda item: str(item["lease_set_id"]),
            )
            return {
                "lease_ids": [item["lease_set_id"] for item in states],
                "lease_states": states,
                "lease_valid": bool(leases) and all(lease.expires_at > now for lease in leases),
            }
