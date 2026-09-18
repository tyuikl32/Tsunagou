import threading

import pytest

from tsunagou.modules.tasks import TaskService, TaskStateError


def open_task(service: TaskService):
    task = service.create_task("task", "do it")
    service.ready(task.task_id)
    service.publish(task.task_id)
    return task


def test_concurrent_claim_has_one_owner() -> None:
    service = TaskService()
    task = open_task(service)
    results = []

    def claim(agent: str) -> None:
        try:
            results.append(service.claim(task.task_id, agent).owner_agent_id)
        except TaskStateError:
            results.append("rejected")

    threads = [threading.Thread(target=claim, args=(agent,)) for agent in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["a", "rejected"] or sorted(results) == ["b", "rejected"]


def test_resume_is_claimed_then_start_and_submit_review() -> None:
    service = TaskService()
    task = open_task(service)
    attempt = service.claim(task.task_id, "worker")
    service.block(task.task_id, "waiting")
    resumed = service.resume(task.task_id, "worker")
    assert resumed.status == "claimed"
    with pytest.raises(TaskStateError, match="blocked"):
        service.start(task.task_id, "worker", workspace_ready=False)
    # blocked resume is explicit; it does not silently start after a failed preflight
    service.resume(task.task_id, "worker")
    service.start(task.task_id, "worker")
    result = service.submit(task.task_id, "worker", {"answer": 42})
    service.review(task.task_id, "reviewer", result.result_id, decision="accepted")
    assert service.tasks[task.task_id].status == "completed"
    assert service.attempts[attempt.attempt_id].status == "completed"


def test_changes_requested_closes_old_attempt_and_parent_does_not_cascade() -> None:
    service = TaskService()
    parent = service.create_task("parent", "coordinate")
    child = service.create_task("child", "execute", parent_task_id=parent.task_id)
    service.ready(child.task_id)
    service.publish(child.task_id)
    service.claim(child.task_id, "worker")
    service.start(child.task_id, "worker")
    result = service.submit(child.task_id, "worker", {"done": False})
    service.review(child.task_id, "reviewer", result.result_id, decision="changes_requested")
    assert child.status == "changes_requested"
    assert parent.status == "draft"
    service.ready(child.task_id)
    service.publish(child.task_id)
    new_attempt = service.claim(child.task_id, "worker")
    assert new_attempt.attempt_id != result.attempt_id


def test_blocks_dag_rejects_cycle_and_restore_is_atomic() -> None:
    service = TaskService()
    first = service.create_task("first", "x")
    second = service.create_task("second", "y")
    service.add_block(first.task_id, second.task_id)
    with pytest.raises(TaskStateError, match="cycle"):
        service.add_block(second.task_id, first.task_id)
    service.ready(first.task_id)
    with pytest.raises(TaskStateError, match="restore_open"):
        service.restore_open([first.task_id, second.task_id])
    assert first.status == "ready"
