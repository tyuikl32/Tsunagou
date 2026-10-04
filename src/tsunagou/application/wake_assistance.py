"""Authenticated, message-scoped manual host assistance; never a scheduler."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.messaging import MessageStore
from tsunagou.platform.private_files import write_private_bytes
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.time import format_timestamp, now_ms


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


class WakeAssistance:
    def __init__(
        self, *, authority: AuthorityService, messages: MessageStore, project_id: str,
        project_root: Path, state_dir: Path, database: Any = None, native: Any = None,
        runner: Callable[..., dict[str, Any]] | None = None,
        route_directories: dict[str, Path] | None = None,
        native_policy: Callable[[], bool] | None = None,
    ) -> None:
        self.authority, self.messages = authority, messages
        self.project_id, self.project_root = project_id, project_root.resolve()
        self.database, self.native, self.runner = database, native, runner
        self.native_policy = native_policy
        self.routes = route_directories or {
            host: Path.home() / ".tsunagou" / "hosts" / host for host in ("codex", "opencode", "deepseek")
        }
        self.path = state_dir / "host-assistance.json"
        self._lock = threading.RLock()
        self._recipient_locks: dict[str, threading.RLock] = {}
        self.records: dict[str, Any] = {}
        if self.path.exists():
            try:
                records = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(records, dict) or any(not isinstance(value, dict) for value in records.values()):
                    raise ValueError("invalid_journal")
                self.records = records
            except (OSError, ValueError) as exc:
                raise RuntimeError("host_assistance_journal_invalid") from exc
        # A process crash after dispatch cannot prove that no host turn started.
        for record in self.records.values():
            if isinstance(record, dict) and record.get("result") == "starting":
                record.update(result="unknown", state="unknown", error_code="wake_outcome_unknown")
        if native is not None:
            native.manual_delivery = self.native_fence

    def _authorize(self, context: dict[str, Any], capability: str = "message.send") -> None:
        with self._domain_lock():
            self._authorize_committed(context, capability)

    def _domain_lock(self) -> Any:
        return self.database.lock if self.database is not None else contextlib.nullcontext()

    def _authorize_committed(self, context: dict[str, Any], capability: str) -> None:
        session = self.authority.sessions.get(str(context.get("session_id") or ""))
        if (session is None or not session.active or session.agent_id != context.get("principal_id")
                or session.connection_epoch != context.get("connection_epoch")):
            raise PermissionError("stale_connection_epoch")
        grant = self.authority.find_grant(
            agent_id=session.agent_id, session_id=session.session_id, capability=capability,
        )
        if grant is None:
            raise PermissionError("capability_denied")
        self.authority.authorize(agent_id=session.agent_id, session_id=session.session_id,
                                 grant_id=grant.grant_id, capability=capability)

    def _identity(self, agent_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        with self._domain_lock():
            return self._identity_committed(agent_id)

    def _identity_committed(self, agent_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        public: dict[str, Any] = {"agent_id": agent_id, "host": "unknown", "version": None,
                                  "machine": "unknown", "identity_evidence": []}
        agent = self.authority.agents.get(agent_id)
        if agent is None or agent.status != "active":
            return public, None
        candidates: list[tuple[str, dict[str, Any]]] = []
        for host, directory in self.routes.items():
            for path in directory.glob("*.json"):
                route = _object(path)
                conversation = route.get("conversation_id")
                if (route.get("format_version") != 1 or route.get("project_id") != self.project_id
                        or not isinstance(conversation, str) or not conversation
                        or path.stem != hashlib.sha256(conversation.encode()).hexdigest()
                        or route.get("adapter", "codex") != host
                        or canonical_digest({"conversation_id": conversation}) != agent.conversation_digest):
                    continue
                root = route.get("project_root")
                session_file = route.get("session_file")
                if not isinstance(root, str) or Path(root).resolve() != self.project_root or not isinstance(session_file, str):
                    continue
                # Routes are private local installation records, never model-selected files.
                private = _object(Path(session_file))
                session = self.authority.sessions.get(str(private.get("session_id") or ""))
                token = private.get("secret_token")
                if (session is None or session.agent_id != agent_id or not session.active or session.status != "ready"
                        or private.get("agent_id") != agent_id
                        or session.connection_epoch != private.get("connection_epoch")
                        or session.conversation_digest != agent.conversation_digest
                        or not isinstance(token, str) or not self.authority.verify_token(session.session_id, token)):
                    continue
                candidates.append((host, route))
        if len(candidates) != 1:
            # A machine label is self-reported, never sufficient to claim local access.
            return public, None
        host, route = candidates[0]
        credential = _object(Path(route["session_file"]))
        public.update(host=host, machine="local", identity_evidence=[agent.conversation_digest, canonical_digest({
            "session_id": credential.get("session_id"), "connection_epoch": credential.get("connection_epoch"),
        })])
        return public, route

    def peers(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        with self._domain_lock():
            self._authorize(context, "coordination.read")
            return {"agents": [self._identity(agent.agent_id)[0] for agent in self.authority.agents.values()
                               if agent.status == "active"]}

    def candidates(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        with self._domain_lock():
            return self._candidates_committed(payload, context)

    def _candidates_committed(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        self._authorize(context)
        command_id = payload.get("source_command_id")
        if not isinstance(command_id, str) or not command_id.strip():
            raise ValueError("command_id_required")
        if self.database is not None:
            with self.database.lock, contextlib.closing(self.database._connect()) as conn:
                origin = conn.execute("SELECT 1 FROM commands WHERE project_id=? AND principal_id=? AND command_id=? LIMIT 1",
                                      (self.project_id, context["principal_id"], command_id)).fetchone()
            if origin is None:
                raise PermissionError("wake_message_access_denied")
        candidates = []
        for message in self.messages.messages.values():
            if (message.sender_agent_id != context["principal_id"]
                    or not (message.command_id == command_id or message.command_id.startswith(command_id + ":"))):
                continue
            required = any(item.message_id == message.message_id and item.contract.get("required", True)
                           for item in self.messages.obligations.values())
            if required or message.kind in {"task.assigned", "task.submitted"}:
                candidates.append({"message_id": message.message_id, "recipient_agent_id": message.recipient_agent_id,
                                   "kind": message.kind, "response_required": required})
        return {"messages": candidates}

    def _message(self, message_id: str, context: dict[str, Any]) -> Any:
        with self._domain_lock():
            return self._message_committed(message_id, context)

    def _message_committed(self, message_id: str, context: dict[str, Any]) -> Any:
        self._authorize(context)
        message = self.messages.messages.get(message_id)
        if message is None:
            raise PermissionError("wake_message_access_denied")
        allowed = message.sender_agent_id == context["principal_id"]
        if not allowed and message.sender_agent_id == "system" and self.database is not None:
            with self.database.lock, contextlib.closing(self.database._connect()) as conn:
                row = conn.execute(
                    "SELECT 1 FROM outbox o JOIN events e ON o.project_id=e.project_id AND o.event_seq=e.event_seq "
                    "WHERE o.project_id=? AND o.target_ref=? AND e.actor_ref=? LIMIT 1",
                    (self.project_id, f"message/{message_id}", context["principal_id"]),
                ).fetchone()
            allowed = row is not None
        if not allowed:
            raise PermissionError("wake_message_access_denied")
        return message

    def _save(self, message_id: str, value: dict[str, Any]) -> None:
        with self._lock:
            self.records[message_id] = value
            write_private_bytes(self.path, (json.dumps(self.records, ensure_ascii=False, sort_keys=True) + "\n").encode())

    def native_fence(self, message_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self.records.get(message_id)
            if not isinstance(record, dict):
                return None
            return {"state": "unknown" if record.get("result") in {"unknown", "starting"} else "completed",
                    "error_code": "manual_wake_recorded", "message_id": message_id,
                    "completion_reason": "manual_assistance_owns_delivery"}

    def _recipient_lock(self, recipient: str) -> Any:
        if self.native is not None:
            return self.native.recipient_lock(recipient)
        with self._lock:
            return self._recipient_locks.setdefault(recipient, threading.RLock())

    def _native_active(self, recipient: str) -> bool:
        if self.native is not None:
            with self.native._lock:
                if any(item.get("agent_id") == recipient and item.get("state") in {"starting", "queued", "running", "unknown"}
                       for item in self.native.attempts.values()):
                    return True
        return False

    def _native_pending(self, message_id: str) -> bool:
        if self.database is None:
            return False
        with self.database.lock, contextlib.closing(self.database._connect()) as conn:
            return conn.execute(
                "SELECT 1 FROM outbox WHERE project_id=? AND kind='host_wake' AND target_ref=? AND status='pending' LIMIT 1",
                (self.project_id, f"message/{message_id}"),
            ).fetchone() is not None

    def _native_status(self, base: dict[str, Any], message_id: str, recipient: str) -> None:
        """Expose only correlated execution facts, not provider internals or secrets."""
        with self._domain_lock():
            enabled = self.native_policy() if self.native_policy is not None else None
        attempt = self.native.status(message_id=message_id, recipient_agent_id=recipient) if self.native else None
        native: dict[str, Any] = {"enabled": enabled, "outbox_status": None, "attempt_count": None,
                                  "attempt_state": None, "error_code": None}
        if self.database is not None:
            with self.database.lock, contextlib.closing(self.database._connect()) as conn:
                row = conn.execute(
                    "SELECT status,attempt_count FROM outbox WHERE project_id=? AND kind='host_wake' "
                    "AND target_ref=? ORDER BY rowid DESC LIMIT 1",
                    (self.project_id, f"message/{message_id}"),
                ).fetchone()
            if row is not None:
                native.update(outbox_status=row[0], attempt_count=row[1])
        # An absent turn digest is absence of proof, not proof of no host execution.
        base["progress"]["host_turn_started"] = None
        if attempt is not None:
            native.update(attempt_state=attempt.get("state"), error_code=attempt.get("error_code"))
            base["error_code"] = attempt.get("error_code")
            proven = any(isinstance(item, dict) and item.get("kind") == "turn_started"
                         and item.get("message_id") == message_id for item in attempt.get("evidence", []))
            if proven and attempt.get("turn_id_digest") and not attempt.get("coalesced_into"):
                base["progress"]["host_turn_started"] = True
                base["evidence"] = [attempt["turn_id_digest"]]
        if enabled is False:
            base["error_code"] = "native_wake_disabled"
        base["native"] = native

    def status(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return self._run(payload, context, wake=False)

    def wake(self, payload: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return self._run(payload, context, wake=True)

    def _run(self, payload: dict[str, Any], context: dict[str, Any], *, wake: bool) -> dict[str, Any]:
        message_id = payload.get("message_id")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError("message_id_required")
        message = self._message(message_id, context)
        with self._recipient_lock(message.recipient_agent_id):
            # Identity/grants may have changed while another caller held this lock.
            with self._domain_lock():
                message = self._message(message_id, context)
                sender, sender_route = self._identity(context["principal_id"])
                target, target_route = self._identity(message.recipient_agent_id)
                delivery = copy.deepcopy(self.messages.deliveries.get(message_id))
                obligations = copy.deepcopy([item for item in self.messages.obligations.values() if item.message_id == message_id])
                replied = any(item.sender_agent_id == message.recipient_agent_id and item.in_reply_to == message_id
                              for item in self.messages.messages.values())
            base: dict[str, Any] = {
                "message_id": message_id, "sender": sender, "target": target, "lane": "unsupported",
                "state": "unknown", "can_queue": "unknown", "result": "unsupported", "error_code": None,
                "response_required": any(item.contract.get("required", True) for item in obligations),
                "progress": {"durably_received": True, "host_turn_started": False,
                             "presented": bool(delivery and delivery.presented_at is not None),
                             "business_response": replied or any(item.status == "responded" for item in obligations)},
                "entry": {"tool": "coordination__wake_status", "arguments": {"message_id": message_id}},
                "evidence": [], "observed_at": format_timestamp(now_ms()),
            }
            if sender_route is None or target_route is None:
                remote = "remote" in {sender["machine"], target["machine"]}
                base["error_code"] = "cross_machine_unsupported" if remote else "host_identity_unverified"
                return base
            if sender["host"] == target["host"] == "codex":
                base.update(lane="native", result="native_channel_only", error_code=None)
                self._native_status(base, message_id, message.recipient_agent_id)
                return base
            # A covered native lane retains its queued work. Never silently cancel it.
            if self._native_active(message.recipient_agent_id) or (target["host"] == "codex" and self._native_pending(message_id)):
                base.update(lane="native", result="pending", error_code="native_wake_pending")
                return base
            base["lane"] = "fallback"
            if base["progress"]["presented"] or (delivery and delivery.status == "acked") or base["progress"]["business_response"]:
                base.update(result="already_delivered", error_code=None)
                return base
            prior = self.records.get(message_id)
            if wake and prior is not None:
                base.update({key: prior[key] for key in ("state", "result", "error_code", "evidence") if key in prior})
                base["progress"]["host_turn_started"] = bool(prior.get("turn_started"))
                return base
            observed = self._host("status", target, target_route, message_id)
            for key in ("state", "can_queue", "result", "error_code", "evidence", "observed_at"):
                if key in observed:
                    base[key] = observed[key]
            target["version"] = observed.get("version")
            base["progress"]["host_turn_started"] = bool(observed.get("turn_started") and observed.get("request_associated"))
            if prior is not None:
                # Fresh host facts do not erase a previous possibly accepted
                # request. Advertise inspection only, never an unusable retry.
                base["prior_result"] = prior.get("result", "unknown")
                base["retry_allowed"] = False
                base["error_code"] = base.get("error_code") or "wake_already_attempted"
                return base
            if observed.get("request_associated") and observed.get("turn_started") and observed.get("state") == "running":
                base.update(result="same_request_running", error_code=None)
                return base
            if observed.get("request_associated") or observed.get("result") != "observed" or observed.get("error_code"):
                return base
            if observed.get("state") != "idle":
                if observed.get("state") != "running" or observed.get("can_queue") is not True:
                    return base
            base["entry"] = {"tool": "coordination__wake", "arguments": {"message_id": message_id}}
            if not wake:
                return base
            with self._domain_lock():
                self._message(message_id, context)
                current_sender, _ = self._identity(context["principal_id"])
                current_target, _ = self._identity(message.recipient_agent_id)
                if (current_sender["identity_evidence"] != sender["identity_evidence"]
                        or current_target["identity_evidence"] != target["identity_evidence"]):
                    base.update(result="failed", error_code="host_identity_changed")
                    return base
                latest_delivery = self.messages.deliveries.get(message_id)
                if latest_delivery is not None and (latest_delivery.presented_at is not None or latest_delivery.status == "acked"):
                    base.update(result="already_delivered", error_code=None)
                    base["progress"]["presented"] = latest_delivery.presented_at is not None
                    return base
                # Fence native delivery and retries durably BEFORE any host side effect.
                self._save(message_id, {"result": "starting", "state": "unknown", "observed_at": format_timestamp(now_ms())})
            if self.database is not None:
                # The current native providers cover Codex only. Retire the
                # unsupported intent while holding its recipient fence; a future
                # already scheduled by the outbox sees manual_delivery above.
                with self.database.transaction("manual-wake-fence") as uow:
                    uow.conn.execute(
                        "UPDATE outbox SET status='done' WHERE project_id=? AND kind='host_wake' AND target_ref=? AND status='pending'",
                        (self.project_id, f"message/{message_id}"),
                    )
            outcome = self._host("wake", target, target_route, message_id)
            self._save(message_id, outcome)
            for key in ("state", "can_queue", "result", "error_code", "evidence", "observed_at"):
                if key in outcome:
                    base[key] = outcome[key]
            base["progress"]["host_turn_started"] = bool(outcome.get("turn_started") and outcome.get("request_associated"))
            base["entry"] = {"tool": "coordination__wake_status", "arguments": {"message_id": message_id}}
            return base

    def _host(self, action: str, target: dict[str, Any], route: dict[str, Any], message_id: str) -> dict[str, Any]:
        if self.runner is None:
            return {"state": "unknown", "result": "unsupported", "error_code": "host_runner_unavailable"}
        try:
            return self.runner(action, adapter=target["host"], conversation_id=route["conversation_id"],
                               project_root=str(self.project_root), message_id=message_id)
        except Exception:
            return {"state": "unknown", "result": "unknown" if action == "wake" else "failed",
                    "error_code": "host_operation_failed", "observed_at": format_timestamp(now_ms())}
