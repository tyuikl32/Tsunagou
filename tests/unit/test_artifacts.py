from pathlib import Path

import pytest

from tsunagou.modules.artifacts import ArtifactService


def test_stream_finalize_hash_access_and_explicit_promotion(tmp_path: Path) -> None:
    service = ArtifactService(tmp_path / "artifacts", default_size_limit=10)
    intent = service.begin_upload(domain_ref="task/1", actor="worker", recipient_agent_id="worker")
    service.write_chunk(intent.intent_id, b"hello")
    ref = service.finalize(intent.intent_id, media_type="text/plain")
    with pytest.raises(PermissionError, match="recipient"):
        service.read(ref.artifact_ref, actor="main", domain_authorized=lambda *_: True)
    assert service.read(ref.artifact_ref, actor="worker", domain_authorized=lambda domain, actor, ref_id: domain == "task/1") == b"hello"
    with pytest.raises(PermissionError, match="promotion"):
        service.promote(ref.artifact_ref, actor_kind="worker", actor_id="worker", project_shared_allowed=lambda *_: True)
    service.promote(ref.artifact_ref, actor_kind="main", actor_id="main", project_shared_allowed=lambda *_: True)
    assert [item.artifact_ref for item in service.checkpoint_export([ref.artifact_ref])] == [ref.artifact_ref]


def test_truncation_tamper_digest_mismatch_and_no_auto_gc(tmp_path: Path) -> None:
    service = ArtifactService(tmp_path / "artifacts", default_size_limit=4)
    intent = service.begin_upload(domain_ref="task/1", actor="worker")
    with pytest.raises(ValueError, match="size"):
        service.write_chunk(intent.intent_id, b"12345")
    mismatch = service.begin_upload(domain_ref="task/2", actor="worker", expected_digest="0" * 64)
    service.write_chunk(mismatch.intent_id, b"data")
    with pytest.raises(ValueError, match="digest"):
        service.finalize(mismatch.intent_id)
    good = service.begin_upload(domain_ref="task/3", actor="worker")
    service.write_chunk(good.intent_id, b"data")
    ref = service.finalize(good.intent_id)
    blob_path = service.storage_dir / service.blobs[ref.digest].local_relative_path
    assert blob_path.exists()
    assert service.cleanup_expired(now=10**12) == []
    assert blob_path.exists()


def test_unknown_hash_is_not_a_read_capability(tmp_path: Path) -> None:
    service = ArtifactService(tmp_path / "artifacts")
    intent = service.begin_upload(domain_ref="task/1", actor="worker")
    service.write_chunk(intent.intent_id, b"x")
    ref = service.finalize(intent.intent_id)
    with pytest.raises(PermissionError):
        service.read(ref.digest, actor="worker", domain_authorized=lambda *_: True)
