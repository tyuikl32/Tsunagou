from __future__ import annotations

from pathlib import Path

from tsunagou.modules.resources import ResourceKey, ResourceRequest, ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.platform.maintenance import RuntimeMaintenance


def test_maintenance_never_changes_silent_task_or_reservation(tmp_path: Path) -> None:
    database = ProjectDatabase(tmp_path / "state.sqlite3")
    tasks = TaskService()
    task = tasks.create_task("ownership", "no expiry")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    attempt = tasks.claim(task.task_id, "worker")
    resources = ResourceService()
    reservation = resources.reserve_set(
        task_id=task.task_id, attempt_id=attempt.attempt_id, owner_agent_id="worker",
        execution_epoch=1, scope_digest="scope",
        requests=[ResourceRequest(ResourceKey.path("root", "a.py"), "exclusive_write")],
    )
    reservation.created_at = 1
    maintenance = RuntimeMaintenance(database=database)
    assert maintenance.run_once() == 0
    assert reservation.status == "active" and attempt.status == "claimed"
    assert task.current_attempt_id == attempt.attempt_id
    assert database.last_event_seq() == 0


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

    maintenance = RuntimeMaintenance(
        database=database, interval_seconds=0.05,
    )

    assert maintenance.run_once() == 1
    with database._connect() as conn:
        job = conn.execute("SELECT status,lease_owner,lease_until FROM jobs WHERE id=?", (job_id,)).fetchone()
        operation = conn.execute("SELECT status FROM operations WHERE id=?", (operation_id,)).fetchone()
    assert tuple(job) == ("retry_wait", None, None)
    assert tuple(operation) == ("retry_wait",)
