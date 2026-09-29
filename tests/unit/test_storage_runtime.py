from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

import pytest

from tsunagou.platform.db.sqlite import ProjectDatabase, _contains_secret_shape, _redact_result
from tsunagou.shared_kernel.errors import IdempotencyConflict, RevisionConflict
from tsunagou.shared_kernel.time import format_timestamp, parse_timestamp


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


def test_audit_event_envelope_is_timestamped_filterable_and_cursor_stable(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3", project_id="p1")

    for number, actor in enumerate(("agent/1", "agent/2", "agent/1"), start=1):
        def handler(uow, actor=actor, number=number):
            uow.append_event(
                lineage_id="lineage-1", event_type="thing.updated",
                aggregate_ref="thing/1", actor_ref=actor,
                subject_ref="task/1", revision_before=number - 1,
                revision_after=number, evidence_refs=("evidence/1",),
                payload={"number": number},
            )
            return {"number": number}

        db.dispatch(
            principal_id=actor, command_kind="thing.update", command_id=f"cmd-{number}",
            payload={"number": number},
            handler=handler,
        )

    page = db.list_events(limit=2)
    assert [item["event_seq"] for item in page] == [1, 2]
    assert page[0]["recorded_at"] >= page[0]["occurred_at"]
    assert page[0]["subject_ref"] == "task/1"
    assert page[0]["caused_by_command_id"] == "cmd-1"
    assert page[0]["evidence_refs"] == ["evidence/1"]
    assert format_timestamp(page[0]["occurred_at"]).endswith("Z")

    filtered = db.list_events(limit=10, cursor=1, actor_ref="agent/1", subject_ref="task/1")
    assert [item["event_seq"] for item in filtered] == [3]
    assert parse_timestamp(format_timestamp(page[0]["occurred_at"])) == page[0]["occurred_at"]


def test_public_timestamp_parser_rejects_naive_values() -> None:
    with pytest.raises(ValueError, match="timestamp_timezone_required"):
        parse_timestamp("2026-09-28T00:00:00")


def test_sensitive_command_result_is_private_and_replayed(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3", project_id="p1")
    result = {"agent_id": "agent/1", "secret_token": "secret-sentinel", "reconnect_nonce": "nonce-sentinel"}

    first = db.dispatch(
        principal_id="agent/1", command_kind="session.reconnect", command_id="cmd-secret",
        payload={"n": 1}, handler=lambda _uow: result,
    )
    replay = db.dispatch(
        principal_id="agent/1", command_kind="session.reconnect", command_id="cmd-secret",
        payload={"n": 1}, handler=lambda _uow: {"unexpected": True},
    )
    assert {key: first.result[key] for key in result} == result
    assert replay.result == first.result
    assert first.result["delivery_status"] == "delivered"
    with db._connect() as conn:
        raw = str(conn.execute("SELECT result_json FROM commands").fetchone()[0])
        assert "secret-sentinel" not in raw
        assert "nonce-sentinel" not in raw
        assert "delivery:" in raw
    delivery_files = list((tmp_path / "state.sqlite3.deliveries").glob("*.bin"))
    assert len(delivery_files) == 1
    if __import__("os").name == "nt":
        assert b"secret-sentinel" not in delivery_files[0].read_bytes()


@pytest.mark.parametrize("key,value", [
    ("token_usage", "unavailable"), ("TOKEN_USAGE", {"input": 42, "output": 7}), ("tokenUsage", "unavailable"),
])
def test_message_usage_accounting_does_not_create_credential_delivery(tmp_path: Path, key, value) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3", project_id="p1")
    message = {"message_id": "message-usage", "payload": {key: value}}
    assert not _contains_secret_shape(message)
    assert _redact_result(message) == message
    first = db.dispatch(principal_id="recipient", command_kind="inbox.fetch", command_id="fetch-usage",
                        payload={"message_id": "message-usage"}, handler=lambda _: message)
    replay = db.dispatch(principal_id="recipient", command_kind="inbox.fetch", command_id="fetch-usage",
                         payload={"message_id": "message-usage"}, handler=lambda _: pytest.fail("replayed handler"))
    assert first.result == replay.result == message
    with closing(db._connect()) as conn:
        row = conn.execute("SELECT result_json,delivery_ref FROM commands WHERE command_id='fetch-usage'").fetchone()
        assert row["delivery_ref"] is None and json.loads(row["result_json"]) == message
    assert not list(db.delivery_store.root.glob("*.bin"))


@pytest.mark.parametrize("payload", [
    {"token_usage": {"access_token": "secret-sentinel"}},
    {"tokenUsage": {"access_token": "secret-sentinel"}},
    {"token_usage": [{"token": "secret-sentinel"}]},
    {"token_usage": "unavailable", "secret_token": "secret-sentinel"},
    {"token_usage_extra": "secret-sentinel"},
])
def test_usage_accounting_exception_still_protects_nested_and_real_credentials(tmp_path: Path, payload) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3", project_id="p1")
    message = {"message_id": "message-sensitive", "payload": payload}
    assert _contains_secret_shape(message)
    assert "secret-sentinel" not in json.dumps(_redact_result(message))
    returned = db.dispatch(principal_id="recipient", command_kind="inbox.fetch", command_id="fetch-sensitive",
                           payload={"message_id": "message-sensitive"}, handler=lambda _: message)
    assert returned.result["payload"] == payload and returned.result["delivery_ref"].startswith("delivery:")
    with closing(db._connect()) as conn:
        row = conn.execute("SELECT result_json,delivery_ref FROM commands WHERE command_id='fetch-sensitive'").fetchone()
        assert row["delivery_ref"] and "secret-sentinel" not in row["result_json"]


def test_legacy_sensitive_rows_require_revocation_not_live_secret_replay(tmp_path: Path) -> None:
    db = ProjectDatabase(tmp_path / "state.sqlite3", project_id="p1")
    with db._connect() as conn:
        conn.execute(
            """INSERT INTO commands(project_id,principal_id,command_kind,command_id,input_hash,
               result_json,event_seq,created_at) VALUES(?,?,?,?,?,?,?,?)""",
            ("p1", "agent/1", "session.reconnect", "legacy", "hash",
             'x', None, 1),
        )
    from tsunagou.shared_kernel.digests import canonical_digest
    with db._connect() as conn:
        conn.execute(
            "UPDATE commands SET input_hash=? WHERE command_id='legacy'",
            (canonical_digest({"project_id": "p1", "principal_id": "agent/1",
                               "command_kind": "session.reconnect", "payload": {},
                               "expected_revision": None}),),
        )
        conn.execute(
            "UPDATE commands SET result_json=? WHERE command_id='legacy'",
            ('{"secret_token":"legacy-secret","agent_id":"agent/1"}',),
        )
    assert db.sensitive_command_rows()[0]["command_id"] == "legacy"
    with pytest.raises(RuntimeError, match="credential_revocation_migration_required"):
        db.scrub_sensitive_command_rows()
    with pytest.raises(RuntimeError, match="legacy_credential_migration_required"):
        db.dispatch(
            principal_id="agent/1", command_kind="session.reconnect", command_id="legacy",
            payload={}, handler=lambda _uow: {"unexpected": True},
        )
    assert list((tmp_path / "state.sqlite3.deliveries").glob("*.bin")) == []
