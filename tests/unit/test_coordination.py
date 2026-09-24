from __future__ import annotations

import time
from pathlib import Path

import pytest

from tsunagou.application.handlers import build_handlers
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.coordination import CoordinationService
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES


def _baseline() -> dict[str, object]:
    return {"baseline": {
        name: {"status": "supported", "evidence_refs": [f"test:{name}"]}
        for name in BASELINE_CAPABILITIES
    }}


def _actors() -> tuple[AuthorityService, dict[str, object]]:
    authority = AuthorityService(None)
    actors: dict[str, object] = {}
    for name in ("main", "worker-a", "worker-b", "worker-c"):
        receipt = authority.redeem_ticket(
            authority.issue_ticket(name, f"conversation-{name}", requested_role="main" if name == "main" else "worker"),
            name, f"conversation-{name}", baseline=_baseline(),
        )
        actors[name] = receipt
    authority.appoint_main(actor_kind="user_control", agent_id=actors["main"].agent_id)  # type: ignore[union-attr]
    return authority, actors


def _ctx(receipt: object, kind: str) -> dict[str, object]:
    return {
        "kind": kind, "principal_id": receipt.agent_id, "session_id": receipt.session_id,
        "connection_epoch": receipt.connection_epoch, "command_id": f"test-{time.time_ns()}",
    }


def test_plan_requires_ready_worker_coverage_and_ready_gate() -> None:
    authority, actors = _actors()
    coordination = CoordinationService()
    tasks = TaskService()
    resources = ResourceService()
    handlers = build_handlers(
        authority=authority, tasks=tasks, resources=resources, coordination=coordination,
    )
    main = _ctx(actors["main"], "M")
    workers = [actors[name] for name in ("worker-a", "worker-b", "worker-c")]
    plan = handlers["coordination.plan"]({
        "objective": "parallel test",
        "auto_wake": True,
        "assignments": [
            {"title": f"part-{index}", "task_objective": "do part", "assigned_worker_id": worker.agent_id}
            for index, worker in enumerate(workers)
        ],
    }, main)
    assert plan["status"] == "active"
    first = plan["assignments"][0]
    worker = _ctx(workers[0], "B")
    with pytest.raises(ValueError, match="host_acceptance_required|worker_ready_required"):
        handlers["task.claim"]({"task_id": first["task_id"]}, worker)
    handlers["coordination.wake.accepted"]({
        "assignment_id": first["assignment_id"], "wake_attempt_id": first["wake_attempt_id"],
        "host_turn_id": "turn-1",
    }, {"kind": "D"})
    ready = handlers["worker.ready"]({
        "assignment_id": first["assignment_id"], "wake_attempt_id": first["wake_attempt_id"],
    }, worker)
    assert ready["status"] == "ready"
    claimed = handlers["task.claim"]({"task_id": first["task_id"]}, worker)
    assert claimed["attempt_id"]


def test_progress_renews_each_active_lease_and_takeover_is_explicit() -> None:
    authority, actors = _actors()
    coordination = CoordinationService()
    tasks = TaskService()
    resources = ResourceService(ttl_seconds=120)
    handlers = build_handlers(
        authority=authority, tasks=tasks, resources=resources, coordination=coordination,
    )
    main = _ctx(actors["main"], "M")
    worker = _ctx(actors["worker-a"], "B")
    plan = handlers["coordination.plan"]({
        "objective": "takeover test",
        "auto_wake": True,
        "assignments": [
            {"title": f"part-{index}", "task_objective": "do part", "assigned_worker_id": actors[f"worker-{suffix}"].agent_id}
            for index, suffix in enumerate(("a", "b", "c"))
        ],
    }, main)
    assignment = plan["assignments"][0]
    handlers["coordination.wake.accepted"]({
        "assignment_id": assignment["assignment_id"],
        "wake_attempt_id": assignment["wake_attempt_id"],
    }, {"kind": "D"})
    handlers["worker.ready"]({
        "assignment_id": assignment["assignment_id"],
        "wake_attempt_id": assignment["wake_attempt_id"],
    }, worker)
    claimed = handlers["task.claim"]({"task_id": assignment["task_id"]}, worker)
    attempt_id = claimed["attempt_id"]
    intent = handlers["resource.intent"]({
        "task_id": assignment["task_id"], "attempt_id": attempt_id,
        "scope_digest": "scope", "resources": [{
            "kind": "path", "root_id": "root", "segments": ["file.py"], "mode": "exclusive_write",
        }],
    }, worker)
    lease = handlers["resource.acquire"]({
        "task_id": assignment["task_id"], "attempt_id": attempt_id,
        "intent_id": intent["intent_id"], "scope_digest": "scope",
    }, worker)
    preflight = handlers["task.preflight"]({"task_id": assignment["task_id"], "attempt_id": attempt_id}, worker)
    handlers["task.start"]({
        "task_id": assignment["task_id"], "attempt_id": attempt_id,
        "preflight_id": preflight["preflight_id"],
    }, worker)
    expires_before = lease["expires_at"]
    progress = handlers["task.progress"]({
        "task_id": assignment["task_id"], "attempt_id": attempt_id,
        "summary": "working", "evidence_refs": [],
    }, {**worker, "kind": "X"})
    assert progress["renewed_leases"][0]["expires_at"] > expires_before
    takeover = handlers["coordination.takeover"]({
        "assignment_id": assignment["assignment_id"], "takeover_reason": "worker unavailable",
    }, main)
    assert takeover["takeover_reason"] == "worker unavailable"


