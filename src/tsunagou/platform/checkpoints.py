"""Deterministic shared checkpoints, local Git anchors, and recovery helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.digests import canonical_bytes, canonical_digest
from tsunagou.shared_kernel.time import now_ms

_SENSITIVE_KEYS = {
    "token", "secret", "credential", "credential_hash", "ticket", "grant", "lease",
    "job_claim", "absolute_path", "private_message", "user_ceiling_secret",
    "runtime_epoch", "connection_epoch", "session_id", "conversation_id",
    "host_id", "bridge_config", "reconnect_nonce_hash",
}


def _filter_shared(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _filter_shared(item) for key, item in value.items()
            if key.casefold() not in _SENSITIVE_KEYS
            and not any(marker in key.casefold() for marker in ("token", "secret", "credential"))
        }
    if isinstance(value, list):
        return [_filter_shared(item) for item in value]
    return value


def _fsync_tree(directory: Path) -> None:
    for path in directory.rglob("*"):
        if path.is_file():
            with path.open("r+b") as handle:
                os.fsync(handle.fileno())
    _fsync_directory(directory)


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return  # Windows does not expose directory fsync through os.open.
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _record_order(record: dict[str, Any]) -> tuple[int, int | str]:
    if type(record.get("event_seq")) is int:
        return 0, record["event_seq"]
    identity = record.get("id", record.get("subject_ref"))
    if isinstance(identity, str):
        return 1, identity
    return 2, canonical_digest(record)


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
    artifact_files: tuple[dict[str, Any], ...] = ()
    created_at: int | None = None
    created_by: str | None = None
    reason: str | None = None
    projection_version: str = "shared-v1"
    verified_at: int | None = None
    status: str = "sealed"
    project_id: str | None = None
    metadata_integrity: int | None = None
    request_digest: str | None = None


@dataclass(frozen=True, slots=True)
class GitAnchor:
    repository: str
    ref_name: str
    commit_oid: str
    checkpoint_digest: str | None
    status: str


class CheckpointStore:
    def __init__(
        self, root: str | Path, *, format_version: int = 1, write_git_metadata: bool = True,
    ) -> None:
        self.root = Path(root)
        self.format_version = format_version
        self.staging = self.root / "staging"
        # ``root`` is already the project checkpoint directory (the bootstrap
        # passes ``.tsunagou/checkpoints``). Keeping a second ``checkpoints``
        # component unnecessarily lengthens every Git path and breaks normal
        # Windows clones once promoted artifact bytes are included.
        self.checkpoints = self.root
        self.pointer = self.root / "current.json"
        self._publish_lock = threading.RLock()
        if write_git_metadata:
            self.root.mkdir(parents=True, exist_ok=True)
            # These files travel with a clone. Immutable NDJSON/manifest and
            # promoted blob bytes must not depend on global core.autocrlf.
            self._write_managed_file(
                ".gitattributes", b"* -text\n**/* -text\n",
            )
            self._write_managed_file(".gitignore", b"/staging/\n/.current.*\n")
        elif not self.root.is_dir():
            raise FileNotFoundError("checkpoint_store_missing")

    def _write_managed_file(self, filename: str, content: bytes) -> None:
        destination = self.root / filename
        if destination.is_file() and not destination.is_symlink() and destination.read_bytes() == content:
            return
        fd, name = tempfile.mkstemp(prefix=f".{filename}.", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, destination)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def materialize(
        self, *, lineage_id: str, through_event_seq: int,
        schema_bundle_digest: str, domains: dict[str, list[dict[str, Any]]],
        parent_digest: str | None = None, artifact_digests: list[str] | None = None,
        created_by: str | None = None, reason: str | None = None,
        created_at: int | None = None, project_id: str | None = None,
        artifact_contents: dict[str, bytes] | None = None,
    ) -> CheckpointManifest:
        with self._publish_lock:
            return self._materialize(
                lineage_id=lineage_id, through_event_seq=through_event_seq, schema_bundle_digest=schema_bundle_digest,
                domains=domains, parent_digest=parent_digest, artifact_digests=artifact_digests,
                created_by=created_by, reason=reason, created_at=created_at, project_id=project_id,
                artifact_contents=artifact_contents,
            )

    def _materialize(
        self, *, lineage_id: str, through_event_seq: int,
        schema_bundle_digest: str, domains: dict[str, list[dict[str, Any]]],
        parent_digest: str | None = None, artifact_digests: list[str] | None = None,
        created_by: str | None = None, reason: str | None = None,
        created_at: int | None = None,
        project_id: str | None = None,
        artifact_contents: dict[str, bytes] | None = None,
    ) -> CheckpointManifest:
        # The process smoke harness can place a one-shot marker outside the
        # application state.  Consuming it before staging proves that the
        # completion handler preserves the user decision when materialization
        # fails; this path is inert unless the test-only environment variable
        # explicitly names an existing marker.
        failure_marker = os.environ.get("TSUNAGOU_TEST_FAIL_CHECKPOINT_MARKER")
        if failure_marker:
            marker = Path(failure_marker)
            if marker.is_file():
                marker.unlink()
                raise OSError("checkpoint_materialization_test_failure")
        self.staging.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix="checkpoint-", dir=self.staging))
        files: list[dict[str, Any]] = []
        artifact_files: list[dict[str, Any]] = []
        try:
            for domain, records in sorted(domains.items()):
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", domain):
                    raise ValueError("checkpoint_domain_invalid")
                path = staging_dir / f"{domain}.ndjson"
                ordered = sorted((_filter_shared(record) for record in records), key=_record_order)
                data = b"".join(canonical_bytes(record) + b"\n" for record in ordered)
                path.write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                files.append({"path": path.name, "size": len(data), "digest": f"sha256:{digest}"})
            files_tuple = tuple(files)
            digests = tuple(sorted(artifact_digests or []))
            supplied_artifacts = artifact_contents or {}
            if set(supplied_artifacts) != set(digests):
                raise ValueError("checkpoint_artifact_inputs_mismatch")
            for artifact_digest in digests:
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest):
                    raise ValueError("checkpoint_artifact_digest_invalid")
                content = supplied_artifacts[artifact_digest]
                if not isinstance(content, bytes) or canonical_file_digest(content) != artifact_digest:
                    raise ValueError("checkpoint_artifact_digest_mismatch")
                relative_path = f"artifacts/sha256/{artifact_digest[7:]}"
                path = staging_dir / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                artifact_files.append({"path": relative_path, "size": len(content), "digest": artifact_digest})
            artifact_files_tuple = tuple(artifact_files)
            body = {
                "parent_digest": parent_digest, "lineage_id": lineage_id,
                "through_event_seq": through_event_seq, "format_version": self.format_version,
                "schema_bundle_digest": schema_bundle_digest, "files": files_tuple,
                "artifact_digests": digests, "artifact_files": artifact_files_tuple,
                "projection_version": "shared-v1",
                "created_at": created_at, "created_by": created_by, "reason": reason,
                "project_id": project_id, "status": "sealed", "metadata_integrity": 1,
            }
            request_digest = canonical_digest(body)
            # Verification time is authenticated too. Reuse the already
            # verified immutable receipt for the exact request, rather than
            # generating a new timestamp/digest each time a job is retried.
            with self._publish_lock:
                for candidate in self.checkpoints.glob("sha256_*/manifest.json"):
                    try:
                        existing = json.loads(candidate.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    if not isinstance(existing, dict):
                        continue
                    if existing.get("request_digest") == request_digest:
                        existing = self.load(existing["digest"], read_only_future=False)
                        self._advance_pointer(existing)
                        return self._manifest(existing)
            verified_at = now_ms()
            body.update({"request_digest": request_digest, "verified_at": verified_at})
            digest = canonical_digest(body)
            destination = self._directory(digest)
            manifest = CheckpointManifest(
                digest, parent_digest, lineage_id, through_event_seq, self.format_version,
                schema_bundle_digest, files_tuple, digests, artifact_files_tuple,
                created_at, created_by, reason,
                "shared-v1", verified_at, "sealed", project_id, 1, request_digest,
            )
            (staging_dir / "manifest.json").write_bytes(canonical_bytes({**body, "digest": digest}) + b"\n")
            _fsync_tree(staging_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Publish the complete directory in one rename. A crash must never
            # expose a destination that contains only some of its files.
            with self._publish_lock:
                if destination.exists():
                    # New checkpoints use a compact directory key for Windows
                    # path-length headroom. A prefix collision must never
                    # overwrite an already sealed checkpoint.
                    self.verify(digest)
                    shutil.rmtree(staging_dir)
                    return self._manifest(self.load(digest, read_only_future=False))
                os.replace(staging_dir, destination)
                _fsync_directory(destination.parent)
                self.verify(digest)
                self._advance_pointer(self.load(digest))
            return manifest
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

    @staticmethod
    def _manifest(raw: dict[str, Any]) -> CheckpointManifest:
        return CheckpointManifest(
            **{**raw, "files": tuple(raw["files"]), "artifact_digests": tuple(raw.get("artifact_digests", [])),
               "artifact_files": tuple(raw.get("artifact_files", []))},
        )

    def _advance_pointer(self, manifest: dict[str, Any]) -> None:
        if self.pointer.is_file():
            try:
                current = self.load(json.loads(self.pointer.read_text(encoding="utf-8"))["digest"])
            except (OSError, ValueError, KeyError, TypeError):
                current = None
            if current and int(current["through_event_seq"]) > int(manifest["through_event_seq"]):
                return
        self._atomic_pointer({"digest": manifest["digest"], "status": "sealed",
                              "through_event_seq": manifest["through_event_seq"]})

    def load(self, digest: str, *, read_only_future: bool = True) -> dict[str, Any]:
        directory = self._directory(digest)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest["format_version"] > self.format_version and not read_only_future:
            raise ValueError("future_checkpoint_format")
        self.verify(digest)
        if manifest.get("metadata_integrity") != 1:
            # Legacy content hashes did not authenticate provenance. Preserve
            # their data, but do not turn editable actor/time fields into facts.
            manifest.update(created_at=None, created_by=None, reason=None, verified_at=None, project_id=None)
        return {str(key): value for key, value in manifest.items()}

    def _verified_file_bytes(self, directory: Path, entry: dict[str, Any]) -> bytes:
        relative = entry["path"]
        if not isinstance(relative, str) or relative.startswith("/") or "\\" in relative:
            raise ValueError("checkpoint_file_path_invalid")
        parts = relative.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("checkpoint_file_path_invalid")
        path = directory
        for part in parts:
            path = path / part
            if path.is_symlink() or path.is_junction():
                raise ValueError("checkpoint_file_path_invalid")
        if not path.is_file() or not path.resolve(strict=True).is_relative_to(directory.resolve(strict=True)):
            raise ValueError("checkpoint_file_path_invalid")
        data = path.read_bytes()
        if len(data) != entry["size"] or canonical_file_digest(data) != entry["digest"]:
            raise ValueError("checkpoint_file_digest_mismatch")
        return data

    @staticmethod
    def _manifest_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
        return [*manifest["files"], *manifest.get("artifact_files", [])]

    def verify(self, digest: str) -> None:
        directory = self._directory(digest)
        if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
            raise ValueError("checkpoint_directory_invalid")
        manifest_path = directory / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("checkpoint_file_path_invalid")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.verify_manifest(manifest, digest)
        for entry in self._manifest_entries(manifest):
            self._verified_file_bytes(directory, entry)

    @staticmethod
    def verify_manifest(manifest: dict[str, Any], expected_digest: str) -> None:
        required = {"digest", "parent_digest", "lineage_id", "through_event_seq", "format_version",
                    "schema_bundle_digest", "files", "artifact_digests"}
        optional = {"projection_version", "created_at", "created_by", "reason", "verified_at", "status",
                    "project_id", "metadata_integrity", "request_digest", "artifact_files"}
        if not isinstance(manifest, dict) or not required.issubset(manifest) or set(manifest) - required - optional:
            raise ValueError("checkpoint_manifest_invalid")
        if manifest.get("digest") != expected_digest:
            raise ValueError("checkpoint_manifest_digest_mismatch")
        if not isinstance(expected_digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_digest):
            raise ValueError("checkpoint_digest_invalid")
        if any(not isinstance(manifest[key], str) or not manifest[key] for key in ("lineage_id", "schema_bundle_digest")):
            raise ValueError("checkpoint_manifest_invalid")
        parent = manifest["parent_digest"]
        if parent is not None and (not isinstance(parent, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", parent)):
            raise ValueError("checkpoint_manifest_invalid")
        artifacts = manifest["artifact_digests"]
        if not isinstance(artifacts, list | tuple) or any(
            not isinstance(item, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", item) for item in artifacts
        ) or len(set(artifacts)) != len(artifacts) or list(artifacts) != sorted(artifacts):
            raise ValueError("checkpoint_manifest_invalid")
        for field in ("through_event_seq", "format_version"):
            if type(manifest[field]) is not int or manifest[field] < (1 if field == "format_version" else 0):
                raise ValueError("checkpoint_manifest_invalid")
        if not isinstance(manifest["files"], list | tuple) or any(
            not isinstance(entry, dict) or set(entry) != {"path", "size", "digest"}
            or not isinstance(entry["path"], str) or type(entry["size"]) is not int or entry["size"] < 0
            or not isinstance(entry["digest"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", entry["digest"])
            for entry in manifest["files"]
        ):
            raise ValueError("checkpoint_manifest_invalid")
        paths = [entry["path"] for entry in manifest["files"]]
        if len(paths) != len(set(paths)) or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}\.ndjson", p) for p in paths):
            raise ValueError("checkpoint_file_path_invalid")
        if "artifact_files" in manifest:
            artifact_files = manifest["artifact_files"]
            if not isinstance(artifact_files, list | tuple) or any(
                not isinstance(entry, dict) or set(entry) != {"path", "size", "digest"}
                or type(entry["size"]) is not int or entry["size"] < 0
                or not isinstance(entry["digest"], str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", entry["digest"])
                or entry["path"] != f"artifacts/sha256/{entry['digest'][7:]}"
                for entry in artifact_files
            ):
                raise ValueError("checkpoint_artifact_path_invalid")
            artifact_paths = [entry["path"] for entry in artifact_files]
            artifact_file_digests = [entry["digest"] for entry in artifact_files]
            if (len(artifact_paths) != len(set(artifact_paths)) or artifact_file_digests != sorted(artifact_file_digests)
                    or artifact_file_digests != list(artifacts)):
                raise ValueError("checkpoint_artifact_manifest_mismatch")
        elif artifacts:
            # Hash-only references are not enough to prove the saved project
            # contains the promoted artifact bytes.
            raise ValueError("checkpoint_artifact_files_missing")
        body = {key: manifest[key] for key in (
            "parent_digest", "lineage_id", "through_event_seq", "format_version",
            "schema_bundle_digest", "files", "artifact_digests",
        )}
        if "artifact_files" in manifest:
            body["artifact_files"] = manifest["artifact_files"]
        if "projection_version" in manifest:
            body["projection_version"] = manifest["projection_version"]
        if manifest.get("metadata_integrity") is not None:
            metadata_fields = optional - {"artifact_files"}
            if manifest["metadata_integrity"] != 1 or not metadata_fields.issubset(manifest):
                raise ValueError("checkpoint_metadata_integrity_invalid")
            if manifest["status"] != "sealed" or manifest["projection_version"] != "shared-v1":
                raise ValueError("checkpoint_metadata_integrity_invalid")
            if any(manifest[field] is not None and not isinstance(manifest[field], str)
                   for field in ("project_id", "created_by", "reason")):
                raise ValueError("checkpoint_manifest_invalid")
            for field in ("created_at", "verified_at"):
                if manifest[field] is not None and (type(manifest[field]) is not int or manifest[field] < 0):
                    raise ValueError("checkpoint_manifest_invalid")
            body.update({key: manifest[key] for key in (
                "created_at", "created_by", "reason", "project_id", "status", "metadata_integrity",
            )})
            if canonical_digest(body) != manifest["request_digest"]:
                raise ValueError("checkpoint_manifest_digest_mismatch")
            body.update(request_digest=manifest["request_digest"], verified_at=manifest["verified_at"])
        if canonical_digest(body) != manifest["digest"]:
            raise ValueError("checkpoint_manifest_digest_mismatch")

    def recover_staging(self) -> list[str]:
        recovered: list[str] = []
        for directory in self.staging.glob("*"):
            if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
                continue
            manifest_path = directory / "manifest.json"
            if manifest_path.is_symlink() or not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                digest = manifest["digest"]
                self.verify_manifest(manifest, digest)
                for entry in self._manifest_entries(manifest):
                    self._verified_file_bytes(directory, entry)
                destination = self._directory(digest)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with self._publish_lock:
                    if not destination.exists():
                        os.replace(directory, destination)
                    else:
                        self.verify(digest)
                        shutil.rmtree(directory)
                    self.verify(digest)
                recovered.append(digest)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return recovered

    def _directory(self, digest: str) -> Path:
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("checkpoint_digest_invalid")
        compact = self.checkpoints / f"sha256_{digest[7:39]}"
        legacy = self.checkpoints / digest.replace(":", "_")
        # Read pre-PT4 full-key directories without rewriting them. New
        # materialization always targets the compact key to keep clone paths
        # usable on default Windows Git installations.
        return legacy if legacy.exists() and not compact.exists() else compact

    def _atomic_pointer(self, value: dict[str, Any]) -> None:
        fd, name = tempfile.mkstemp(prefix=".current.", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(canonical_bytes(value) + b"\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.pointer)
            _fsync_directory(self.root)
        finally:
            if os.path.exists(name):
                os.unlink(name)


class GitAnchorScanner:
    """Verify checkpoint bytes reachable from local heads/tags, never remote refs."""

    @staticmethod
    def _git(repository: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", "--no-optional-locks", "--literal-pathspecs", *args], cwd=repository,
            check=check, capture_output=True, timeout=15,
        )

    def _regular_blob(self, repository: Path, commit: str, path: str) -> bytes:
        entry = self._git(repository, ["ls-tree", "-z", "--full-tree", commit, "--", path]).stdout
        records = [record for record in entry.split(b"\0") if record]
        if len(records) != 1:
            raise ValueError("checkpoint_tree_path_missing")
        metadata, actual_path = records[0].split(b"\t", 1)
        mode, kind, oid = metadata.split(b" ")
        if mode not in {b"100644", b"100755"} or kind != b"blob" or actual_path.decode("utf-8") != path:
            raise ValueError("checkpoint_tree_path_invalid")
        return self._git(repository, ["cat-file", "blob", oid.decode("ascii")]).stdout

    def scan(
        self, repository: str | Path, checkpoint_digests: set[str],
        checkpoint_paths: dict[str, str] | None = None,
    ) -> list[GitAnchor]:
        root = Path(repository)
        try:
            refs = self._git(root, ["for-each-ref", "refs/heads", "refs/tags", "--format=%(refname) %(objectname)"])
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            # A project can use checkpoints before it has a Git repository.
            # The checkpoint remains verifiable; it simply has no Git anchor.
            return []
        anchors: list[GitAnchor] = []
        for line in refs.stdout.decode("utf-8").splitlines():
            ref_name, object_oid = line.split(" ", 1)
            if not ref_name.startswith(("refs/heads/", "refs/tags/")):
                continue
            check = self._git(root, ["rev-parse", "--verify", f"{object_oid}^{{commit}}"], check=False)
            if check.returncode != 0:
                continue
            tip = check.stdout.decode("ascii").strip()
            commits = self._git(root, ["rev-list", tip]).stdout.decode("ascii").splitlines()
            found = False
            for digest in sorted(checkpoint_digests):
                path = (checkpoint_paths or {}).get(digest)
                if (not path or path.startswith("/") or "\\" in path or ":" in path
                        or any(part in {"", ".", ".."} for part in path.split("/"))):
                    continue
                for commit_oid in commits:
                    try:
                        candidate = json.loads(self._regular_blob(root, commit_oid, path).decode("utf-8"))
                        CheckpointStore.verify_manifest(candidate, digest)
                        prefix = path.rpartition("/")[0]
                        for entry in candidate["files"]:
                            blob_path = f"{prefix}/{entry['path']}" if prefix else entry["path"]
                            content = self._regular_blob(root, commit_oid, blob_path)
                            if len(content) != entry["size"] or canonical_file_digest(content) != entry["digest"]:
                                raise ValueError("checkpoint_tree_mismatch")
                        for entry in candidate.get("artifact_files", []):
                            blob_path = f"{prefix}/{entry['path']}" if prefix else entry["path"]
                            content = self._regular_blob(root, commit_oid, blob_path)
                            if len(content) != entry["size"] or canonical_file_digest(content) != entry["digest"]:
                                raise ValueError("checkpoint_tree_mismatch")
                    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                        continue
                    anchors.append(GitAnchor(str(repository), ref_name, commit_oid, digest, "local_verified"))
                    found = True
                    break
            if not found:
                anchors.append(GitAnchor(str(repository), ref_name, tip, None, "unverified"))
        return anchors


def canonical_file_digest(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


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
    with closing(sqlite3.connect(source)) as source_conn, closing(sqlite3.connect(destination)) as backup_conn:
        source_conn.backup(backup_conn)
        check = backup_conn.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise ValueError("backup_integrity_failed")
    return destination
