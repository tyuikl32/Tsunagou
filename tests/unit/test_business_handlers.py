from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Response

from tsunagou.api.app import CommandRequest, create_app
from tsunagou.api.auth import LocalCommandAuthenticator
from tsunagou.application.handlers import build_handlers
from tsunagou.interfaces.runtime import CommandDispatcher
from tsunagou.modules.authority import AuthorityService
from tsunagou.modules.cognition import CognitionService
from tsunagou.modules.messaging import MessageStore
from tsunagou.modules.tasks import TaskService
from tsunagou.shared_kernel.baseline import ADMISSION_CAPABILITIES

ROOT = Path(__file__).parents[2]


def _admission_baseline() -> dict[str, Any]:
    return {"baseline": {
        name: {"status": "supported", "evidence_refs": [f"fixture:{name}"]}
        for name in ADMISSION_CAPABILITIES
    }}


def _request(payload: dict[str, Any]) -> CommandRequest:
    return CommandRequest(command_id="c", protocol_version="1", schema_bundle_digest="sha256:x", payload=payload)


def _harness(
    tmp_path: Path,
) -> tuple[Any, AuthorityService, TaskService, CognitionService, MessageStore, Any]:
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    authority = AuthorityService(tmp_path / "identity.json")
    tasks = TaskService()
    cognition = CognitionService()
    messages = MessageStore()
    for kind, handler in build_handlers(
        authority=authority, tasks=tasks, cognition=cognition, messages=messages
    ).items():
        dispatcher.register(kind, handler)
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator(authority=authority))
    endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", "") == "/api/v1/commands/{command_kind}"
    )
    return app, authority, tasks, cognition, messages, endpoint


def _enroll_ready(authority: AuthorityService, *, installation: str, conversation: str) -> Any:
    ticket = authority.issue_ticket(installation, conversation)
    return authority.redeem_ticket(ticket, installation, conversation, baseline=_admission_baseline())


def _call(endpoint: Any, kind: str, payload: dict[str, Any], receipt: Any) -> dict[str, Any]:
    return endpoint(
        kind, _request(payload), Response(),
        f"Bearer {receipt.secret_token}", receipt.session_id, receipt.connection_epoch,
    )["result"]


def _open_task(tasks: TaskService, title: str = "t") -> str:
    task = tasks.create_task(title, "objective")
    tasks.ready(task.task_id)
    tasks.publish(task.task_id)
    return task.task_id


def test_task_lifecycle_claim_start_submit(tmp_path: Path) -> None:
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)

    claimed = _call(endpoint, "task.claim", {"task_id": task_id, "capability_snapshot_id": "x"}, receipt)
    assert claimed["status"] == "claimed"
    attempt_id = claimed["attempt_id"]

    started = _call(endpoint, "task.start", {
        "task_id": task_id, "attempt_id": attempt_id,
        "preflight_id": "p", "expected_execution_epoch": 1, "input_digest": "d",
    }, receipt)
    assert started["status"] == "running"
    assert started["execution_grant_id"]

    submitted = _call(endpoint, "task.submit", {
        "task_id": task_id, "attempt_id": attempt_id,
        "summary": "done", "artifact_refs": [], "evidence_refs": [], "workspace_result_ref": "w",
    }, receipt)
    assert submitted["result_id"]
    assert tasks.tasks[task_id].status == "submitted"


def test_task_submit_fails_closed_without_execution_grant(tmp_path: Path) -> None:
    _, authority, tasks, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    task_id = _open_task(tasks)
    claimed = _call(endpoint, "task.claim", {"task_id": task_id, "capability_snapshot_id": "x"}, receipt)

    with pytest.raises(HTTPException) as exc:
        _call(endpoint, "task.submit", {
            "task_id": task_id, "attempt_id": claimed["attempt_id"],
            "summary": "done", "artifact_refs": [], "evidence_refs": [], "workspace_result_ref": "w",
        }, receipt)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "capability_denied"


def test_cognition_report_roundtrip(tmp_path: Path) -> None:
    _, authority, _, cognition, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    report = _call(endpoint, "cognition.report", {
        "task_id": "t1", "attempt_id": "a1",
        "claims": [{"subject_key": "s", "claim_type": "literal", "equality_key": "s", "value": "v", "evidence_refs": ["e"]}],
        "uncertainties": [], "assumptions": [],
    }, receipt)
    assert report["report_id"] in cognition.reports


