from __future__ import annotations

import time
from pathlib import Path

import pytest

from tsunagou.application.handlers import build_handlers
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.coordination import CoordinationService
from tsunagou.modules.messaging import MessageStore
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


def _actors() -> tuple[AuthorityService, dict[str, object]]:
    authority = AuthorityService(None)
    actors: dict[str, object] = {}
    for name in ("main", "worker"):
        receipt = authority.redeem_ticket(
            authority.issue_ticket(
                name,
                f"conversation-{name}",
                requested_role="main" if name == "main" else "worker",
            ),
            name,
            f"conversation-{name}",
            baseline=_baseline(),
        )
        actors[name] = receipt
    authority.appoint_main(actor_kind="user_control", agent_id=actors["main"].agent_id)  # type: ignore[union-attr]
    return authority, actors


def _ctx(receipt: object, kind: str) -> dict[str, object]:
    return {
        "kind": kind,
        "principal_id": receipt.agent_id,
        "session_id": receipt.session_id,
        "connection_epoch": receipt.connection_epoch,
        "command_id": f"reliability-{time.time_ns()}",
    }


def _open_task(tasks: TaskService, title: str = "reliability") -> str:
    task = tasks.create_task(title, "exercise reliability state machine")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    return task.task_id


def _lease_fixture() -> tuple[dict[str, object], AuthorityService, TaskService, ResourceService, object, object]:
    """Create a claimed task with a lease and a preflight captured while it is active."""
    authority, actors = _actors()
    tasks = TaskService()
    resources = ResourceService(ttl_seconds=120)
    handlers = build_handlers(authority=authority, tasks=tasks, resources=resources)
    worker = _ctx(actors["worker"], "B")
    task_id = _open_task(tasks)
    claimed = handlers["task.claim"]({"task_id": task_id}, worker)
    intent = handlers["resource.intent"](
        {
            "task_id": task_id,
            "attempt_id": claimed["attempt_id"],
            "scope_digest": "scope",
            "resources": [
                {
                    "kind": "path",
                    "root_id": "root",
                    "segments": ["reliability.py"],
                    "mode": "exclusive_write",
                }
            ],
        },
        worker,
    )
    lease = handlers["resource.acquire"](
        {
            "task_id": task_id,
            "attempt_id": claimed["attempt_id"],
            "intent_id": intent["intent_id"],
            "scope_digest": "scope",
        },
        worker,
    )
    preflight = handlers["task.preflight"](
        {"task_id": task_id, "attempt_id": claimed["attempt_id"]}, worker
    )
    return worker, authority, tasks, resources, lease, preflight


def test_task_start_rejects_expired_active_lease_before_execution_grant() -> None:
    """A stale maintenance tick must not let task.start cross into running."""
    worker, authority, tasks, resources, lease, preflight = _lease_fixture()
    attempt_id = preflight["attempt_id"]
    task_id = preflight["task_id"]
    handlers = build_handlers(authority=authority, tasks=tasks, resources=resources)

    # Keep the lease status active to model the race: the expiry observer has
    # not run yet, but the wall-clock deadline has already passed.
    resources.lease_sets[lease["lease_set_id"]].expires_at = time.time() - 1

    with pytest.raises(ValueError, match="lease|expired|stale|blocked"):
        handlers["task.start"](
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "preflight_id": preflight["preflight_id"],
            },
            worker,
        )

    assert tasks.attempts[attempt_id].status != "running"
    assert tasks.tasks[task_id].status != "running"
    assert not any(
        grant.attempt_id == attempt_id and grant.status == "active"
        for grant in authority.grants.values()
    )


