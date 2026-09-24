from __future__ import annotations

import pytest

from tsunagou.modules.coordination import CoordinationService


def _assignment() -> tuple[CoordinationService, str, str]:
    service = CoordinationService()
    plan = service.create_plan(
        main_agent_id="main",
        objective="wake callback fencing",
        auto_wake=True,
        assignments=[{"task_id": "task", "assigned_worker_id": "worker"}],
    )
    assignment = service.assignment(plan.assignment_ids[0])
    wake = service.wake(assignment.assignment_id)
    return service, assignment.assignment_id, wake.wake_attempt_id


def test_retry_rejects_late_host_acceptance_without_attempt_id() -> None:
    service, assignment_id, first_id = _assignment()
    retry = service.retry_wake(assignment_id)

    with pytest.raises(ValueError, match="wake_attempt_id_required"):
        service.record_host_accepted(assignment_id, host_turn_id="late")
    with pytest.raises(ValueError, match="stale_wake_attempt"):
        service.record_host_accepted(
            assignment_id, host_turn_id="late", wake_attempt_id=first_id,
        )

    current = service.wake(assignment_id)
    assert current.wake_attempt_id == retry.wake_attempt_id
    assert current.host_accepted is False


def test_retry_rejects_late_worker_ready_without_attempt_id() -> None:
    service, assignment_id, first_id = _assignment()
    retry = service.retry_wake(assignment_id)

    with pytest.raises(ValueError, match="wake_attempt_id_required"):
        service.record_worker_ready(assignment_id, worker_id="worker")
    with pytest.raises(ValueError, match="stale_wake_attempt"):
        service.record_worker_ready(
            assignment_id, worker_id="worker", wake_attempt_id=first_id,
        )

    current = service.wake(assignment_id)
    assert current.wake_attempt_id == retry.wake_attempt_id
    assert current.worker_ready is False
