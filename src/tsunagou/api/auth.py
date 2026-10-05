"""Fail-closed local command authentication for HTTP entrypoints."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from tsunagou.api.liveness import SessionLiveness
from tsunagou.interfaces.runtime import PrincipalContext
from tsunagou.modules.authority import AuthorityService


class LocalCommandAuthenticator:
    """Resolve a principal from a private bearer credential, never caller identity headers.

    This proves the caller's session or user-control identity. Domain handlers
    must still check command-specific grants, scope and revision.
    """

    def __init__(
        self, *, authority: AuthorityService | None = None, control_token: str | None = None,
        liveness: SessionLiveness | None = None,
    ) -> None:
        self.authority = authority
        self.control_token = control_token
        #: 每次成功认证都往这里记一笔（内存级，见 api/liveness.py）。默认自带一份，
        #: 于是单独构造认证器的测试不用关心它。
        self.liveness = liveness if liveness is not None else SessionLiveness()

    def authenticate(
        self, principal_kind: str, authorization: str | None, *,
        session_id: str | None, connection_epoch: int | None,
    ) -> PrincipalContext:
        """认证一次调用，并把**每一次被接受的调用都当成一次心跳**。

        桥按固定间隔做便宜的已认证读取，所以"那台机器最近还活着"不需要新增协议命令
        —— 一次成功的认证就是一次证明（见 api/liveness.py）。过期判断在出口那边做。
        """

        context = self._authenticate(
            principal_kind, authorization, session_id=session_id,
            connection_epoch=connection_epoch,
        )
        self.liveness.seen(getattr(context, "session_id", None) or session_id)
        return context

    def _authenticate(
        self, principal_kind: str, authorization: str | None, *,
        session_id: str | None, connection_epoch: int | None,
    ) -> PrincipalContext:
        prefix = "Bearer "
        if authorization is None or not authorization.startswith(prefix):
            raise PermissionError("authentication_failed")
        token = authorization[len(prefix):]
        if not token or token != token.strip():
            raise PermissionError("authentication_failed")
        if principal_kind == "U":
            if self.control_token is None or not secrets.compare_digest(token, self.control_token):
                raise PermissionError("authentication_failed")
            return PrincipalContext("U", "user_control", credential_proof_hash=hashlib.sha256(token.encode()).hexdigest())
        if principal_kind == "T":
            # The one-time ticket secret is the bearer. redeem_ticket enforces
            # single-use, expiry and identity binding, so this branch only carries
            # the credential to the handler; it never trusts caller identity headers.
            if self.authority is None:
                raise PermissionError("authentication_failed")
            return PrincipalContext("T", token, session_id, connection_epoch, hashlib.sha256(token.encode()).hexdigest())
        if principal_kind == "X":
            # Execution commands carry the agent session credential but are scoped by a
            # task_attempt grant issued at task.begin. Fail closed without one.
            if self.authority is None or session_id is None:
                raise PermissionError("authentication_failed")
            session = self.authority.sessions.get(session_id)
            if (
                session is None or not session.active or session.status != "ready"
                or connection_epoch != session.connection_epoch
                or not self.authority.verify_token(session_id, token)
            ):
                raise PermissionError("authentication_failed")
            if not any(
                grant.kind == "task_attempt" and grant.principal_id == session.agent_id
                and grant.session_id == session_id and grant.status == "active"
                for grant in self.authority.grants.values()
            ):
                raise PermissionError("capability_denied")
            return PrincipalContext("X", session.agent_id, session_id, connection_epoch)
        if principal_kind == "D":
            # Bootstrap authenticated session: the device/daemon proves it still
            # holds the session credential (token) but carries no ordinary grant.
            # reconnect/reprobe/end are gated by the reconnect_nonce compare-and-swap
            # inside AuthorityService.rebind plus handler scope, not a business grant.
            if self.authority is None or session_id is None:
                raise PermissionError("authentication_failed")
            session = self.authority.sessions.get(session_id)
            if (
                session is None or not session.active or session.status != "ready"
                or connection_epoch != session.connection_epoch
                or not self.authority.verify_token(session_id, token)
            ):
                raise PermissionError("authentication_failed")
            return PrincipalContext("D", session.agent_id, session_id, connection_epoch, hashlib.sha256(token.encode()).hexdigest())
        if principal_kind not in {"B", "M", "R"} or self.authority is None or session_id is None:
            raise PermissionError("authentication_failed")
        session = self.authority.sessions.get(session_id)
        if (
            session is None or not session.active or session.status != "ready"
            or connection_epoch != session.connection_epoch
            or not self.authority.verify_token(session_id, token)
        ):
            raise PermissionError("authentication_failed")
        if principal_kind == "R":
            if not any(
                grant.kind == "task_review" and grant.principal_id == session.agent_id
                and grant.session_id in {None, session_id} and grant.status == "active"
                for grant in self.authority.grants.values()
            ):
                raise PermissionError("capability_denied")
            return PrincipalContext("R", session.agent_id, session_id, connection_epoch)
        grant_kind = "agent_base" if principal_kind == "B" else "main_authority"
        if principal_kind == "M" and self.authority.main_agent_id != session.agent_id:
            raise PermissionError("capability_denied")
        if not any(
            grant.kind == grant_kind and grant.principal_id == session.agent_id
            and grant.status == "active"
            and (principal_kind == "M" or grant.session_id == session_id)
            and (principal_kind == "B" or grant.authority_epoch == self.authority.authority_epoch)
            for grant in self.authority.grants.values()
        ):
            raise PermissionError("capability_denied")
        return PrincipalContext(principal_kind, session.agent_id, session_id, connection_epoch)

    def authenticate_reconnect_replay(
        self, database: Any, *, command_kind: str, command_id: str, payload: dict[str, Any],
        authorization: str | None, session_id: str | None, connection_epoch: int | None,
    ) -> PrincipalContext:
        """Prove one old credential can retrieve only its already-committed receipt.

        This never makes the old token valid for an ordinary command. The
        dispatcher carries replay_only into SQLite, so a missing row cannot
        accidentally invoke a credential-rotating handler.
        """
        if (command_kind != "session.reconnect" or database is None or self.authority is None
                or session_id is None or connection_epoch is None or authorization is None
                or not authorization.startswith("Bearer ")):
            raise PermissionError("authentication_failed")
        token = authorization[len("Bearer "):]
        if not token or token != token.strip():
            raise PermissionError("authentication_failed")
        session = self.authority.sessions.get(session_id)
        if session is None or not session.active:
            raise PermissionError("authentication_failed")
        proof = hashlib.sha256(token.encode("utf-8")).hexdigest()
        database.verify_credential_replay(
            principal_id=session.agent_id, command_kind=command_kind, command_id=command_id, payload=payload,
            session_id=session_id, connection_epoch=connection_epoch, proof_hash=proof,
            current_connection_epoch=session.connection_epoch,
        )
        return PrincipalContext("D", session.agent_id, session_id, connection_epoch, proof, replay_only=True)

    def authenticate_reconnect_refresh(
        self, payload: dict[str, Any], *, authorization: str | None,
        session_id: str | None, connection_epoch: int | None,
    ) -> PrincipalContext:
        """Let a session that is *not* ready hand in a fresh capability report.

        A degraded session cannot do business work, and it also cannot reconnect —
        which used to leave "get well" with exactly one route: somebody issues a
        new ticket. That is a person remembering to do the right thing at the right
        time, so the session is allowed this one door instead:

        * it proves the same thing every other branch proves (it holds the current
          credential for this exact session and epoch);
        * it must actually bring a report (``probe_payload``), because the whole
          point is to be re-judged — an empty reconnect stays refused;
        * and it reaches only ``session.reconnect``, never a business command
          (those still authenticate through the branches above).

        The report is judged by the same shared rule as admission, so this cannot
        promote anybody by itself.
        """

        if self.authority is None or session_id is None or connection_epoch is None:
            raise PermissionError("authentication_failed")
        report = payload.get("probe_payload")
        if not isinstance(report, dict) or not report:
            raise PermissionError("authentication_failed")
        if authorization is None or not authorization.startswith("Bearer "):
            raise PermissionError("authentication_failed")
        token = authorization[len("Bearer "):]
        if not token or token != token.strip():
            raise PermissionError("authentication_failed")
        session = self.authority.sessions.get(session_id)
        if (
            session is None or not session.active
            or connection_epoch != session.connection_epoch
            or not self.authority.verify_token(session_id, token)
        ):
            raise PermissionError("authentication_failed")
        return PrincipalContext("D", session.agent_id, session_id, connection_epoch)

    def authenticate_delivery_ack(
        self, authorization: str | None, *, session_id: str | None, connection_epoch: int | None,
    ) -> PrincipalContext:
        if session_id is None:
            return self.authenticate("U", authorization, session_id=None, connection_epoch=None)
        # Even a degraded enrollment must be able to acknowledge durable local
        # credential storage. This proves only session identity, not admission.
        if self.authority is None or authorization is None or not authorization.startswith("Bearer "):
            raise PermissionError("authentication_failed")
        token = authorization[len("Bearer "):]
        session = self.authority.sessions.get(session_id)
        if (session is None or not session.active or connection_epoch != session.connection_epoch
                or not self.authority.verify_token(session_id, token)):
            raise PermissionError("authentication_failed")
        return PrincipalContext("D", session.agent_id, session_id, connection_epoch)
