import pytest

from tsunagou.application.workflows.task_execution import TaskExecutionWorkflow
from tsunagou.modules.cognition import Claim, CognitionService
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import TaskService, TaskStateError
from tsunagou.modules.workspaces import WorkspaceService


def test_two_agents_disagree_contract_then_complete_task() -> None:
    tasks = TaskService()
    cognition = CognitionService()
    workflow = TaskExecutionWorkflow(
        tasks=tasks, cognition=cognition, resources=ResourceService(), workspaces=WorkspaceService()
    )
    task = tasks.create_task("implement", "choose driver")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    attempt = tasks.claim(task.task_id, "agent-a")
    cognition.submit_report(
        task_id=task.task_id, attempt_id=attempt.attempt_id, actor_agent_id="agent-a",
        claims=[Claim("driver", "literal", "value", "shared")],
    )
    cognition.submit_report(
        task_id=task.task_id, attempt_id=attempt.attempt_id, actor_agent_id="agent-b",
        claims=[Claim("driver", "literal", "value", "worktree")],
    )
    proposal = cognition.propose_contract(
        {"driver": "worktree"}, [{"slot": "owner", "agent_id": "agent-a", "required": True}]
    )
    cognition.accept_contract(
        proposal.proposal_id, participant_slot="owner", proposal_digest=proposal.digest, actor_id="agent-a"
    )
    preflight = workflow.preflight(task.task_id)
    assert preflight.valid
    workflow.start(preflight, agent_id="agent-a")
    result = workflow.submit(task.task_id, "agent-a", {"status": "done"})
    assert result.attempt_id == attempt.attempt_id


def test_stale_preflight_and_blocked_resume_never_auto_start() -> None:
    tasks = TaskService()
    workflow = TaskExecutionWorkflow(
        tasks=tasks, cognition=CognitionService(), resources=ResourceService(), workspaces=WorkspaceService()
    )
    task = tasks.create_task("task", "x")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    tasks.claim(task.task_id, "worker")
    preflight = workflow.preflight(task.task_id)
    tasks.block(task.task_id, "user decision")
    with pytest.raises(TaskStateError, match="stale"):
        workflow.start(preflight, agent_id="worker")
    resumed = workflow.resume(task.task_id, "worker")
    assert resumed.valid
    assert tasks.tasks[task.task_id].status == "claimed"
