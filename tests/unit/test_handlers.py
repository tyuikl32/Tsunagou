from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest, create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import build_handlers
from tsunagou.bootstrap.container import build_application
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.shared_kernel.baseline import (
    ADMISSION_CAPABILITIES,
    BASELINE_CAPABILITIES,
    missing_baseline_capabilities,
)

ROOT = Path(__file__).parents[2]


def complete_baseline() -> dict[str, Any]:
    return {"baseline": {
        name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
        for name in BASELINE_CAPABILITIES
    }}


def _endpoint(app: Any) -> Any:
    return next(
        route.endpoint for route in app.routes
        if getattr(route, "path", "") == "/api/v1/commands/{command_kind}"
    )


def _request(payload: dict[str, Any]) -> CommandRequest:
    return CommandRequest(command_id="c", protocol_version="1", schema_bundle_digest="sha256:x", payload=payload)


def _app(tmp_path: Path, *, control_token: str | None = None) -> tuple[Any, AuthorityService]:
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    authority = AuthorityService(tmp_path / "identity.json")
    for kind, handler in build_handlers(authority=authority).items():
        dispatcher.register(kind, handler)
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator(authority=authority, control_token=control_token))
    return app, authority


def _enroll_payload() -> dict[str, Any]:
    return {
        "installation_id": "install-a",
        "conversation_evidence": {"conversation_id": "conversation-a"},
        "probe_payload": complete_baseline(),
    }


def test_enroll_t_principal_reaches_redeem_ticket(tmp_path: Path) -> None:
    app, authority = _app(tmp_path)
    ticket = authority.issue_ticket("install-a", "conversation-a")
    result = _endpoint(app)("agent.enroll", _request(_enroll_payload()), Response(), f"Bearer {ticket}", None, None)
    body = result["result"]
    assert body["baseline_status"] == "ready"
    assert body["agent_id"] in authority.agents
    assert authority.verify_token(body["session_id"], body["secret_token"])


def test_enroll_ticket_is_single_use_and_mismatch_fails_closed(tmp_path: Path) -> None:
    app, authority = _app(tmp_path)
    ticket = authority.issue_ticket("install-a", "conversation-a")
    endpoint = _endpoint(app)
    endpoint("agent.enroll", _request(_enroll_payload()), Response(), f"Bearer {ticket}", None, None)
    with pytest.raises(HTTPException) as exc:
        endpoint("agent.enroll", _request(_enroll_payload()), Response(), f"Bearer {ticket}", None, None)
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "invalid_or_consumed_enrollment_ticket"


def test_enroll_requires_authority_and_conversation_identity(tmp_path: Path) -> None:
    # A T bearer without a configured authority must fail closed, not resolve an identity.
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator())
    with pytest.raises(HTTPException) as exc:
        _endpoint(app)("agent.enroll", _request(_enroll_payload()), Response(), "Bearer whatever", None, None)
    assert exc.value.status_code == 401


def test_issue_user_ticket_returns_redeemable_secret(tmp_path: Path) -> None:
    app, authority = _app(tmp_path, control_token="ctl")
    result = _endpoint(app)(
        "agent.ticket.create.user",
        _request({"kind": "worker", "installation_id": "install-a", "conversation_evidence": {"conversation_id": "conversation-a"}}),
        Response(), "Bearer ctl", None, None,
    )
    secret = result["result"]["secret"]
    assert secret
    receipt = authority.redeem_ticket(secret, "install-a", "conversation-a", baseline=complete_baseline())
    assert receipt.baseline_status == "ready"


def test_appoint_requires_ready_session(tmp_path: Path) -> None:
    app, authority = _app(tmp_path, control_token="ctl")
    endpoint = _endpoint(app)
    degraded = authority.redeem_ticket(
        authority.issue_ticket("install-a", "conversation-a"), "install-a", "conversation-a", baseline={}
    )
    with pytest.raises(HTTPException) as exc:
        endpoint("authority.appoint", _request({"agent_id": degraded.agent_id}), Response(), "Bearer ctl", None, None)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ready_session_required"

    ready = authority.redeem_ticket(
        authority.issue_ticket("install-b", "conversation-b"), "install-b", "conversation-b", baseline=complete_baseline()
    )
    result = endpoint("authority.appoint", _request({"agent_id": ready.agent_id}), Response(), "Bearer ctl", None, None)
    assert result["result"]["main_agent_id"] == ready.agent_id
    assert authority.main_agent_id == ready.agent_id


def test_build_application_full_enrollment_chain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("TSUNAGOU_CONTROL_TOKEN", "ctl")
    endpoint = _endpoint(build_application())
    issued = endpoint(
        "agent.ticket.create.user",
        _request({"kind": "worker", "installation_id": "install-a", "conversation_evidence": {"conversation_id": "conversation-a"}}),
        Response(), "Bearer ctl", None, None,
    )
    secret = issued["result"]["secret"]
    enrolled = endpoint(
        "agent.enroll", _request(_enroll_payload()), Response(), f"Bearer {secret}", None, None,
    )
    assert enrolled["result"]["baseline_status"] == "ready"


def test_build_application_fails_closed_without_control_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TSUNAGOU_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("TSUNAGOU_CONTROL_TOKEN", raising=False)
    endpoint = _endpoint(build_application())
    with pytest.raises(HTTPException) as exc:
        endpoint(
            "agent.ticket.create.user",
            _request({"kind": "worker", "installation_id": "i", "conversation_evidence": {"conversation_id": "c"}}),
            Response(), "Bearer whatever", None, None,
        )
    assert exc.value.status_code == 401


def _admission_baseline() -> dict[str, Any]:
    return {"baseline": {
        name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
        for name in ADMISSION_CAPABILITIES
    }}


def test_admission_only_baseline_grants_ready_and_b_auth(tmp_path: Path) -> None:
    # Direction 4: the 4 pre-enrollment rows are enough to become ready and to
    # authenticate a B session, breaking the degraded->ready deadlock.
    _app_result, authority = _app(tmp_path)
    ticket = authority.issue_ticket("install-a", "conversation-a")
    receipt = authority.redeem_ticket(ticket, "install-a", "conversation-a", baseline=_admission_baseline())
    assert receipt.baseline_status == "ready"
    principal = LocalCommandAuthenticator(authority=authority).authenticate(
        "B", f"Bearer {receipt.secret_token}",
        session_id=receipt.session_id, connection_epoch=receipt.connection_epoch,
    )
    assert principal.principal_id == receipt.agent_id


def test_full_baseline_still_required_by_release_gate(tmp_path: Path) -> None:
    # The release gate keeps requiring all 11 rows; an admission-only baseline is
    # ready for a session but still misses the 7 operational rows for release.
    missing = missing_baseline_capabilities(_admission_baseline())
    assert set(missing) == set(name for name in BASELINE_CAPABILITIES if name not in ADMISSION_CAPABILITIES)
    assert len(missing) == len(BASELINE_CAPABILITIES) - len(ADMISSION_CAPABILITIES)
