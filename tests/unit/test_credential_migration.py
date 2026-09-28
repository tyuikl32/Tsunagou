import contextlib
import json
from pathlib import Path

import pytest

from tsunagou.platform.credential_migration import CredentialMigration, assert_credential_migration_ready
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.platform.private_files import protect_bytes, write_private_bytes
from tsunagou.shared_kernel.errors import LockUnavailable

SECRET = "legacy-usable-secret-sentinel-123456"
TICKET = "legacy-raw-ticket-sentinel-123456"


def _legacy(tmp_path: Path) -> tuple[ProjectDatabase, CredentialMigration]:
    state = tmp_path / ".tsunagou/local"
    state.mkdir(parents=True)
    db = ProjectDatabase(state / "state.sqlite3", project_id="p1")
    with db.transaction("legacy") as uow:
        authority = {
            "sessions": {"s1": {"session_id": "s1", "agent_id": "a1", "active": True, "status": "ready",
                                "credential_hash": "original-hash", "reconnect_nonce_hash": "original-nonce-hash",
                                "connection_epoch": 2}},
            "tickets": {"hash": {"ticket_id": "t1", "used": False, "expires_at": 9999999999}},
            "grants": {"g1": {"status": "active"}}, "agents": {"a1": {"role": "main"}},
            "main_agent_id": "a1", "authority_epoch": 2,
        }
        uow.put_module_state("authority", json.dumps(authority))
        for principal, kind in ((TICKET, "agent.enroll"), ("a1", "session.reconnect")):
            uow.conn.execute(
                "INSERT INTO commands(project_id,principal_id,command_kind,command_id,input_hash,result_json,event_seq,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                ("p1", principal, kind, "same-id", "old-hash", json.dumps({"secret_token": SECRET, "agent_id": "a1"}), None, 100),
            )
        uow.append_event(lineage_id=db.lineage_id, event_type="legacy.updated", aggregate_ref="project/p1", actor_ref="a1",
                         payload={"accidentally_logged": SECRET})
    artifact = tmp_path / ".tsunagou/artifacts/unsafe.patch"
    artifact.parent.mkdir()
    artifact.write_text(f"diff fixture with {SECRET}")
    return db, CredentialMigration(tmp_path)


def test_preview_is_readonly_and_confirm_revokes_scrubs_quarantines_and_replays(tmp_path: Path) -> None:
    db, migration = _legacy(tmp_path)
    before = db.path.read_bytes()
    plan = migration.preview()
    assert before == db.path.read_bytes()
    assert not migration.marker.exists()
    assert SECRET not in json.dumps(plan) and TICKET not in json.dumps(plan)
    assert "artifacts\\unsafe.patch" in plan["quarantine_files"] or "artifacts/unsafe.patch" in plan["quarantine_files"]
    old_epoch = db.runtime_epoch
    report = migration.apply(plan["plan_digest"])
    assert report["status"] == "completed" and report["integrity_check"] == "ok"
    assert migration.apply(plan["plan_digest"]) == report
    assert db.runtime_epoch != old_epoch
    assert_credential_migration_ready(migration.state_dir)
    with contextlib.closing(db._connect()) as conn:
        authority = json.loads(conn.execute("SELECT payload_json FROM module_state WHERE module='authority'").fetchone()[0])
        assert authority["sessions"]["s1"]["active"] is False
        assert authority["sessions"]["s1"]["connection_epoch"] == 3
        assert authority["tickets"]["hash"]["used"] is True
        assert authority["grants"]["g1"]["status"] == "revoked"
        assert authority["main_agent_id"] is None
        receipts = conn.execute("SELECT principal_id,result_json FROM commands").fetchall()
        assert len(receipts) == 2  # Composite IDs were not conflated.
        assert sum(row[0].startswith("ticket-sha256:") for row in receipts) == 1
        assert all(json.loads(row[1])["delivery_status"] == "revoked" for row in receipts)
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db.path) + suffix)
        if path.exists():
            assert SECRET.encode() not in path.read_bytes() and TICKET.encode() not in path.read_bytes()
    backup = migration.state_dir / report["backup_relative_path"]
    assert backup.is_file() and SECRET.encode() in backup.read_bytes()
    assert not (tmp_path / ".tsunagou/artifacts/unsafe.patch").exists()
    assert (backup.parent / "quarantine/artifacts/unsafe.patch").exists()
    assert len([event for event in db.list_events() if event["event_type"] == "credential.migrate"]) == 1


def test_changed_plan_and_live_daemon_are_rejected(tmp_path: Path) -> None:
    db, migration = _legacy(tmp_path)
    plan = migration.preview()
    db.acquire_process_lock()
    try:
        with pytest.raises(LockUnavailable):
            migration.apply(plan["plan_digest"])
    finally:
        db.release_process_lock()
    (tmp_path / ".tsunagou/artifacts/unsafe.patch").write_text(f"changed {SECRET}")
    with pytest.raises(ValueError, match="migration_plan_changed"):
        migration.apply(plan["plan_digest"])
    assert not migration.marker.exists()


