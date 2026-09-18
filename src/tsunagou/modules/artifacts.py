"""Streaming local content-addressed artifacts and domain-owned references."""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tsunagou.shared_kernel.ids import new_id


@dataclass(slots=True)
class UploadIntent:
    intent_id: str
    domain_ref: str
    actor: str
    size_limit: int
    expected_digest: str | None
    recipient_agent_id: str | None
    temp_path: Path
    received_bytes: int = 0
    status: str = "pending"
    expires_at: float = 0.0


@dataclass(slots=True)
class ArtifactBlob:
    digest: str
    size_bytes: int
    media_type: str
    local_relative_path: str
    storage_state: str = "local"
    verified_at: float | None = None


@dataclass(slots=True)
class ArtifactRef:
    artifact_ref: str
    digest: str
    domain_ref: str
    owner_actor: str
    recipient_agent_id: str | None
    storage_scope: str = "local"


class ArtifactService:
    def __init__(self, storage_dir: str | Path, *, default_size_limit: int = 16 * 1024 * 1024) -> None:
        self.storage_dir = Path(storage_dir)
        self.temp_dir = self.storage_dir / "tmp"
        self.blob_dir = self.storage_dir / "blobs" / "sha256"
        self.default_size_limit = default_size_limit
        self.uploads: dict[str, UploadIntent] = {}
        self.blobs: dict[str, ArtifactBlob] = {}
        self.refs: dict[str, ArtifactRef] = {}

    def begin_upload(
        self, *, domain_ref: str, actor: str, size_limit: int | None = None,
        expected_digest: str | None = None, recipient_agent_id: str | None = None,
        ttl_seconds: int = 3600,
    ) -> UploadIntent:
        limit = self.default_size_limit if size_limit is None else size_limit
        if limit <= 0:
            raise ValueError("invalid_size_limit")
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        intent = UploadIntent(
            new_id(), domain_ref, actor, limit, expected_digest, recipient_agent_id,
            self.temp_dir / f"{new_id()}.part", expires_at=time.time() + ttl_seconds,
        )
        intent.temp_path.touch()
        self.uploads[intent.intent_id] = intent
        return intent

    def write_chunk(self, intent_id: str, chunk: bytes) -> int:
        intent = self._pending(intent_id)
        if intent.received_bytes + len(chunk) > intent.size_limit:
            intent.status = "failed"
            self._remove_temp(intent)
            raise ValueError("upload_size_limit_exceeded")
        with intent.temp_path.open("ab") as handle:
            handle.write(chunk)
            handle.flush()
        intent.received_bytes += len(chunk)
        return intent.received_bytes

    def finalize(self, intent_id: str, *, media_type: str = "application/octet-stream") -> ArtifactRef:
        intent = self._pending(intent_id)
        digest = hashlib.sha256()
        try:
            with intent.temp_path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
            actual_digest = digest.hexdigest()
            if intent.expected_digest is not None and intent.expected_digest != actual_digest:
                intent.status = "failed"
                self._remove_temp(intent)
                raise ValueError("upload_digest_mismatch")
            relative = Path(actual_digest[:2]) / actual_digest[2:]
            destination = self.blob_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                self._remove_temp(intent)
            else:
                os.replace(intent.temp_path, destination)
            self.blobs.setdefault(
                actual_digest,
                ArtifactBlob(
                    actual_digest, intent.received_bytes, media_type,
                    str(Path("blobs") / "sha256" / relative), verified_at=time.time(),
                ),
            )
            intent.status = "finalized"
            ref = ArtifactRef(new_id(), actual_digest, intent.domain_ref, intent.actor, intent.recipient_agent_id)
            self.refs[ref.artifact_ref] = ref
            return ref
        except OSError as exc:
            intent.status = "failed"
            self._remove_temp(intent)
            raise ValueError("artifact_finalize_failed") from exc

    def read(
        self, artifact_ref: str, *, actor: str,
        domain_authorized: Callable[[str, str, str], bool],
    ) -> bytes:
        ref = self.refs.get(artifact_ref)
        if ref is None:
            raise PermissionError("artifact_access_denied")
        if ref.recipient_agent_id is not None and ref.recipient_agent_id != actor:
            raise PermissionError("artifact_recipient_only")
        if not domain_authorized(ref.domain_ref, actor, artifact_ref):
            raise PermissionError("artifact_domain_access_denied")
        blob = self.blobs.get(ref.digest)
        if blob is None:
            raise FileNotFoundError("artifact_unavailable")
        return (self.storage_dir / blob.local_relative_path).read_bytes()

    def promote(
        self, artifact_ref: str, *, actor_kind: str, actor_id: str,
        project_shared_allowed: Callable[[str, str], bool],
    ) -> ArtifactRef:
        if actor_kind not in {"main", "user_control"}:
            raise PermissionError("promotion_user_or_main_only")
        ref = self.refs.get(artifact_ref)
        if ref is None or not project_shared_allowed(ref.domain_ref, artifact_ref):
            raise PermissionError("artifact_promotion_denied")
        ref.storage_scope = "project_shared"
        ref.owner_actor = actor_id
        blob = self.blobs[ref.digest]
        blob.storage_state = "promoted"
        return ref

    def cleanup_expired(self, *, now: float | None = None) -> list[str]:
        now = time.time() if now is None else now
        removed: list[str] = []
        for intent in self.uploads.values():
            if intent.status == "pending" and intent.expires_at <= now:
                intent.status = "expired"
                self._remove_temp(intent)
                removed.append(intent.intent_id)
        return removed

    def checkpoint_export(self, artifact_refs: list[str]) -> list[ArtifactRef]:
        exported: list[ArtifactRef] = []
        for artifact_ref in artifact_refs:
            ref = self.refs.get(artifact_ref)
            if ref is not None and ref.storage_scope == "project_shared":
                exported.append(ref)
        return exported

    def _pending(self, intent_id: str) -> UploadIntent:
        intent = self.uploads.get(intent_id)
        if intent is None or intent.status != "pending":
            raise ValueError("upload_intent_not_pending")
        if intent.expires_at <= time.time():
            intent.status = "expired"
            self._remove_temp(intent)
            raise ValueError("upload_intent_expired")
        return intent

    @staticmethod
    def _remove_temp(intent: UploadIntent) -> None:
        try:
            intent.temp_path.unlink()
        except FileNotFoundError:
            pass
