"""Deterministic shared checkpoints, local Git anchors, and recovery helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.digests import canonical_bytes, canonical_digest
from tsunagou.shared_kernel.ids import new_id

_SENSITIVE_KEYS = {
    "token", "secret", "credential", "credential_hash", "ticket", "grant", "lease",
    "job_claim", "absolute_path", "private_message", "user_ceiling_secret",
}


def _filter_shared(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _filter_shared(item) for key, item in value.items()
            if key.casefold() not in _SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_filter_shared(item) for item in value]
    return value


def _fsync_tree(directory: Path) -> None:
    for path in directory.rglob("*"):
        if path.is_file():
            with path.open("r+b") as handle:
                os.fsync(handle.fileno())


@dataclass(frozen=True, slots=True)
class CheckpointManifest:
    digest: str
    parent_digest: str | None
    lineage_id: str
    through_event_seq: int
    format_version: int
    schema_bundle_digest: str
    files: tuple[dict[str, Any], ...]
    artifact_digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GitAnchor:
    repository: str
    ref_name: str
    commit_oid: str
    checkpoint_digest: str | None
    status: str


class CheckpointStore:
    def __init__(self, root: str | Path, *, format_version: int = 1) -> None:
        self.root = Path(root)
        self.format_version = format_version
        self.staging = self.root / "staging"
        self.checkpoints = self.root / "checkpoints"
        self.pointer = self.root / "current.json"
        self.root.mkdir(parents=True, exist_ok=True)

    def materialize(
        self, *, lineage_id: str, through_event_seq: int,
        schema_bundle_digest: str, domains: dict[str, list[dict[str, Any]]],
        parent_digest: str | None = None, artifact_digests: list[str] | None = None,
    ) -> CheckpointManifest:
        checkpoint_id = new_id()
        staging_dir = self.staging / checkpoint_id
        staging_dir.mkdir(parents=True, exist_ok=False)
        files: list[dict[str, Any]] = []
        try:
            for domain, records in sorted(domains.items()):
                path = staging_dir / f"{domain}.ndjson"
                ordered = sorted((_filter_shared(record) for record in records), key=lambda item: canonical_digest(item))
                data = b"".join(canonical_bytes(record) + b"\n" for record in ordered)
                path.write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                files.append({"path": path.name, "size": len(data), "digest": f"sha256:{digest}"})
            files_tuple = tuple(files)
            body = {
                "parent_digest": parent_digest, "lineage_id": lineage_id,
                "through_event_seq": through_event_seq, "format_version": self.format_version,
                "schema_bundle_digest": schema_bundle_digest, "files": files_tuple,
                "artifact_digests": tuple(sorted(artifact_digests or [])),
            }
            digest = canonical_digest(body)
            manifest = CheckpointManifest(
                digest, parent_digest, lineage_id, through_event_seq, self.format_version,
                schema_bundle_digest, files_tuple, tuple(sorted(artifact_digests or [])),
            )
            (staging_dir / "manifest.json").write_bytes(canonical_bytes({**body, "digest": digest}) + b"\n")
            _fsync_tree(staging_dir)
            destination = self._directory(digest)
            if destination.exists():
                shutil.rmtree(staging_dir)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.mkdir()
                for child in staging_dir.iterdir():
                    os.replace(child, destination / child.name)
                staging_dir.rmdir()
            self._atomic_pointer({"digest": digest, "status": "sealed", "through_event_seq": through_event_seq})
            return manifest
        except BaseException:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            raise

    def load(self, digest: str, *, read_only_future: bool = True) -> dict[str, Any]:
        directory = self._directory(digest)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["format_version"] > self.format_version and not read_only_future:
            raise ValueError("future_checkpoint_format")
        self.verify(digest)
        return {str(key): value for key, value in manifest.items()}

    def verify(self, digest: str) -> None:
        directory = self._directory(digest)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            data = (directory / entry["path"]).read_bytes()
            if len(data) != entry["size"] or f"sha256:{hashlib.sha256(data).hexdigest()}" != entry["digest"]:
                raise ValueError("checkpoint_file_digest_mismatch")
        body = {key: manifest[key] for key in (
            "parent_digest", "lineage_id", "through_event_seq", "format_version",
            "schema_bundle_digest", "files", "artifact_digests",
        )}
        if canonical_digest(body) != manifest["digest"]:
            raise ValueError("checkpoint_manifest_digest_mismatch")

    def recover_staging(self) -> list[str]:
        recovered: list[str] = []
        for directory in self.staging.glob("*"):
            manifest_path = directory / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                digest = manifest["digest"]
                destination = self._directory(digest)
                if not destination.exists():
                    os.replace(directory, destination)
                else:
                    shutil.rmtree(directory)
                self.verify(digest)
                recovered.append(digest)
            except (OSError, ValueError, KeyError):
                continue
        return recovered

    def _directory(self, digest: str) -> Path:
        return self.checkpoints / digest.replace(":", "_")

    def _atomic_pointer(self, value: dict[str, Any]) -> None:
        fd, name = tempfile.mkstemp(prefix=".current.", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(canonical_bytes(value) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.pointer)
        finally:
            if os.path.exists(name):
                os.unlink(name)


class GitAnchorScanner:
    """Read-only refs scanner; remote refs, reflogs, and unreachable objects are excluded."""

    def scan(self, repository: str | Path, checkpoint_digests: set[str]) -> list[GitAnchor]:
        result = subprocess.run(
            ["git", "for-each-ref", "refs/heads", "refs/tags", "--format=%(refname) %(objectname)"],
            cwd=Path(repository), check=True, capture_output=True, text=True, timeout=15,
        )
        anchors: list[GitAnchor] = []
        for line in result.stdout.splitlines():
            ref_name, commit_oid = line.split(" ", 1)
            check = subprocess.run(
                ["git", "cat-file", "-e", f"{commit_oid}^{{commit}}"],
                cwd=Path(repository), check=False, capture_output=True, timeout=15,
            )
            if check.returncode != 0:
                continue
            checkpoint = next((digest for digest in checkpoint_digests if digest in commit_oid), None)
            anchors.append(GitAnchor(str(repository), ref_name, commit_oid, checkpoint, "local_verified"))
        return anchors


def merge_lineage(
    base: dict[str, dict[str, Any]], left: dict[str, dict[str, Any]],
    right: dict[str, dict[str, Any]], *, sealed: bool = False,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if sealed:
        raise ValueError("sealed_lineage_cannot_merge")
    merged: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []
    for key in sorted(set(base) | set(left) | set(right)):
        base_value, left_value, right_value = base.get(key), left.get(key), right.get(key)
        if left_value == right_value:
            if left_value is not None:
                merged[key] = left_value
        elif left_value == base_value:
            if right_value is not None:
                merged[key] = right_value
        elif right_value == base_value:
            if left_value is not None:
                merged[key] = left_value
        else:
            conflicts.append(key)
    return merged, conflicts


def backup_sqlite(database: str | Path, backup_dir: str | Path) -> Path:
    source = Path(database)
    destination = Path(backup_dir) / f"{source.name}.backup"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_conn, sqlite3.connect(destination) as backup_conn:
        source_conn.backup(backup_conn)
        check = backup_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise ValueError("backup_integrity_failed")
    return destination
