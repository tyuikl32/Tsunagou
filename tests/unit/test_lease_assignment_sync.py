from __future__ import annotations

import time
from pathlib import Path

import pytest

from tsunagou.application.handlers import build_handlers
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.coordination import CoordinationService
from tsunagou.modules.resources import ResourceKey, ResourceRequest, ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.platform.maintenance import RuntimeMaintenance
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES


def _baseline() -> dict[str, object]:
    return {
        "baseline": {
            name: {"status": "supported", "evidence_refs": [f"test:{name}"]}
            for name in BASELINE_CAPABILITIES
        }
    }


def _actors() -> tuple[AuthorityService, object, object]:
    authority = AuthorityService(None)
    receipts = []
    for name, role in (("main", "main"), ("worker", "worker")):
        ticket = authority.issue_ticket(name, f"session-{name}", requested_role=role)
        receipts.append(
            authority.redeem_ticket(
                ticket, name, f"session-{name}", baseline=_baseline(),
            )
        )
    authority.appoint_main(actor_kind="user_control", agent_id=receipts[0].agent_id)
    return authority, receipts[0], receipts[1]


def _context(receipt: object, kind: str = "B") -> dict[str, object]:
    return {
        "kind": kind,
        "principal_id": receipt.agent_id,  # type: ignore[attr-defined]
        "session_id": receipt.session_id,  # type: ignore[attr-defined]
        "connection_epoch": receipt.connection_epoch,  # type: ignore[attr-defined]
        "command_id": f"lease-assignment-{time.time_ns()}",
    }


def _task_with_lease(
    *, coordination: CoordinationService | None = None,
) -> tuple[TaskService, ResourceService, object, object, dict[str, object], dict[str, object]]:
    authority, _main, worker = _actors()
    tasks = TaskService()
    task = tasks.create_task("lease sync", "reconcile assignment after expiry")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    coordination = coordination or CoordinationService()
    plan = coordination.create_plan(
        main_agent_id="main",
        objective="lease assignment sync",
        auto_wake=False,
        assignments=[{"task_id": task.task_id, "assigned_worker_id": worker.agent_id}],  # type: ignore[attr-defined]
    )
    assignment = coordination.assignment(plan.assignment_ids[0])
    resources = ResourceService(ttl_seconds=120)
    handlers = build_handlers(
        authority=authority, tasks=tasks, resources=resources,
        coordination=coordination,
    )
    worker_context = _context(worker)
    claimed = handlers["task.claim"]({"task_id": task.task_id}, worker_context)
    intent = handlers["resource.intent"](
        {
            "task_id": task.task_id,
            "attempt_id": claimed["attempt_id"],
            "scope_digest": "scope",
            "resources": [{
                "kind": "path", "root_id": "root", "segments": ["lease-sync.py"],
                "mode": "exclusive_write",
            }],
        },
        worker_context,
    )
    lease = handlers["resource.acquire"](
        {
            "task_id": task.task_id,
            "attempt_id": claimed["attempt_id"],
            "intent_id": intent["intent_id"],
            "scope_digest": "scope",
        },
        worker_context,
    )
    return tasks, resources, worker, assignment, worker_context, {
        "task_id": task.task_id,
        "attempt_id": claimed["attempt_id"],
        "lease_set_id": lease["lease_set_id"],
        "handlers": handlers,
        "authority": authority,
    }


def test_handler_lease_reconciliation_blocks_assignment_idempotently() -> None:
    coordination = CoordinationService()
    tasks, resources, _worker, assignment, worker_context, facts = _task_with_lease(
        coordination=coordination,
    )
    lease = resources.lease_sets[facts["lease_set_id"]]
    lease.expires_at = time.time() - 1

    with pytest.raises(ValueError, match="resource_lease_expired|attempt|preflight"):
        facts["handlers"]["task.start"](  # type: ignore[index]
            {"task_id": facts["task_id"], "attempt_id": facts["attempt_id"]},
            worker_context,
        )

    assert tasks.tasks[facts["task_id"]].status == "open"
    assert tasks.attempts[facts["attempt_id"]].status == "orphaned"
    assert assignment.status == "blocked"
    assert assignment.claimed_attempt_id is None
    assert assignment.started_at is None
    events = [
        event for event in coordination.events
        if event.kind == "lease.expired" and event.assignment_id == assignment.assignment_id
    ]
    assert len(events) == 1
    assert events[0].important

    # The stale lease row remains expired and a repeated request must not add
    # another event or create a replacement WakeAttempt.
    with pytest.raises((ValueError, KeyError)):
        facts["handlers"]["task.start"](  # type: ignore[index]
            {"task_id": facts["task_id"], "attempt_id": facts["attempt_id"]},
            worker_context,
        )
    assert len([
        event for event in coordination.events
        if event.kind == "lease.expired" and event.assignment_id == assignment.assignment_id
    ]) == 1