def test_wake_callbacks_are_rejected_after_deadline() -> None:
    service = CoordinationService()

    host_plan = service.create_plan(
        main_agent_id="main",
        objective="deadline host acceptance",
        auto_wake=True,
        wake_deadline_seconds=60,
        assignments=[{"task_id": "task-host", "assigned_worker_id": "worker"}],
    )
    host_assignment = service.assignment(host_plan.assignment_ids[0])
    host_wake = service.wake(host_assignment.assignment_id)
    host_wake.deadline = time.time() - 1
    with pytest.raises(ValueError, match="wake_attempt_id_required"):
        service.record_host_accepted(host_assignment.assignment_id, host_turn_id="late-host")
    with pytest.raises(ValueError, match="expired|deadline|closed"):
        service.record_host_accepted(
            host_assignment.assignment_id,
            host_turn_id="late-host",
            wake_attempt_id=host_wake.wake_attempt_id,
        )

    ready_plan = service.create_plan(
        main_agent_id="main",
        objective="deadline worker ready",
        auto_wake=True,
        wake_deadline_seconds=60,
        assignments=[{"task_id": "task-ready", "assigned_worker_id": "worker"}],
    )
    ready_assignment = service.assignment(ready_plan.assignment_ids[0])
    ready_wake = service.wake(ready_assignment.assignment_id)
    service.record_host_accepted(
        ready_assignment.assignment_id,
        host_turn_id="host-ok",
        wake_attempt_id=ready_wake.wake_attempt_id,
    )
    ready_wake.deadline = time.time() - 1
    with pytest.raises(ValueError, match="wake_attempt_id_required"):
        service.record_worker_ready(ready_assignment.assignment_id, worker_id="worker")
    with pytest.raises(ValueError, match="expired|deadline|closed"):
        service.record_worker_ready(
            ready_assignment.assignment_id,
            worker_id="worker",
            wake_attempt_id=ready_wake.wake_attempt_id,
        )


class _MaintenanceState:
    def __init__(self) -> None:
        self.persisted = 0

    def capture(self) -> dict[str, str]:
        return {"marker": "before"}

    def restore(self, snapshot: dict[str, str]) -> None:
        del snapshot

    def persist(self, uow: object, *, actor_ref: str, command_kind: str) -> None:
        del actor_ref
        self.persisted += 1
        uow.append_event(
            lineage_id="local",
            event_type=command_kind,
            aggregate_ref="project/local-project",
            actor_ref="runtime",
            payload={},
        )


def test_runtime_maintenance_retries_expired_wakes_three_total_times(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "state.sqlite3")
    authority = AuthorityService(None)
    tasks = TaskService()
    resources = ResourceService()
    coordination = CoordinationService()
    plan = coordination.create_plan(
        main_agent_id="main",
        objective="wake retry",
        auto_wake=True,
        wake_deadline_seconds=60,
        assignments=[{"task_id": "task", "assigned_worker_id": "worker"}],
    )
    assignment = coordination.assignment(plan.assignment_ids[0])
    state = _MaintenanceState()
    maintenance = RuntimeMaintenance(
        database=database,
        state_runtime=state,
        resources=resources,
        tasks=tasks,
        authority=authority,
        coordination=coordination,
        interval_seconds=0.05,
    )

    # Expire each newly-created attempt before the next maintenance tick.
    for _ in range(3):
        coordination.wake(assignment.assignment_id).deadline = time.time() - 1
        maintenance.run_once()

    wakes = [
        wake for wake in coordination.wake_attempts.values()
        if wake.assignment_id == assignment.assignment_id
    ]
    assert len(wakes) == 3
    assert sorted(wake.retry_count for wake in wakes) == [0, 1, 2]
    final = coordination.wake(assignment.assignment_id)
    assert final.status in {"expired", "failed"}
    assert assignment.status == "blocked"
    assert any(
        event.kind == "wake.failed" and event.important
        and event.assignment_id == assignment.assignment_id
        for event in coordination.events
    )