def test_interruption_fences_startup_and_original_plan_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, migration = _legacy(tmp_path)
    plan = migration.preview()
    original = migration._revoke_and_scrub

    def interrupted(operation_id: str, known: set[str]) -> None:
        original(operation_id, known)
        raise RuntimeError("fixture_after_revocation_commit")

    with monkeypatch.context() as context:
        context.setattr(migration, "_revoke_and_scrub", interrupted)
        with pytest.raises(RuntimeError, match="fixture_after_revocation_commit"):
            migration.apply(plan["plan_digest"])
    with pytest.raises(RuntimeError, match="credential_migration_incomplete"):
        assert_credential_migration_ready(migration.state_dir)
    assert migration.apply(plan["plan_digest"])["status"] == "completed"
    assert_credential_migration_ready(migration.state_dir)
    assert len([event for event in db.list_events() if event["event_type"] == "credential.migrate"]) == 1


def test_unmarked_legacy_database_cannot_start_or_be_reopened_by_old_completed_marker(tmp_path: Path) -> None:
    db, migration = _legacy(tmp_path)
    before = db.path.read_bytes()
    with pytest.raises(RuntimeError, match="^credential_migration_required$"):
        assert_credential_migration_ready(migration.state_dir)
    assert before == db.path.read_bytes()
    plan = migration.preview()
    report = migration.apply(plan["plan_digest"])
    # Recreate a leaked credential after a prior completed migration. Its
    # completion marker must not bypass the startup fence.
    with db.transaction("restored-legacy-row") as uow:
        uow.conn.execute("UPDATE commands SET result_json=? WHERE command_kind='session.reconnect'",
                         (json.dumps({"secret_token": SECRET}),))
    with pytest.raises(RuntimeError, match="^credential_migration_required$"):
        assert_credential_migration_ready(migration.state_dir)
    new_plan = migration.preview()
    rerun = migration.apply(new_plan["plan_digest"])
    assert rerun["operation_id"] != report["operation_id"]
    assert_credential_migration_ready(migration.state_dir)


def test_old_plaintext_escrow_is_blocked_even_with_safe_database(tmp_path: Path) -> None:
    state_dir = tmp_path / ".tsunagou/local"
    ProjectDatabase(state_dir / "state.sqlite3", project_id="p1")
    assert_credential_migration_ready(state_dir)
    (state_dir / "state.sqlite3.deliveries/old.json").write_text(json.dumps({"secret_token": SECRET}))
    with pytest.raises(RuntimeError, match="^credential_migration_required$"):
        assert_credential_migration_ready(state_dir)
    migration = CredentialMigration(tmp_path)
    migration.apply(migration.preview()["plan_digest"])
    assert_credential_migration_ready(state_dir)


def test_assembled_daemon_rejects_legacy_before_constructing_database_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tsunagou.bootstrap import container

    _, migration = _legacy(tmp_path)
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(migration.state_dir))

    def forbidden_writer(*args: object, **kwargs: object) -> None:
        raise AssertionError("database_writer_opened_before_migration_check")

    monkeypatch.setattr(container, "ProjectDatabase", forbidden_writer)
    with pytest.raises(RuntimeError, match="^credential_migration_required$"):
        container.build_application()


@pytest.mark.parametrize("value", [[], None, "completed", {"status": "in_progress"}, {"status": "completed"}])
def test_nonobject_or_incomplete_private_marker_fails_closed(tmp_path: Path, value: object) -> None:
    write_private_bytes(tmp_path / "credential-migration.json", protect_bytes(json.dumps(value).encode()))
    with pytest.raises(RuntimeError, match="^credential_migration_incomplete$"):
        assert_credential_migration_ready(tmp_path)


@pytest.mark.parametrize("result", ["incomplete-json-with-sensitive-sentinel", "[]", "null"])
def test_migration_handles_corrupt_credential_result_without_guessing_fields(tmp_path: Path, result: str) -> None:
    db, migration = _legacy(tmp_path)
    with db.transaction("corrupt-result") as uow:
        uow.conn.execute("UPDATE commands SET result_json=? WHERE command_kind='session.reconnect'", (result,))
    migration.apply(migration.preview()["plan_digest"])
    assert_credential_migration_ready(migration.state_dir)
    with contextlib.closing(db._connect()) as conn:
        value = json.loads(conn.execute("SELECT result_json FROM commands WHERE command_kind='session.reconnect'").fetchone()[0])
    assert value["delivery_status"] == "revoked"


def test_quarantine_report_survives_crash_after_unlink_before_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, migration = _legacy(tmp_path)
    plan = migration.preview()
    original = migration._save_marker

    def interrupted(marker: dict) -> None:
        if marker.get("quarantined_files"):
            raise RuntimeError("fixture_after_quarantine_unlink")
        original(marker)

    with monkeypatch.context() as context:
        context.setattr(migration, "_save_marker", interrupted)
        with pytest.raises(RuntimeError, match="fixture_after_quarantine_unlink"):
            migration.apply(plan["plan_digest"])
    assert not (tmp_path / ".tsunagou/artifacts/unsafe.patch").exists()
    report = migration.apply(plan["plan_digest"])
    assert str(Path("artifacts/unsafe.patch")) in report["quarantined_files"]
