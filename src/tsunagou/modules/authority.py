"""Local enrollment, session identity, opaque credentials, and typed grants."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tsunagou.shared_kernel.baseline import missing_admission_capabilities
from tsunagou.shared_kernel.digests import canonical_digest
from tsunagou.shared_kernel.ids import new_id

GRANT_KINDS = {"agent_base", "main_authority", "task_attempt", "task_review", "handoff_transition"}


def _save_json(path: Path, value: Any) -> None:
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


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> int:
    return int(time.time())


@dataclass(slots=True)
class EnrollmentTicket:
    ticket_id: str
    secret_hash: str
    installation_digest: str
    conversation_digest: str
    expires_at: int
    used: bool = False


@dataclass(slots=True)
class Agent:
    agent_id: str
    installation_digest: str
    # An Agent is one host conversation/worker, not an IDE installation. Keep
    # the conversation binding on the Agent as well as its Session so a
    # rebind request can never retarget a different conversation.
    conversation_digest: str = ""
    status: str = "active"
    role: str = "worker"


@dataclass(slots=True)
class Session:
    session_id: str
    agent_id: str
    conversation_digest: str
    credential_hash: str
    reconnect_nonce_hash: str
    connection_epoch: int = 1
    status: str = "degraded"
    baseline: dict[str, Any] = field(default_factory=dict)
    active: bool = True


@dataclass(frozen=True, slots=True)
class Grant:
    grant_id: str
    kind: str
    principal_id: str
    session_id: str | None
    runtime_epoch: str
    authority_epoch: int | None
    task_id: str | None
    attempt_id: str | None
    execution_epoch: int | None
    capabilities: frozenset[str]
    scope: dict[str, Any]
    status: str = "active"


@dataclass(frozen=True, slots=True)
class EnrollmentReceipt:
    agent_id: str
    session_id: str
    connection_epoch: int
    baseline_status: str
    secret_token: str
    reconnect_nonce: str


class AuthorityService:
    """A small durable authority store with no OAuth/keyring/refresh protocol."""

    def __init__(self, state_path: str | Path | None = None) -> None:
        self.state_path = Path(state_path) if state_path else None
        self._lock = threading.RLock()
        self.tickets: dict[str, EnrollmentTicket] = {}
        self.agents: dict[str, Agent] = {}
        self.sessions: dict[str, Session] = {}
        self.grants: dict[str, Grant] = {}
        self.main_agent_id: str | None = None
        self.authority_epoch = 1
        self._load()

    def _load(self) -> None:
        if self.state_path is None or not self.state_path.is_file():
            return
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.tickets = {}
        migrated_ticket = False
        for key, value in raw.get("tickets", {}).items():
            if "secret_hash" in value:
                ticket = EnrollmentTicket(**value)
            else:
                # Older local state used the redeemable secret as its key and ID.
                # Rewrite it immediately so a read does not leave that secret on disk.
                migrated_ticket = True
                ticket = EnrollmentTicket(
                    new_id(), _token_hash(key), value["installation_digest"],
                    value["conversation_digest"], value["expires_at"], value.get("used", False),
                )
            self.tickets[ticket.secret_hash] = ticket
        self.sessions = {
            key: Session(**{**value, "reconnect_nonce_hash": value.get("reconnect_nonce_hash", "")})
            for key, value in raw.get("sessions", {}).items()
        }
        self.agents = {}
        for key, value in raw.get("agents", {}).items():
            conversation_digest = value.get("conversation_digest") or next(
                (session.conversation_digest for session in self.sessions.values()
                 if session.agent_id == key),
                "",
            )
            self.agents[key] = Agent(**{**value, "conversation_digest": conversation_digest})
        self.grants = {
            key: Grant(**{**value, "capabilities": frozenset(value.get("capabilities", []))})
            for key, value in raw.get("grants", {}).items()
        }
        self.main_agent_id = raw.get("main_agent_id")
        self.authority_epoch = raw.get("authority_epoch", 1)
        if migrated_ticket:
            self._save()

    def _save(self) -> None:
        if self.state_path is None:
            return
        raw = {
            "tickets": {key: asdict(value) for key, value in self.tickets.items()},
            "agents": {key: asdict(value) for key, value in self.agents.items()},
            "sessions": {key: asdict(value) for key, value in self.sessions.items()},
            "grants": {key: {**asdict(value), "capabilities": sorted(value.capabilities)} for key, value in self.grants.items()},
            "main_agent_id": self.main_agent_id,
            "authority_epoch": self.authority_epoch,
        }
        _save_json(self.state_path, raw)

    def issue_ticket(self, installation_id: str, conversation_id: str, ttl_seconds: int = 600) -> str:
        with self._lock:
            secret = secrets.token_urlsafe(32)
            secret_hash = _token_hash(secret)
            self.tickets[secret_hash] = EnrollmentTicket(
                new_id(), secret_hash, canonical_digest({"installation_id": installation_id}),
                canonical_digest({"conversation_id": conversation_id}), _now() + ttl_seconds,
            )
            self._save()
            return secret

    def redeem_ticket(
        self,
        ticket_id: str,
        installation_id: str,
        conversation_id: str,
        *,
        baseline: dict[str, Any] | None = None,
        nonce: str | None = None,
    ) -> EnrollmentReceipt:
        del nonce  # the ticket itself is single-use; nonce is an adapter correlation field
        with self._lock:
            ticket = self.tickets.get(_token_hash(ticket_id))
            if ticket is None or ticket.used or ticket.expires_at < _now():
                raise ValueError("invalid_or_consumed_enrollment_ticket")
            installation_digest = canonical_digest({"installation_id": installation_id})
            conversation_digest = canonical_digest({"conversation_id": conversation_id})
            if ticket.installation_digest != installation_digest or ticket.conversation_digest != conversation_digest:
                raise ValueError("enrollment_identity_mismatch")
            if any(
                session.conversation_digest == ticket.conversation_digest and session.active
                for session in self.sessions.values()
            ):
                raise ValueError("conversation_already_attached")
            snapshot = baseline or {}
            status = session_status(snapshot)
            snapshot_digest = canonical_digest(snapshot)
            ticket.used = True
            agent = Agent(
                new_id(), ticket.installation_digest, ticket.conversation_digest,
            )
            session_id = new_id()
            token = secrets.token_urlsafe(32)
            reconnect_nonce = secrets.token_urlsafe(24)
            session = Session(
                session_id, agent.agent_id, ticket.conversation_digest, _token_hash(token),
                _token_hash(reconnect_nonce),
                status=status,
                baseline={"status": status, "digest": snapshot_digest},
            )
            agent.status = "active" if status == "ready" else "provisioning"
            self.agents[agent.agent_id] = agent
            self.sessions[session_id] = session
            if status == "ready":
                self._issue_base_grant(session)
            self._save()
            return EnrollmentReceipt(
                agent.agent_id, session_id, session.connection_epoch, session.status,
                token, reconnect_nonce,
            )

    def redeem_rebind_ticket(
        self, ticket_id: str, installation_id: str, conversation_id: str, *,
        target_agent_id: str | None = None, baseline: dict[str, Any] | None = None,
    ) -> EnrollmentReceipt:
        """Resume an already-attached session with a fresh one-time ticket.

        ``redeem_ticket`` refuses an already-attached conversation, so a resumed
        conversation needs its own path: verify a *new* ticket against the same
        installation/conversation, locate the existing session (by target agent or
        by conversation digest), consume the ticket, then rebind the session with a
        bumped epoch, a fresh credential and the new baseline. This is what proves
        ``identity.continuity_evidence``: the same conversation digest coming back
        across a resume, never a second identity for the same conversation.
        """
        with self._lock:
            ticket = self.tickets.get(_token_hash(ticket_id))
            if ticket is None or ticket.used or ticket.expires_at < _now():
                raise ValueError("invalid_or_consumed_enrollment_ticket")
            installation_digest = canonical_digest({"installation_id": installation_id})
            conversation_digest = canonical_digest({"conversation_id": conversation_id})
            if ticket.installation_digest != installation_digest or ticket.conversation_digest != conversation_digest:
                raise ValueError("enrollment_identity_mismatch")
            session = None
            if target_agent_id is not None:
                session = next(
                    (candidate for candidate in self.sessions.values()
                     if candidate.agent_id == target_agent_id
                     and candidate.conversation_digest == conversation_digest
                     and candidate.active), None,
                )
                if session is None:
                    raise ValueError("session_not_rebindable")
            else:
                session = next(
                    (candidate for candidate in self.sessions.values()
                     if candidate.conversation_digest == conversation_digest and candidate.active), None,
                )
            if session is None:
                raise ValueError("session_not_rebindable")
            ticket.used = True
            return self.rebind(session.session_id, baseline=baseline)

    def rebind(
        self, session_id: str, *, expected_nonce: str | None = None,
        expected_connection_epoch: int | None = None,
        baseline: dict[str, Any] | None = None,
    ) -> EnrollmentReceipt:
        with self._lock:
            session = self.sessions.get(session_id)
            if session is None or not session.active:
                raise ValueError("session_not_rebindable")
            if expected_connection_epoch is not None and expected_connection_epoch != session.connection_epoch:
                raise PermissionError("stale_connection_epoch")
            if expected_nonce is not None and not secrets.compare_digest(
                session.reconnect_nonce_hash, _token_hash(expected_nonce)
            ):
                raise PermissionError("stale_reconnect_nonce")
            new_status = session_status(baseline) if baseline is not None else None
            new_digest = canonical_digest(baseline) if baseline is not None else None
            token = secrets.token_urlsafe(32)
            reconnect_nonce = secrets.token_urlsafe(24)
            session.credential_hash = _token_hash(token)
            session.reconnect_nonce_hash = _token_hash(reconnect_nonce)
            session.connection_epoch += 1
            if baseline is not None:
                assert new_status is not None and new_digest is not None
                session.baseline = {"status": new_status, "digest": new_digest}
                session.status = new_status
                self.agents[session.agent_id].status = "active" if session.status == "ready" else "provisioning"
                if session.status == "ready" and not any(
                    grant.kind == "agent_base" and grant.session_id == session_id and grant.status == "active"
                    for grant in self.grants.values()
                ):
                    self._issue_base_grant(session)
                if session.status != "ready":
                    for key, grant in list(self.grants.items()):
                        if grant.principal_id == session.agent_id and grant.status == "active":
                            self.grants[key] = Grant(**{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"})
            self._save()
            return EnrollmentReceipt(
                session.agent_id, session_id, session.connection_epoch, session.status,
                token, reconnect_nonce,
            )

    def verify_token(self, session_id: str, token: str) -> bool:
        session = self.sessions.get(session_id)
        return bool(session and session.active and secrets.compare_digest(session.credential_hash, _token_hash(token)))

    def _issue_base_grant(self, session: Session) -> None:
        grant = Grant(
            new_id(), "agent_base", session.agent_id, session.session_id, new_id(), None, None, None, None,
            frozenset({
                "coordination.read", "coordination.report",
                "task.claim", "task.coordinate_self",
                "cognition.report",
                "cognition.discuss",
                "contract.propose", "contract.accept",
                "resource.intent", "resource.acquire", "resource.release", "workspace.prepare",
                "inbox.consume",
                "message.send", "message.respond",
            }), {"agent_id": session.agent_id},
        )
        self.grants[grant.grant_id] = grant

    def appoint_main(self, *, actor_kind: str, agent_id: str) -> Grant:
        if actor_kind != "user_control":
            raise PermissionError("user_only")
        with self._lock:
            agent = self.agents.get(agent_id)
            if agent is None:
                raise KeyError(agent_id)
            if agent.status != "active" or not any(
                session.agent_id == agent_id and session.active and session.status == "ready"
                for session in self.sessions.values()
            ):
                raise PermissionError("ready_session_required")
            if self.main_agent_id is not None and self.main_agent_id != agent_id:
                self.agents[self.main_agent_id].role = "worker"
            self.main_agent_id = agent_id
            agent.role = "main"
            self.authority_epoch += 1
            for key, existing in list(self.grants.items()):
                if existing.kind == "main_authority" and existing.status == "active":
                    self.grants[key] = Grant(**{**asdict(existing), "capabilities": existing.capabilities, "status": "revoked"})
            grant = Grant(
                new_id(), "main_authority", agent_id, None, new_id(), self.authority_epoch,
                None, None, None, frozenset({"task.manage", "root.manage", "agent.appoint", "coordination.write",
                "workspace.select", "task.review", "user.decision.propose",
                "cognition.resolve", "contract.accept_proxy", "durability.checkpoint"}),
                {"agent_id": agent_id},
            )
            self.grants[grant.grant_id] = grant
            self._save()
            return grant

    def revoke_main(self, *, actor_kind: str) -> None:
        if actor_kind != "user_control":
            raise PermissionError("user_only")
        with self._lock:
            self.main_agent_id = None
            self.authority_epoch += 1
            for key, grant in list(self.grants.items()):
                if grant.kind == "main_authority":
                    self.grants[key] = Grant(**{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"})
            self._save()

    def issue_grant(
        self, *, issuer_agent_id: str, kind: str, principal_id: str, session_id: str | None = None,
        task_id: str | None = None, attempt_id: str | None = None, execution_epoch: int | None = None,
        capabilities: set[str] | frozenset[str] = frozenset(), scope: dict[str, Any] | None = None,
    ) -> Grant:
        if kind not in GRANT_KINDS:
            raise ValueError("invalid_grant_kind")
        if kind == "main_authority" or "agent.appoint" in capabilities:
            raise PermissionError("only_user_can_appoint_or_issue_main")
        if issuer_agent_id != self.main_agent_id:
            raise PermissionError("main_authority_required")
        if not any(
            session.agent_id == issuer_agent_id and session.active and session.status == "ready"
            for session in self.sessions.values()
        ):
            raise PermissionError("ready_session_required")
        if session_id is not None:
            target = self.sessions.get(session_id)
            if target is None or target.agent_id != principal_id or not target.active or target.status != "ready":
                raise PermissionError("ready_target_session_required")
        grant = Grant(
            new_id(), kind, principal_id, session_id, new_id(), self.authority_epoch,
            task_id, attempt_id, execution_epoch, frozenset(capabilities), scope or {},
        )
        with self._lock:
            self.grants[grant.grant_id] = grant
            self._save()
        return grant

    def authorize(
        self, *, agent_id: str, session_id: str, grant_id: str, capability: str,
        task_id: str | None = None, attempt_id: str | None = None,
        runtime_epoch: str | None = None, authority_epoch: int | None = None,
        execution_epoch: int | None = None,
    ) -> Grant:
        session = self.sessions.get(session_id)
        grant = self.grants.get(grant_id)
        if session is None or grant is None or not session.active or grant.status != "active":
            raise PermissionError("invalid_session_or_grant")
        if session.status != "ready":
            raise PermissionError("ready_session_required")
        if session.agent_id != agent_id or grant.principal_id != agent_id:
            raise PermissionError("principal_mismatch")
        if capability not in grant.capabilities:
            raise PermissionError("capability_denied")
        if runtime_epoch is not None and grant.runtime_epoch != runtime_epoch:
            raise PermissionError("stale_runtime_epoch")
        if authority_epoch is not None and grant.authority_epoch != authority_epoch:
            raise PermissionError("stale_authority_epoch")
        if execution_epoch is not None and grant.execution_epoch != execution_epoch:
            raise PermissionError("stale_execution_epoch")
        if grant.task_id is not None and grant.task_id != task_id:
            raise PermissionError("task_scope_denied")
        if grant.attempt_id is not None and grant.attempt_id != attempt_id:
            raise PermissionError("attempt_scope_denied")
        return grant

    def find_grant(
        self, *, agent_id: str, capability: str, session_id: str | None = None,
        task_id: str | None = None, attempt_id: str | None = None,
    ) -> Grant | None:
        """Locate an active grant carrying a capability, scoped to session/task/attempt.

        Command payloads do not carry a ``grant_id``; this maps a resolved principal and
        its intended scope back to the grant that ``authorize`` will then re-validate.
        """
        for grant in self.grants.values():
            if grant.status != "active" or grant.principal_id != agent_id:
                continue
            if capability not in grant.capabilities:
                continue
            # A grant whose session_id is None (e.g. main_authority) is deliberately
            # session-independent: it binds to the principal across all of its
            # sessions, so it must not be filtered out by a session-scoped lookup.
            if session_id is not None and grant.session_id is not None and grant.session_id != session_id:
                continue
            if task_id is not None and grant.task_id != task_id:
                continue
            if attempt_id is not None and grant.attempt_id != attempt_id:
                continue
            return grant
        return None

    def issue_execution_grant(
        self, *, agent_id: str, session_id: str, task_id: str, attempt_id: str,
        execution_epoch: int = 1,
    ) -> Grant:
        """Issue the ``task.execute`` grant inside the ``task.start`` transaction.

        This is the catalog's start-time execution grant. It is only reachable after
        ``TaskService.start`` has verified attempt ownership, so it never grants
        execution to an agent that did not successfully start the attempt.
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if session is None or not session.active or session.status != "ready" or session.agent_id != agent_id:
                raise PermissionError("ready_session_required")
            grant = Grant(
                new_id(), "task_attempt", agent_id, session_id, new_id(), self.authority_epoch,
                task_id, attempt_id, execution_epoch, frozenset({"task.execute", "workspace.result"}),
                {"task_id": task_id, "attempt_id": attempt_id},
            )
            self.grants[grant.grant_id] = grant
            self._save()
            return grant

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "agents": {key: {"agent_id": value.agent_id, "status": value.status, "role": value.role} for key, value in self.agents.items()},
            "sessions": {
                key: {
                    "session_id": value.session_id,
                    "agent_id": value.agent_id,
                    "status": value.status,
                    "connection_epoch": value.connection_epoch,
                }
                for key, value in self.sessions.items()
            },
            "main_agent_id": self.main_agent_id,
            "authority_epoch": self.authority_epoch,
        }

    def reset_runtime(self) -> None:
        """Invalidate every runtime grant/session after a lineage reset."""
        with self._lock:
            self.authority_epoch += 1
            self.main_agent_id = None
            for agent in self.agents.values():
                agent.role = "worker"
            for session in self.sessions.values():
                session.active = False
                session.status = "ended"
            for key, grant in list(self.grants.items()):
                self.grants[key] = Grant(**{**asdict(grant), "capabilities": grant.capabilities, "status": "revoked"})
            self._save()


def session_status(baseline: dict[str, Any]) -> str:
    # Readiness gates on the 4 pre-enrollment admission capabilities only; the
    # 7 operational capabilities are proven by ready sessions and feed the
    # release gate rather than session admission.
    return "degraded" if missing_admission_capabilities(baseline) else "ready"