def test_important_events_are_durable_and_visible() -> None:
    service = CoordinationService()
    event = service.record_event(
        "worker.ready", actor_id="worker", assignment_id="assignment",
        task_id="task", summary="ready", important=True,
    )
    snapshot = {
        "event_id": event.event_id, "kind": event.kind,
        "important": event.important,
    }
    assert snapshot == {"event_id": event.event_id, "kind": "worker.ready", "important": True}


def test_wake_retry_is_three_total_attempts() -> None:
    service = CoordinationService()
    plan = service.create_plan(
        main_agent_id="main", objective="retry", auto_wake=True,
        assignments=[{"task_id": "task", "assigned_worker_id": "worker"}],
    )
    assignment = service.assignment(plan.assignment_ids[0])
    second = service.retry_wake(assignment.assignment_id)
    third = service.retry_wake(assignment.assignment_id)
    assert second.retry_count == 1
    assert third.retry_count == 2
    with pytest.raises(ValueError, match="retry_limit"):
        service.retry_wake(assignment.assignment_id)


def test_review_rework_creates_a_fresh_wake_attempt() -> None:
    service = CoordinationService()
    plan = service.create_plan(
        main_agent_id="main", objective="rework", auto_wake=True,
        assignments=[{"task_id": "task", "assigned_worker_id": "worker"}],
    )
    assignment = service.assignment(plan.assignment_ids[0])
    first_wake = service.wake(assignment.assignment_id)
    service.record_host_accepted(
        assignment.assignment_id, wake_attempt_id=first_wake.wake_attempt_id,
    )
    service.record_worker_ready(
        assignment.assignment_id, worker_id="worker",
        wake_attempt_id=first_wake.wake_attempt_id,
    )
    service.mark_claimed("task", "worker", "attempt-1")
    service.mark_submitted("task", "worker", "attempt-1")
    replacement = service.rework(assignment.assignment_id, reason="tests failed")
    assert replacement is not None
    assert replacement.wake_attempt_id != first_wake.wake_attempt_id
    assert replacement.previous_attempt_id == first_wake.wake_attempt_id
    assert assignment.status == "waking"


def test_project_opt_in_controls_plan_default(tmp_path: Path) -> None:
    authority, actors = _actors()
    repo = tmp_path / "coordination"
    (repo / ".git").mkdir(parents=True)
    registry = ProjectRegistry.initialize(repo, name="demo", objective="parallel")
    coordination = CoordinationService()
    tasks = TaskService()
    handlers = build_handlers(
        authority=authority, tasks=tasks, resources=ResourceService(),
        coordination=coordination, project_registry=registry,
    )
    main = _ctx(actors["main"], "M")
    assignments = [
        {"title": f"part-{index}", "task_objective": "do part", "assigned_worker_id": actors[name].agent_id}
        for index, name in enumerate(("worker-a", "worker-b", "worker-c"))
    ]
    with pytest.raises(ValueError, match="project_opt_in"):
        handlers["coordination.plan"]({"objective": "parallel", "auto_wake": True, "assignments": assignments}, main)
    configured = handlers["project.configure"]({
        "policy_patch": {"auto_wake_multi_agent": True}, "reason": "enable parallel wake",
    }, main)
    assert configured["settings"]["auto_wake_multi_agent"] is True
    plan = handlers["coordination.plan"]({"objective": "parallel", "assignments": assignments}, main)
    assert all(item["wake_attempt_id"] for item in plan["assignments"])


def test_project_policy_controls_implicit_auto_wake(tmp_path) -> None:
    authority, actors = _actors()
    repository = tmp_path / "coordination"
    (repository / ".git").mkdir(parents=True)
    projects = ProjectRegistry.initialize(repository, name="demo", objective="coordinate")
    coordination = CoordinationService()
    tasks = TaskService()
    handlers = build_handlers(authority=authority, tasks=tasks, coordination=coordination, project_registry=projects)
    main = _ctx(actors["main"], "M")
    assignment_payload = [
        {"title": f"part-{index}", "task_objective": "do part", "assigned_worker_id": actors[f"worker-{suffix}"].agent_id}
        for index, suffix in enumerate(("a", "b", "c"))
    ]
    with pytest.raises(ValueError, match="auto_wake_project_opt_in_required"):
        handlers["coordination.plan"]({
            "objective": "not enabled", "auto_wake": True, "assignments": assignment_payload,
        }, main)
    handlers["project.configure"]({
        "policy_patch": {"auto_wake_multi_agent": True}, "reason": "enable multi-agent wake",
    }, main)
    plan = handlers["coordination.plan"]({"objective": "enabled", "assignments": assignment_payload}, main)
    assert all(item["wake_attempt_id"] for item in plan["assignments"])
