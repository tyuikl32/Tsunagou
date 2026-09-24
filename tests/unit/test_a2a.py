"""Tests for the authenticated A2A adapter boundary."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from tsunagou.api.app import create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.messaging import MessageStore
from tsunagou.shared_kernel.baseline import BASELINE_CAPABILITIES

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "a2a"
SCHEMAS = ROOT / "protocol" / "schemas" / "a2a"


def _ready(authority: AuthorityService, installation: str, conversation: str):
    ticket = authority.issue_ticket(installation, conversation)
    baseline = {
        "baseline": {
            name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
            for name in BASELINE_CAPABILITIES
        },
    }
    return authority.redeem_ticket(ticket, installation, conversation, baseline=baseline)


def _app(tmp_path: Path):
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    authority = AuthorityService(tmp_path / "identity.json")
    messages = MessageStore(tmp_path / "messages.json")
    sender = _ready(authority, "install-sender", "conversation-sender")
    recipient = _ready(authority, "install-recipient", "conversation-recipient")
    authority.appoint_main(actor_kind="user_control", agent_id=sender.agent_id)
    transition_calls: list[tuple[str, str, str]] = []

    def message_send(payload: dict[str, object], context: dict[str, object]) -> dict[str, object]:
        message = messages.send(
            command_id=str(context["command_id"]),
            sender_agent_id=str(context["principal_id"]),
            recipient_agent_id=str(payload["recipient_agent_id"]),
            kind=str(payload.get("kind", "message")),
            subject_ref=str(payload.get("subject_ref", "")),
            summary=str(payload["summary"]),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        )
        return {"message_id": message.message_id, "recipient_agent_id": message.recipient_agent_id}

    dispatcher.register("message.send", message_send)

    def task_transition(kind: str):
        def handler(payload: dict[str, object], context: dict[str, object]) -> dict[str, object]:
            transition_calls.append((kind, str(context["kind"]), str(payload["task_id"])))
            status = {"task.cancel_request": "cancel_requested", "task.fail": "failed", "task.recover": "open"}[kind]
            return {"task_id": payload["task_id"], "status": status, "revision": 4}

        return handler

    dispatcher.register("task.cancel_request", task_transition("task.cancel_request"))
    dispatcher.register("task.fail", task_transition("task.fail"))
    dispatcher.register("task.recover", task_transition("task.recover"))
    app = create_app(
        dispatcher,
        authenticator=LocalCommandAuthenticator(authority=authority),
        query_provider=lambda kind, _project: {
            "tasks": {"items": [{"task_id": "task-1", "status": "running", "revision": 2}]},
        }.get(kind, {"items": []}),
    )
    app.state.a2a_transition_calls = transition_calls
    return app, sender, recipient, messages


def test_agent_card_declares_a2a_and_truthful_wake_capability(tmp_path: Path) -> None:
    app, _, _, _ = _app(tmp_path)
    card = app.state.a2a_gateway.agent_card("http://127.0.0.1:8000/api/v1/a2a")

    Draft202012Validator(json.loads((SCHEMAS / "agent-card.schema.json").read_text(encoding="utf-8"))).validate(card)
    assert card["protocolVersion"] == "1.0"
    assert card["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
    assert card["capabilities"]["streaming"] is False
    assert card["capabilities"]["pushNotifications"] is True
    assert card["x-tsunagou"]["wake"] == "push-notification"


def test_a2a_message_send_uses_internal_message_store_and_idempotency(tmp_path: Path) -> None:
    app, sender, recipient, messages = _app(tmp_path)
    headers = {
        "Authorization": f"Bearer {sender.secret_token}",
        "Tsunagou-Session-Id": sender.session_id,
        "Tsunagou-Connection-Epoch": str(sender.connection_epoch),
    }
    body = json.loads((FIXTURES / "message-send.json").read_text(encoding="utf-8"))
    body["params"]["message"]["messageId"] = "external-message-1"
    body["params"]["message"]["metadata"]["tsunagou"]["recipient_agent_id"] = recipient.agent_id
    Draft202012Validator(json.loads((SCHEMAS / "message-send.schema.json").read_text(encoding="utf-8"))).validate(body)

    endpoint = next(
        route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/a2a/agents/{recipient_agent_id}"
    )
    first = endpoint(
        recipient.agent_id,
        body,
        authorization=headers["Authorization"],
        session_id=headers["Tsunagou-Session-Id"],
        connection_epoch=int(headers["Tsunagou-Connection-Epoch"]),
    )
    second = endpoint(
        recipient.agent_id,
        body,
        authorization=headers["Authorization"],
        session_id=headers["Tsunagou-Session-Id"],
        connection_epoch=int(headers["Tsunagou-Connection-Epoch"]),
    )
    changed = json.loads(json.dumps(body))
    changed["params"]["message"]["parts"][0]["text"] = "Different content with the same external message ID."
    conflict = endpoint(
        recipient.agent_id,
        changed,
        authorization=headers["Authorization"],
        session_id=headers["Tsunagou-Session-Id"],
        connection_epoch=int(headers["Tsunagou-Connection-Epoch"]),
    )

    first_id = first["result"]["message"]["messageId"]
    assert second["result"]["message"]["messageId"] == first_id
    assert conflict["error"]["data"]["code"] == "idempotency_conflict"
    assert len(messages.messages) == 1
    stored = next(iter(messages.messages.values()))
    assert stored.sender_agent_id == sender.agent_id
    assert stored.recipient_agent_id == recipient.agent_id
    assert stored.payload["a2a"]["message_id"] == "external-message-1"


def test_a2a_message_send_pushes_standard_configuration_without_persisting_credentials(tmp_path: Path) -> None:
    app, sender, recipient, messages = _app(tmp_path)
    delivered: list[tuple[str, dict[str, object]]] = []
    app.state.a2a_gateway.push_notifier = lambda config, event: (
        delivered.append((config.url, event)) or {"http_status": 202}
    )
    endpoint = next(
        route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/a2a/agents/{recipient_agent_id}"
    )
    body = json.loads((FIXTURES / "message-send.json").read_text(encoding="utf-8"))
    body["params"]["message"]["messageId"] = "external-push-1"
    body["params"]["message"]["metadata"]["tsunagou"]["recipient_agent_id"] = recipient.agent_id
    body["params"]["configuration"] = {
        "returnImmediately": True,
        "taskPushNotificationConfig": {
            "url": "http://127.0.0.1:9876/wake",
            "token": "private-callback-token",
            "authentication": {"scheme": "Bearer", "credentials": "private-auth"},
        },
    }
    Draft202012Validator(json.loads((SCHEMAS / "message-send.schema.json").read_text(encoding="utf-8"))).validate(body)
    response = endpoint(
        recipient.agent_id, body,
        authorization=f"Bearer {sender.secret_token}", session_id=sender.session_id,
        connection_epoch=sender.connection_epoch,
    )
    push = response["result"]["message"]["metadata"]["tsunagou"]["push"]
    assert push["status"] == "delivered"
    assert response["result"]["message"]["metadata"]["tsunagou"]["wake"] == "requested"
    assert delivered[0][0] == "http://127.0.0.1:9876/wake"
    stored_payload = json.dumps([message.payload for message in messages.messages.values()])
    assert "private-callback-token" not in stored_payload
    assert "private-auth" not in stored_payload


def test_a2a_task_query_maps_internal_task_without_new_truth_source(tmp_path: Path) -> None:
    app, sender, _, _ = _app(tmp_path)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/a2a")
    body = json.loads((FIXTURES / "tasks-get.json").read_text(encoding="utf-8"))
    body["params"]["id"] = "tsunagou:task:task-1"
    Draft202012Validator(json.loads((SCHEMAS / "tasks-get.schema.json").read_text(encoding="utf-8"))).validate(body)
    response = endpoint(
        body,
        authorization=f"Bearer {sender.secret_token}",
        session_id=sender.session_id,
        connection_epoch=sender.connection_epoch,
    )

    assert response["result"]["status"]["state"] == "working"
    assert response["result"]["metadata"]["tsunagou"]["task_id"] == "task-1"


def test_a2a_task_transitions_reuse_main_and_worker_authority(tmp_path: Path) -> None:
    app, sender, recipient, _ = _app(tmp_path)
    cancel_endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/a2a")
    main_headers = {
        "Authorization": f"Bearer {sender.secret_token}",
        "Tsunagou-Session-Id": sender.session_id,
        "Tsunagou-Connection-Epoch": str(sender.connection_epoch),
    }
    worker_headers = {
        "Authorization": f"Bearer {recipient.secret_token}",
        "Tsunagou-Session-Id": recipient.session_id,
        "Tsunagou-Connection-Epoch": str(recipient.connection_epoch),
    }
    canceled = cancel_endpoint(
        {"jsonrpc": "2.0", "id": "cancel-1", "method": "tasks/cancel",
         "params": {"id": "tsunagou:task:task-1", "reason": "user changed direction"}},
        authorization=main_headers["Authorization"], session_id=sender.session_id,
        connection_epoch=sender.connection_epoch,
    )
    failed = cancel_endpoint(
        {"jsonrpc": "2.0", "id": "fail-1", "method": "tasks/fail",
         "params": {"id": "task-1", "attemptId": "attempt-1", "reason": "validation failed"}},
        authorization=worker_headers["Authorization"], session_id=recipient.session_id,
        connection_epoch=recipient.connection_epoch,
    )
    retried = cancel_endpoint(
        {"jsonrpc": "2.0", "id": "retry-1", "method": "tasks/retry",
         "params": {"id": "task-1", "attemptId": "attempt-1", "reason": "retry after fix"}},
        authorization=main_headers["Authorization"], session_id=sender.session_id,
        connection_epoch=sender.connection_epoch,
    )
    denied = cancel_endpoint(
        {"jsonrpc": "2.0", "id": "cancel-2", "method": "tasks/cancel",
         "params": {"id": "task-1", "reason": "worker cannot cancel"}},
        authorization=worker_headers["Authorization"], session_id=recipient.session_id,
        connection_epoch=recipient.connection_epoch,
    )

    assert canceled["result"]["metadata"]["tsunagou"]["transition"] == "task.cancel_request"
    assert failed["result"]["status"]["state"] == "failed"
    assert retried["result"]["status"]["state"] == "submitted"
    assert denied["error"]["data"]["code"] == "capability_denied"
    assert app.state.a2a_transition_calls == [
        ("task.cancel_request", "M", "task-1"),
        ("task.fail", "B", "task-1"),
        ("task.recover", "M", "task-1"),
    ]


def test_a2a_rejects_missing_authentication_and_unsupported_stream(tmp_path: Path) -> None:
    app, _, _, _ = _app(tmp_path)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/v1/a2a")
    body = {"jsonrpc": "2.0", "id": "rpc", "method": "message/stream", "params": {}}

    unsupported = endpoint(body)
    assert unsupported["error"]["data"]["code"] == "a2a_method_not_supported"

    missing_auth = endpoint(
        {"jsonrpc": "2.0", "id": "rpc", "method": "tasks/get", "params": {"id": "task-1"}},
        authorization=None,
        session_id=None,
        connection_epoch=None,
    )
    assert missing_auth["error"]["data"]["code"] == "authentication_failed"
