import json
from pathlib import Path

import pytest
from fastapi import Response

from tsunagou.api.app import CommandRequest, create_app
from tsunagou.interfaces.runtime import BlackboardComposer, CommandDispatcher

ROOT = Path(__file__).parents[2]


def dispatcher() -> CommandDispatcher:
    return CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")


def test_http_and_dispatcher_share_hash_and_mcp_hides_user_commands() -> None:
    service = dispatcher()
    service.register("task.claim", lambda payload, context: {"accepted": payload.get("task_id"), "actor": context["principal_id"]})
    app = create_app(service)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/commands/{command_kind}")
    response = endpoint(
        "task.claim",
        CommandRequest(command_id="c", protocol_version="1", schema_bundle_digest="sha256:x", payload={"task_id": "t"}),
        Response(), "B", "agent-1",
    )
    assert response["result"]["actor"] == "agent-1"
    assert all(tool["name"] != "agent.ticket.create.user" for tool in service.mcp_tools())
    with pytest.raises(PermissionError):
        service.dispatch(
            "task.claim",
            {"command_id": "c", "protocol_version": "1", "schema_bundle_digest": "x", "payload": {}},
            principal_kind="U", principal_id="user",
        )


def test_blackboard_filters_secrets_and_marks_truncation() -> None:
    snapshot = BlackboardComposer().compose({
        "identity": {"agent_id": "a", "token": "secret"},
        "blockers": [{"id": str(i)} for i in range(3)],
    }, max_items=2)
    assert "token" not in json.dumps(snapshot)
    assert snapshot["truncated"]["blockers"] == 1
    assert "snapshot_digest" in snapshot
