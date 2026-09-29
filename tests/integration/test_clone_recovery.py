"""Real local Git clone -> preview/confirm -> daemon recovery without authority."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_trace_audit import Runtime
from typer.testing import CliRunner

from tsunagou.bootstrap.container import build_application
from tsunagou.cli.app import app as cli
from tsunagou.modules.projects import ProjectRegistry
from tsunagou.platform.clone_recovery import CloneRecovery
from tsunagou.shared_kernel.ids import new_id


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    source = tmp_path / "source"
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    registry = ProjectRegistry.initialize(source, name="restore", objective="keep history")
    assert registry.project is not None
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(source))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(source / ".tsunagou/local"))
    monkeypatch.setenv("TSUNAGOU_PROJECT_ID", registry.project.project_id)
    monkeypatch.setenv("TSUNAGOU_PROJECT_INDEX", str(tmp_path / "projects.json"))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "control")
    monkeypatch.delenv("TSUNAGOU_HOST_WAKE", raising=False)
    server = build_application()
    runtime = Runtime(server, registry.project.project_id)
    try:
        main, _ = runtime.enroll("main")
        worker, _ = runtime.enroll("worker")
        runtime.call("authority.appoint", {"agent_id": main["agent_id"]})
        task = runtime.call("task.create", {"title": "resume later", "objective": "never revive a grant"}, main)
        runtime.call("task.ready", {"task_id": task["task_id"]}, main)
        runtime.call("task.publish", {"task_id": task["task_id"]}, main)
        claim = runtime.call(
            "task.begin",
            {"task_id": task["task_id"], "expected_task_revision": server.state.state_runtime.tasks.tasks[task["task_id"]].revision},
            worker,
        )
        state = server.state.state_runtime
        before_artifact = state.capture()
        artifact_bytes = b"promoted artifact survives clean-clone recovery\n"
        upload = state.artifacts.begin_upload(domain_ref=f"task/{task['task_id']}", actor=worker["agent_id"])
        state.artifacts.write_chunk(upload.intent_id, artifact_bytes)
        artifact = state.artifacts.finalize(upload.intent_id, media_type="text/plain")
        state.artifacts.promote(
            artifact.artifact_ref,
            actor_kind="main",
            actor_id=main["agent_id"],
            project_shared_allowed=lambda *_: True,
        )
        artifact.project_id = registry.project.project_id
        artifact.lineage_id = state.lineage_id
        with runtime.db.transaction(new_id()) as uow:
            state.persist(
                uow,
                actor_ref=main["agent_id"],
                command_kind="artifact.promote",
                before=before_artifact,
                command_payload={"domain_ref": artifact.domain_ref},
                result={"artifact_ref": artifact.artifact_ref},
            )
        checkpoint = runtime.call("checkpoint.create.user", {"reason": "clone_fixture"})
        assert checkpoint["checkpoint_status"] == "sealed"
    finally:
        server.state.project_database.release_process_lock()
    subprocess.run(["git", "-c", "core.autocrlf=false", "add", ".tsunagou/project.json", ".tsunagou/checkpoints"], cwd=source, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "shared checkpoint"], cwd=source, check=True)
    target = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", "--no-local", str(source), str(target)], check=True)
    return {
        "root": target,
        "project_id": registry.project.project_id,
        "task_id": task["task_id"],
        "attempt_id": claim["attempt_id"],
        "checkpoint": checkpoint,
        "worker": worker,
        "main": main,
        "artifact_ref": artifact.artifact_ref,
        "artifact_bytes": artifact_bytes,
        "artifact_digest": artifact.digest,
    }


def test_clean_clone_preview_confirm_and_restart(clone: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    root = clone["root"]
    digest = clone["checkpoint"]["checkpoint_digest"]
    recovery = CloneRecovery(root)
    preview = recovery.preview(digest)
    assert preview["can_confirm"] and preview["requires_recovery_review"] == 1
    assert preview["local_anchors"]
    assert not (root / ".tsunagou/local").exists()
    with pytest.raises(ValueError, match="preview_changed"):
        recovery.confirm(digest, "wrong")
    result = recovery.confirm(digest, preview["plan_digest"])
    assert result["status"] == "restored"
    assert recovery.confirm(digest, preview["plan_digest"])["replayed"]
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(root))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(root / ".tsunagou/local"))
    restored = build_application()
    try:
        state = restored.state.state_runtime
        assert state.authority.main_agent_id is None
        assert not state.authority.sessions and not state.authority.grants and not state.authority.tickets
        assert not state.resources.reservations and not state.project_registry.local_bindings
        task = state.tasks.tasks[clone["task_id"]]
        assert task.status == "blocked" and task.block_reason == "recovery_review" and task.current_attempt_id is None
        assert state.tasks.attempts[clone["attempt_id"]].status == "orphaned"
        assert state.authority.agents[clone["worker"]["agent_id"]].status == "retired"
        artifact = state.artifacts.refs[clone["artifact_ref"]]
        assert artifact.storage_scope == "project_shared" and artifact.recipient_agent_id is None
        assert state.artifacts.blobs[clone["artifact_digest"]].storage_state == "promoted"
        assert (
            state.artifacts.read(
                clone["artifact_ref"],
                actor="restored-reader",
                domain_authorized=lambda *_: True,
            )
            == clone["artifact_bytes"]
        )
        events = restored.state.project_database.list_events(limit=200)
        assert any(row["event_type"] == "task.create" for row in events)
        activation = next(row for row in events if row["event_type"] == "project.replica.activated")
        assert activation["event_seq"] > preview["through_event_seq"]
        assert activation["actor_ref"] == "user_control"
        with contextlib.closing(sqlite3.connect(root / ".tsunagou/local/state.sqlite3")) as conn:
            assert not conn.execute("SELECT 1 FROM jobs WHERE status='running'").fetchall()
            assert clone["worker"]["secret_token"] not in str(conn.execute("SELECT payload_json FROM module_state").fetchall())
    finally:
        restored.state.project_database.release_process_lock()


def test_restore_cli_and_unconfirmed_clone_cannot_start(clone: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    root = clone["root"]
    monkeypatch.setenv("TSUNAGOU_PROJECT_ROOT", str(root))
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(root / ".tsunagou/local"))
    with pytest.raises(RuntimeError, match="checkpoint_restore_required"):
        build_application()
    runner = CliRunner()
    args = ["project", "restore", "--coordination-root", str(root), "--checkpoint-digest", clone["checkpoint"]["checkpoint_digest"]]
    preview = runner.invoke(cli, args)
    assert preview.exit_code == 0, preview.output
    value = json.loads(preview.output)
    confirmed = runner.invoke(cli, [*args, "--confirm-plan-digest", value["plan_digest"]])
    assert confirmed.exit_code == 0, confirmed.output
    assert json.loads(confirmed.output)["status"] == "restored"


def test_clone_rejects_local_credentials_and_unanchored_content(clone: dict[str, Any]) -> None:
    root = clone["root"]
    recovery = CloneRecovery(root)
    digest = clone["checkpoint"]["checkpoint_digest"]
    private = root / ".tsunagou/local"
    private.mkdir()
    ticket = private / "ticket.json"
    ticket.write_text('{"secret":"copied-old-ticket"}', encoding="utf-8")
    with pytest.raises(ValueError, match="clean_local_state"):
        recovery.preview(digest)
    ticket.unlink()
    # A matching worktree alone is insufficient after all local anchor refs
    # are removed; remote tracking refs and reflogs cannot authorize recovery.
    refs = subprocess.check_output(
        ["git", "for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags"], cwd=root, text=True
    ).splitlines()
    for ref in refs:
        subprocess.run(["git", "update-ref", "-d", ref], cwd=root, check=True)
    preview = recovery.preview(digest)
    assert not preview["can_confirm"]
    with pytest.raises(ValueError, match="verified_supported"):
        recovery.confirm(digest, preview["plan_digest"])
