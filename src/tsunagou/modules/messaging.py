"""Durable pull-first inboxes, delivery leases, and response obligations."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id

MAX_SUMMARY = 4_096
MAX_PAYLOAD_BYTES = 256 * 1024


def _now() -> float:
    return time.time()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


@dataclass(frozen=True, slots=True)
class Message:
    message_id: str
    command_id: str
    sender_agent_id: str
    recipient_agent_id: str
    kind: str
    subject_ref: str
    summary: str
    payload: dict[str, Any]
    payload_digest: str
    routing_snapshot_id: str
    created_at: float
    in_reply_to: str | None = None


@dataclass(slots=True)
class Delivery:
    message_id: str
    recipient_agent_id: str
    priority: int
    status: str = "pending"
    attempts: int = 0
    lease_until: float | None = None
    available_at: float = field(default_factory=_now)
    acked_at: float | None = None
    presented_at: float | None = None
    presentation_evidence: dict[str, Any] | None = None


@dataclass(slots=True)
class ResponseObligation:
    obligation_id: str
    message_id: str
    recipient_agent_id: str
    contract: dict[str, Any]
    status: str = "open"
    response_message_id: str | None = None
    closed_at: float | None = None


class MessageStore:
    def __init__(self, state_path: str | Path | None = None) -> None:
        self.state_path = Path(state_path) if state_path else None
        self._lock = threading.RLock()
        self.messages: dict[str, Message] = {}
        self.deliveries: dict[str, Delivery] = {}
        self.obligations: dict[str, ResponseObligation] = {}
        self.command_index: dict[str, str] = {}
        self.push_failures: dict[str, int] = {}
        self.high_watermark = 0
        self._load()

    def _load(self) -> None:
        if self.state_path is None or not self.state_path.is_file():
            return
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.messages = {key: Message(**value) for key, value in raw.get("messages", {}).items()}
        self.deliveries = {key: Delivery(**value) for key, value in raw.get("deliveries", {}).items()}
        self.obligations = {key: ResponseObligation(**value) for key, value in raw.get("obligations", {}).items()}
        self.command_index = raw.get("command_index", {})
        self.push_failures = raw.get("push_failures", {})
        self.high_watermark = raw.get("high_watermark", len(self.messages))

    def _save(self) -> None:
        if self.state_path is None:
            return
        _write(self.state_path, {
            "messages": {key: asdict(value) for key, value in self.messages.items()},
            "deliveries": {key: asdict(value) for key, value in self.deliveries.items()},
            "obligations": {key: asdict(value) for key, value in self.obligations.items()},
            "command_index": self.command_index,
            "push_failures": self.push_failures,
            "high_watermark": self.high_watermark,
        })

    def send(
        self,
        *,
        command_id: str,
        sender_agent_id: str,
        recipient_agent_id: str,
        kind: str,
        subject_ref: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        response_contract: dict[str, Any] | None = None,
        in_reply_to: str | None = None,
    ) -> Message:
        if not summary or len(summary) > MAX_SUMMARY:
            raise ValueError("summary_limit_exceeded")
        payload = payload or {}
        if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload_limit_exceeded")
        payload_digest = canonical_digest(payload)
        with self._lock:
            existing = self.command_index.get(command_id)
            if existing is not None:
                prior = self.messages[existing]
                if (
                    prior.sender_agent_id == sender_agent_id
                    and prior.recipient_agent_id == recipient_agent_id
                    and prior.kind == kind
                    and prior.subject_ref == subject_ref
                    and prior.summary == summary
                    and prior.payload_digest == payload_digest
                ):
                    return prior
                raise ValueError("command_id_conflict")
            message = Message(
                new_id(), command_id, sender_agent_id, recipient_agent_id, kind, subject_ref,
                summary, payload, payload_digest, new_id(), _now(), in_reply_to,
            )
            self.messages[message.message_id] = message
            self.deliveries[message.message_id] = Delivery(message.message_id, recipient_agent_id, priority)
            self.command_index[command_id] = message.message_id
            self.high_watermark += 1
            if response_contract is not None:
                required = response_contract.get("required", True)
                if required:
                    obligation = ResponseObligation(new_id(), message.message_id, recipient_agent_id, response_contract)
                    self.obligations[obligation.obligation_id] = obligation
            self._save()
            return message

    def fetch(self, recipient_agent_id: str, *, limit: int = 50, now: float | None = None) -> list[Message]:
        if limit <= 0 or limit > 200:
            raise ValueError("invalid_batch_limit")
        now = _now() if now is None else now
        with self._lock:
            candidates = [
                delivery for delivery in self.deliveries.values()
                if delivery.recipient_agent_id == recipient_agent_id
                and delivery.available_at <= now
                and (delivery.status == "pending" or (delivery.status == "leased" and (delivery.lease_until or 0) <= now))
            ]
            candidates.sort(key=lambda item: (-item.priority, item.available_at, item.message_id))
            selected = candidates[:limit]
            for delivery in selected:
                delivery.status = "leased"
                delivery.attempts += 1
                delivery.lease_until = now + 30
            self._save()
            return [self.messages[item.message_id] for item in selected]

    def ack(self, recipient_agent_id: str, message_id: str) -> None:
        with self._lock:
            delivery = self._delivery_for(recipient_agent_id, message_id)
            delivery.status = "acked"
            delivery.acked_at = _now()
            delivery.lease_until = None
            self._save()

    def present(self, recipient_agent_id: str, message_id: str, evidence: dict[str, Any]) -> None:
        if not evidence:
            raise ValueError("presentation_evidence_required")
        with self._lock:
            delivery = self._delivery_for(recipient_agent_id, message_id)
            delivery.presented_at = _now()
            delivery.presentation_evidence = evidence
            self._save()

    def defer(self, recipient_agent_id: str, message_id: str, delay_seconds: float = 30) -> None:
        with self._lock:
            delivery = self._delivery_for(recipient_agent_id, message_id)
            delivery.status = "pending"
            delivery.lease_until = None
            delivery.available_at = _now() + max(0, delay_seconds)
            self._save()

    def respond(self, recipient_agent_id: str, obligation_id: str, response_message_id: str) -> None:
        with self._lock:
            obligation = self.obligations.get(obligation_id)
            if obligation is None or obligation.recipient_agent_id != recipient_agent_id:
                raise PermissionError("obligation_recipient_mismatch")
            if obligation.status != "open":
                raise ValueError("obligation_already_closed")
            response = self.messages.get(response_message_id)
            if response is None:
                raise ValueError("response_message_not_found")
            if response.sender_agent_id != recipient_agent_id:
                raise PermissionError("response_sender_mismatch")
            if response.in_reply_to != obligation.message_id:
                raise ValueError("response_not_linked_to_obligation")
            obligation.status = "responded"
            obligation.response_message_id = response_message_id
            obligation.closed_at = _now()
            self._save()

    def waive(self, actor_agent_id: str, obligation_id: str, *, is_main: bool = False) -> None:
        with self._lock:
            obligation = self.obligations.get(obligation_id)
            if obligation is None or (obligation.recipient_agent_id != actor_agent_id and not is_main):
                raise PermissionError("obligation_actor_denied")
            obligation.status = "waived"
            obligation.closed_at = _now()
            self._save()

    def supersede(self, obligation_id: str, replacement_id: str) -> None:
        with self._lock:
            obligation = self.obligations[obligation_id]
            obligation.status = "superseded"
            obligation.response_message_id = replacement_id
            obligation.closed_at = _now()
            self._save()

    def mark_push_failure(self, recipient_agent_id: str) -> bool:
        with self._lock:
            count = self.push_failures.get(recipient_agent_id, 0) + 1
            self.push_failures[recipient_agent_id] = count
            self._save()
            return count >= 3

    def push_suppressed(self, recipient_agent_id: str) -> bool:
        return self.push_failures.get(recipient_agent_id, 0) >= 3

    def sync(self, recipient_agent_id: str, *, after_message_id: str | None = None) -> list[Message]:
        with self._lock:
            messages = [
                message for message in self.messages.values()
                if message.recipient_agent_id == recipient_agent_id
            ]
            messages.sort(key=lambda item: (item.created_at, item.message_id))
            if after_message_id is None:
                return messages
            ids = [item.message_id for item in messages]
            try:
                index = ids.index(after_message_id)
            except ValueError:
                return messages
            return messages[index + 1 :]

    def _delivery_for(self, recipient_agent_id: str, message_id: str) -> Delivery:
        message = self.messages.get(message_id)
        delivery = self.deliveries.get(message_id)
        if message is None or delivery is None or delivery.recipient_agent_id != recipient_agent_id:
            raise PermissionError("inbox_access_denied")
        return delivery

