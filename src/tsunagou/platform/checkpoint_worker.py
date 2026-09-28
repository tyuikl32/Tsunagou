"""Commit immutable checkpoint inputs, then materialize them outside SQLite."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

from tsunagou.platform.checkpoints import CheckpointStore
from tsunagou.platform.db.sqlite import ProjectDatabase, UnitOfWork
from tsunagou.platform.shared_checkpoint import export_shared
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.time import now_ms


class CheckpointWorker:
    def __init__(self, database: ProjectDatabase, store: CheckpointStore, state_runtime: Any, schema_digest: str) -> None:
        self.database, self.store, self.state_runtime = database, store, state_runtime
        self.schema_digest = schema_digest
        self._run_lock = threading.Lock()

    def stage(
        self, uow: UnitOfWork, *, operation_id: str, created_by: str, reason: str,
    ) -> None:
        """Called after domain persistence, in the same command transaction."""
        domains = export_shared(self.state_runtime.capture())
        artifact_inputs, artifact_digests = self._artifact_inputs(domains)
        row = uow.conn.execute(
            "SELECT MAX(event_seq) FROM events WHERE project_id=?", (self.database.project_id,),
        ).fetchone()
        through = int(row[0] or 0)
        domains.update(self._public_history(uow, through))
        previous = uow.conn.execute(
            "SELECT result_json FROM operations WHERE project_id=? AND kind='checkpoint.create' "
            "AND status='succeeded' AND result_json IS NOT NULL ORDER BY created_at DESC,id DESC LIMIT 1",
            (self.database.project_id,),
        ).fetchone()
        parent = json.loads(previous[0]).get("checkpoint_digest") if previous else None
        # Freeze the exact milestone. A retry cannot silently snapshot newer
        # business state and pretend it is the originally confirmed milestone.
        payload = {
            "lineage_id": self.state_runtime.lineage_id, "through_event_seq": through,
            "schema_bundle_digest": self.schema_digest, "domains": domains,
            "created_by": created_by, "created_at": uow.recorded_at, "reason": reason,
            "project_id": self.database.project_id, "parent_digest": parent,
            "artifact_inputs": artifact_inputs, "artifact_digests": artifact_digests,
        }
        uow.enqueue_job(operation_id=operation_id, handler_kind="checkpoint.materialize", payload=payload)
        uow.stage_outbox(kind="checkpoint.materialize", target_ref=operation_id, payload=payload)

    def _public_history(self, uow: UnitOfWork, through: int) -> dict[str, list[dict[str, Any]]]:
        from tsunagou.platform.shared_checkpoint import public_document

        def shared_subject(value: Any) -> bool:
            return isinstance(value, str) and value.split("/", 1)[0].split(":", 1)[0] in {
                "project", "task", "attempt", "result", "review", "scope_request", "progress", "root", "repository",
                "report", "claim", "discrepancy", "contract", "acceptance", "risk_request", "risk_submission",
                "risk_acceptance", "workspace", "baseline", "workspace_result", "isolation_decision", "git_request",
                "decision", "operation", "agent", "artifact",
            }

        events = []
        for row in uow.conn.execute(
            "SELECT * FROM events WHERE project_id=? AND event_seq<=? ORDER BY event_seq",
            (self.database.project_id, through),
        ):
            event = dict(row)
            action = event["event_type"].removeprefix("command.")
            if action.startswith(("message.", "inbox.", "session.", "agent.ticket.", "agent.enroll", "resource.", "job.")):
                continue
            if not shared_subject(event.get("subject_ref") or event["aggregate_ref"]):
                continue
            payload = json.loads(event["payload_json"])
            changes = payload.get("changes", []) if isinstance(payload, dict) else []
            if any(not shared_subject(change.get("subject_ref")) for change in changes):
                continue
            exported = {key: event[key] for key in (
                "event_seq", "event_id", "project_id", "lineage_id", "event_type", "schema_version", "aggregate_ref",
                "actor_ref", "command_id", "occurred_at", "recorded_at", "subject_ref", "outcome", "reason_code",
                "caused_by_command_id", "revision_before", "revision_after", "projection_version",
            )}
            exported["evidence_refs"] = [ref for ref in json.loads(event["evidence_refs_json"] or "[]")
                                          if shared_subject(ref) or isinstance(ref, str) and ref.startswith("sha256:")]
            # State values can contain private free-form payloads. Keep only
            # the public audit change envelope, not arbitrary historical data.
            exported["changes"] = [
                {key: change[key] for key in ("subject_ref", "revision_before", "revision_after", "created_at", "updated_at")
                 if key in change} for change in changes
            ]
            events.append(public_document(exported))
        times = [public_document(dict(row)) for row in uow.conn.execute(
            "SELECT project_id,lineage_id,subject_ref,created_at,updated_at,revision,last_event_seq "
            "FROM entity_audit_metadata WHERE project_id=? ORDER BY lineage_id,subject_ref", (self.database.project_id,),
        ) if shared_subject(row["subject_ref"])]
        operations = []
        for row in uow.conn.execute(
            "SELECT id,kind,requested_by,input_digest,status,created_at,updated_at,revision,error_code "
            "FROM operations WHERE project_id=? ORDER BY id", (self.database.project_id,),
        ):
            record = dict(row)
            record["resolutions"] = [public_document(dict(resolution)) for resolution in uow.conn.execute(
                "SELECT actor,conclusion,reason,followup_operation_id,digest,created_at FROM resolutions WHERE operation_id=? ORDER BY id",
                (row["id"],),
            )]
            operations.append(public_document(record))
        return {"audit_events": events, "entity_times": times, "operation_history": operations}

    @staticmethod
    def _artifact_inputs(domains: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[str]]:
        records = domains.get("artifacts", [])
        if not records:
            return [], []
        if len(records) != 1:
            raise ValueError("checkpoint_artifact_domain_invalid")
        record = records[0]
        refs = record.get("refs", {})
        blobs = record.get("blobs", {})
        if not isinstance(refs, dict) or not isinstance(blobs, dict):
            raise ValueError("checkpoint_artifact_domain_invalid")
        by_digest: dict[str, dict[str, Any]] = {}
        for ref in refs.values():
            digest_value = ref.get("digest") if isinstance(ref, dict) else None
            if not isinstance(digest_value, str) or not re.fullmatch(r"[0-9a-f]{64}", digest_value):
                raise ValueError("checkpoint_artifact_digest_invalid")
            blob = blobs.get(digest_value)
            if not isinstance(blob, dict) or blob.get("digest") != digest_value:
                raise ValueError("checkpoint_artifact_blob_missing")
            size = blob.get("size_bytes")
            media_type = blob.get("media_type")
            local_path = blob.get("local_relative_path")
            if type(size) is not int or size < 0 or not isinstance(media_type, str) or not isinstance(local_path, str):
                raise ValueError("checkpoint_artifact_metadata_invalid")
            digest = f"sha256:{digest_value}"
            item = {"digest": digest, "size_bytes": size, "media_type": media_type,
                    "local_relative_path": local_path}
            prior = by_digest.setdefault(digest, item)
            if prior != item:
                raise ValueError("checkpoint_artifact_metadata_conflict")
        digests = sorted(by_digest)
        return [by_digest[digest] for digest in digests], digests

    def _read_artifact_inputs(self, inputs: object) -> dict[str, bytes]:
        if not isinstance(inputs, list):
            raise ValueError("checkpoint_artifact_inputs_invalid")
        if not inputs:
            return {}
        artifacts = getattr(self.state_runtime, "artifacts", None)
        if artifacts is None:
            raise ValueError("checkpoint_artifact_storage_unavailable")
        root = Path(artifacts.storage_dir).resolve(strict=True)
        contents: dict[str, bytes] = {}
        for item in inputs:
            if not isinstance(item, dict):
                raise ValueError("checkpoint_artifact_input_invalid")
            digest = item.get("digest")
            size = item.get("size_bytes")
            relative = item.get("local_relative_path")
            if (not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                    or type(size) is not int or size < 0 or not isinstance(relative, str)):
                raise ValueError("checkpoint_artifact_input_invalid")
            hex_digest = digest[7:]
            canonical_relative = f"blobs/sha256/{hex_digest[:2]}/{hex_digest[2:]}"
            if relative.replace("\\", "/") != canonical_relative:
                raise ValueError("checkpoint_artifact_path_invalid")
            path = root
            for part in canonical_relative.split("/"):
                path = path / part
                if path.is_symlink() or path.is_junction():
                    raise ValueError("checkpoint_artifact_path_invalid")
            if not path.is_file() or not path.resolve(strict=True).is_relative_to(root):
                raise ValueError("checkpoint_artifact_path_invalid")
            content = path.read_bytes()
            if len(content) != size or f"sha256:{hashlib.sha256(content).hexdigest()}" != digest:
                raise ValueError("checkpoint_artifact_digest_mismatch")
            contents[digest] = content
        if len(contents) != len(inputs):
            raise ValueError("checkpoint_artifact_inputs_duplicate")
        return contents

    def request_genesis(self) -> None:
        with self.database.transaction("checkpoint-genesis") as uow:
            exists = uow.conn.execute(
                "SELECT 1 FROM operations WHERE project_id=? AND kind='checkpoint.create' LIMIT 1",
                (self.database.project_id,),
            ).fetchone()
            if exists:
                return
            operation = uow.create_operation(kind="checkpoint.create", requested_by="runtime", payload={"reason": "genesis"})
            self.stage(uow, operation_id=operation, created_by="runtime", reason="genesis")

    def retry(self, uow: UnitOfWork, *, actor: str, operation_id: str | None = None) -> str:
        row = uow.conn.execute(
            "SELECT o.id,j.id AS job_id FROM operations o JOIN jobs j ON j.operation_id=o.id "
            "WHERE o.project_id=? AND o.kind='checkpoint.create' AND o.status IN ('failed','retry_wait') "
            "AND (? IS NULL OR o.id=?) ORDER BY o.created_at DESC LIMIT 1",
            (self.database.project_id, operation_id, operation_id),
        ).fetchone()
        if row is None:
            raise KeyError("checkpoint_operation_not_found")
        stamp = now_ms()
        uow.conn.execute(
            "UPDATE operations SET status='pending',error_code=NULL,updated_at=?,revision=revision+1 WHERE id=?",
            (stamp, row["id"]),
        )
        uow.conn.execute(
            "UPDATE jobs SET status='queued',available_at=?,lease_until=NULL,lease_owner=NULL,"
            "max_attempts=MAX(max_attempts,attempt_count+1),updated_at=? WHERE id=?", (stamp, stamp, row["job_id"]),
        )
        uow.conn.execute("UPDATE outbox SET status='pending' WHERE project_id=? AND target_ref=?",
                         (self.database.project_id, row["id"]))
        uow.record_operation_event(row["id"], "checkpoint.retry_requested", actor=actor,
                                   before="failed", after="pending", job_id=row["job_id"])
        return str(row["id"])

    def run_once(self, operation_id: str | None = None) -> int:
        if not self._run_lock.acquire(blocking=False):
            return 0
        try:
            job = self.database.claim_job("runtime/checkpoint", handler_kind="checkpoint.materialize", operation_id=operation_id)
            if job is None:
                return 0
            result = None
            error = None
            try:
                payload = json.loads(job["payload_json"])
                if canonical_digest(payload) != job["input_digest"]:
                    raise ValueError("checkpoint_input_digest_mismatch")
                self.store.recover_staging()
                inputs = payload.pop("artifact_inputs", [])
                artifact_contents = self._read_artifact_inputs(inputs)
                materialize_payload = {key: value for key, value in payload.items() if key != "artifact_digests"}
                manifest = self.store.materialize(
                    **materialize_payload, artifact_digests=payload.get("artifact_digests", []),
                    artifact_contents=artifact_contents,
                )
                result = {"checkpoint_digest": manifest.digest, "through_event_seq": manifest.through_event_seq,
                          "verified_at": manifest.verified_at, "checkpoint_status": "sealed"}
            except (OSError, ValueError, KeyError, TypeError):
                error = "checkpoint_materialization_failed"
            self.database.finish_job(
                job["job_id"], worker_id="runtime/checkpoint", lease_epoch=job["lease_epoch"],
                outcome="failed" if error else "succeeded", error_code=error, result=result,
            )
            return 1
        finally:
            self._run_lock.release()

    def decorate_result(self, result: dict[str, Any]) -> dict[str, Any]:
        operation_id = result.get("operation_id")
        if not operation_id:
            return result
        with contextlib.closing(self.database._connect()) as conn:
            row = conn.execute(
                "SELECT status,result_json,error_code FROM operations WHERE id=? AND project_id=? AND kind='checkpoint.create'",
                (operation_id, self.database.project_id),
            ).fetchone()
        if row is None:
            return result
        return {"status": row["status"], **result, **(json.loads(row["result_json"]) if row["result_json"] else {}),
                "checkpoint_status": "sealed" if row["status"] == "succeeded" else row["status"],
                **({"error_code": row["error_code"]} if row["error_code"] else {})}

    def reconcile_project_projection(self) -> None:
        registry = self.state_runtime.project_registry
        if registry is None:
            return
        # Serialize against the command writer, but never hold a SQL write
        # transaction during file I/O. Failure leaves SQLite unchanged; a later
        # maintenance tick or restart rebuilds this disposable projection.
        with self.database.lock:
            registry.materialize_projection()