def test_contract_propose_accept_roundtrip(tmp_path: Path) -> None:
    _, authority, _, cognition, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    proposed = _call(endpoint, "contract.propose", {
        "contract_id": "c1", "contract_kind": "kind", "payload": {"x": 1},
        "participants_required": [{"slot": "self", "agent_id": receipt.agent_id}],
        "participants_optional": [], "subject_ref": "s", "input_refs": [], "supersedes_id": "",
    }, receipt)
    accepted = _call(endpoint, "contract.accept", {
        "proposal_id": proposed["proposal_id"], "participant_slot": "self",
        "proposal_digest": proposed["digest"], "evidence_refs": [],
    }, receipt)
    assert accepted["status"] == "accepted"
    assert cognition.proposals[proposed["proposal_id"]].status == "accepted"


def test_inbox_claim_fetch_ack_roundtrip(tmp_path: Path) -> None:
    _, authority, _, _, messages, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    messages.send(
        command_id="cmd1", sender_agent_id="other", recipient_agent_id=receipt.agent_id,
        kind="message", subject_ref="s", summary="hello",
    )
    claimed = _call(endpoint, "inbox.claim", {"limit": 50, "max_bytes": 1000}, receipt)
    assert claimed["count"] == 1
    message_id = claimed["messages"][0]["message_id"]

    fetched = _call(endpoint, "inbox.fetch", {"delivery_lease_id": message_id}, receipt)
    assert fetched["message_id"] == message_id

    acked = _call(endpoint, "inbox.ack", {"message_id": message_id, "reason": "done"}, receipt)
    assert acked["acked"] is True


def test_message_send_idempotent_dedup(tmp_path: Path) -> None:
    _, authority, _, _, _, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    payload = {"recipient_agent_id": "other-agent", "kind": "message", "subject_ref": "s", "summary": "hello"}
    first = _call(endpoint, "message.send", payload, receipt)
    second = _call(endpoint, "message.send", payload, receipt)
    assert first["message_id"] == second["message_id"]


def test_message_respond_closes_obligation(tmp_path: Path) -> None:
    _, authority, _, _, messages, endpoint = _harness(tmp_path)
    receipt = _enroll_ready(authority, installation="install-a", conversation="conversation-a")
    messages.send(
        command_id="c1", sender_agent_id="other", recipient_agent_id=receipt.agent_id,
        kind="message", subject_ref="s", summary="question", response_contract={"required": True},
    )
    obligation_id = next(iter(messages.obligations))
    result = _call(endpoint, "message.respond", {
        "obligation_id": obligation_id, "response_message_id": "resp-1",
        "evidence_refs": [], "summary": "answer", "response_payload": {},
    }, receipt)
    assert result["status"] == "responded"
    assert messages.obligations[obligation_id].status == "responded"


def test_business_commands_denied_for_degraded_session(tmp_path: Path) -> None:
    # A degraded session has no agent_base grant and must fail closed before any
    # business command is dispatched.
    dispatcher = CommandDispatcher(ROOT / "protocol" / "registry" / "commands.json")
    authority = AuthorityService(tmp_path / "identity.json")
    for kind, handler in build_handlers(authority=authority).items():
        dispatcher.register(kind, handler)
    app = create_app(dispatcher, authenticator=LocalCommandAuthenticator(authority=authority))
    endpoint = next(
        route.endpoint for route in app.routes
        if getattr(route, "path", "") == "/api/v1/commands/{command_kind}"
    )
    ticket = authority.issue_ticket("install-a", "conversation-a")
    receipt = authority.redeem_ticket(ticket, "install-a", "conversation-a", baseline={})
    assert receipt.baseline_status == "degraded"
    with pytest.raises(HTTPException) as exc:
        endpoint(
            "task.claim", _request({"task_id": "t", "capability_snapshot_id": "x"}), Response(),
            f"Bearer {receipt.secret_token}", receipt.session_id, receipt.connection_epoch,
        )
    assert exc.value.status_code == 401
