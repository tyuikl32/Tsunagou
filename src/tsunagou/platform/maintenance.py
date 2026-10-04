"""Small durable maintenance loop for mechanical runtime reconciliation."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class RuntimeMaintenance:
    """Maintain checkpoints and internal Job claims, never infer Agent liveness."""

    def __init__(
        self, *, database: Any,
        interval_seconds: float = 1.0, checkpoint_worker: Any | None = None,
    ) -> None:
        self.checkpoint_worker = checkpoint_worker
        self.database = database
        self.interval_seconds = max(0.05, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._run_lock = threading.Lock()
        self.last_projection_error: str | None = None
        self.after_run: Callable[[], None] | None = None

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
        if thread is None or not thread.is_alive():
            self._thread = None

    def run_once(self) -> int:
        """Run internal persistence maintenance without changing task ownership."""
        if not self._run_lock.acquire(blocking=False):
            return 0
        try:
            checkpoints = 0
            if self.checkpoint_worker is not None:
                checkpoints = self.checkpoint_worker.run_once()
                try:
                    self.checkpoint_worker.reconcile_project_projection()
                    self.last_projection_error = None
                except (OSError, ValueError):
                    # A disposable JSON projection must not stop independent
                    # checkpoint retries when a filesystem is unavailable.
                    self.last_projection_error = "project_projection_materialization_failed"
            with self.database.lock:
                return checkpoints + self._reconcile_locked()
        finally:
            self._run_lock.release()
            if self.after_run is not None:
                self.after_run()

    def _reconcile_locked(self) -> int:
        # Jobs describe internal handler execution and retain their own deadlines.
        # Resource reservations and user/Agent waits have no elapsed-time fence.
        return int(self.database.recover_expired_jobs())

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.run_once()
            except Exception:
                # A later tick retries.  The command path remains available even
                # if a maintenance pass fails due to a transient filesystem lock.
                time.sleep(min(self.interval_seconds, 0.25))
