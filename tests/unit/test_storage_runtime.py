from __future__ import annotations

from pathlib import Path

import pytest

from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.shared_kernel.errors import IdempotencyConflict, RevisionConflict


def test_transaction_event_outbox_and_idempotency(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3", project_id="p1")

    def handler(uow):
        seq = uow.append_event(
            lineage_id="lineage-1", event_type="thing_created",
            aggregate_ref="thing/1", actor_ref="agent/1", payload={"value": 1},
        )
        uow.stage_outbox(kind="notify", target_ref="thing/1", payload={"seq": seq})
        return {"value": 1, "seq": seq}

    first = db.dispatch(
        principal_id="agent/1", command_kind="thing.create", command_id="cmd-1",
        payload={"value": 1}, handler=handler,
    )
    replay = db.dispatch(
        principal_id="agent/1", command_kind="thing.create", command_id="cmd-1",
        payload={"value": 1}, handler=lambda _: {"value": 99},
    )
    assert first.result == replay.result
    assert replay.replayed is True
    with pytest.raises(IdempotencyConflict):
        db.dispatch(
            principal_id="agent/1", command_kind="thing.create", command_id="cmd-1",
            payload={"value": 2}, handler=handler,
        )
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1


def test_rollback_does_not_leave_event_or_command(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3")

    def failing(uow):
        uow.append_event(
            lineage_id="l", event_type="will_rollback",
            aggregate_ref="x", actor_ref="a", payload={},
        )
        raise RuntimeError("injected")

    with pytest.raises(RuntimeError):
        db.dispatch(
            principal_id="a", command_kind="test.fail", command_id="c",
            payload={}, handler=failing,
        )
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0


def test_job_lease_fences_stale_worker_and_unknown_is_historical(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3")

    with db.transaction("create-operation") as uow:
        operation_id = uow.create_operation(
            kind="external", requested_by="agent", payload={"path": "x"}
        )
        job_id = uow.enqueue_job(
            operation_id=operation_id, handler_kind="external_call", payload={"path": "x"}
        )
    claimed = db.claim_job("worker-a")
    assert claimed is not None and claimed["job_id"] == job_id
    with pytest.raises(RevisionConflict):
        db.finish_job(job_id, worker_id="worker-b", lease_epoch=claimed["lease_epoch"], outcome="succeeded")
    db.mark_unknown(operation_id)
    with db._connect() as conn:
        row = conn.execute("SELECT status FROM operations WHERE id=?", (operation_id,)).fetchone()
        assert row[0] == "outcome_unknown"
    with db.transaction("resolve") as uow:
        uow.resolve_operation(
            operation_id, actor="main", conclusion="risk_accepted",
            evidence_refs=[{"kind": "external", "ref": "receipt"}], reason="accepted",
        )
    with db._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM resolutions WHERE operation_id=?", (operation_id,)
        ).fetchone()[0] == 1


def test_resolution_payload_is_not_used_as_an_execution_retry(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3")
    with db.transaction("create") as uow:
        operation_id = uow.create_operation(
            kind="unverifiable", requested_by="a", payload={"n": 1}
        )
        uow.resolve_operation(
            operation_id, actor="a", conclusion="retry_authorized",
            evidence_refs=[], reason="new operation required",
        )
    with db._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_retry_backoff_and_expired_external_effect_becomes_unknown(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3")
    with db.transaction("create-jobs") as uow:
        retry_op = uow.create_operation(kind="local", requested_by="a", payload={})
        retry_job = uow.enqueue_job(
            operation_id=retry_op, handler_kind="local_step", payload={}, max_attempts=3
        )
        ext_op = uow.create_operation(kind="external", requested_by="a", payload={})
        ext_job = uow.enqueue_job(
            operation_id=ext_op, handler_kind="external_call", payload={}, max_attempts=3
        )
    first = db.claim_job("worker-a", lease_seconds=1)
    assert first is not None and first["job_id"] in {retry_job, ext_job}
    db.finish_job(
        first["job_id"], worker_id="worker-a", lease_epoch=first["lease_epoch"],
        outcome="retry", backoff_seconds=1,
    )
    second = db.claim_job("worker-b", lease_seconds=1)
    assert second is not None
    db.finish_job(
        second["job_id"], worker_id="worker-b", lease_epoch=second["lease_epoch"],
        outcome="unknown",
    )
    with db._connect() as conn:
        statuses = dict(conn.execute("SELECT id,status FROM operations").fetchall())
        assert "retry_wait" in statuses.values() or "outcome_unknown" in statuses.values()


def test_runtime_epoch_rotation_rejects_stale_worker(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3")
    with db._connect() as conn:
        old_epoch = conn.execute(
            "SELECT runtime_epoch FROM runtime_fences WHERE project_id=?", ("local-project",)
        ).fetchone()[0]
    new_epoch = db.rotate_runtime_epoch()
    assert new_epoch != old_epoch
    with pytest.raises(RevisionConflict):
        with db.transaction("stale") as uow:
            uow.assert_runtime_epoch(old_epoch)
