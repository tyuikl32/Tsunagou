from __future__ import annotations

import contextlib
import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.digests import canonical_bytes, canonical_digest
from tsunagou.shared_kernel.errors import IdempotencyConflict, LockUnavailable, RevisionConflict
from tsunagou.shared_kernel.ids import new_id

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX CI
    msvcrt = None  # type: ignore[assignment]

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    fcntl = None  # type: ignore[assignment]


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
  occurred_at INTEGER NOT NULL,
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
    def __init__(self, path: Path, timeout: float = 5.0) -> None:
        self.path = path
        self.timeout = timeout
        self.handle: Any = None

    def __enter__(self) -> ProjectLock:
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

    def append_event(
        self,
        *,
        lineage_id: str,
        event_type: str,
        aggregate_ref: str,
        actor_ref: str,
        payload: dict[str, Any],
        schema_version: str = "1.0",
    ) -> int:
        current = self.conn.execute(
            "SELECT COALESCE(MAX(event_seq), 0) FROM events WHERE project_id=?",
            (self.project_id,),
        ).fetchone()[0]
        seq = int(current) + 1
        payload_json = canonical_bytes(payload).decode("utf-8")
        self.conn.execute(
            """INSERT INTO events(project_id,event_seq,event_id,lineage_id,event_type,
               schema_version,aggregate_ref,actor_ref,command_id,occurred_at,payload_json,digest)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                self.project_id, seq, new_id(), lineage_id, event_type, schema_version,
                aggregate_ref, actor_ref, self.command_id, _now_ms(), payload_json,
                canonical_digest(payload),
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
        return operation_id

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


class ProjectDatabase:
    def __init__(self, path: str | Path, project_id: str = "local-project") -> None:
        self.path = Path(path)
        self.project_id = project_id
        self.lock = ProjectLock(self.path.with_suffix(self.path.suffix + ".lock"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

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
                if conn.execute(
                    "SELECT 1 FROM runtime_fences WHERE project_id=?", (self.project_id,)
                ).fetchone() is None:
                    conn.execute(
                        "INSERT INTO runtime_fences(project_id,runtime_epoch) VALUES(?,?)",
                        (self.project_id, new_id()),
                    )
            finally:
                conn.close()

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
    ) -> DispatchResult:
        input_hash = canonical_digest({
            "project_id": self.project_id, "principal_id": principal_id,
            "command_kind": command_kind, "payload": payload,
            "expected_revision": expected_revision,
        })
        with self.lock:
            conn = self._connect()
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    """SELECT input_hash,result_json,event_seq FROM commands
                       WHERE project_id=? AND principal_id=? AND command_kind=? AND command_id=?""",
                    (self.project_id, principal_id, command_kind, command_id),
                ).fetchone()
                if row is not None:
                    if row["input_hash"] != input_hash:
                        raise IdempotencyConflict(command_id)
                    conn.commit()
                    return DispatchResult(
                        command_id, __import__("json").loads(row["result_json"]),
                        row["event_seq"], True,
                    )
                uow = UnitOfWork(conn, self.project_id, command_id)
                result = handler(uow)
                conn.execute(
                    """INSERT INTO commands(project_id,principal_id,command_kind,command_id,input_hash,
                       result_json,event_seq,created_at) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        self.project_id, principal_id, command_kind, command_id, input_hash,
                        canonical_bytes(result).decode("utf-8"), uow._event_seq, _now_ms(),
                    ),
                )
                conn.commit()
                return DispatchResult(command_id, result, uow._event_seq, False)
            except BaseException:
                conn.rollback()
                raise
            finally:
                conn.close()

    def claim_job(self, worker_id: str, lease_seconds: int = 60) -> dict[str, Any] | None:
        # Reconcile leases before selecting work. A worker process can disappear
        # without running a finally block, so an expired lease must not remain
        # permanently in ``running``.
        self.recover_expired_jobs()
        with self.transaction() as uow:
            now = _now_ms()
            row = uow.conn.execute(
                """SELECT * FROM jobs WHERE project_id=? AND status IN ('queued','retry_wait')
                   AND available_at<=? AND (lease_until IS NULL OR lease_until<?)
                   ORDER BY available_at,id LIMIT 1""",
                (self.project_id, now, now),
            ).fetchone()
            if row is None:
                return None
            attempt_no = int(row["attempt_count"]) + 1
            if attempt_no > row["max_attempts"]:
                uow.conn.execute(
                    "UPDATE jobs SET status='failed',updated_at=? WHERE id=?", (now, row["id"])
                )
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
            return {"job_id": row["id"], "operation_id": row["operation_id"],
                    "attempt_no": attempt_no, "lease_epoch": lease_epoch,
                    "payload_json": row["payload_json"]}

    def finish_job(
        self, job_id: str, *, worker_id: str, lease_epoch: int, outcome: str,
        error_code: str | None = None, backoff_seconds: int = 1
    ) -> None:
        if outcome not in {"succeeded", "failed", "retry", "unknown"}:
            raise ValueError("invalid_job_outcome")
        with self.transaction() as uow:
            row = uow.conn.execute(
                "SELECT operation_id,attempt_count,max_attempts,handler_kind FROM jobs "
                "WHERE id=? AND lease_owner=? AND lease_epoch=?",
                (job_id, worker_id, lease_epoch),
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
                "UPDATE operations SET status=?,updated_at=?,revision=revision+1 WHERE id=?",
                (op_status, now, row["operation_id"]),
            )

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
