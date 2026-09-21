"""Small durable maintenance loop for mechanical runtime reconciliation."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Any


class RuntimeMaintenance:
    """Reconcile expired execution leases without inventing business decisions.

    The callback runs under the same SQLite file lock as command dispatch.  It
    therefore cannot observe or persist a half-written module snapshot.  The
    thread is intentionally narrow: lease expiry is a mechanical fence; the
    owning Agent or user still decides whether an orphaned task is reopened,
    cancelled, or failed.
    """

    def __init__(
        self, *, database: Any, state_runtime: Any, resources: Any,
        tasks: Any, authority: Any, interval_seconds: float = 1.0,
    ) -> None:
        self.database = database
        self.state_runtime = state_runtime
        self.resources = resources
        self.tasks = tasks
        self.authority = authority
        self.interval_seconds = max(0.05, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="tsunagou-runtime-maintenance", daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(1.0, self.interval_seconds * 2))
        self._thread = None

    def run_once(self) -> int:
        """Reconcile due leases and return the number of lease sets expired."""
        if not self._run_lock.acquire(blocking=False):
            return 0
        snapshot = self.state_runtime.capture()
        try:
            # Job leases are durable rows, so recovery must run even when no
            # in-memory resource lease has expired.  The database operation is
            # deliberately mechanical: it only moves abandoned work back to
            # retry/unknown and never executes the handler effect.
            expired_jobs = self.database.recover_expired_jobs()
            with self.database.transaction("runtime-lease-reconcile") as uow:
                expired = self.resources.expire_due()
                if not expired:
                    return expired_jobs
                for lease_id in expired:
                    lease = self.resources.lease_sets.get(lease_id)
                    if lease is None:
                        continue
                    attempt = self.tasks.attempts.get(lease.attempt_id)
                    if attempt is None or attempt.status not in {"claimed", "running"}:
                        continue
                    task = self.tasks.tasks.get(attempt.task_id)
                    if task is not None and task.current_attempt_id == attempt.attempt_id:
                        self.tasks.orphan(task.task_id, reason="resource_lease_expired")
                    for grant_id, grant in list(self.authority.grants.items()):
                        if grant.attempt_id == attempt.attempt_id and grant.status == "active":
                            self.authority.grants[grant_id] = type(grant)(
                                **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"},
                            )
                self.state_runtime.persist(
                    uow, actor_ref="runtime", command_kind="resource.lease.expired",
                )
                return len(expired) + expired_jobs
        except BaseException:
            # Memory mutations must never survive a failed SQL transaction.
            # Rebuild from the snapshot that the dispatcher also uses for rollback.
            self.state_runtime.restore(snapshot)
            raise
        finally:
            self._run_lock.release()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception:
                # A later tick retries.  The command path remains available even
                # if a maintenance pass fails due to a transient filesystem lock.
                time.sleep(min(self.interval_seconds, 0.25))
