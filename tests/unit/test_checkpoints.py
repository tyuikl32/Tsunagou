import json
from pathlib import Path

import pytest

from tsunagou.platform.checkpoints import CheckpointStore, backup_sqlite, merge_lineage


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
