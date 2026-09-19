import json
from pathlib import Path

import pytest
from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest, create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.interfaces.runtime import BlackboardComposer, CommandDispatcher, PrincipalContext
from tsunagou.modules.authority import AuthorityService
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES

ROOT = Path(__file__).parents[2]


def dispatcher() -> CommandDispatcher:
    return CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")


def test_http_and_dispatcher_share_hash_and_mcp_hides_user_commands(tmp_path: Path) -> None:
    service = dispatcher()
    service.register("task.claim", lambda payload, context: {"accepted": payload.get("task_id"), "actor": context["principal_id"]})
    authority = AuthorityService(tmp_path / "identity.json")
    ticket = authority.issue_ticket("installation", "conversation")
    receipt = authority.redeem_ticket(ticket, "installation", "conversation", baseline={"baseline": {
        name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
        for name in BASELINE_CAPABILITIES
    }})
    app = create_app(service, authenticator=LocalCommandAuthenticator(authority=authority))
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")
    response = endpoint(
        "task.claim",
        CommandRequest(command_id="c", protocol_version="1", schema_bundle_digest="sha256:x", payload={"task_id": "t"}),
        Response(), f"Bearer {receipt.secret_token}", receipt.session_id, 1,
    )
    assert response["result"]["actor"] == receipt.agent_id
    with pytest.raises(HTTPException) as stale:
        endpoint(
            "task.claim",
            CommandRequest(command_id="c2", protocol_version="1", schema_bundle_digest="sha256:x", payload={}),
            Response(), f"Bearer {receipt.secret_token}", receipt.session_id, 2,
        )
    assert stale.value.status_code == 401
    assert all(tool["name"] != "agent.ticket.create.user" for tool in service.mcp_tools())
    with pytest.raises(PermissionError):
        service.dispatch(
            "task.claim",
            {"command_id": "c", "protocol_version": "1", "schema_bundle_digest": "x", "payload": {}},
            principal=PrincipalContext("U", "user"),
        )


def test_http_rejects_spoofed_identity_headers_and_stale_session(tmp_path: Path) -> None:
    service = dispatcher()
    service.register("task.claim", lambda _payload, _context: {"accepted": True})
    authority = AuthorityService(tmp_path / "identity.json")
    ticket = authority.issue_ticket("installation", "conversation")
    receipt = authority.redeem_ticket(ticket, "installation", "conversation", baseline={"baseline_ok": True})
    app = create_app(service, authenticator=LocalCommandAuthenticator(authority=authority))
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")
    request = CommandRequest(command_id="c", protocol_version="1", schema_bundle_digest="sha256:x", payload={})
    with pytest.raises(HTTPException) as missing:
        endpoint("task.claim", request, Response(), None, None, None)
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException) as degraded:
        endpoint("task.claim", request, Response(), f"Bearer {receipt.secret_token}", receipt.session_id, 1)
    assert degraded.value.status_code == 401
    headers = app.openapi()["paths"]["/api/v1/commands/{command_kind}"]["post"]["parameters"]
    assert all(not item["name"].startswith("X-Principal-") for item in headers)


def test_user_control_credential_is_distinct_from_agent_credential(tmp_path: Path) -> None:
    service = dispatcher()
    service.register("agent.ticket.create.user", lambda _payload, context: {"actor": context["principal_id"]})
    authority = AuthorityService(tmp_path / "identity.json")
    app = create_app(service, authenticator=LocalCommandAuthenticator(authority=authority, control_token="private-control"))
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")
    request = CommandRequest(command_id="c", protocol_version="1", schema_bundle_digest="sha256:x", payload={"kind": "worker"})
    result = endpoint("agent.ticket.create.user", request, Response(), "Bearer private-control", None, None)
    assert result["result"]["actor"] == "user_control"
    with pytest.raises(HTTPException) as wrong:
        endpoint("agent.ticket.create.user", request, Response(), "Bearer wrong", None, None)
    assert wrong.value.status_code == 401


def test_blackboard_filters_secrets_and_marks_truncation() -> None:
    snapshot = BlackboardComposer().compose({
        "identity": {"agent_id": "a", "token": "secret"},
        "blockers": [{"id": str(i)} for i in range(3)],
    }, max_items=2)
    assert "token" not in json.dumps(snapshot)
    assert snapshot["truncated"]["blockers"] == 1
    assert "snapshot_digest" in snapshot
