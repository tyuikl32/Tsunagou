import json
from pathlib import Path

import pytest

from tsunagou.platform.checkpoints import CheckpointStore, GitAnchorScanner, backup_sqlite, merge_lineage


def test_checkpoint_is_deterministic_filtered_and_verifiable(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / "checkpoints")
    domains = {
        "projects": [{"id": "p", "name": "demo", "absolute_path": "C:\\secret"}],
        "agents": [{"id": "a", "token": "do-not-export", "role": "worker"}],
    }
    first = store.materialize(lineage_id="l", through_event_seq=2, schema_bundle_digest="sha256:s", domains=domains)
    second = store.materialize(lineage_id="l", through_event_seq=2, schema_bundle_digest="sha256:s", domains=domains)
    assert first.digest == second.digest
    manifest = store.load(first.digest)
    assert "absolute_path" not in (store._directory(first.digest) / "projects.ndjson").read_text(encoding="utf-8")
    assert "token" not in json.dumps(manifest)
    store.verify(first.digest)
    with pytest.raises(ValueError, match="file_digest"):
        path = store._directory(first.digest) / "projects.ndjson"
        path.write_text(path.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
        store.verify(first.digest)


def test_lineage_conflict_and_backup(tmp_path: Path) -> None:
    merged, conflicts = merge_lineage(
        {"x": {"v": 1}}, {"x": {"v": 2}, "a": {"v": 1}}, {"x": {"v": 3}},
    )
    assert merged == {"a": {"v": 1}}
    assert conflicts == ["x"]
    with pytest.raises(ValueError, match="sealed"):
        merge_lineage({}, {}, {}, sealed=True)
    database = tmp_path / "state.sqlite3"
    import sqlite3
    with sqlite3.connect(database) as conn:
        conn.execute("create table t (id integer)")
        conn.execute("insert into t values (1)")
    backup = backup_sqlite(database, tmp_path / "backups")
    assert backup.exists()


def test_git_anchor_requires_manifest_content_on_local_ref(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    import subprocess
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    store = CheckpointStore(repository / "shared")
    manifest = store.materialize(lineage_id="lineage", through_event_seq=1,
                                 schema_bundle_digest="sha256:s", domains={"tasks": [{"id": "task"}]})
    digest = manifest.digest
    manifest_path = (store._directory(digest) / "manifest.json").relative_to(repository).as_posix()
    subprocess.run(["git", "-c", "core.autocrlf=false", "add", "shared"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "checkpoint"], cwd=repository, check=True)
    anchors = GitAnchorScanner().scan(
        repository, {digest}, {digest: manifest_path},
    )
    assert anchors and anchors[0].checkpoint_digest == digest
    # A digest that merely happens to be a substring of the commit id is never
    # accepted without readable manifest content.
    assert GitAnchorScanner().scan(repository, {"sha256:" + anchors[0].commit_oid[:8]})[0].checkpoint_digest is None
    subprocess.run(["git", "tag", "-a", "checkpoint", "-m", "verified"], cwd=repository, check=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/hidden", "HEAD"], cwd=repository, check=True)
    anchors = GitAnchorScanner().scan(repository, {digest}, {digest: manifest_path})
    assert {a.ref_name for a in anchors} == {"refs/heads/master", "refs/tags/checkpoint"}
    assert all(a.checkpoint_digest == digest for a in anchors)
    assert len({a.commit_oid for a in anchors}) == 1
    # Matching manifest text is insufficient when its referenced tree differs.
    (store._directory(digest) / "tasks.ndjson").write_text("tampered\n", encoding="utf-8")
    subprocess.run(["git", "-c", "core.autocrlf=false", "add", "shared"], cwd=repository, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "corrupt"], cwd=repository, check=True)
    anchors = GitAnchorScanner().scan(repository, {digest}, {digest: manifest_path})
    branch = next(a for a in anchors if a.ref_name.startswith("refs/heads/"))
    # A corrupt tip does not erase an earlier valid copy still reachable from
    # the branch. The anchor must name the verified ancestor, not the bad tip.
    assert branch.checkpoint_digest == digest
    corrupt_tip = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repository, text=True).strip()
    assert branch.commit_oid != corrupt_tip
    assert next(a for a in anchors if a.ref_name.startswith("refs/tags/")).checkpoint_digest == digest
