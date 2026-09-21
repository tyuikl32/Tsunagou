"""Fail-closed local command authentication for HTTP entrypoints."""

from __future__ import annotations

import secrets

from tsunagou.interfaces.runtime import PrincipalContext
from tsunagou.modules.authority import AuthorityService


class LocalCommandAuthenticator:
    """Resolve a principal from a private bearer credential, never caller identity headers.

    This proves the caller's session or user-control identity. Domain handlers
    must still check command-specific grants, scope and revision.
    """

    def __init__(
        self, *, authority: AuthorityService | None = None, control_token: str | None = None
    ) -> None:
        self.authority = authority
        self.control_token = control_token

    def authenticate(
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
            return PrincipalContext("U", "user_control")
        if principal_kind == "T":
            # The one-time ticket secret is the bearer. redeem_ticket enforces
            # single-use, expiry and identity binding, so this branch only carries
            # the credential to the handler; it never trusts caller identity headers.
            if self.authority is None:
                raise PermissionError("authentication_failed")
            return PrincipalContext("T", token, session_id, connection_epoch)
        if principal_kind == "X":
            # Execution commands carry the agent session credential but are scoped by a
            # task_attempt grant issued at task.start. Fail closed without one.
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
            return PrincipalContext("D", session.agent_id, session_id, connection_epoch)
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
