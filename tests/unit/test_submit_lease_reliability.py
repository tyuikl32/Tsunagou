"""Regression coverage for the task.submit execution/Lease boundary."""

from __future__ import annotations

import time
from typing import Any

import pytest

from tsunagou.application.handlers import build_handlers
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.resources import ResourceKey, ResourceRequest, ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES


def _baseline() -> dict[str, Any]:
    return {
        "baseline": {
            name: {"status": "supported", "evidence_refs": [f"test:{name}"]}
            for name in ADMISSION_CAPABILITIES
        }
    }


def _fixture() -> tuple[dict[str, str], AuthorityService, TaskService, ResourceService, str, str, str]:
    authority = AuthorityService(None)
    receipt = authority.redeem_ticket(
        authority.issue_ticket("worker", "worker-conversation"),
        "worker", "worker-conversation", baseline=_baseline(),
    )
    tasks = TaskService()
    resources = ResourceService()
    handlers = build_handlers(authority=authority, tasks=tasks, resources=resources)
    task = tasks.create_task("submit", "release execution lease")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    worker = {
        "kind": "B", "principal_id": receipt.agent_id,
        "session_id": receipt.session_id, "command_id": "submit-reliability",
    }
    claimed = handlers["task.claim"]({"task_id": task.task_id}, worker)
    attempt_id = claimed["attempt_id"]
    intent = resources.declare_intent(
        task_id=task.task_id, attempt_id=attempt_id, owner_agent_id=receipt.agent_id,
        scope_digest="submit-scope",
        resources=[ResourceRequest(ResourceKey.path("root", "result.txt"), "exclusive_write")],
        reason="submit test",
    )
    lease = resources.reserve_set(intent.intent_id, execution_epoch=1, attempt_status="claimed")
    preflight = tasks.preflight(task.task_id, receipt.agent_id, attempt_id=attempt_id)
    tasks.start(task.task_id, receipt.agent_id, preflight_id=preflight.preflight_id, require_preflight=True)
    authority.issue_execution_grant(
        agent_id=receipt.agent_id, session_id=receipt.session_id,
        task_id=task.task_id, attempt_id=attempt_id,
    )
    return worker, authority, tasks, resources, task.task_id, attempt_id, lease.lease_set_id


def test_task_submit_releases_active_lease() -> None:
    worker, authority, tasks, resources, task_id, attempt_id, lease_id = _fixture()
    handlers = build_handlers(authority=authority, tasks=tasks, resources=resources)

    result = handlers["task.submit"](
        {"task_id": task_id, "attempt_id": attempt_id, "summary": "done"}, worker,
    )

    assert result["result_id"] in tasks.results
    assert tasks.tasks[task_id].status == "submitted"
    assert tasks.attempts[attempt_id].status == "submitted"
    assert resources.lease_sets[lease_id].status == "released"


def test_task_submit_rejects_expired_lease_without_result() -> None:
    worker, authority, tasks, resources, task_id, attempt_id, lease_id = _fixture()
    handlers = build_handlers(authority=authority, tasks=tasks, resources=resources)
    resources.lease_sets[lease_id].expires_at = time.time() - 1

    with pytest.raises(ValueError, match="resource_lease_expired"):
        handlers["task.submit"](
            {"task_id": task_id, "attempt_id": attempt_id, "summary": "late"}, worker,
        )

    assert not tasks.results
    assert tasks.tasks[task_id].status == "open"
    assert tasks.attempts[attempt_id].status == "orphaned"
    assert resources.lease_sets[lease_id].status == "expired"

