import pytest

from tsunagou.application.workflows.task_execution import TaskExecutionWorkflow
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.tasks import TaskService, TaskStateError
from tsunagou.shared_kernel.errors import RevisionConflict


def fixture():
    tasks, cognition = TaskService(), CognitionService()
    workflow = TaskExecutionWorkflow(tasks=tasks, cognition=cognition)
    task = tasks.create_task("implement", "complete work")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    return tasks, cognition, workflow, task


def test_block_requires_new_attempt_and_stale_revision_cannot_take_ownership():
    tasks, cognition, workflow, task = fixture()
    stale = task.revision
    attempt = workflow.begin_attempt(task.task_id, "worker", task.revision)
    tasks.start(task.task_id, "worker")
    assert workflow.begin_attempt(task.task_id, "worker", task.revision) is attempt
    with pytest.raises(RevisionConflict):
        workflow.begin_attempt(task.task_id, "worker", stale)
    tasks.block(task.task_id, "waiting")
    with pytest.raises(TaskStateError):
        workflow.submit(task.task_id, "worker", {"summary": "late"}, attempt_id=attempt.attempt_id)
    fresh = workflow.begin_attempt(task.task_id, "other", task.revision)
    assert fresh.attempt_id != attempt.attempt_id


def test_only_required_accepted_contracts_and_real_task_dependencies_gate_begin():
    tasks, cognition, workflow, task = fixture()
    proposal = cognition.propose_contract({}, [{"slot": "owner", "agent_id": "worker", "required": True}])
    task.required_contract_ids = (proposal.proposal_id,)
    with pytest.raises(TaskStateError, match="required_contract_not_accepted"):
        workflow.begin_attempt(task.task_id, "worker", task.revision)
    cognition.accept_contract(proposal.proposal_id, participant_slot="owner", proposal_digest=proposal.digest, actor_id="worker")
    dependency = tasks.create_task("upstream", "dependency")
    task.blocks.add(dependency.task_id)
    with pytest.raises(TaskStateError, match="dependency_pending"):
        workflow.begin_attempt(task.task_id, "worker", task.revision)
    tasks.ready(dependency.task_id)
    tasks.publish(dependency.task_id)
    tasks.claim(dependency.task_id, "upstream")
    tasks.start(dependency.task_id, "upstream")
    result = tasks.submit(dependency.task_id, "upstream", {"summary": "done"})
    tasks.review(dependency.task_id, "main", result.result_id, decision="accepted")
    attempt = workflow.begin_attempt(task.task_id, "worker", task.revision)
    tasks.start(task.task_id, "worker")
    with pytest.raises(PermissionError):
        workflow.submit(task.task_id, "other", {}, attempt_id=attempt.attempt_id)
    assert workflow.submit(task.task_id, "worker", {"summary": "done"}, attempt_id=attempt.attempt_id).attempt_id == attempt.attempt_id
