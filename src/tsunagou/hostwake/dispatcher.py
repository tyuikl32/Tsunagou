"""A2A delivery to host-wake orchestration.

This is intentionally a delivery adapter, not a second task state machine.
The durable MessageStore remains authoritative; failed wake attempts leave the
message available through the normal inbox pull path.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from tsunagou.hostwake.port import HostWakePort, HostWakeRequest, WakeAttempt
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id


class WakeDispatcher:
    def __init__(self, provider: HostWakePort, *, attempts_path: str | Path | None = None) -> None:
        self.provider = provider
        self.attempts_path = Path(attempts_path) if attempts_path else None
        self._lock = threading.RLock()
        self.attempts: dict[str, dict[str, Any]] = {}
        self._watchers: dict[str, threading.Thread] = {}
        self._load()
        self._mark_inflight_after_restart()

    def on_delivery(
        self,
        *,
        message_id: str,
        recipient_agent_id: str,
        project_id: str | None,
        callback_status: str | None = None,
    ) -> dict[str, Any]:
        """Start or replay exactly one host wake for a durable delivery."""
        key = self._key(recipient_agent_id, message_id)
        with self._lock:
            prior = self.attempts.get(key)
            if prior is not None:
                if prior.get("state") == "unknown" and prior.get("error_code") == "host_wake_process_restarted":
                    # The old provider process is gone.  A new delivery may
                    # retry the pull prompt once; while it is running the
                    # normal idempotency key still prevents a second turn.
                    self.attempts.pop(key, None)
                    self._save()
                    prior = None
                else:
                    if prior.get("state") == "running":
                        self._ensure_watcher(key, prior)
                    return dict(prior)
            stored = getattr(self.provider, "store", None)
            binding_item = stored.get(recipient_agent_id) if stored is not None else None
            if binding_item is None:
                result = {
                    "wake_attempt_id": f"wake:{new_id()}", "state": "failed",
                    "agent_id": recipient_agent_id, "message_id": message_id,
                    "error_code": "host_binding_not_found",
                }
                self.attempts[key] = result
                self._save()
                return dict(result)
            binding, _record = binding_item
            if binding.status != "ready":
                result = {
                    "wake_attempt_id": f"wake:{new_id()}", "state": "unknown",
                    "agent_id": recipient_agent_id, "message_id": message_id,
                    "error_code": "host_binding_not_ready",
                }
                self.attempts[key] = result
                self._save()
                return dict(result)
            attempt_id = f"wake:{new_id()}"
            request = HostWakeRequest(
                wake_attempt_id=attempt_id,
                agent_id=recipient_agent_id,
                message_id=message_id,
                project_id=project_id,
                binding=binding,
                cwd_digest=binding.cwd_digest,
                scope_digest=binding.scope_digest,
                policy_digest=binding.policy_digest,
                connection_epoch=binding.connection_epoch,
            )
            attempt = self.provider.wake(request)
            result = self._serialize(attempt)
            if callback_status is not None:
                cast(list[dict[str, Any]], result["evidence"]).insert(0, self._callback_evidence(
                    attempt_id=attempt_id, agent_id=recipient_agent_id,
                    message_id=message_id, callback_status=callback_status,
                ))
            self.attempts[key] = result
            self._save()
            if attempt.state == "running":
                self._ensure_watcher(key, result)
            return dict(result)

    def _ensure_watcher(self, key: str, prior: dict[str, Any]) -> None:
        watcher_key = f"watch:{key}"
        with self._lock:
            thread = self._watchers.get(watcher_key)
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._watch_attempt,
                args=(key, str(prior.get("wake_attempt_id", "")), watcher_key),
                daemon=True,
                name="tsunagou-host-wake",
            )
            self._watchers[watcher_key] = thread
            thread.start()

    def _watch_attempt(self, key: str, attempt_id: str, watcher_key: str) -> None:
        poll = getattr(self.provider, "poll", None)
        if not callable(poll) or not attempt_id:
            return
        try:
            for _ in range(1200):
                time.sleep(0.25)
                with self._lock:
                    prior = self.attempts.get(key)
                if prior is None or prior.get("state") != "running":
                    return
                try:
                    updated = poll(attempt_id)
                except Exception:
                    self._mark_unknown(key, attempt_id, "host_wake_state_lost")
                    return
                if updated is None:
                    self._mark_unknown(key, attempt_id, "host_wake_state_lost")
                    return
                serialized = self._serialize(updated)
                with self._lock:
                    prior_evidence = (self.attempts.get(key) or {}).get("evidence", [])
                    serialized["evidence"] = self._merge_evidence(prior_evidence, serialized.get("evidence", []))
                    self.attempts[key] = serialized
                    self._save()
                if updated.state != "running":
                    return
        finally:
            with self._lock:
                self._watchers.pop(watcher_key, None)

    def status(self, *, message_id: str, recipient_agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self.attempts.get(self._key(recipient_agent_id, message_id))
            return dict(item) if item is not None else None

    def record_presented(
        self,
        *,
        agent_id: str,
        message_id: str,
        evidence_digest: str | None,
        evidence_kind: str | None,
    ) -> dict[str, Any] | None:
        """Attach Agent presentation evidence after the inbox command commits."""
        with self._lock:
            key = self._key(agent_id, message_id)
            item = self.attempts.get(key)
            if item is None:
                return None
            evidence = item.setdefault("evidence", [])
            if not any(entry.get("kind") == "agent_presented" for entry in evidence):
                evidence.append({
                    "kind": "agent_presented",
                    "wake_attempt_id": item.get("wake_attempt_id"),
                    "agent_id": agent_id,
                    "message_id": message_id,
                    "status": "observed",
                    "evidence_digest": canonical_digest({
                        "agent_id": agent_id, "message_id": message_id,
                        "evidence_digest": evidence_digest, "evidence_kind": evidence_kind,
                    }),
                    "details": {"evidence_kind": evidence_kind},
                })
                self._save()
            return dict(item)

    def _load(self) -> None:
        if self.attempts_path is None or not self.attempts_path.is_file():
            return
        raw = json.loads(self.attempts_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            self.attempts = {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}

    def _mark_inflight_after_restart(self) -> None:
        changed = False
        for item in self.attempts.values():
            if item.get("state") == "running":
                item["state"] = "unknown"
                item["error_code"] = "host_wake_process_restarted"
                item["error_message"] = "managed host wake process was recreated"
                changed = True
        if changed:
            self._save()

    def _mark_unknown(self, key: str, attempt_id: str, error_code: str) -> None:
        with self._lock:
            item = self.attempts.get(key)
            if item is None or item.get("wake_attempt_id") != attempt_id:
                return
            item["state"] = "unknown"
            item["error_code"] = error_code
            item["error_message"] = "managed host wake state is no longer observable"
            self._save()

    def _save(self) -> None:
        if self.attempts_path is None:
            return
        self.attempts_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.attempts_path.name}.", dir=self.attempts_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.attempts, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.attempts_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _key(agent_id: str, message_id: str) -> str:
        return f"{agent_id}:{message_id}"

    @staticmethod
    def _serialize(attempt: WakeAttempt) -> dict[str, Any]:
        return {
            "wake_attempt_id": attempt.wake_attempt_id,
            "agent_id": attempt.agent_id,
            "message_id": attempt.message_id,
            "state": attempt.state,
            "thread_id_digest": attempt.thread_id_digest,
            "turn_id_digest": attempt.turn_id_digest,
            "evidence": [asdict(item) for item in attempt.evidence],
            "error_code": attempt.error_code,
            "error_message": attempt.error_message,
            "updated_at": attempt.updated_at,
        }

    @staticmethod
    def _callback_evidence(
        *, attempt_id: str, agent_id: str, message_id: str, callback_status: str,
    ) -> dict[str, Any]:
        return {
            "kind": "callback_received",
            "wake_attempt_id": attempt_id,
            "agent_id": agent_id,
            "message_id": message_id,
            "status": "observed",
            "evidence_digest": canonical_digest({
                "attempt_id": attempt_id, "agent_id": agent_id,
                "message_id": message_id, "callback_status": callback_status,
            }),
            "details": {"callback_status": callback_status},
        }

    @staticmethod
    def _merge_evidence(
        prior: Any,
        current: Any,
    ) -> list[dict[str, Any]]:
        """Preserve presentation/callback evidence racing with event polling."""

        merged: list[dict[str, Any]] = []
        for source in (prior, current):
            if not isinstance(source, list):
                continue
            for entry in source:
                if not isinstance(entry, dict):
                    continue
                key = (entry.get("kind"), entry.get("evidence_digest"))
                if any((item.get("kind"), item.get("evidence_digest")) == key for item in merged):
                    continue
                merged.append(dict(entry))
        return merged
