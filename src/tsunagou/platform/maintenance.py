"""Small durable maintenance loop for mechanical runtime reconciliation."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Any


class RuntimeMaintenance:
    """Reconcile mechanical Lease and wake deadlines without business decisions.

    The callback runs under the same SQLite file lock as command dispatch.  It
    therefore cannot observe or persist a half-written module snapshot.  The
    thread is intentionally narrow: Lease expiry is a mechanical fence and
    wake expiry advances only the durable retry state; the owning Agent or
    user still decides whether an orphaned task is reopened, cancelled, or
    failed.
    """

    def __init__(
        self, *, database: Any, state_runtime: Any, resources: Any,
        tasks: Any, authority: Any, coordination: Any | None = None,
        interval_seconds: float = 1.0,
    ) -> None:
        self.database = database
        self.state_runtime = state_runtime
        self.resources = resources
        self.tasks = tasks
        self.authority = authority
        # Keep direct unit-test construction backwards compatible while the
        # normal container can pass the coordination service explicitly.
        self.coordination = (
            coordination if coordination is not None
            else getattr(state_runtime, "coordination", None)
        )
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
        """Reconcile due leases/wake deadlines and return work processed.

        Wake deadline reconciliation is deliberately independent from Lease
        maintenance. It only advances WakeAttempt state and never creates or
        renews an execution Lease on a worker's behalf.
        """
        if not self._run_lock.acquire(blocking=False):
            return 0
        snapshot = self.state_runtime.capture()
        try:
            # Job leases are durable rows, so recovery must run even when no
            # in-memory resource lease has expired.  The database operation is
            # deliberately mechanical: it only moves abandoned work back to
            # retry/unknown and never executes the handler effect.
            expired_jobs = int(self.database.recover_expired_jobs())
            with self.database.transaction("runtime-lease-reconcile") as uow:
                expired_wakes = 0
                if self.coordination is not None:
                    expired_wakes = int(self.coordination.reconcile_wake_deadlines())
                expired = self.resources.expire_due()
                expired_ids = set(expired)
                # A prior pass can persist the resource expiry before the
                # in-memory Attempt/Assignment reconciliation completes.  Scan
                # those rows as well so a later maintenance tick can finish
                # the fence without requiring another lease transition.
                expired_ids.update(
                    lease.lease_set_id for lease in self.resources.lease_sets.values()
                    if lease.status == "expired"
                )
                assignment_reconciled = 0
                for lease_id in expired_ids:
                    lease = self.resources.lease_sets.get(lease_id)
                    if lease is None:
                        continue
                    attempt = self.tasks.attempts.get(lease.attempt_id)
                    if attempt is None:
                        continue
                    if attempt.status in {"claimed", "running"}:
                        task = self.tasks.tasks.get(attempt.task_id)
                        if task is not None and task.current_attempt_id == attempt.attempt_id:
                            self.tasks.orphan(task.task_id, reason="resource_lease_expired")
                    if self.coordination is not None:
                        assignment_reconciled += int(self.coordination.mark_lease_expired(
                            attempt.task_id, attempt.attempt_id,
                        ))
                    for grant_id, grant in list(self.authority.grants.items()):
                        if grant.attempt_id == attempt.attempt_id and grant.status == "active":
                            self.authority.grants[grant_id] = type(grant)(
                                **{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"},
                            )
                if not expired and not expired_wakes and not assignment_reconciled:
                    return expired_jobs
                self.state_runtime.persist(
                    uow, actor_ref="runtime", command_kind="resource.lease.expired",
                )
                # A newly-expired Lease already accounts for this pass.  Add
                # the reconciliation count only when it was the sole work,
                # such as repairing a previously persisted expiry.
                return (
                    len(expired) + expired_wakes + expired_jobs
                    + (assignment_reconciled if not expired else 0)
                )
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
