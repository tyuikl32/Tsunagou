from __future__ import annotations

import time
from pathlib import Path

from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.resources import ResourceKey, ResourceRequest, ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.platform.maintenance import RuntimeMaintenance


class FakeState:
    def __init__(self) -> None:
        self.persisted = 0
        self.restored = False

    def capture(self) -> dict[str, str]:
        return {"marker": "before"}

    def restore(self, snapshot: dict[str, str]) -> None:
        self.restored = snapshot == {"marker": "before"}

    def persist(self, uow: object, *, actor_ref: str, command_kind: str) -> None:
        del actor_ref
        self.persisted += 1
        uow.append_event(  # type: ignore[attr-defined]
            lineage_id="local", event_type=command_kind,
            aggregate_ref="project/local-project", actor_ref="runtime", payload={},
        )


def test_expired_lease_orphans_attempt_and_persists_reconciliation(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "state.sqlite3")
    tasks = TaskService()
    task = tasks.create_task("lease", "expire")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    attempt = tasks.claim(task.task_id, "worker")
    resources = ResourceService(ttl_seconds=1)
    intent = resources.declare_intent(
        task_id=task.task_id, attempt_id=attempt.attempt_id, owner_agent_id="worker",
        scope_digest="scope", resources=[ResourceRequest(ResourceKey.path("root", "a.py"), "exclusive_write")],
        reason="test",
    )
    lease = resources.reserve_set(intent.intent_id, execution_epoch=1, now=time.time() - 2)
    state = FakeState()
    maintenance = RuntimeMaintenance(
        database=database, state_runtime=state, resources=resources,
        tasks=tasks, authority=AuthorityService(None), interval_seconds=0.05,
    )

    assert maintenance.run_once() == 1
    assert lease.status == "expired"
    assert tasks.tasks[task.task_id].status == "orphaned"
    assert tasks.attempts[attempt.attempt_id].status == "orphaned"
    assert state.persisted == 1
    assert database.last_event_seq() == 1


def test_expired_job_lease_is_recovered_without_executing_effect(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "state.sqlite3")
    with database.transaction("seed-job") as uow:
        operation_id = uow.create_operation(
            kind="workspace.prepare", requested_by="worker", payload={"root": "repo"},
            status="running",
        )
        job_id = uow.enqueue_job(
            operation_id=operation_id, handler_kind="internal.workspace.prepare",
            payload={"root": "repo"},
        )
    with database.transaction("expire-job") as uow:
        now = 0
        uow.conn.execute(
            """UPDATE jobs SET status='running',attempt_count=1,lease_owner=?,
               lease_epoch=1,lease_until=?,updated_at=? WHERE id=?""",
            ("dead-worker", now, now, job_id),
        )
        uow.conn.execute(
            """INSERT INTO job_attempts(job_id,attempt_no,lease_epoch,worker_id,started_at)
               VALUES(?,?,?,?,?)""",
            (job_id, 1, 1, "dead-worker", now),
        )

    state = FakeState()
    maintenance = RuntimeMaintenance(
        database=database, state_runtime=state, resources=ResourceService(),
        tasks=TaskService(), authority=AuthorityService(None), interval_seconds=0.05,
    )

    assert maintenance.run_once() == 1
    with database._connect() as conn:
        job = conn.execute("SELECT status,lease_owner,lease_until FROM jobs WHERE id=?", (job_id,)).fetchone()
        operation = conn.execute("SELECT status FROM operations WHERE id=?", (operation_id,)).fetchone()
    assert tuple(job) == ("retry_wait", None, None)
    assert tuple(operation) == ("retry_wait",)
