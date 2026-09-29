"""A2A delivery to host-wake orchestration.

This is intentionally a delivery adapter, not a second task state machine.
The durable MessageStore remains authoritative; failed wake attempts leave the
message available through the normal inbox pull path.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tsunagou.hostwake.port import HostWakePort, HostWakeRequest, WakeAttempt
from tsunagou.platform.telemetry import active_telemetry
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id
from tsunagou.shared_kernel.time import format_timestamp, now_ms, parse_timestamp


class WakeDispatcher:
    def __init__(
        self, provider: HostWakePort, *, attempts_path: str | Path | None = None,
        diagnostics_path: str | Path | None = None,
    ) -> None:
        self.provider = provider
        self.attempts_path = Path(attempts_path) if attempts_path else None
        self.diagnostics_path = Path(diagnostics_path) if diagnostics_path else None
        self._lock = threading.RLock()
        self.attempts: dict[str, dict[str, Any]] = {}
        self.diagnostic_events: list[dict[str, Any]] = []
        self._watchers: dict[str, threading.Thread] = {}
        self._recipient_locks: dict[str, threading.RLock] = {}
        # Bound by HostDeliveryWorker to committed, recipient-scoped deliveries.
        self.deliveries_acked: Callable[[str, tuple[str, ...]], bool] | None = None
        self._stop = threading.Event()
        self._load()
        self._load_diagnostics()
        self._mark_inflight_after_restart()

    def on_delivery(
        self, *, message_id: str, recipient_agent_id: str, project_id: str | None,
        callback_status: str | None = None,
        command_id: str | None = None, task_id: str | None = None,
        attempt_id: str | None = None, actor_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist dispatch identity before RPC; serialize only this recipient."""
        key = self._key(recipient_agent_id, message_id)
        with self._lock:
            recipient_lock = self._recipient_locks.setdefault(recipient_agent_id, threading.RLock())
        with recipient_lock:
            already_acked = (self.deliveries_acked(recipient_agent_id, (message_id,))
                             if self.deliveries_acked is not None else False)
            with self._lock:
                prior = self.attempts.get(key)
                stored = getattr(self.provider, "store", None)
                binding_item = stored.get(recipient_agent_id) if stored is not None else None
                native = binding_item is not None and binding_item[0].provider == "codex_desktop_app"
                retry = prior is not None and (
                    prior.get("error_code") == "host_wake_process_restarted" and not native
                    or prior.get("error_code") in {"host_binding_not_found", "host_binding_not_ready"}
                    and binding_item is not None and binding_item[0].status == "ready"
                )
                if prior is not None and not retry:
                    self._ensure_watcher(key, prior)
                    return dict(prior)
                history = list((prior or {}).get("previous_attempts", []))
                if prior is not None:
                    history.append({k: v for k, v in prior.items() if k != "previous_attempts"})
                business_attempt_id = attempt_id
                attempt_id = f"wake:{new_id()}"
                base: dict[str, Any] = {
                    "wake_attempt_id": attempt_id, "agent_id": recipient_agent_id,
                    "message_id": message_id, "project_id": project_id, "state": "starting",
                    "evidence": [], "updated_at": format_timestamp(now_ms()),
                    "previous_attempts": history,
                    "command_id": command_id, "task_id": task_id,
                    "attempt_id": business_attempt_id, "actor_id": actor_id,
                    "trigger_source": "daemon_delivery",
                }
                self._append_diagnostic("wake_requested", **self._correlation(base), occurred_at=base["updated_at"])
                if callback_status is not None:
                    base["evidence"].append(self._callback_evidence(
                        attempt_id=attempt_id, agent_id=recipient_agent_id,
                        message_id=message_id, callback_status=callback_status,
                    ))
                if already_acked:
                    return self._complete_consumed(key, base)
                if binding_item is None or binding_item[0].status != "ready":
                    base.update(state="failed", error_code="host_binding_not_found" if binding_item is None else "host_binding_not_ready")
                    self._update(key, base)
                    return dict(base)
                binding = binding_item[0]
                # Messages already waiting for the same idle opportunity share
                # one pull notification. New messages during a running turn
                # wait for its end, as that turn may already have read its inbox.
                queued = next(((k, v) for k, v in self.attempts.items()
                               if native and v.get("agent_id") == recipient_agent_id
                               and v.get("state") == "queued" and not v.get("coalesced_into")), None)
                if queued is not None:
                    batch_key, batch = queued
                    base.update(state="queued", wake_attempt_id=batch["wake_attempt_id"], coalesced_into=batch_key)
                    self._update(key, base)
                    return dict(base)
                base["binding_revision"] = binding.binding_revision
                self._update(key, base)
                request = self._request(base, binding)
            # The Desktop can take seconds to answer. Never keep the global
            # dispatcher lock, database lock or another recipient waiting here.
            try:
                with active_telemetry().span("host.wake", self._correlation(base)) as span:
                    attempt = self.provider.wake(request)
                    active_telemetry().outcome(span, attempt.state, attempt.error_code)
            except Exception as exc:
                attempt = WakeAttempt(attempt_id, recipient_agent_id, message_id, "failed",
                                      error_code=getattr(exc, "code", "host_provider_failed"),
                                      error_message="Host provider failed to dispatch the notification")
            with self._lock:
                current = self.attempts.get(key)
                if self._stop.is_set() or current is None or current.get("wake_attempt_id") != attempt_id:
                    return dict(current or base)
                result = {**current, **self._serialize(attempt)}
                result["evidence"] = self._merge_evidence(current.get("evidence"), result.get("evidence"))
                self._update(key, result)
                self._ensure_watcher(key, result)
                return dict(result)

    @staticmethod
    def _request(item: dict[str, Any], binding: Any) -> HostWakeRequest:
        return HostWakeRequest(
            wake_attempt_id=item["wake_attempt_id"], agent_id=item["agent_id"],
            message_id=item["message_id"], project_id=item.get("project_id"), binding=binding,
            cwd_digest=binding.cwd_digest, scope_digest=binding.scope_digest,
            policy_digest=binding.policy_digest, connection_epoch=binding.connection_epoch,
        )

    def _update(self, key: str, result: dict[str, Any]) -> None:
        """Caller holds the short persistence lock; all terminal paths log."""
        previous = self.attempts.get(key) or {}
        self.attempts[key] = result
        self._record_evidence(result)
        if (result.get("state"), result.get("error_code")) != (previous.get("state"), previous.get("error_code")):
            result["updated_at"] = format_timestamp(now_ms())
            self._append_diagnostic(
                f"wake_{result['state']}", **self._correlation(result),
                occurred_at=result["updated_at"], error_code=result.get("error_code"),
                details={"completion_reason": result.get("completion_reason")},
                transition=True,
            )
        for alias_key, alias in list(self.attempts.items()):
            if alias.get("coalesced_into") == key:
                self._update(alias_key, {
                    **alias, "state": result["state"], "turn_id_digest": result.get("turn_id_digest"),
                    "error_code": result.get("error_code"), "updated_at": result.get("updated_at"),
                    "completion_reason": result.get("completion_reason"),
                })
        if result != previous:
            self._save()

    def _complete_consumed(self, key: str, item: dict[str, Any]) -> dict[str, Any]:
        """Complete only the notification lifecycle, not an invented host turn."""
        observed = format_timestamp(now_ms())
        reason = "messages_already_acked"
        result = {**item, "state": "completed", "completion_reason": reason,
                  "turn_id_digest": None, "error_code": None, "error_message": None,
                  "updated_at": observed}
        result["evidence"] = self._merge_evidence(item.get("evidence"), [{
            "kind": "wake_skipped", "wake_attempt_id": item["wake_attempt_id"],
            "agent_id": item["agent_id"], "message_id": item["message_id"], "status": "observed",
            "observed_at": observed,
            "evidence_digest": canonical_digest({"wake_attempt_id": item["wake_attempt_id"], "completion_reason": reason}),
            "details": {"completion_reason": reason, "trigger_source": "daemon_delivery"},
        }])
        self._update(key, result)
        return dict(result)

    def _skip_consumed_batch(self, key: str, attempt_id: str) -> bool:
        """Caller serializes the recipient; database reads never hold _lock."""
        if self.deliveries_acked is None:
            return False
        with self._lock:
            item = self.attempts.get(key)
            if item is None or item.get("state") != "queued" or item.get("wake_attempt_id") != attempt_id:
                return False
            recipient = str(item["agent_id"])
            message_ids = tuple(str(value["message_id"]) for batch_key, value in self.attempts.items()
                                if batch_key == key or value.get("coalesced_into") == key)
        if not self.deliveries_acked(recipient, message_ids):
            return False
        with self._lock:
            current = self.attempts.get(key)
            if current is None or current.get("state") != "queued" or current.get("wake_attempt_id") != attempt_id:
                return False
            self._complete_consumed(key, current)
        return True

    def _ensure_watcher(self, key: str, prior: dict[str, Any]) -> None:
        if prior.get("coalesced_into") or self._stop.is_set():
            return
        if prior.get("state") not in {"queued", "starting", "running", "unknown"}:
            return
        item = self.provider.store.get(str(prior.get("agent_id"))) if hasattr(self.provider, "store") else None
        if prior.get("state") == "unknown" and (item is None or item[0].provider != "codex_desktop_app"):
            return
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
            while not self._stop.wait(0.5):
                with self._lock:
                    prior = self.attempts.get(key)
                if prior is None or prior.get("state") not in {"queued", "starting", "running", "unknown"}:
                    return
                try:
                    with self._lock:
                        recipient_lock = self._recipient_locks.setdefault(str(prior["agent_id"]), threading.RLock())
                    with recipient_lock:
                        if self._skip_consumed_batch(key, attempt_id):
                            return
                        updated = poll(attempt_id)
                        if updated is None:
                            self._mark_unknown(key, attempt_id, "host_wake_state_lost")
                            return
                        serialized = self._serialize(updated)
                        serialized["project_id"] = prior.get("project_id")
                        with self._lock:
                            if self._stop.is_set() or (self.attempts.get(key) or {}).get("wake_attempt_id") != attempt_id:
                                return
                            prior_evidence = (self.attempts.get(key) or {}).get("evidence", [])
                            serialized["evidence"] = self._merge_evidence(prior_evidence, serialized.get("evidence", []))
                            self._update(key, {**prior, **serialized})
                except Exception:
                    self._mark_unknown(key, attempt_id, "host_wake_state_lost")
                    return
                if updated.state in {"completed", "failed"}:
                    return
                if updated.state == "unknown" and self._stop.wait(4.5):
                    return
        finally:
            with self._lock:
                self._watchers.pop(watcher_key, None)

    def stop(self) -> None:
        self._stop.set()

    def resume_pending(self) -> None:
        """Resume persisted observations without sending an ambiguous wake twice."""
        with self._lock:
            for key, prior in self.attempts.items():
                if prior.get("coalesced_into") or prior.get("state") not in {"queued", "starting", "running", "unknown"}:
                    continue
                item = self.provider.store.get(str(prior.get("agent_id"))) if hasattr(self.provider, "store") else None
                if item is None or item[0].provider != "codex_desktop_app":
                    continue
                restore = getattr(self.provider, "restore_attempt", None)
                if callable(restore):
                    restore(self._request(prior, item[0]), str(prior["state"]))
                    self._ensure_watcher(key, prior)

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
                    "observed_at": format_timestamp(now_ms()),
                })
                self._record_evidence(item, only_kinds={"agent_presented"})
                self._save()
            return dict(item)

    def _load(self) -> None:
        if self.attempts_path is None or not self.attempts_path.is_file():
            return
        raw = json.loads(self.attempts_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            self.attempts = {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}

    def _load_diagnostics(self) -> None:
        if self.diagnostics_path is None or not self.diagnostics_path.is_file():
            return
        try:
            raw = json.loads(self.diagnostics_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, list):
            # Reading an earlier journal never manufactures a missing source
            # time or rewrites the stored evidence. The original run survives.
            for item in raw:
                if not isinstance(item, dict):
                    continue
                value = {"occurred_at": None, "recorded_at": None, "actor_id": None,
                         "command_id": None, "task_id": None, "attempt_id": None,
                         "trigger_source": "unknown", "error_code": None, **item}
                for name in ("occurred_at", "recorded_at", "observed_at"):
                    try:
                        value[name] = format_timestamp(parse_timestamp(value.get(name)))
                    except (ValueError, OverflowError):
                        value[name] = None
                self.diagnostic_events.append(value)

    def diagnostics(self, *, project_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(item) for item in self.diagnostic_events
                if project_id is None or item.get("project_id") == project_id
            ]

    def _mark_inflight_after_restart(self) -> None:
        changed = False
        for key, old in list(self.attempts.items()):
            item = dict(old)
            if item.get("state") in {"starting", "running"}:
                item["state"] = "unknown"
                item["error_code"] = "host_wake_process_restarted"
                item["error_message"] = "daemon restarted; original host turn must be inspected"
                self._update(key, item)
                changed = True
        if changed:
            self._save()

    def _mark_unknown(self, key: str, attempt_id: str, error_code: str) -> None:
        with self._lock:
            item = self.attempts.get(key)
            if item is None or item.get("wake_attempt_id") != attempt_id:
                return
            item = dict(item)
            item["state"] = "unknown"
            item["error_code"] = error_code
            item["error_message"] = "host wake state is no longer observable"
            self._update(key, item)

    def _record_evidence(self, item: dict[str, Any], *, only_kinds: set[str] | None = None) -> None:
        for evidence in item.get("evidence", []):
            if not isinstance(evidence, dict):
                continue
            kind = evidence.get("kind")
            if not isinstance(kind, str) or (only_kinds is not None and kind not in only_kinds):
                continue
            details = evidence.get("details") or {}
            occurred = evidence.get("observed_at")
            if kind in {"turn_started", "turn_completed", "wake_failed"}:
                source = details.get("host_started_at" if kind == "turn_started" else "host_completed_at")
                occurred = format_timestamp(source * 1000) if type(source) is int else None
            correlation = self._correlation(item)
            # Presentation is an inbox observation, not proof of who initiated
            # its host turn. Never upgrade a failed automatic wake from an ACK.
            correlation["trigger_source"] = details.get("trigger_source", "unknown")
            self._append_diagnostic(
                kind, **correlation,
                evidence_digest=evidence.get("evidence_digest"),
                occurred_at=occurred, observed_at=evidence.get("observed_at"), details=details,
            )

    @staticmethod
    def _correlation(item: dict[str, Any]) -> dict[str, Any]:
        return {key: item.get(key) for key in (
            "project_id", "actor_id", "agent_id", "command_id", "task_id", "attempt_id",
            "message_id", "wake_attempt_id", "trigger_source",
        )}

    def record_command_failure(self, *, project_id: str | None, actor_id: str | None,
                               command_id: str | None, command_kind: str, error_code: str = "command_rejected") -> None:
        with self._lock:
            self._append_diagnostic(
                "command_rejected", project_id=project_id, actor_id=actor_id,
                command_id=command_id, agent_id=actor_id, message_id=None, wake_attempt_id=None,
                error_code=error_code if re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", error_code) else "command_rejected",
                occurred_at=format_timestamp(now_ms()),
                details={"command_kind": command_kind}, transition=True,
            )

    def _append_diagnostic(
        self, kind: str, *, project_id: Any, agent_id: Any, message_id: Any,
        wake_attempt_id: Any, evidence_digest: Any = None, observed_at: Any = None,
        details: dict[str, Any] | None = None,
        actor_id: Any = None, command_id: Any = None, task_id: Any = None, attempt_id: Any = None,
        occurred_at: Any = None, trigger_source: Any = "unknown", error_code: Any = None,
        transition: bool = False,
    ) -> None:
        if not kind:
            return
        key = (kind, wake_attempt_id, message_id, evidence_digest)
        if not transition and any(
            (item.get("kind"), item.get("wake_attempt_id"), item.get("message_id"), item.get("evidence_digest")) == key
            for item in self.diagnostic_events
        ):
            return
        def timestamp(value: Any) -> str | None:
            try:
                return format_timestamp(parse_timestamp(value)) if isinstance(value, str) else None
            except (ValueError, OverflowError):
                return None

        details = details or {}
        trigger_source = trigger_source if trigger_source in {
            "daemon_delivery", "user_followup", "developer_followup", "unknown",
        } else "unknown"
        event = {
            "diagnostic_id": f"diagnostic:{new_id()}", "kind": kind,
            "project_id": project_id if isinstance(project_id, str) else None,
            "agent_id": agent_id, "message_id": message_id,
            "actor_id": actor_id, "command_id": command_id, "task_id": task_id, "attempt_id": attempt_id,
            "wake_attempt_id": wake_attempt_id if isinstance(wake_attempt_id, str) else None,
            "evidence_digest": evidence_digest if isinstance(evidence_digest, str) else None,
            "occurred_at": timestamp(occurred_at), "recorded_at": format_timestamp(now_ms()),
            "observed_at": timestamp(observed_at), "trigger_source": trigger_source,
            "error_code": error_code if isinstance(error_code, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", error_code) else None,
            "details": {key: value for key, value in details.items()
                        if isinstance(key, str) and key in {
                            "error_code", "callback_status", "evidence_kind", "connection_epoch",
                            "thread_id_digest", "turn_id_digest",
                            "trigger_source", "host_started_at", "host_completed_at", "command_kind",
                            "completion_reason",
                        } and (value is None or type(value) is int or isinstance(value, str)
                               and re.fullmatch(r"[a-zA-Z0-9_:./-]{1,160}", value))},
        }
        self.diagnostic_events.append(event)
        self._save_diagnostics()

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

    def _save_diagnostics(self) -> None:
        if self.diagnostics_path is None:
            return
        self.diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.diagnostics_path.name}.", dir=self.diagnostics_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.diagnostic_events, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.diagnostics_path)
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
            "error_message": "Host wake failed; inspect the error code" if attempt.error_code else None,
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