class _MaintenanceState:
    def capture(self) -> dict[str, str]:
        return {"marker": "before"}

    def restore(self, snapshot: dict[str, str]) -> None:
        del snapshot

    def persist(self, uow: object, *, actor_ref: str, command_kind: str) -> None:
        del actor_ref
        uow.append_event(  # type: ignore[attr-defined]
            lineage_id="local", event_type=command_kind,
            aggregate_ref="project/local-project", actor_ref="runtime", payload={},
        )


def test_runtime_maintenance_blocks_assignment_after_lease_expiry(tmp_path: Path) -> None:
    authority, _main, worker = _actors()
    tasks = TaskService()
    task = tasks.create_task("maintenance lease sync", "reconcile")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    attempt = tasks.claim(task.task_id, worker.agent_id)  # type: ignore[attr-defined]
    coordination = CoordinationService()
    plan = coordination.create_plan(
        main_agent_id="main", objective="maintenance lease sync", auto_wake=False,
        assignments=[{"task_id": task.task_id, "assigned_worker_id": worker.agent_id}],  # type: ignore[attr-defined]
    )
    assignment = coordination.assignment(plan.assignment_ids[0])
    coordination.mark_claimed(task.task_id, worker.agent_id, attempt.attempt_id)  # type: ignore[attr-defined]

    resources = ResourceService(ttl_seconds=1)
    intent = resources.declare_intent(
        task_id=task.task_id, attempt_id=attempt.attempt_id,
        owner_agent_id=worker.agent_id, scope_digest="scope",
        resources=[ResourceRequest(ResourceKey.path("root", "maintenance.py"), "exclusive_write")],
        reason="test",
    )
    lease = resources.reserve_set(intent.intent_id, execution_epoch=1, now=time.time() - 2)
    maintenance = RuntimeMaintenance(
        database=ProjectDatabase(tmp_path / "state.sqlite3"),
        state_runtime=_MaintenanceState(), resources=resources, tasks=tasks,
        authority=authority, coordination=coordination,
    )

    assert maintenance.run_once() == 1
    assert lease.status == "expired"
    assert tasks.attempts[attempt.attempt_id].status == "orphaned"
    assert tasks.tasks[task.task_id].status == "open"
    assert assignment.status == "blocked"
    assert assignment.claimed_attempt_id is None
    assert assignment.started_at is None
    assert len([
        event for event in coordination.events
        if event.kind == "lease.expired" and event.assignment_id == assignment.assignment_id
    ]) == 1


def test_runtime_maintenance_repairs_assignment_after_partial_orphan_recovery(tmp_path: Path) -> None:
    """A stale Assignment is repaired even when Task/Attempt were fenced first."""
    coordination = CoordinationService()
    tasks, resources, _worker, assignment, _worker_context, facts = _task_with_lease(
        coordination=coordination,
    )
    attempt = tasks.attempts[facts["attempt_id"]]
    task = tasks.tasks[facts["task_id"]]
    attempt.status = "orphaned"
    task.status = "open"
    task.current_attempt_id = None
    lease = resources.lease_sets[facts["lease_set_id"]]
    lease.status = "expired"
    lease.expires_at = time.time() - 1

    maintenance = RuntimeMaintenance(
        database=ProjectDatabase(tmp_path / "state.sqlite3"),
        state_runtime=_MaintenanceState(), resources=resources, tasks=tasks,
        authority=facts["authority"], coordination=coordination,
    )

    assert maintenance.run_once() == 1
    assert assignment.status == "blocked"
    assert assignment.claimed_attempt_id is None
    assert assignment.started_at is None
    assert len([
        event for event in coordination.events
        if event.kind == "lease.expired" and event.assignment_id == assignment.assignment_id
    ]) == 1

    # A second maintenance pass is replay-safe and does not duplicate the
    # important coordination event.
    assert maintenance.run_once() == 0
    assert len([
        event for event in coordination.events
        if event.kind == "lease.expired" and event.assignment_id == assignment.assignment_id
    ]) == 1