def test_maintenance_does_not_renew_live_lease_without_worker_call(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "state.sqlite3")
    tasks = TaskService()
    task = tasks.create_task("live lease", "worker renewal")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    attempt = tasks.claim(task.task_id, "worker")
    resources = ResourceService(ttl_seconds=120)
    intent = resources.declare_intent(
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        owner_agent_id="worker",
        scope_digest="scope",
        resources=[ResourceRequest(ResourceKey.path("root", "file.py"), "exclusive_write")],
        reason="test",
    )
    lease = resources.reserve_set(intent.intent_id, execution_epoch=1, attempt_status="claimed")
    previous_expiry = lease.expires_at
    maintenance = RuntimeMaintenance(
        database=database,
        state_runtime=_MaintenanceState(),
        resources=resources,
        tasks=tasks,
        authority=AuthorityService(None),
        interval_seconds=0.05,
    )

    assert maintenance.run_once() == 0
    assert lease.status == "active"
    assert lease.expires_at == previous_expiry

    renewed = resources.renew(
        lease.lease_set_id,
        attempt_id=attempt.attempt_id,
        execution_epoch=attempt.execution_epoch,
        scope_digest="scope",
    )
    assert renewed.expires_at > previous_expiry


def test_main_message_send_makes_lease_reminder_visible_to_worker() -> None:
    authority, actors = _actors()
    messages = MessageStore()
    handlers = build_handlers(authority=authority, messages=messages)
    main = _ctx(actors["main"], "M")
    worker_id = actors["worker"].agent_id
    assignment_id = "assignment-reminder"
    attempt_id = "attempt-reminder"
    result = handlers["message.send"](
        {
            "recipient_agent_id": worker_id,
            "kind": "lease.reminder",
            "subject_ref": assignment_id,
            "summary": "Renew the active lease before continuing.",
            "payload": {
                "assignment_id": assignment_id,
                "task_id": "task-reminder",
                "attempt_id": attempt_id,
                "lease_expires_at": time.time() + 30,
                "renew_with": ["task.progress", "resource.renew"],
            },
        },
        main,
    )

    message_id = result["message_id"]
    visible = messages.sync(worker_id)
    assert [message.message_id for message in visible] == [message_id]
    message = messages.messages[message_id]
    assert message.sender_agent_id == actors["main"].agent_id
    assert message.subject_ref == assignment_id
    assert message.payload["attempt_id"] == attempt_id
    assert message.payload["renew_with"] == ["task.progress", "resource.renew"]


def test_worker_lifecycle_responses_expose_worker_owned_renewal_guidance() -> None:
    authority, actors = _actors()
    tasks = TaskService()
    resources = ResourceService(ttl_seconds=120)
    handlers = build_handlers(authority=authority, tasks=tasks, resources=resources)
    worker = _ctx(actors["worker"], "B")
    task_id = _open_task(tasks, title="guidance")

    claimed = handlers["task.claim"]({"task_id": task_id}, worker)
    assert claimed["lease_guidance"]["renewal_owner"] == "worker"
    assert claimed["lease_guidance"]["daemon_heartbeat"] is False
    assert claimed["lease_guidance"]["leases"] == []

    intent = handlers["resource.intent"](
        {
            "task_id": task_id,
            "attempt_id": claimed["attempt_id"],
            "scope_digest": "scope",
            "resources": [
                {
                    "kind": "path",
                    "root_id": "root",
                    "segments": ["guidance.py"],
                    "mode": "exclusive_write",
                }
            ],
        },
        worker,
    )
    acquired = handlers["resource.acquire"](
        {
            "task_id": task_id,
            "attempt_id": claimed["attempt_id"],
            "intent_id": intent["intent_id"],
            "scope_digest": "scope",
        },
        worker,
    )
    guidance = acquired["lease_guidance"]
    assert guidance["renewal_owner"] == "worker"
    assert guidance["daemon_heartbeat"] is False
    assert guidance["leases"][0]["lease_set_id"] == acquired["lease_set_id"]
    assert guidance["leases"][0]["expires_at"] == acquired["expires_at"]
