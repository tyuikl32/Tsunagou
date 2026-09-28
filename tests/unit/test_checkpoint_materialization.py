"""PT4 materialization acceptance against real SQLite, files, and Git trees."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from tsunagou.modules.artifacts import ArtifactService
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.platform.checkpoint_worker import CheckpointWorker
from tsunagou.platform.checkpoints import CheckpointStore, GitAnchorScanner
from tsunagou.platform.clone_recovery import CloneRecovery
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.platform.maintenance import RuntimeMaintenance
from tsunagou.platform.shared_checkpoint import public_document
from tsunagou.shared_kernel.digests import canonical_bytes, canonical_digest
from tsunagou.shared_kernel.errors import RevisionConflict


class State:
    lineage_id = "lineage"
    project_registry = None

    def __init__(self) -> None:
        self.snapshot = {
            "projects": {"project": {"project_id": "local-project", "name": "before", "runtime_epoch": "EPOCH-SENTINEL"}},
            "tasks": {"tasks": {"task": {"task_id": "task", "title": "before", "runtime_extra": "UNKNOWN-SENTINEL"}}},
            "authority": {"agents": {"a": {"agent_id": "a", "installation_digest": "installation",
                                          "conversation_digest": "CONVERSATION-SENTINEL"}},
                          "sessions": {"session": {"secret_token": "TOKEN-SENTINEL"}}},
            "messages": {"messages": {"message": {"body": "PRIVATE-INBOX-SENTINEL"}}},
            "resources": {"lease_sets": {"lease": {"lease_owner": "LEASE-SENTINEL"}}},
            "workspaces": {"baselines": {"baseline": {"manifest_id": "baseline", "root_identities": ["C:\\PRIVATE-PATH"]}}},
        }

    def capture(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.snapshot))


@pytest.fixture
def runtime(tmp_path: Path):
    database = ProjectDatabase(tmp_path / "state.sqlite3")
    store = CheckpointStore(tmp_path / "shared")
    state = State()
    worker = CheckpointWorker(database, store, state, "sha256:" + "a" * 64)
    yield database, store, state, worker
    database.release_process_lock()


def stage(database, worker, *, reason="milestone") -> str:
    with database.transaction("stage") as uow:
        operation = uow.create_operation(kind="checkpoint.create", requested_by="main", payload={"reason": reason})
        worker.stage(uow, operation_id=operation, created_by="main", reason=reason)
    return operation


def operation(database, identity: str) -> dict:
    with closing(database._connect()) as connection:
        return dict(connection.execute("SELECT * FROM operations WHERE id=?", (identity,)).fetchone())


def add_promoted_artifact(state: State, storage_dir: Path) -> tuple[ArtifactService, str]:
    service = ArtifactService(storage_dir)
    intent = service.begin_upload(domain_ref="task/task", actor="main")
    content = b"promoted project artifact"
    service.write_chunk(intent.intent_id, content)
    ref = service.finalize(intent.intent_id, media_type="application/octet-stream")
    service.promote(ref.artifact_ref, actor_kind="main", actor_id="main",
                    project_shared_allowed=lambda *_: True)
    ref.project_id = "local-project"
    ref.lineage_id = "lineage"
    state.artifacts = service
    state.snapshot["artifacts"] = {
        "refs": {ref.artifact_ref: asdict(ref)},
        "blobs": {ref.digest: asdict(service.blobs[ref.digest])},
    }
    return service, ref.digest


def test_rollback_has_no_effect_and_postcommit_reuses_frozen_input(runtime, monkeypatch) -> None:
    database, store, state, worker = runtime
    with pytest.raises(RuntimeError):
        with database.transaction("rollback") as uow:
            identity = uow.create_operation(kind="checkpoint.create", requested_by="main", payload={})
            worker.stage(uow, operation_id=identity, created_by="main", reason="rolled-back")
            raise RuntimeError("rollback")
    assert worker.run_once() == 0 and not store.pointer.exists()
    identity = stage(database, worker)
    state.snapshot["tasks"]["tasks"]["task"]["title"] = "after"
    original = store.materialize

    def verify_postcommit(**arguments):
        # A second writer can start: no SQLite write transaction spans file IO.
        with closing(database._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        return original(**arguments)

    monkeypatch.setattr(store, "materialize", verify_postcommit)
    assert worker.run_once(identity) == 1
    result = json.loads(operation(database, identity)["result_json"])
    manifest = store.load(result["checkpoint_digest"])
    text = "\n".join(path.read_text(encoding="utf-8") for path in store._directory(manifest["digest"]).glob("*.ndjson"))
    assert '"title":"before"' in text and '"title":"after"' not in text
    assert "SENTINEL" not in text and "PRIVATE-PATH" not in text
    assert manifest["project_id"] == database.project_id and manifest["created_by"] == "main"
    assert manifest["created_at"] is not None and manifest["verified_at"] is not None
    assert worker.run_once(identity) == 0


@pytest.mark.parametrize("window", ["before_rename", "before_pointer"])
def test_file_failure_then_retry_keeps_one_immutable_receipt(runtime, monkeypatch, window: str) -> None:
    database, store, _, worker = runtime
    identity = stage(database, worker)
    replace = os.replace
    atomic_pointer = store._atomic_pointer
    if window == "before_rename":
        def fail_rename(source, destination):
            if Path(source).is_dir():
                raise OSError("fixture before directory publish")
            return replace(source, destination)
        monkeypatch.setattr(os, "replace", fail_rename)
    else:
        monkeypatch.setattr(store, "_atomic_pointer", lambda value: (_ for _ in ()).throw(OSError("fixture pointer failure")))
    worker.run_once(identity)
    assert operation(database, identity)["status"] == "failed"
    published = list(store.checkpoints.glob("sha256_*/manifest.json"))
    existing_bytes = published[0].read_bytes() if published else None
    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(store, "_atomic_pointer", atomic_pointer)
    with database.transaction("retry") as uow:
        worker.retry(uow, actor="main", operation_id=identity)
    restarted = CheckpointWorker(database, CheckpointStore(store.root), State(), worker.schema_digest)
    assert restarted.run_once(identity) == 1
    assert operation(database, identity)["status"] == "succeeded"
    receipts = list(store.checkpoints.glob("sha256_*/manifest.json"))
    assert len(receipts) == 1
    if existing_bytes:
        assert receipts[0].read_bytes() == existing_bytes
    with closing(database._connect()) as connection:
        assert [row[0] for row in connection.execute("SELECT outcome FROM job_attempts ORDER BY attempt_no")] == ["failed", "succeeded"]
        assert connection.execute("SELECT status FROM outbox").fetchone()[0] == "done"


def test_crash_after_pointer_before_receipt_recovers_without_duplicate(runtime, monkeypatch) -> None:
    database, store, _, worker = runtime
    identity = stage(database, worker)
    finish = database.finish_job
    monkeypatch.setattr(database, "finish_job", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit("crash")))
    with pytest.raises(SystemExit):
        worker.run_once(identity)
    first_pointer = store.pointer.read_bytes()
    assert operation(database, identity)["status"] == "running"
    with database.transaction("expire") as uow:
        job = dict(uow.conn.execute("SELECT * FROM jobs WHERE operation_id=?", (identity,)).fetchone())
        uow.conn.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (job["id"],))
    monkeypatch.setattr(database, "finish_job", finish)
    assert CheckpointWorker(database, store, State(), worker.schema_digest).run_once(identity) == 1
    assert store.pointer.read_bytes() == first_pointer
    assert len(list(store.checkpoints.glob("sha256_*"))) == 1
    with pytest.raises(RevisionConflict):
        database.finish_job(job["id"], worker_id=job["lease_owner"], lease_epoch=job["lease_epoch"], outcome="succeeded")


def test_corrupt_job_input_is_never_materialized(runtime) -> None:
    database, store, _, worker = runtime
    identity = stage(database, worker)
    with database.transaction("tamper") as uow:
        row = uow.conn.execute("SELECT id,payload_json FROM jobs WHERE operation_id=?", (identity,)).fetchone()
        payload = json.loads(row["payload_json"])
        payload["created_by"] = "forged-actor"
        uow.conn.execute("UPDATE jobs SET payload_json=? WHERE id=?", (json.dumps(payload), row["id"]))
    worker.run_once(identity)
    assert operation(database, identity)["status"] == "failed"
    assert not store.pointer.exists()


def test_promoted_artifact_is_copied_and_git_anchor_checks_its_bytes(runtime, tmp_path: Path) -> None:
    database, store, state, worker = runtime
    service, raw_digest = add_promoted_artifact(state, tmp_path / "artifact-storage")
    identity = stage(database, worker)
    assert worker.run_once(identity) == 1
    manifest = store.load(json.loads(operation(database, identity)["result_json"])["checkpoint_digest"])
    checkpoint_dir = store._directory(manifest["digest"])
    artifact_entry = manifest["artifact_files"][0]
    assert artifact_entry == {
        "path": f"artifacts/sha256/{raw_digest}", "size": len(b"promoted project artifact"),
        "digest": f"sha256:{raw_digest}",
    }
    assert (checkpoint_dir / artifact_entry["path"]).read_bytes() == b"promoted project artifact"

    subprocess.run(["git", "init", "--quiet", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "config", "user.name", "PT4 test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "pt4@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "core.longpaths=true", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "promoted checkpoint"], cwd=tmp_path, check=True)
    manifest_path = (checkpoint_dir / "manifest.json").relative_to(tmp_path).as_posix()
    anchors = GitAnchorScanner().scan(tmp_path, {manifest["digest"]}, {manifest["digest"]: manifest_path})
    assert len(anchors) == 1 and anchors[0].checkpoint_digest == manifest["digest"]

    (checkpoint_dir / artifact_entry["path"]).write_bytes(b"corrupted archived artifact")
    with pytest.raises(ValueError, match="checkpoint_file_digest_mismatch"):
        store.verify(manifest["digest"])


def test_corrupted_promoted_artifact_fails_after_commit_without_checkpoint(runtime, tmp_path: Path) -> None:
    database, store, state, worker = runtime
    service, raw_digest = add_promoted_artifact(state, tmp_path / "artifact-storage")
    identity = stage(database, worker)
    source = service.storage_dir / service.blobs[raw_digest].local_relative_path
    source.write_bytes(b"tampered after commit")
    assert worker.run_once(identity) == 1
    assert operation(database, identity)["status"] == "failed"
    assert not store.pointer.exists()
    assert list(store.checkpoints.glob("sha256_*/manifest.json")) == []


def test_public_checkpoint_text_redacts_embedded_paths_and_bearer_sentinels() -> None:
    public = public_document({
        "reason": (
            r"Windows C:\Users\alice\private.txt; UNC \\server\share\secret.db; "
            "POSIX /home/alice/private.db; bearer top-secret-token; retry after failure"
        ),
        "normal_prose": "keep HTTPS https://example.invalid/api/v1 available",
    })
    text = public["reason"]
    assert r"C:\Users" not in text and r"server\share" not in text and "/home/alice" not in text
    assert "top-secret-token" not in text and "[REDACTED]" in text
    assert "retry after failure" in text
    assert public["normal_prose"] == "keep HTTPS https://example.invalid/api/v1 available"


def test_clone_preview_is_byte_for_byte_read_only_for_legacy_store(tmp_path: Path) -> None:
    root = tmp_path / "legacy-clone"
    shared = root / ".tsunagou"
    shared.mkdir(parents=True)
    (shared / "project.json").write_text(json.dumps({"project_id": "local-project"}), encoding="utf-8")
    store = CheckpointStore(shared / "checkpoints")
    manifest = store.materialize(
        lineage_id="lineage", through_event_seq=1, schema_bundle_digest="schema",
        domains={"project": [{"project_id": "local-project", "current_lineage_id": "lineage"}]},
        project_id="local-project",
    )
    # Simulate an existing clone created before checkpoint Git metadata was managed.
    (store.root / ".gitattributes").unlink()
    (store.root / ".gitignore").unlink()
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(root)], check=True)
    subprocess.run(["git", "config", "user.name", "PT4 test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "pt4@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "legacy shared history"], cwd=root, check=True)
    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    preview = CloneRecovery(root).preview(manifest.digest)

    after = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert preview["status"] == "preview"
    assert before == after


def test_parent_is_frozen_from_completed_operation_and_metadata_is_hashed(runtime) -> None:
    database, store, _, worker = runtime
    first = stage(database, worker)
    worker.run_once(first)
    previous = json.loads(operation(database, first)["result_json"])["checkpoint_digest"]
    second = stage(database, worker)
    worker.run_once(second)
    current = store.load(json.loads(operation(database, second)["result_json"])["checkpoint_digest"])
    assert current["parent_digest"] == previous
    for field, changed in (("created_by", "forged"), ("created_at", 1), ("verified_at", 1), ("project_id", "foreign")):
        altered = {**current, field: changed}
        with pytest.raises(ValueError, match="digest"):
            store.verify_manifest(altered, current["digest"])


def test_staging_recovery_checks_content_and_repairs_damaged_pointer(runtime) -> None:
    database, store, _, worker = runtime
    identity = stage(database, worker)
    worker.run_once(identity)
    digest = json.loads(operation(database, identity)["result_json"])["checkpoint_digest"]
    original = store._directory(digest)
    staged = store.staging / "interrupted"
    os.replace(original, staged)
    store.pointer.write_text("broken-json", encoding="utf-8")
    assert store.recover_staging() == [digest]
    manifest = store.load(digest)
    store._advance_pointer(manifest)
    assert json.loads(store.pointer.read_text(encoding="utf-8"))["digest"] == digest
    corrupt = store.staging / "corrupt"
    shutil.copytree(original, corrupt)
    next(corrupt.glob("*.ndjson")).write_text("bad", encoding="utf-8")
    assert store.recover_staging() == []
    assert corrupt.exists()


def test_checkpoint_bytes_survive_clone_with_autocrlf_true(tmp_path: Path) -> None:
    source = tmp_path / "source"
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(source)], check=True)
    store = CheckpointStore(source / "shared")
    manifest = store.materialize(lineage_id="lineage", through_event_seq=1, schema_bundle_digest="schema",
                                 domains={"tasks": [{"id": "task", "title": "line one\nline two"}]})
    subprocess.run(["git", "-c", "core.autocrlf=true", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "snapshot"], cwd=source, check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "-c", "core.autocrlf=true", "clone", "--quiet", str(source), str(clone)], check=True)
    CheckpointStore(clone / "shared").verify(manifest.digest)


def test_projection_failure_does_not_block_independent_maintenance(runtime) -> None:
    database, _, state, _ = runtime

    class BrokenProjection:
        def run_once(self):
            return 0

        def reconcile_project_projection(self):
            raise OSError("disk full")

    maintenance = RuntimeMaintenance(database=database, state_runtime=state, tasks=TaskService(),
        resources=ResourceService(), authority=AuthorityService(None), checkpoint_worker=BrokenProjection())
    assert maintenance.run_once() == 0
    assert maintenance.last_projection_error == "project_projection_materialization_failed"


def test_manifest_shape_and_legacy_provenance_are_explicit(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    body = {"parent_digest": None, "lineage_id": "lineage", "through_event_seq": 1,
            "format_version": 1, "schema_bundle_digest": "schema", "files": [], "artifact_digests": []}
    digest = canonical_digest(body)
    directory = store._directory(digest)
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_bytes(canonical_bytes({**body, "digest": digest,
        "created_by": "unprotected-actor", "created_at": 1, "verified_at": 2}))
    legacy = store.load(digest)
    assert legacy["created_by"] is legacy["created_at"] is legacy["verified_at"] is None
    with pytest.raises(ValueError, match="invalid"):
        store.verify_manifest({**body, "digest": digest, "files": [{"path": "../escape", "size": 0}]}, digest)


@pytest.mark.parametrize("window", ["before_rename", "after_rename"])
def test_actual_process_exit_recovers_fsynced_staging_or_published_directory(tmp_path: Path, window: str) -> None:
    script = """
