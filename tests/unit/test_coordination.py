import pytest

from tsunagou.modules.coordination import CoordinationService


def test_assignments_allow_one_worker_many_tasks_and_status_is_a_task_projection():
    service = CoordinationService()
    plan = service.create_plan(
        main_agent_id="main",
        objective="work",
        assignments=[
            {"task_id": "first", "assigned_worker_id": "worker"},
            {"task_id": "second", "assigned_worker_id": "worker", "dependencies": ["first"]},
        ],
    )
    assignment = service.assignment(plan.assignment_ids[0])
    assert not hasattr(assignment, "status") and not hasattr(assignment, "claimed_attempt_id")
    assert service.coverage({"first": "submitted", "second": "open"})["by_status"] == {"submitted": 1, "open": 1}
    assert service.require_assigned_worker("first", "worker") is assignment
    with pytest.raises(PermissionError):
        service.require_assigned_worker("first", "main")
    service.takeover(assignment.assignment_id, main_agent_id="main", reason="explicit reassignment")
    assert service.require_assigned_worker("first", "main") is assignment
    with pytest.raises(PermissionError):
        service.require_assigned_worker("first", "worker")


def test_duplicate_assignment_rejected_before_any_mutation():
    service = CoordinationService()
    with pytest.raises(ValueError, match="duplicate_assignment_task"):
        service.create_plan(
            main_agent_id="main",
            objective="work",
            assignments=[
                {"task_id": "first", "assigned_worker_id": "a"},
                {"task_id": "first", "assigned_worker_id": "b"},
            ],
        )
    assert not service.plans and not service.assignments
