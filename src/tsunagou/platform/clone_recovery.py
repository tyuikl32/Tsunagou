"""Offline user-control preview/confirm for a clean clone of shared history."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from tsunagou.application.workflows.lifecycle import LifecycleService
from tsunagou.modules.artifacts import ArtifactService
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.coordination import CoordinationService
from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.projects import ProjectRegistry, physical_identity
from tsunagou.modules.resources import ResourceService
from tsunagou.modules.tasks import TaskService
from tsunagou.modules.workspaces import WorkspaceService
from tsunagou.platform.checkpoints import CheckpointStore, GitAnchorScanner
from tsunagou.platform.db.sqlite import ProjectDatabase, ProjectLock, UnitOfWork
from tsunagou.platform.shared_checkpoint import export_shared
from tsunagou.platform.state import ServiceStateRuntime
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import format_timestamp, now_ms


class CloneRecovery:
    """Never overwrites an initialized local DB, credentials, or bindings."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve(strict=True)
        self.shared = self.root / ".tsunagou"
        self.local = self.shared / "local"
        if not self.shared.is_dir() or self.shared.is_symlink() or self.local.is_symlink():
            raise ValueError("recovery_project_path_invalid")
        self.store = CheckpointStore(self.shared / "checkpoints")

    def _domains(self, manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        directory = self.store._directory(manifest["digest"])
        result = {}
        for entry in manifest["files"]:
            name = entry["path"].removesuffix(".ndjson")
            result[name] = [json.loads(line) for line in (directory / entry["path"]).read_text(encoding="utf-8").splitlines()]
            if any(not isinstance(item, dict) for item in result[name]):
                raise ValueError("checkpoint_record_invalid")
        return result

    def _assert_clean(self) -> None:
        if self.local.is_dir() and any(self.local.iterdir()):
            raise ValueError("restore_requires_clean_local_state")
        if (self.shared / "bridges").exists():
            raise ValueError("restore_requires_clean_bridge_state")

    def preview(self, digest: str) -> dict[str, Any]:
        self._assert_clean()
        manifest = self.store.load(digest)
        domains = self._domains(manifest)
        projects = domains.get("project", [])
        if len(projects) != 1:
            raise ValueError("checkpoint_project_required")
        project = projects[0]
        local_project = json.loads((self.shared / "project.json").read_text(encoding="utf-8"))
        if project.get("project_id") != local_project.get("project_id"):
            raise ValueError("checkpoint_project_mismatch")
        if project.get("current_lineage_id") != manifest["lineage_id"]:
            raise ValueError("checkpoint_lineage_mismatch")
        if manifest.get("project_id") not in {None, project["project_id"]}:
            raise ValueError("checkpoint_project_mismatch")
        relative = (self.store._directory(digest) / "manifest.json").relative_to(self.root).as_posix()
        anchors = GitAnchorScanner().scan(self.root, {digest}, {digest: relative})
        verified = [{"ref_name": anchor.ref_name, "commit_oid": anchor.commit_oid}
                    for anchor in anchors if anchor.checkpoint_digest == digest]
        tasks = domains.get("tasks", [{}])[0].get("tasks", {})
        plan = {
            "project_id": project["project_id"], "lineage_id": manifest["lineage_id"],
            "checkpoint_digest": digest, "manifest_digest": canonical_digest(manifest),
            "target_identity": physical_identity(self.root), "through_event_seq": manifest["through_event_seq"],
            "format_version": manifest["format_version"], "projection_version": manifest.get("projection_version"),
            "task_count": len(tasks),
            "requires_recovery_review": sum(item["status"] not in {"completed", "cancelled", "failed"} for item in tasks.values()),
            "local_anchors": verified, "authority": "unassigned", "root_bindings": "unbound",
            "runtime_credentials": "not_imported", "mode": "clean_clone",
        }
        return {**plan, "status": "preview", "plan_digest": canonical_digest(plan),
                "previewed_at": format_timestamp(now_ms()),
                "can_confirm": manifest["format_version"] <= self.store.format_version
                and manifest.get("projection_version") == "shared-v1" and bool(verified)}

    def confirm(self, digest: str, plan_digest: str) -> dict[str, Any]:
        # The same bootstrap lock is acquired before daemon DB creation. It is
        # outside .local, so a preview/failed confirmation leaves a clean clone.
        with ProjectLock(self.shared / "bootstrap.lock"):
            installed = self.local / "state.sqlite3"
            if installed.is_file():
                with contextlib.closing(sqlite3.connect(installed.as_uri() + "?mode=ro", uri=True)) as conn:
                    row = conn.execute("SELECT value FROM runtime_meta WHERE key='clone_restore_receipt'").fetchone()
                if row is not None:
                    receipt = json.loads(row[0])
                    if receipt["checkpoint_digest"] == digest and receipt["plan_digest"] == plan_digest:
                        return {**receipt, "replayed": True}
                raise ValueError("restore_requires_clean_local_state")
            preview = self.preview(digest)
            if preview["plan_digest"] != plan_digest:
                raise ValueError("restore_preview_changed")
            if not preview["can_confirm"]:
                raise ValueError("restore_verified_supported_checkpoint_required")
            manifest = self.store.load(digest, read_only_future=False)
            domains = self._domains(manifest)
            # Reject a private or future field smuggled into an otherwise valid
            # digest; only the owner export DTO is an importable state shape.
            candidate = {key: values[0] for key, values in domains.items()
                         if key not in {"project", "audit_events", "entity_times", "operation_history"} and len(values) == 1}
            candidate["projects"] = {"project": domains["project"][0]}
            projected = export_shared(candidate)
            actual = {key: values for key, values in domains.items()
                      if key not in {"audit_events", "entity_times", "operation_history"}}
            if projected != actual:
                raise ValueError("checkpoint_shared_dto_mismatch")
            return self._install(domains, manifest, plan_digest)

    def _install(self, domains: dict[str, list[dict[str, Any]]], manifest: dict[str, Any], plan_digest: str) -> dict[str, Any]:
        project_id = domains["project"][0]["project_id"]
        self.local.mkdir(exist_ok=True)
        # Build and verify in an isolated directory. Only the complete DB is
        # published; old source checkpoints and Git remain untouched.
        with tempfile.TemporaryDirectory(prefix="restore-", dir=self.shared) as temporary:
            database = ProjectDatabase(Path(temporary) / "state.sqlite3", project_id=project_id)
            registry = ProjectRegistry(self.root)
            registry.managed_by_database = True
            authority = AuthorityService(None)
            state = ServiceStateRuntime(
                database=database, project_registry=registry, authority=authority,
                tasks=TaskService(), cognition=CognitionService(), messages=MessageStore(None),
                resources=ResourceService(), workspaces=WorkspaceService(), coordination=CoordinationService(),
                lifecycle=LifecycleService(registry=registry, authority=authority),
                artifacts=ArtifactService(self.local / "artifacts"),
            )
            imported_before = state.import_shared(domains)
            command_id = new_id()
            with database.transaction(command_id) as uow:
                uow.conn.execute("UPDATE runtime_meta SET value=? WHERE key=?",
                                 (manifest["lineage_id"], f"lineage:{project_id}"))
                uow.conn.execute("INSERT INTO runtime_meta(key,value) VALUES(?,?)",
                                 (f"event_seq_floor:{project_id}", str(manifest["through_event_seq"])))
                self._import_history(uow, domains, manifest)
                state.persist(uow, actor_ref="user_control", command_kind="project.replica.activate",
                              before=imported_before,
                              command_payload={"reason": "confirmed_clone_restore"},
                              result={"project_id": project_id, "checkpoint_digest": manifest["digest"]})
                uow.append_event(
                    lineage_id=manifest["lineage_id"], event_type="project.replica.activated",
                    aggregate_ref=f"project/{project_id}", actor_ref="user_control",
                    evidence_refs=[manifest["digest"]], reason_code="confirmed_clone_restore",
                    payload={"source_checkpoint_digest": manifest["digest"], "through_event_seq": manifest["through_event_seq"]},
                )
                receipt = {"status": "restored", "project_id": project_id, "lineage_id": manifest["lineage_id"],
                           "checkpoint_digest": manifest["digest"], "plan_digest": plan_digest,
                           "restored_at": format_timestamp(now_ms()), "authority": "unassigned",
                           "next": "start_daemon_then_enroll_appoint_bind_and_review_tasks"}
                uow.conn.execute("INSERT INTO runtime_meta(key,value) VALUES('clone_restore_receipt',?)",
                                 (json.dumps(receipt),))
            with contextlib.closing(database._connect()) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("restore_integrity_failed")
                if conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
                    raise ValueError("restore_wal_busy")
            # Atomic install is the recovery commit point. Following projection
            # writes are disposable and will be retried on daemon startup.
            os.replace(database.path, self.local / "state.sqlite3")
            try:
                registry.materialize_projection()
            except OSError:
                receipt["projection_status"] = "pending_reconcile"
            return receipt

    @staticmethod
    def _import_history(uow: UnitOfWork, domains: dict[str, list[dict[str, Any]]], manifest: dict[str, Any]) -> None:
        columns = (
            "project_id event_seq event_id lineage_id event_type schema_version aggregate_ref actor_ref command_id "
            "occurred_at recorded_at subject_ref outcome reason_code caused_by_command_id revision_before revision_after "
            "evidence_refs_json projection_version payload_json digest"
        ).split()
        for source in domains.get("audit_events", []):
            row = dict(source)
            if row.get("project_id") != uow.project_id or not 0 < int(row["event_seq"]) <= int(manifest["through_event_seq"]):
                raise ValueError("checkpoint_event_identity_invalid")
            payload = {"changes": row.pop("changes", []), "source_checkpoint_digest": manifest["digest"]}
            row["payload_json"] = json.dumps(payload)
            row["evidence_refs_json"] = json.dumps(row.pop("evidence_refs", []))
            row["digest"] = canonical_digest(payload)
            row.setdefault("schema_version", "1.0")
            row.setdefault("projection_version", "shared-v1")
            row.setdefault("aggregate_ref", row.get("subject_ref"))
            row.setdefault("command_id", row.get("caused_by_command_id") or "legacy_unknown")
            row.setdefault("outcome", "committed")
            uow.conn.execute(f"INSERT INTO events({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                             [row.get(key) for key in columns])
        for row in domains.get("entity_times", []):
            if row.get("project_id") != uow.project_id:
                raise ValueError("checkpoint_entity_identity_invalid")
            keys = "project_id lineage_id subject_ref created_at updated_at revision last_event_seq".split()
            uow.conn.execute(f"INSERT INTO entity_audit_metadata({','.join(keys)}) VALUES(?,?,?,?,?,?,?)",
                             [row.get(key) for key in keys])
        uow.conn.execute(
            "CREATE TABLE checkpoint_import_history(source_digest TEXT NOT NULL,kind TEXT NOT NULL,payload_json TEXT NOT NULL)",
        )
        for row in domains.get("operation_history", []):
            uow.conn.execute("INSERT INTO checkpoint_import_history VALUES(?,?,?)",
                             (manifest["digest"], "operation", json.dumps(row)))
