"""Drain committed message outbox entries into the existing host dispatcher."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from tsunagou.hostwake.dispatcher import WakeDispatcher
from tsunagou.platform.db.sqlite import ProjectDatabase
from tsunagou.platform.telemetry import Telemetry
from tsunagou.shared_kernel.time import now_ms


class HostDeliveryWorker:
    def __init__(self, database: ProjectDatabase, dispatcher: WakeDispatcher, telemetry: Telemetry | None = None) -> None:
        self.database, self.dispatcher = database, dispatcher
        self.telemetry = telemetry or Telemetry()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tsunagou-host-delivery")
        self._pending: dict[int, tuple[str, Future[dict[str, Any]]]] = {}
        self.dispatcher.deliveries_acked = self._deliveries_acked

    def _deliveries_acked(self, recipient: str, message_ids: tuple[str, ...]) -> bool:
        """Read committed ACKs only; presentation, leases and silence are not ACK."""
        if not message_ids:
            return False
        try:
            with self.database.lock, contextlib.closing(self.database._connect()) as conn:
                snapshot = conn.execute(
                    "SELECT payload_json FROM module_state WHERE project_id=? AND module='messages'",
                    (self.database.project_id,),
                ).fetchone()
            deliveries = json.loads(snapshot[0]).get("deliveries", {}) if snapshot else {}
        except (OSError, sqlite3.Error, ValueError):
            # Unavailable state cannot prove consumption or cancel a delivery.
            return False
        return all(deliveries.get(identity, {}).get("recipient_agent_id") == recipient
                   and deliveries[identity].get("status") == "acked" for identity in message_ids)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self.dispatcher.resume_pending()
        self._thread = threading.Thread(target=self._run, daemon=True, name="tsunagou-message-outbox")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.dispatcher.stop()

    def _run(self) -> None:
        while not self._stop.wait(0.5):
            try:
                self.run_once()
            except (OSError, RuntimeError, sqlite3.Error):
                # The durable row remains pending if its receipt cannot be
                # saved. This never marks the underlying business task blocked.
                continue

    def run_once(self) -> int:
        for identity, (_recipient, future) in list(self._pending.items()):
            if not future.done():
                continue
            try:
                result = future.result()
            except Exception:
                result = {"error_code": "host_wake_dispatch_failed", "state": "failed"}
            retry = result.get("error_code") in {"host_binding_not_found", "host_binding_not_ready", "host_wake_dispatch_failed"}
            with self.database.transaction("host-wake-outbox") as uow:
                uow.conn.execute(
                    "UPDATE outbox SET status=?,attempt_count=attempt_count+1,next_attempt_at=? "
                    "WHERE project_id=? AND id=? AND kind='host_wake'",
                    ("pending" if retry else "done", now_ms() + 5000, self.database.project_id, identity),
                )
            self._pending.pop(identity)
        with self.database.lock, contextlib.closing(self.database._connect()) as conn:
            rows = conn.execute(
                "SELECT o.id,o.target_ref,e.command_id,e.actor_ref,e.payload_json FROM outbox o "
                "JOIN events e ON o.project_id=e.project_id AND o.event_seq=e.event_seq "
                "WHERE o.project_id=? AND o.kind='host_wake' "
                "AND o.status='pending' AND o.next_attempt_at<=? ORDER BY o.id LIMIT 100",
                (self.database.project_id, now_ms()),
            ).fetchall()
            snapshot = conn.execute(
                "SELECT payload_json FROM module_state WHERE project_id=? AND module='messages'",
                (self.database.project_id,),
            ).fetchone()
            messages = json.loads(snapshot[0]).get("messages", {}) if snapshot else {}
        scheduled = 0
        active_recipients = {recipient for recipient, _future in self._pending.values()}
        # Only pass identifiers to the host boundary, never private bodies.
        for row in rows:
            if len(self._pending) >= 4:
                break
            if row["id"] in self._pending:
                continue
            message_id = str(row["target_ref"]).removeprefix("message/")
            message = messages.get(message_id)
            if message is None:
                continue
            recipient = message["recipient_agent_id"]
            if recipient in active_recipients:
                continue
            event_payload = json.loads(row["payload_json"])
            correlation = event_payload.get("correlation") or {}
            subject = message.get("subject_ref", "")
            future = self._executor.submit(self._deliver, message_id, recipient, {
                "command_id": row["command_id"], "actor_id": row["actor_ref"],
                "task_id": correlation.get("task_id") or (subject.split("/", 1)[1] if subject.startswith("task/") else None),
                "attempt_id": correlation.get("attempt_id"),
            }, event_payload.get("traceparent"))
            self._pending[row["id"]] = (recipient, future)
            active_recipients.add(recipient)
            scheduled += 1
        return scheduled

    def _deliver(self, message_id: str, recipient: str, correlation: dict[str, Any], parent: str | None) -> dict[str, Any]:
        attrs = {**correlation, "message_id": message_id, "agent_id": recipient,
                 "project_id": self.database.project_id, "trigger_source": "daemon_delivery"}
        with self.telemetry.activate(parent), self.telemetry.span("outbox.deliver", attrs) as span:
            result = self.dispatcher.on_delivery(message_id=message_id, recipient_agent_id=recipient,
                                                project_id=self.database.project_id, **correlation)
            self.telemetry.annotate(span, {"wake_attempt_id": result.get("wake_attempt_id")})
            self.telemetry.outcome(span, result["state"], result.get("error_code"))
            return result