import os, sys
from pathlib import Path
from tsunagou.platform.checkpoints import CheckpointStore
store = CheckpointStore(sys.argv[1])
original = os.replace
if sys.argv[2] == 'before_rename':
    def replace(source, destination):
        if Path(source).is_dir():
            os._exit(91)
        return original(source, destination)
    os.replace = replace
else:
    store._atomic_pointer = lambda value: os._exit(91)
store.materialize(lineage_id='lineage', through_event_seq=1, schema_bundle_digest='schema', domains={'tasks':[{'id':'task'}]})
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), window], check=False, capture_output=True)
    assert result.returncode == 91, result.stderr.decode()
    store = CheckpointStore(tmp_path)
    assert not store.pointer.exists()
    recovered = store.recover_staging()
    assert len(recovered) == (1 if window == "before_rename" else 0)
    manifest = store.materialize(lineage_id="lineage", through_event_seq=1, schema_bundle_digest="schema",
                                 domains={"tasks": [{"id": "task"}]})
    store.verify(manifest.digest)
    assert len(list(store.checkpoints.glob("sha256_*"))) == 1
    assert json.loads(store.pointer.read_text(encoding="utf-8"))["digest"] == manifest.digest


def test_remote_ref_and_reflog_are_not_anchors_and_tree_symlinks_are_rejected(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(tmp_path)], check=True)
    store = CheckpointStore(tmp_path / "shared")
    manifest = store.materialize(lineage_id="lineage", through_event_seq=1, schema_bundle_digest="schema", domains={})
    manifest_file = store._directory(manifest.digest) / "manifest.json"
    relative = manifest_file.relative_to(tmp_path).as_posix()
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "valid"], cwd=tmp_path, check=True)
    oid = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/saved", oid], cwd=tmp_path, check=True)
    subprocess.run(["git", "update-ref", "-d", "refs/heads/main"], cwd=tmp_path, check=True)
    scanner = GitAnchorScanner()
    assert scanner.scan(tmp_path, {manifest.digest}, {manifest.digest: relative}) == []
    blob = subprocess.check_output(["git", "hash-object", "-w", "--stdin"], cwd=tmp_path, input=manifest_file.read_bytes()).decode().strip()
    subprocess.run(["git", "update-index", "--cacheinfo", f"120000,{blob},{relative}"], cwd=tmp_path, check=True)
    tree = subprocess.check_output(["git", "write-tree"], cwd=tmp_path, text=True).strip()
    # A parentless commit prevents the valid old tree from qualifying as an
    # ancestor; only the deliberately wrong symlink-mode entry is reachable.
    bad_commit = subprocess.check_output(["git", "commit-tree", tree, "-m", "bad mode"], cwd=tmp_path, text=True).strip()
    subprocess.run(["git", "update-ref", "refs/heads/main", bad_commit], cwd=tmp_path, check=True)
    result = scanner.scan(tmp_path, {manifest.digest}, {manifest.digest: relative})
    assert len(result) == 1 and result[0].checkpoint_digest is None
