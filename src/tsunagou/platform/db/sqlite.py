from __future__ import annotations

import contextlib
import json
import os
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.platform.delivery import SecretDeliveryStore
from tsunagou.shared_kernel.digests import canonical_bytes, canonical_digest
from tsunagou.shared_kernel.errors import IdempotencyConflict, LockUnavailable, RevisionConflict
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import now_ms

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX CI
    msvcrt = None  # type: ignore[assignment]

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]


_SECRET_KEY_PARTS = ("secret", "token", "nonce", "password", "authorization", "api_key", "credential")


def _contains_secret_shape(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            any(part in str(key).casefold() for part in _SECRET_KEY_PARTS)
            or _contains_secret_shape(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_secret_shape(item) for item in value)
    return False


def _redact_result(value: dict[str, Any]) -> dict[str, Any]:
    def redact(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                str(key): "[REDACTED]"
                if any(part in str(key).casefold() for part in _SECRET_KEY_PARTS)
                else redact(child)
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [redact(child) for child in item]
        if isinstance(item, tuple):
            return [redact(child) for child in item]
        return item

    return dict(redact(value))


_SAFE_CREDENTIAL_FIELDS = frozenset({
    "agent_id", "session_id", "connection_epoch", "baseline_status", "requested_role",
    "ticket_id", "ticket_ref", "status", "target_agent_id",
})


def _safe_credential_result(value: dict[str, Any]) -> dict[str, Any]:
    """Whitelist handoff metadata; an arbitrary response is never a safe receipt."""
    return {key: item for key, item in value.items() if key in _SAFE_CREDENTIAL_FIELDS
            and (item is None or isinstance(item, (str, int, bool)))}


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS runtime_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
  project_id TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  command_kind TEXT NOT NULL,
  command_id TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  result_json TEXT NOT NULL,
  event_seq INTEGER,
  created_at INTEGER NOT NULL,
  delivery_ref TEXT,
  principal_kind TEXT,
  auth_session_id TEXT,
  auth_connection_epoch INTEGER,
  auth_proof_hash TEXT,
  PRIMARY KEY(project_id, principal_id, command_kind, command_id)
);
CREATE TABLE IF NOT EXISTS events (
  project_id TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  event_id TEXT NOT NULL UNIQUE,
  lineage_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  aggregate_ref TEXT NOT NULL,
  actor_ref TEXT NOT NULL,
  command_id TEXT NOT NULL,
  occurred_at INTEGER,
  recorded_at INTEGER,
  subject_ref TEXT NOT NULL,
  outcome TEXT NOT NULL DEFAULT 'committed',
  reason_code TEXT,
  caused_by_command_id TEXT,
  revision_before INTEGER,
  revision_after INTEGER,
  evidence_refs_json TEXT NOT NULL DEFAULT '[]',
  projection_version TEXT NOT NULL DEFAULT 'v1',
  payload_json TEXT NOT NULL,
  digest TEXT NOT NULL,
  PRIMARY KEY(project_id, event_seq)
);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  event_seq INTEGER NOT NULL,
  kind TEXT NOT NULL,
  target_ref TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','running','done','failed')),
  attempt_count INTEGER NOT NULL DEFAULT 0,
  next_attempt_at INTEGER NOT NULL,
  UNIQUE(project_id, event_seq, kind, target_ref)
);
CREATE TABLE IF NOT EXISTS operations (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  requested_by TEXT NOT NULL,
  input_digest TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('pending','running','retry_wait','succeeded','failed','cancelled','outcome_unknown')),
  result_json TEXT,
  error_code TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS resolutions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  operation_id TEXT NOT NULL REFERENCES operations(id),
  actor TEXT NOT NULL,
  conclusion TEXT NOT NULL,
  evidence_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  followup_operation_id TEXT,
  digest TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  operation_id TEXT NOT NULL REFERENCES operations(id),
  project_id TEXT NOT NULL,
  handler_kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  input_digest TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('queued','running','retry_wait','succeeded','failed','cancelled')),
  available_at INTEGER NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  timeout_seconds INTEGER NOT NULL DEFAULT 120,
  lease_owner TEXT,
  lease_epoch INTEGER NOT NULL DEFAULT 0,
  lease_until INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS job_attempts (
  job_id TEXT NOT NULL REFERENCES jobs(id),
  attempt_no INTEGER NOT NULL,
  lease_epoch INTEGER NOT NULL,
  worker_id TEXT NOT NULL,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  outcome TEXT,
  error_code TEXT,
  PRIMARY KEY(job_id, attempt_no)
);
CREATE TABLE IF NOT EXISTS runtime_fences (
  project_id TEXT PRIMARY KEY,
  runtime_epoch TEXT NOT NULL,
  connection_epoch INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS module_state (
  project_id TEXT NOT NULL,
  module TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  payload_json TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY(project_id, module)
);
CREATE TABLE IF NOT EXISTS entity_audit_metadata (
  project_id TEXT NOT NULL,
  lineage_id TEXT NOT NULL,
  subject_ref TEXT NOT NULL,
  created_at INTEGER,
  updated_at INTEGER,
  revision INTEGER,
  last_event_seq INTEGER,
  PRIMARY KEY(project_id,lineage_id,subject_ref)
);
"""


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True, slots=True)
class DispatchResult:
    command_id: str
    result: dict[str, Any]
    event_seq: int | None
    replayed: bool = False


class ProjectLock:
    def __init__(self, path: Path, timeout: float = 5.0, *, serialize_threads: bool = False) -> None:
        self.path = path
        self.timeout = timeout
        self.handle: Any = None
        self._thread_guard = threading.RLock() if serialize_threads else None
        self._depth = 0

    def __enter__(self) -> ProjectLock:
        if self._thread_guard is not None:
            if not self._thread_guard.acquire(timeout=self.timeout):
                raise LockUnavailable(str(self.path))
            if self._depth:
                self._depth += 1
                return self
        try:
            result = self._enter_file_lock()
        except BaseException:
            if self._thread_guard is not None:
                self._thread_guard.release()
            raise
        self._depth = 1
        return result

    def _enter_file_lock(self) -> ProjectLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("r+b") if self.path.exists() else self.path.open("w+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if msvcrt is not None:
                    self.handle.seek(0)
                    self.handle.write(b"0")
                    self.handle.flush()
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                elif fcntl is not None:
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.handle.close()
                    self.handle = None
                    raise LockUnavailable(str(self.path)) from None
                time.sleep(0.02)

    def __exit__(self, *_: object) -> None:
        if self._thread_guard is not None:
            self._depth -= 1
            if self._depth:
                self._thread_guard.release()
                return
        try:
            self._exit_file_lock()
        finally:
            if self._thread_guard is not None:
                self._thread_guard.release()

    def _exit_file_lock(self) -> None:
        if self.handle is None:
            return
        try:
            if msvcrt is not None:
                self.handle.seek(0)
                try:
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                except PermissionError:
                    # Windows releases a region lock when the owning handle is closed.
                    pass
            elif fcntl is not None:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class UnitOfWork:
    def __init__(self, conn: sqlite3.Connection, project_id: str, command_id: str) -> None:
        self.conn = conn
        self.project_id = project_id
        self.command_id = command_id
        self._event_seq: int | None = None
        self.recorded_at = now_ms()

    def append_event(
        self,
        *,
        lineage_id: str,
        event_type: str,
        aggregate_ref: str,
        actor_ref: str,
        payload: dict[str, Any],
        schema_version: str = "1.0",
        subject_ref: str | None = None,
        outcome: str = "committed",
        reason_code: str | None = None,
        caused_by_command_id: str | None = None,
        revision_before: int | None = None,
        revision_after: int | None = None,
        evidence_refs: list[str] | tuple[str, ...] = (),
        projection_version: str = "v1",
    ) -> int:
        current = self.conn.execute(
            "SELECT COALESCE(MAX(event_seq), 0) FROM events WHERE project_id=?",
            (self.project_id,),
        ).fetchone()[0]
        floor = self.conn.execute(
            "SELECT value FROM runtime_meta WHERE key=?", (f"event_seq_floor:{self.project_id}",),
        ).fetchone()
        current = max(int(current), int(floor[0]) if floor else 0)
        seq = int(current) + 1
        payload_json = canonical_bytes(payload).decode("utf-8")
        occurred_at = self.recorded_at
        event_id = new_id()
        self.conn.execute(
            """INSERT INTO events(project_id,event_seq,event_id,lineage_id,event_type,
               schema_version,aggregate_ref,actor_ref,command_id,occurred_at,recorded_at,
               subject_ref,outcome,reason_code,caused_by_command_id,revision_before,
               revision_after,evidence_refs_json,projection_version,payload_json,digest)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self.project_id, seq, event_id, lineage_id, event_type, schema_version,
                aggregate_ref, actor_ref, self.command_id, occurred_at, occurred_at,
                subject_ref or aggregate_ref, outcome, reason_code,
                caused_by_command_id or self.command_id, revision_before, revision_after,
                canonical_bytes(list(evidence_refs)).decode("utf-8"), projection_version,
                payload_json, canonical_digest(payload),
            ),
        )
        self._event_seq = seq
        return seq

    def stage_outbox(self, *, kind: str, target_ref: str, payload: dict[str, Any]) -> None:
        if self._event_seq is None:
            raise ValueError("append_event_required_before_outbox")
        self.conn.execute(
            """INSERT INTO outbox(project_id,event_seq,kind,target_ref,payload_digest,status,next_attempt_at)
               VALUES(?,?,?,?,?,'pending',?)""",
            (self.project_id, self._event_seq, kind, target_ref, canonical_digest(payload), _now_ms()),
        )

    def create_operation(
        self, *, kind: str, requested_by: str, payload: dict[str, Any], status: str = "pending"
    ) -> str:
        operation_id = new_id()
        now = _now_ms()
        self.conn.execute(
            """INSERT INTO operations(id,project_id,kind,requested_by,input_digest,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (operation_id, self.project_id, kind, requested_by, canonical_digest(payload), status, now, now),
        )
        self.record_operation_event(operation_id, "operation.created", actor=requested_by, before=None, after=status)
        return operation_id

    def record_operation_event(
        self, operation_id: str, event_type: str, *, actor: str,
        before: str | None, after: str, job_id: str | None = None,
        reason_code: str | None = None, evidence_refs: tuple[str, ...] = (),
    ) -> None:
        project = self.conn.execute(
            "SELECT payload_json FROM module_state WHERE project_id=? AND module='projects'", (self.project_id,),
        ).fetchone()
        lineage = json.loads(project[0]).get("project", {}).get("current_lineage_id") if project else None
        if not lineage:
            lineage = self.conn.execute(
                "SELECT value FROM runtime_meta WHERE key=?", (f"lineage:{self.project_id}",),
            ).fetchone()[0]
        self.append_event(
            lineage_id=str(lineage), event_type=event_type, aggregate_ref=f"operation/{operation_id}",
            actor_ref=actor, subject_ref=f"operation/{operation_id}", reason_code=reason_code,
            evidence_refs=evidence_refs,
            payload={"operation_id": operation_id, "job_id": job_id,
                     "state_before": before, "state_after": after},
        )

    def enqueue_job(
        self, *, operation_id: str, handler_kind: str, payload: dict[str, Any],
        timeout_seconds: int = 120, max_attempts: int = 5
    ) -> str:
        job_id = new_id()
        now = _now_ms()
        self.conn.execute(
            """INSERT INTO jobs(id,operation_id,project_id,handler_kind,payload_json,input_digest,
               status,available_at,max_attempts,timeout_seconds,created_at,updated_at)
               VALUES(?,?,?,?,?,?, 'queued', ?, ?, ?, ?, ?)""",
            (
                job_id, operation_id, self.project_id, handler_kind,
                canonical_bytes(payload).decode("utf-8"), canonical_digest(payload), now,
                max_attempts, timeout_seconds, now, now,
            ),
        )
        owner = self.conn.execute("SELECT requested_by FROM operations WHERE id=?", (operation_id,)).fetchone()[0]
        self.record_operation_event(operation_id, "job.queued", actor=owner, before=None, after="queued", job_id=job_id)
        return job_id

    def resolve_operation(
        self, operation_id: str, *, actor: str, conclusion: str,
        evidence_refs: list[dict[str, Any]], reason: str, followup_operation_id: str | None = None
    ) -> None:
        if conclusion not in {"verified_succeeded", "verified_failed", "risk_accepted", "retry_authorized"}:
            raise ValueError("invalid_operation_conclusion")
        now = _now_ms()
        payload = {
            "operation_id": operation_id, "actor": actor, "conclusion": conclusion,
            "evidence_refs": evidence_refs, "reason": reason,
            "followup_operation_id": followup_operation_id,
        }
        self.conn.execute(
            """INSERT INTO resolutions(operation_id,actor,conclusion,evidence_json,reason,
               followup_operation_id,digest,created_at) VALUES(?,?,?,?,?,?,?,?)""",
            (
                operation_id, actor, conclusion, canonical_bytes(evidence_refs).decode("utf-8"),
                reason, followup_operation_id, canonical_digest(payload), now,
            ),
        )
        self.conn.execute(
            "UPDATE operations SET revision=revision+1,updated_at=? WHERE id=?",
            (now, operation_id),
        )

    def assert_runtime_epoch(self, expected: str) -> None:
        row = self.conn.execute(
            "SELECT runtime_epoch FROM runtime_fences WHERE project_id=?", (self.project_id,)
        ).fetchone()
        if row is None or row[0] != expected:
            raise RevisionConflict("stale_runtime_epoch")

    def put_module_state(self, module: str, payload_json: str) -> int:
        """Persist one module snapshot inside the command transaction.

        Snapshots are module-scoped recovery material, not a substitute for the
        public domain model. The owning service remains the source of semantics;
        this table only makes the existing service state survive a daemon restart
        while its normalized repositories are being migrated.
        """
        row = self.conn.execute(
            "SELECT revision,payload_json FROM module_state WHERE project_id=? AND module=?",
            (self.project_id, module),
        ).fetchone()
        if row is not None and json.loads(row[1]) == json.loads(payload_json):
            return int(row[0])
        revision = int(row[0]) + 1 if row is not None else 1
        self.conn.execute(
            """INSERT INTO module_state(project_id,module,revision,payload_json,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(project_id,module) DO UPDATE SET
                 revision=excluded.revision,payload_json=excluded.payload_json,
                 updated_at=excluded.updated_at""",
            (self.project_id, module, revision, payload_json, self.recorded_at),
        )
        return revision

    def record_entity_change(
        self, *, lineage_id: str, subject_ref: str, existed: bool,
        revision_before: int | None, revision_after: int | None,
    ) -> dict[str, Any]:
        """Keep observed entity times alongside, never inside, the domain snapshot.

        A pre-existing entity without metadata has unknown creation time. Its
        first *observed change* supplies updated_at only; upgrades never invent
        earlier business timestamps. Audit revisions are observation counters
        only when the domain does not already own a CAS revision.
        """
        old = self.conn.execute(
            "SELECT revision,created_at FROM entity_audit_metadata "
            "WHERE project_id=? AND lineage_id=? AND subject_ref=?",
            (self.project_id, lineage_id, subject_ref),
        ).fetchone()
        before = revision_before if revision_before is not None else (old[0] if old else None)
        after = revision_after if revision_after is not None else (int(before or 0) + 1)
        created_at = old[1] if old else (None if existed else self.recorded_at)
        self.conn.execute(
            """INSERT INTO entity_audit_metadata
               (project_id,lineage_id,subject_ref,created_at,updated_at,revision,last_event_seq)
               VALUES(?,?,?,?,?,?,NULL) ON CONFLICT(project_id,lineage_id,subject_ref)
               DO UPDATE SET updated_at=excluded.updated_at,revision=excluded.revision""",
            (self.project_id, lineage_id, subject_ref, created_at, self.recorded_at, after),
        )
        return {"subject_ref": subject_ref, "revision_before": before, "revision_after": after,
                "revision_source": "domain" if revision_after is not None else "audit_observation",
                "created_at": created_at, "updated_at": self.recorded_at}


class ProjectDatabase:
    def __init__(self, path: str | Path, project_id: str = "local-project") -> None:
        self.path = Path(path)
        self.project_id = project_id
        self.lock = ProjectLock(self.path.with_suffix(self.path.suffix + ".lock"), serialize_threads=True)
        self.process_lock = ProjectLock(self.path.with_suffix(self.path.suffix + ".runtime.lock"))
        self._process_lock_held = False
        # Test-only hook for the commit-window crash gate. Production callers
        # leave it unset; a raised hook simulates a process dying after commit
        # and before the response reaches the caller.
        self.post_commit_hook: Callable[[], None] | None = None
        self.delivery_store = SecretDeliveryStore(self.path.with_suffix(self.path.suffix + ".deliveries"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def acquire_process_lock(self) -> None:
        if not self._process_lock_held:
            self.process_lock.__enter__()
            self._process_lock_held = True

    def release_process_lock(self) -> None:
        if self._process_lock_held:
            self.process_lock.__exit__(None, None, None)
            self._process_lock_held = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _initialize(self) -> None:
        with self.lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
                self._ensure_schema_columns(conn)
                conn.execute(
                    "INSERT OR IGNORE INTO runtime_meta(key,value) VALUES(?,?)",
                    (f"lineage:{self.project_id}", new_id()),
                )
                if conn.execute(
                    "SELECT 1 FROM runtime_fences WHERE project_id=?", (self.project_id,)
                ).fetchone() is None:
                    conn.execute(
                        "INSERT INTO runtime_fences(project_id,runtime_epoch) VALUES(?,?)",
                        (self.project_id, new_id()),
                    )
            finally:
                conn.close()

    @staticmethod
    def _ensure_schema_columns(conn: sqlite3.Connection) -> None:
        """Apply additive PT1 columns to databases created by older prototypes."""

        columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(events)").fetchall()
        }
        command_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(commands)").fetchall()}
        for name, definition in {
            "delivery_ref": "TEXT", "principal_kind": "TEXT", "auth_session_id": "TEXT",
            "auth_connection_epoch": "INTEGER", "auth_proof_hash": "TEXT",
        }.items():
            if name not in command_columns:
                conn.execute(f"ALTER TABLE commands ADD COLUMN {name} {definition}")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS commands_delivery_ref "
            "ON commands(project_id,delivery_ref) WHERE delivery_ref IS NOT NULL"
        )
        additions = {
            "recorded_at": "INTEGER",
            "subject_ref": "TEXT",
            "outcome": "TEXT NOT NULL DEFAULT 'committed'",
            "reason_code": "TEXT",
            "caused_by_command_id": "TEXT",
            "revision_before": "INTEGER",
            "revision_after": "INTEGER",
            "evidence_refs_json": "TEXT NOT NULL DEFAULT '[]'",
            "projection_version": "TEXT NOT NULL DEFAULT 'v1'",
        }
        for name, definition in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE events ADD COLUMN {name} {definition}")
        # Existing events already have a daemon timestamp. Preserve it as the
        # recorded time and mark their semantic subject as the old aggregate;
        # never invent a timestamp for records that did not have one.
        if "recorded_at" not in columns:
            conn.execute("UPDATE events SET recorded_at=occurred_at WHERE recorded_at IS NULL")
        conn.execute(
            "UPDATE events SET subject_ref=aggregate_ref WHERE subject_ref IS NULL"
        )
        conn.execute(
            "UPDATE events SET caused_by_command_id=command_id WHERE caused_by_command_id IS NULL"
        )
        conn.execute(
            "UPDATE events SET evidence_refs_json='[]' WHERE evidence_refs_json IS NULL"
        )
        conn.execute(
            "UPDATE events SET projection_version='v1' WHERE projection_version IS NULL"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS events_actor_seq ON events(project_id,actor_ref,event_seq)")
        conn.execute("CREATE INDEX IF NOT EXISTS events_subject_seq ON events(project_id,subject_ref,event_seq)")
        conn.execute("CREATE INDEX IF NOT EXISTS events_time_seq ON events(project_id,occurred_at,event_seq)")

    @property
    def lineage_id(self) -> str:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute("SELECT value FROM runtime_meta WHERE key=?", (f"lineage:{self.project_id}",)).fetchone()
            if row is None:
                raise RuntimeError("project_lineage_missing")
            return str(row[0])

    def entity_metadata(self, lineage_id: str) -> dict[str, dict[str, Any]]:
        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT subject_ref,created_at,updated_at,revision,last_event_seq "
                "FROM entity_audit_metadata WHERE project_id=? AND lineage_id=?",
                (self.project_id, lineage_id),
            ).fetchall()
        return {str(row["subject_ref"]): dict(row) for row in rows}

    def module_state(self, module: str) -> str | None:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload_json FROM module_state WHERE project_id=? AND module=?",
                (self.project_id, module),
            ).fetchone()
            return None if row is None else str(row[0])

    def last_event_seq(self) -> int:
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(event_seq), 0) FROM events WHERE project_id=?",
                (self.project_id,),
            ).fetchone()
            return int(row[0]) if row is not None else 0

    def get_event(self, event_id: str) -> dict[str, Any] | None:
        """Read one audit event without exposing the raw SQLite connection."""
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                """SELECT project_id,lineage_id,schema_version,event_id,event_seq,event_type,aggregate_ref,actor_ref,command_id,
                          occurred_at,recorded_at,subject_ref,outcome,reason_code,
                          caused_by_command_id,revision_before,revision_after,
                          evidence_refs_json,projection_version,payload_json,digest
                   FROM events WHERE project_id=? AND event_id=?""",
                (self.project_id, event_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "event_id": str(row["event_id"]), "event_seq": int(row["event_seq"]),
            "project_id": str(row["project_id"]), "lineage_id": str(row["lineage_id"]),
            "schema_version": str(row["schema_version"]), "event_type": str(row["event_type"]),
            "aggregate_ref": str(row["aggregate_ref"]), "actor_ref": str(row["actor_ref"]),
            "command_id": str(row["command_id"]),
            "occurred_at": int(row["occurred_at"]) if row["occurred_at"] is not None else None,
            "recorded_at": int(row["recorded_at"]) if row["recorded_at"] is not None else None,
            "subject_ref": str(row["subject_ref"]) if row["subject_ref"] is not None else None,
            "outcome": str(row["outcome"]), "reason_code": row["reason_code"],
            "caused_by_command_id": row["caused_by_command_id"],
            "revision_before": row["revision_before"], "revision_after": row["revision_after"],
            "evidence_refs": json.loads(str(row["evidence_refs_json"] or "[]")),
            "projection_version": str(row["projection_version"] or "v1"),
            "payload": json.loads(str(row["payload_json"])), "digest": str(row["digest"]),
        }

    def list_events(
        self,
        *,
        limit: int = 50,
        cursor: int | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
        actor_ref: str | None = None,
        subject_ref: str | None = None,
        through_event_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return a stable, scope-bound audit page in ascending event order.

        ``cursor`` is the last returned ``event_seq``.  The caller owns the
        public ``next_cursor`` wrapper; keeping the database primitive numeric
        makes replay and migration deterministic.
        """
        # One internal look-ahead row is allowed; the public API still caps
        # returned pages at 200. Clamping this primitive to 200 loses next_cursor.
        bounded = max(1, min(int(limit), 201))
        if from_ms is not None and to_ms is not None and from_ms > to_ms:
            raise ValueError("invalid_time_range")
        predicates = ["project_id=?"]
        values: list[Any] = [self.project_id]
        if cursor is not None:
            predicates.append("event_seq > ?")
            values.append(int(cursor))
        if through_event_seq is not None:
            predicates.append("event_seq <= ?")
            values.append(through_event_seq)
        if from_ms is not None:
            predicates.append("occurred_at >= ?")
            values.append(int(from_ms))
        if to_ms is not None:
            predicates.append("occurred_at <= ?")
            values.append(int(to_ms))
        if actor_ref:
            predicates.append("actor_ref = ?")
            values.append(actor_ref)
        if subject_ref:
            predicates.append("subject_ref = ?")
            values.append(subject_ref)
        values.append(bounded)
        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(
                f"""SELECT project_id,lineage_id,schema_version,event_id,event_seq,event_type,aggregate_ref,actor_ref,command_id,
                          occurred_at,recorded_at,subject_ref,outcome,reason_code,
                          caused_by_command_id,revision_before,revision_after,
                          evidence_refs_json,projection_version,payload_json,digest
                   FROM events WHERE {' AND '.join(predicates)}
                   ORDER BY event_seq ASC LIMIT ?""",
                values,
            ).fetchall()
        return [
            {
                "event_id": str(row["event_id"]), "event_seq": int(row["event_seq"]),
                "project_id": str(row["project_id"]), "lineage_id": str(row["lineage_id"]),
                "schema_version": str(row["schema_version"]),
                "event_type": str(row["event_type"]), "aggregate_ref": str(row["aggregate_ref"]),
                "actor_ref": str(row["actor_ref"]), "command_id": str(row["command_id"]),
                "occurred_at": int(row["occurred_at"]) if row["occurred_at"] is not None else None,
                "recorded_at": int(row["recorded_at"]) if row["recorded_at"] is not None else None,
                "subject_ref": str(row["subject_ref"]) if row["subject_ref"] is not None else None,
                "outcome": str(row["outcome"]), "reason_code": row["reason_code"],
                "caused_by_command_id": row["caused_by_command_id"],
                "revision_before": row["revision_before"], "revision_after": row["revision_after"],
                "evidence_refs": json.loads(str(row["evidence_refs_json"] or "[]")),
                "projection_version": str(row["projection_version"] or "v1"),
                "payload": json.loads(str(row["payload_json"])), "digest": str(row["digest"]),
            }
            for row in rows
        ]

    @property
    def runtime_epoch(self) -> str:
        """Return the persisted runtime fence used to invalidate old sessions."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT runtime_epoch FROM runtime_fences WHERE project_id=?",
                (self.project_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("runtime_fence_missing")
            return str(row[0])

    @contextlib.contextmanager
    def transaction(self, command_id: str | None = None) -> Iterator[UnitOfWork]:
        with self.lock:
            conn = self._connect()
            uow = UnitOfWork(conn, self.project_id, command_id or new_id())
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield uow
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()
            finally:
                conn.close()

    def dispatch(
        self,
        *,
        principal_id: str,
        command_kind: str,
        command_id: str,
        payload: dict[str, Any],
        handler: Callable[[UnitOfWork], dict[str, Any]],
        expected_revision: int | None = None,
        principal_kind: str | None = None,
        auth_session_id: str | None = None,
        auth_connection_epoch: int | None = None,
        auth_proof_hash: str | None = None,
        replay_only: bool = False,
        on_rollback: Callable[[], None] | None = None,
    ) -> DispatchResult:
        input_hash = canonical_digest({
            "project_id": self.project_id, "principal_id": principal_id,
            "command_kind": command_kind, "payload": payload,
            "expected_revision": expected_revision,
        })
        with self.lock:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE")
            committed = False
            try:
                row = conn.execute(
                    """SELECT * FROM commands
                       WHERE project_id=? AND principal_id=? AND command_kind=? AND command_id=?""",
                    (self.project_id, principal_id, command_kind, command_id),
                ).fetchone()
                if row is not None:
                    if row["input_hash"] != input_hash:
                        raise IdempotencyConflict(command_id)
                    if row["delivery_ref"] is not None:
                        self._verify_delivery_request(
                            row, principal_kind=principal_kind, auth_session_id=auth_session_id,
                            auth_connection_epoch=auth_connection_epoch, auth_proof_hash=auth_proof_hash,
                        )
                    elif replay_only:
                        raise PermissionError("authentication_failed")
                    conn.commit()
                    committed = True
                    return DispatchResult(
                        command_id, self._private_command_result(dict(row)),
                        row["event_seq"], True,
                    )
                if replay_only:
                    raise PermissionError("authentication_failed")
                uow = UnitOfWork(conn, self.project_id, command_id)
                result = handler(uow)
                binding = {"project_id": self.project_id, "principal_id": principal_id,
                           "command_kind": command_kind, "command_id": command_id, "input_hash": input_hash}
                stored_result = self._store_sensitive_result(result, binding=binding)
                conn.execute(
                    """INSERT INTO commands(project_id,principal_id,command_kind,command_id,input_hash,
                       result_json,event_seq,created_at,delivery_ref,principal_kind,auth_session_id,
                       auth_connection_epoch,auth_proof_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        self.project_id, principal_id, command_kind, command_id, input_hash,
                        canonical_bytes(stored_result).decode("utf-8"), uow._event_seq, _now_ms(),
                        stored_result.get("delivery_ref"), principal_kind, auth_session_id,
                        auth_connection_epoch, auth_proof_hash,
                    ),
                )
                # These opt-in exits are used only by the standalone process
                # crash harness.  They make the two response/commit windows
                # observable without adding a production HTTP fault endpoint.
                if os.environ.get("TSUNAGOU_TEST_EXIT_BEFORE_COMMIT_COMMAND_ID") == command_id:
                    os._exit(73)
                conn.commit()
                committed = True
                if self.post_commit_hook is not None:
                    hook = self.post_commit_hook
                    self.post_commit_hook = None
                    hook()
                if os.environ.get("TSUNAGOU_TEST_EXIT_AFTER_COMMIT_COMMAND_ID") == command_id:
                    os._exit(74)
                response_result = self._private_command_result({
                    **binding, "delivery_ref": stored_result.get("delivery_ref"),
                    "result_json": json.dumps(stored_result),
                })
                return DispatchResult(command_id, response_result, uow._event_seq, False)
            except BaseException:
                if not committed:
                    conn.rollback()
                    if on_rollback is not None:
                        on_rollback()
                raise
            finally:
                conn.close()

    def _store_sensitive_result(self, result: dict[str, Any], *, binding: dict[str, Any]) -> dict[str, Any]:
        """Persist a safe receipt while returning the full result to this caller."""

        if not _contains_secret_shape(result):
            return result
        metadata = self.delivery_store.put(result, binding=binding)
        return {**_safe_credential_result(result), **metadata}

    @staticmethod
    def _delivery_binding(row: dict[str, Any]) -> dict[str, Any]:
        return {key: row[key] for key in ("project_id", "principal_id", "command_kind", "command_id", "input_hash")}

    def _private_command_result(self, row: dict[str, Any]) -> dict[str, Any]:
        """Called only after exact authenticated command replay, never by queries."""
        result: dict[str, Any] = json.loads(row["result_json"])
        ref = row.get("delivery_ref")
        if not isinstance(ref, str):
            if _contains_secret_shape(result):
                raise RuntimeError("legacy_credential_migration_required")
            return result
        session_id = result.get("session_id")
        if isinstance(session_id, str):
            # A later rebind/revocation must not make an older pending receipt
            # readable again, even if its original transport proof is valid.
            authority_json = self.module_state("authority")
            if authority_json is not None:
                session = json.loads(authority_json).get("sessions", {}).get(session_id)
                if (not isinstance(session, dict) or not session.get("active")
                        or session.get("connection_epoch") != result.get("connection_epoch")):
                    return {**result, "delivery_status": "revoked", "recovery_action": "reconnect_required"}
        binding = self._delivery_binding(row)
        try:
            private = self.delivery_store.read(ref, binding=binding)
        except RuntimeError as exc:
            states = {"secret_delivery_consumed": "consumed", "secret_delivery_expired": "expired",
                      "secret_delivery_revoked": "revoked", "secret_delivery_missing": "unavailable"}
            state = states.get(str(exc))
            if state is None:
                raise
            return {**result, "delivery_status": state, "recovery_action": "reconnect_required"}
        return {**private, **self.delivery_store.metadata(ref, binding=binding)}

    @staticmethod
    def _verify_delivery_request(
        row: sqlite3.Row, *, principal_kind: str | None, auth_session_id: str | None,
        auth_connection_epoch: int | None, auth_proof_hash: str | None,
    ) -> None:
        if (row["principal_kind"] != principal_kind or row["auth_session_id"] != auth_session_id
                or row["auth_connection_epoch"] != auth_connection_epoch
                or not secrets.compare_digest(str(row["auth_proof_hash"] or ""), str(auth_proof_hash or ""))):
            raise PermissionError("secret_delivery_scope_denied")

    def verify_credential_replay(
        self, *, principal_id: str, command_kind: str, command_id: str, payload: dict[str, Any],
        session_id: str, connection_epoch: int, proof_hash: str, current_connection_epoch: int,
    ) -> None:
        if command_kind != "session.reconnect":
            raise PermissionError("authentication_failed")
        expected_hash = canonical_digest({
            "project_id": self.project_id, "principal_id": principal_id, "command_kind": command_kind,
            "payload": payload, "expected_revision": None,
        })
        with contextlib.closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM commands WHERE project_id=? AND principal_id=? AND command_kind=? AND command_id=?",
                (self.project_id, principal_id, command_kind, command_id),
            ).fetchone()
        if row is None or row["delivery_ref"] is None or row["input_hash"] != expected_hash:
            raise PermissionError("authentication_failed")
        safe = json.loads(row["result_json"])
        if safe.get("session_id") != session_id or safe.get("connection_epoch") != current_connection_epoch:
            raise PermissionError("authentication_failed")
        self._verify_delivery_request(row, principal_kind="D", auth_session_id=session_id,
                                      auth_connection_epoch=connection_epoch, auth_proof_hash=proof_hash)

    def acknowledge_credential_delivery(
        self, delivery_ref: str, *, principal_kind: str, principal_id: str,
        session_id: str | None, connection_epoch: int | None,
    ) -> dict[str, Any]:
        with self.lock:
            with contextlib.closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT * FROM commands WHERE project_id=? AND delivery_ref=?", (self.project_id, delivery_ref),
                ).fetchone()
                if row is None:
                    raise PermissionError("secret_delivery_scope_denied")
                safe = json.loads(row["result_json"])
                user_ticket = (principal_kind == "U" and row["principal_kind"] == "U"
                               and row["principal_id"] == principal_id and row["command_kind"] == "agent.ticket.create.user")
                target_session = (principal_kind == "D" and safe.get("agent_id") == principal_id
                                  and session_id is not None and safe.get("session_id") == session_id
                                  and safe.get("connection_epoch") == connection_epoch)
                if target_session:
                    authority_row = conn.execute(
                        "SELECT payload_json FROM module_state WHERE project_id=? AND module='authority'", (self.project_id,),
                    ).fetchone()
                    if authority_row is not None:
                        current_session = json.loads(authority_row[0]).get("sessions", {}).get(session_id)
                        target_session = bool(
                            isinstance(current_session, dict) and current_session.get("active")
                            and current_session.get("agent_id") == principal_id
                            and current_session.get("connection_epoch") == connection_epoch
                        )
                if not user_ticket and not target_session:
                    raise PermissionError("secret_delivery_scope_denied")
                metadata = self.delivery_store.acknowledge(delivery_ref, binding=self._delivery_binding(dict(row)))
                # The vault consumes first. A crash before this safe receipt
                # update leaves no recoverable secret; retry reconciles metadata.
                conn.execute(
                    "UPDATE commands SET result_json=? WHERE project_id=? AND delivery_ref=?",
                    (canonical_bytes({**safe, **metadata}).decode("utf-8"), self.project_id, delivery_ref),
                )
                return dict(metadata)

    def sensitive_command_rows(self) -> list[dict[str, Any]]:
        """Return a metadata-only inventory of legacy command rows with secrets."""

        with contextlib.closing(self._connect()) as conn:
            rows = conn.execute(
                    """SELECT project_id,principal_id,command_id,command_kind,created_at,result_json,delivery_ref FROM commands
                   WHERE project_id=? ORDER BY created_at,command_id""",
                (self.project_id,),
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                try:
                    value = json.loads(str(row["result_json"]))
                except json.JSONDecodeError:
                    continue
                if _contains_secret_shape(value) and row["delivery_ref"] is None:
                    result.append({
                        "project_id": str(row["project_id"]),
                        "principal_digest": canonical_digest({"principal_id": str(row["principal_id"])}),
                        "command_id": str(row["command_id"]), "command_kind": str(row["command_kind"]),
                        "created_at": int(row["created_at"]),
                    })
            return result

    def scrub_sensitive_command_rows(self) -> dict[str, int]:
        """Refuse the obsolete migration that preserved live leaked credentials."""
        raise RuntimeError("credential_revocation_migration_required")

    def claim_job(
        self, worker_id: str, lease_seconds: int = 60, *,
        handler_kind: str | None = None, operation_id: str | None = None,
    ) -> dict[str, Any] | None:
        # Reconcile leases before selecting work. A worker process can disappear
        # without running a finally block, so an expired lease must not remain
        # permanently in ``running``.
        self.recover_expired_jobs()
        with self.transaction() as uow:
            now = _now_ms()
            row = uow.conn.execute(
                """SELECT * FROM jobs WHERE project_id=? AND status IN ('queued','retry_wait')
                   AND available_at<=? AND (lease_until IS NULL OR lease_until<?)
                   AND (? IS NULL OR handler_kind=?) AND (? IS NULL OR operation_id=?)
                   ORDER BY available_at,id LIMIT 1""",
                (self.project_id, now, now, handler_kind, handler_kind, operation_id, operation_id),
            ).fetchone()
            if row is None:
                return None
            attempt_no = int(row["attempt_count"]) + 1
            if attempt_no > row["max_attempts"]:
                uow.conn.execute(
                    "UPDATE jobs SET status='failed',updated_at=? WHERE id=?", (now, row["id"])
                )
                uow.conn.execute(
                    "UPDATE operations SET status='failed',error_code='job_attempts_exhausted',"
                    "revision=revision+1,updated_at=? WHERE id=?", (now, row["operation_id"]),
                )
                uow.conn.execute("UPDATE outbox SET status='failed' WHERE project_id=? AND target_ref=?",
                                 (self.project_id, row["operation_id"]))
                uow.record_operation_event(row["operation_id"], "job.exhausted", actor=worker_id,
                                           before=row["status"], after="failed", job_id=row["id"],
                                           reason_code="job_attempts_exhausted")
                return None
            lease_epoch = int(row["lease_epoch"]) + 1
            uow.conn.execute(
                """UPDATE jobs SET status='running',attempt_count=?,lease_owner=?,lease_epoch=?,
                   lease_until=?,updated_at=? WHERE id=?""",
                (attempt_no, worker_id, lease_epoch, now + lease_seconds * 1000, now, row["id"]),
            )
            uow.conn.execute(
                """INSERT INTO job_attempts(job_id,attempt_no,lease_epoch,worker_id,started_at)
                   VALUES(?,?,?,?,?)""",
                (row["id"], attempt_no, lease_epoch, worker_id, now),
            )
            uow.conn.execute(
                "UPDATE operations SET status='running',updated_at=?,revision=revision+1 WHERE id=?",
                (now, row["operation_id"]),
            )
            uow.record_operation_event(row["operation_id"], "job.started", actor=worker_id,
                                       before=row["status"], after="running", job_id=row["id"])
            return {"job_id": row["id"], "operation_id": row["operation_id"],
                    "attempt_no": attempt_no, "lease_epoch": lease_epoch,
                    "payload_json": row["payload_json"], "input_digest": row["input_digest"]}

    def finish_job(
        self, job_id: str, *, worker_id: str, lease_epoch: int, outcome: str,
        error_code: str | None = None, backoff_seconds: int = 1, result: dict[str, Any] | None = None,
    ) -> None:
        if outcome not in {"succeeded", "failed", "retry", "unknown"}:
            raise ValueError("invalid_job_outcome")
        with self.transaction() as uow:
            row = uow.conn.execute(
                "SELECT operation_id,attempt_count,max_attempts,handler_kind FROM jobs "
                "WHERE id=? AND lease_owner=? AND lease_epoch=? AND status='running' AND lease_until>?",
                (job_id, worker_id, lease_epoch, _now_ms()),
            ).fetchone()
            if row is None:
                raise RevisionConflict("stale_job_lease")
            now = _now_ms()
            if outcome == "succeeded":
                status, op_status, available_at = "succeeded", "succeeded", now
            elif outcome == "retry" and int(row["attempt_count"]) < int(row["max_attempts"]):
                delay = max(1, backoff_seconds) * (2 ** max(0, int(row["attempt_count"]) - 1))
                status, op_status, available_at = "retry_wait", "retry_wait", now + delay * 1000
            elif outcome == "unknown":
                # An external effect may have happened. Preserve the job record,
                # but never automatically replay it.
                status, op_status, available_at = "failed", "outcome_unknown", now
            else:
                status, op_status, available_at = "failed", "failed", now
            uow.conn.execute(
                "UPDATE jobs SET status=?,available_at=?,lease_until=NULL,updated_at=? WHERE id=?",
                (status, available_at, now, job_id),
            )
            uow.conn.execute(
                """UPDATE job_attempts SET finished_at=?,outcome=?,error_code=?
                   WHERE job_id=? AND attempt_no=?""",
                (now, outcome, error_code, job_id, row["attempt_count"]),
            )
            uow.conn.execute(
                "UPDATE operations SET status=?,updated_at=?,revision=revision+1,error_code=?,result_json=? WHERE id=?",
                (op_status, now, error_code, json.dumps(result) if result is not None else None, row["operation_id"]),
            )
            if row["handler_kind"] == "checkpoint.materialize":
                uow.conn.execute(
                    "UPDATE outbox SET status=?,attempt_count=attempt_count+1 WHERE project_id=? AND target_ref=?",
                    ("done" if status == "succeeded" else "failed", self.project_id, row["operation_id"]),
                )
            refs = (str(result["checkpoint_digest"]),) if result and result.get("checkpoint_digest") else ()
            uow.record_operation_event(row["operation_id"], "job.finished", actor=worker_id,
                                       before="running", after=op_status, job_id=job_id,
                                       reason_code=error_code, evidence_refs=refs)

    def recover_expired_jobs(self) -> int:
        """Move expired leases to retry or unknown without executing effects."""
        with self.transaction("recover-expired") as uow:
            now = _now_ms()
            rows = uow.conn.execute(
                "SELECT id,operation_id,attempt_count,max_attempts,handler_kind FROM jobs "
                "WHERE project_id=? AND status='running' AND lease_until IS NOT NULL AND lease_until<=?",
                (self.project_id, now),
            ).fetchall()
            for row in rows:
                is_external = str(row["handler_kind"]).startswith("external")
                if is_external:
                    job_status, op_status = "failed", "outcome_unknown"
                elif int(row["attempt_count"]) < int(row["max_attempts"]):
                    job_status, op_status = "retry_wait", "retry_wait"
                else:
                    job_status, op_status = "failed", "failed"
                uow.conn.execute(
                    "UPDATE jobs SET status=?,lease_owner=NULL,lease_until=NULL,available_at=?,updated_at=? WHERE id=?",
                    (job_status, now, now, row["id"]),
                )
                uow.conn.execute(
                    "UPDATE operations SET status=?,error_code=?,updated_at=?,revision=revision+1 WHERE id=?",
                    (op_status, "lease_expired" if is_external else None, now, row["operation_id"]),
                )
                if row["handler_kind"] == "checkpoint.materialize":
                    uow.conn.execute("UPDATE outbox SET status=? WHERE project_id=? AND target_ref=?",
                                     ("failed" if job_status == "failed" else "pending", self.project_id, row["operation_id"]))
                uow.conn.execute(
                    "UPDATE job_attempts SET finished_at=?,outcome='expired',error_code='lease_expired' "
                    "WHERE job_id=? AND attempt_no=? AND finished_at IS NULL",
                    (now, row["id"], row["attempt_count"]),
                )
                uow.record_operation_event(row["operation_id"], "job.lease_expired", actor="runtime",
                                           before="running", after=op_status, job_id=row["id"],
                                           reason_code="lease_expired")
            return len(rows)

    def rotate_runtime_epoch(self) -> str:
        """Invalidate stale workers and return the new project runtime epoch."""
        epoch = new_id()
        with self.transaction("rotate-runtime-epoch") as uow:
            uow.conn.execute(
                "UPDATE runtime_fences SET runtime_epoch=?,connection_epoch=connection_epoch+1 WHERE project_id=?",
                (epoch, self.project_id),
            )
        return epoch

    def mark_unknown(self, operation_id: str, error_code: str = "external_effect_unknown") -> None:
        with self.transaction() as uow:
            uow.conn.execute(
                "UPDATE operations SET status='outcome_unknown',error_code=?,revision=revision+1,updated_at=? WHERE id=?",
                (error_code, _now_ms(), operation_id),
            )
