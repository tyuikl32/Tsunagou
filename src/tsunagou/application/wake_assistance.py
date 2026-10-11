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

from tsunagou.application.host_wake_runner import sanitize_diagnostics
from tsunagou.hostwake.timing import declared_timing, plan_delivery
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.messaging import MessageStore
from tsunagou.platform.private_files import write_private_bytes
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.errors import PermissionRefused
from tsunagou.shared_kernel.time import format_timestamp, now_ms


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


# The delivery timing each automatic channel's own class declares. Kept as a literal
# table so reading a capability never needs to import (or construct) a provider.
_PROVIDER_DELIVERY_TIMING: dict[str, str] = {
    "codex_desktop_app": "idle_only",
    "managed_app_server": "unknown",
    "desktop_attach": "unknown",
}

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
            held = sorted({cap for item in self.authority.grants.values()
                           if item.principal_id == session.agent_id and item.status == "active"
                           for cap in item.capabilities})
            raise PermissionRefused("capability_denied", {
                "capability": capability, "held": held,
                "next": ("这条命令要的能力不在你手上：把这件事交给 main，"
                         "或请它把能力交接给你（你现有的能力见 held）。"),
            })
        self.authority.authorize(agent_id=session.agent_id, session_id=session.session_id,
                                 grant_id=grant.grant_id, capability=capability)

    def _identity(self, agent_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        with self._domain_lock():
            return self._identity_committed(agent_id)

    def _identity_committed(self, agent_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
        public: dict[str, Any] = {"agent_id": agent_id, "host": "unknown", "version": None,
                                  "machine": "unknown", "identity_evidence": [], **self._machine_fields(agent_id)}
        agent = self.authority.agents.get(agent_id)
        if agent is None or agent.status != "active":
            return public, None
        # A machine name is only ever recorded when an Agent arrived through an
        # invitation (``agent import --machine``), so this project's own record already
        # says "somewhere else"; ``_machine_fields`` keeps the name rather than
        # collapsing it, because "which machine" is what a reader needs.
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
            # Where it does say "elsewhere", ``_machine_fields`` already reports that;
            # otherwise the answer stays "unknown" rather than being upgraded by a name.
            return public, None
        host, route = candidates[0]
        credential = _object(Path(route["session_file"]))
        public.update(host=host, **self._machine_fields(agent_id, verified_local=True),
                      identity_evidence=[agent.conversation_digest, canonical_digest({
                          "session_id": credential.get("session_id"), "connection_epoch": credential.get("connection_epoch"),
                      })])
        return public, route

    def _machine_fields(self, agent_id: str, *, verified_local: bool = False) -> dict[str, Any]:
        """Where an Agent is, split into what was reported and what was verified.

        ``machine`` is the name a reader can act on; ``machine_name`` is the raw
        self-reported value; ``machine_scope`` is the judgement that decides whether a
        wake is possible at all. Only ``machine_scope`` may drive that decision.
        """
        agent = self.authority.agents.get(agent_id)
        reported = str(getattr(agent, "machine", "") or "").strip()
        if verified_local:
            return {"machine": "local", "machine_name": reported or None, "machine_scope": "local"}
        if reported:
            return {"machine": reported, "machine_name": reported, "machine_scope": "remote"}
        return {"machine": "unknown", "machine_name": None, "machine_scope": "unknown"}

    @staticmethod
    def _remote_reason(machine: str) -> str:
        """Why a network-enrolled Agent cannot be woken from here, in plain words."""
        return (
            f"跨机器不支持主动唤醒：{machine or '远端'} 上的这个 Agent 不在本机，"
            "本机既没有可核实的本地宿主路由，也没有入向通道。消息留在本机收件箱里，"
            "需要对方自己来取（coordination.wake_status 只能报告这个事实）。"
        )

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
        # 看门狗与拒绝回响是以 ``runtime`` 的名义发的（``task.resume`` / ``coordination.stalled``
        # / ``task.refused``）⇒ 发件人不是任何 Agent，"寄件人才能查"这条把它们全挡在门外，
        # 于是**没有人**能问"那条唤醒到底送没送到"（2026-10-10 审计）。这两个角色的消息
        # 对 main 和收件人开放：它本来就该看得见自己的球。
        if not allowed and message.sender_agent_id == "runtime":
            allowed = context["principal_id"] in {message.recipient_agent_id,
                                                 getattr(self.authority, "main_agent_id", None)}
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
                                  "attempt_state": None, "error_code": None,
                                  # Whether a daemon-delivered wake can even reach this Agent.
                                  # ``None`` = not answerable here, never a hopeful True.
                                  "automatic_channel_available": self._native_lane_available(recipient)}
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
            if isinstance(attempt.get("delivery"), dict):
                # The automatic lane's own report: when its provider observed the timing.
                base["delivery"] = attempt["delivery"]
            proven = any(isinstance(item, dict) and item.get("kind") == "turn_started"
                         and item.get("message_id") == message_id for item in attempt.get("evidence", []))
            if proven and attempt.get("turn_id_digest") and not attempt.get("coalesced_into"):
                base["progress"]["host_turn_started"] = True
                base["evidence"] = [attempt["turn_id_digest"]]
        if enabled is False:
            base["error_code"] = "native_wake_disabled"
        base["native"] = native

    def recorded_progress(self, message_id: str) -> dict[str, Any]:
        """这份通知**已经记录在本地**的投递事实，不探测宿主。

        ``status()`` 为了回答"对方宿主开始这一轮没有"会去问宿主，逐条调用太重；而分派记录
        （``records``）与投递状态（``messages.deliveries``）里已有的那部分，足够回答
        "它到了吗、它开始了吗" —— 主 Agent 以前正是靠反复调用 ``coordination.wake_status``
        才敢判断这些（那些轮次本身就是成本）。

        ``wake_recorded`` 与 ``host_turn_started`` 一起给，是为了不让"还没派发过唤醒"与
        "派发了但宿主没开始"被读成同一件事。
        """

        record = self.records.get(message_id) or {}
        delivery = self.messages.deliveries.get(message_id)
        return {
            "delivered": delivery is not None,
            "presented": bool(delivery and delivery.presented_at is not None),
            "acked": bool(delivery and delivery.status == "acked"),
            "wake_recorded": bool(record),
            "host_turn_started": bool(record.get("turn_started")),
        }

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
            base.update(self._delivery_report(target))
            if sender_route is None or target_route is None:
                # Two different refusals, and the difference is the whole point:
                # a name recorded at invitation time means the Agent is on another
                # machine, which has no verified local route and no inbound channel;
                # anything else only means this daemon cannot prove a local route.
                remote = "remote" in {sender.get("machine_scope"), target.get("machine_scope")}
                if remote:
                    machine = target["machine"] if target.get("machine_scope") == "remote" else sender["machine"]
                    base.update(error_code="cross_machine_unsupported", next=self._remote_reason(str(machine)))
                else:
                    base["error_code"] = "host_identity_unverified"
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
                if diagnostics := sanitize_diagnostics(prior.get("diagnostics")):
                    base["diagnostics"] = diagnostics
                base["retry_allowed"] = False
                base["progress"]["host_turn_started"] = bool(prior.get("turn_started"))
                base.update(self._delivery_report(target, prior))
                return base
            observed = self._host("status", target, target_route, message_id)
            for key in ("state", "can_queue", "result", "error_code", "evidence", "observed_at",
                        "diagnostics", "delivery"):
                if key in observed:
                    base[key] = observed[key]
            base.update(self._delivery_report(target, observed))
            target["version"] = observed.get("version")
            base["progress"]["host_turn_started"] = bool(observed.get("turn_started") and observed.get("request_associated"))
            if prior is not None:
                # Fresh host facts do not erase a previous possibly accepted
                # request. Advertise inspection only, never an unusable retry.
                base["prior_result"] = prior.get("result", "unknown")
                if diagnostics := sanitize_diagnostics(prior.get("diagnostics")):
                    base["prior_diagnostics"] = diagnostics
                base["retry_allowed"] = False
                base["error_code"] = base.get("error_code") or "wake_already_attempted"
                return base
            if observed.get("error_code") or observed.get("result") in {"failed", "unknown"}:
                # This status-only precheck never invoked the wake operation.
                # Do not infer this from runner stages after a wake was attempted.
                base["preflight_failed"] = True
            if observed.get("request_associated") and observed.get("turn_started") and observed.get("state") == "running":
                base.update(result="same_request_running", error_code=None)
                return base
            if observed.get("request_associated") or observed.get("result") != "observed" or observed.get("error_code"):
                return base
            if observed.get("state") == "unloaded" and target["host"] == "deepseek" and observed.get("can_queue") is True:
                pass  # The plugin resumes this bound original session, never creates one.
            elif observed.get("state") != "idle":
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
            for key in ("state", "can_queue", "result", "error_code", "evidence", "observed_at",
                        "diagnostics", "delivery"):
                if key in outcome:
                    base[key] = outcome[key]
            base.update(self._delivery_report(target, outcome, fallback=observed))
            base["progress"]["host_turn_started"] = bool(outcome.get("turn_started") and outcome.get("request_associated"))
            base["entry"] = {"tool": "coordination__wake_status", "arguments": {"message_id": message_id}}
            return base

    def _declared_timing(self, target: dict[str, Any], provider: str | None = None) -> tuple[str, str]:
        """What this Agent's host says it can do, and where that statement comes from.

        Read from the automatic provider's own binding when this daemon has one (that is
        the only place a host capability is declared), never guessed from the adapter
        name. An adapter we know nothing about reports ``unknown``.
        """
        store = getattr(self.native, "store", None) if self.native is not None else None
        get_item = getattr(store, "get", None) if store is not None else None
        item = get_item(str(target.get("agent_id"))) if callable(get_item) else None
        if item is not None:
            ref = item[0]
            declared = declared_timing(getattr(ref, "delivery_timing", None),
                                       (getattr(ref, "capabilities", None) or {}).get("delivery_timing"))
            if declared != "unknown":
                return declared, "host_binding"
        if provider is not None:
            # The automatic attempt records which channel handled it, and a channel that
            # has a known busy-behaviour answer declares it on its own class.
            declared = _PROVIDER_DELIVERY_TIMING.get(provider)
            if declared is not None:
                return declared, "provider_declaration"
        return "unknown", "no_host_capability_declaration"

    def _native_lane_available(self, recipient: str) -> bool | None:
        """Whether this daemon holds a *usable* automatic channel for that Agent.

        ``None`` means the question cannot be answered here (no dispatcher bound, or its
        provider keeps no binding store). It is never upgraded to ``True`` by the
        adapter's name: an automatic channel needs a binding, and only a binding store
        can say whether one exists.
        """
        if self.native is None:
            return None
        store = getattr(self.native, "store", None)
        get_item = getattr(store, "get", None) if store is not None else None
        if not callable(get_item):
            return None
        item = get_item(recipient)
        if item is None:
            return False
        return getattr(item[0], "status", None) == "ready"

    def _delivery_report(self, target: dict[str, Any], *sources: Any, fallback: Any = None) -> dict[str, Any]:
        """When this attempt's reminder is (or will be) read.

        The runner reports the timing it actually got, so that statement wins over the
        declared capability. Nothing observed anywhere stays ``unknown``: a caller that
        cannot be told the timing must not be told a convenient one, and a request that
        cannot be honoured is reported as an explicit degradation instead of a success.

        ``sources`` are read latest-first, so the wake's own report beats the earlier
        precheck; ``fallback`` is only consulted when nothing else said anything.
        """
        provider = None
        for value in (*sources, fallback):
            if isinstance(value, dict) and isinstance(value.get("provider"), str):
                provider = value["provider"]
        declared, source = self._declared_timing(target, provider)
        lane = self._native_lane_available(str(target.get("agent_id")))
        if lane is None and provider in _PROVIDER_DELIVERY_TIMING:
            # A known channel class, but this daemon exposes no binding store to check.
            # Whatever it delivers, this reader cannot see it.
            lane = False
        if lane is None:
            source = source if source != "unknown" else "automatic_channel_unknown"
        used = declared
        for value in (fallback, *reversed(sources)):
            if not isinstance(value, dict):
                continue
            delivery = value.get("delivery")
            if not isinstance(delivery, dict):
                continue
            if isinstance(delivery.get("declared"), str):
                declared = delivery["declared"]
            if isinstance(delivery.get("used"), str):
                used = delivery["used"]
            if isinstance(delivery.get("source"), str):
                source = delivery["source"]
        if lane is False and used == "unknown":
            # Nobody can be woken through a channel that does not exist, so "unknown"
            # would understate what is known here: there is no wake path at all.
            declared = used = "none"
            source = "no_automatic_channel"
        return {"delivery": plan_delivery(used=used, declared=declared, source=source).to_public()}

    def _host(self, action: str, target: dict[str, Any], route: dict[str, Any], message_id: str) -> dict[str, Any]:
        if self.runner is None:
            return {"state": "unknown", "result": "unsupported", "error_code": "host_runner_unavailable"}
        try:
            private_ids = {"project_id": self.project_id, "agent_id": target["agent_id"]} if target["host"] == "deepseek" else {}
            result = dict(self.runner(action, adapter=target["host"], conversation_id=route["conversation_id"],
                                      project_root=str(self.project_root), message_id=message_id, **private_ids))
            diagnostics = sanitize_diagnostics(result.pop("diagnostics", None))
            if diagnostics:
                result["diagnostics"] = diagnostics
            return result
        except Exception:
            return {"state": "unknown", "result": "unknown" if action == "wake" else "failed",
                    "error_code": "host_operation_failed", "observed_at": format_timestamp(now_ms())}
