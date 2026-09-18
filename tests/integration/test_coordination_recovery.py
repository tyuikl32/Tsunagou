from pathlib import Path
from typing import Any, NoReturn

import pytest

from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.tasks import TaskService, TaskStateError
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.shared_kernel.errors import RevisionConflict


def test_pull_ack_recovery_keeps_one_delivery_and_one_owner(tmp_path: Path) -> None:
    messages = MessageStore(tmp_path / "inbox.json")
    message = messages.send(
        command_id="message-1", sender_agent_id="main", recipient_agent_id="worker",
        kind="task", subject_ref="task/1", summary="coordinate",
    )
    first = messages.fetch("worker")
    reloaded = MessageStore(tmp_path / "inbox.json")
    assert [item.message_id for item in first] == [message.message_id]
    assert reloaded.fetch("other") == []
    reloaded.ack("worker", message.message_id)
    assert reloaded.fetch("worker") == []

    tasks = TaskService()
    task = tasks.create_task("one", "one owner")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    tasks.claim(task.task_id, "agent-a")
    with pytest.raises(TaskStateError, match="task_not_claimable"):
        tasks.claim(task.task_id, "agent-b")


def test_sqlite_crash_before_commit_and_epoch_fence_are_not_success(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3")

    def crash(uow: Any) -> NoReturn:
        uow.append_event(lineage_id="l", event_type="will_rollback", aggregate_ref="x", actor_ref="a", payload={})
        raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        db.dispatch(principal_id="a", command_kind="test.crash", command_id="c", payload={}, handler=crash)
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    with db._connect() as conn:
        old = conn.execute(
            "SELECT runtime_epoch FROM runtime_fences WHERE project_id=?", ("local-project",)
        ).fetchone()[0]
    db.rotate_runtime_epoch()
    with pytest.raises(RevisionConflict):
        with db.transaction("stale") as uow:
            uow.assert_runtime_epoch(old)
